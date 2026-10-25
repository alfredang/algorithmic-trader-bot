"""Worker: runs bots on their schedules, the always-on AI agent and a heartbeat (APScheduler).

Start it as a separate process (``uv run trader worker`` / the ``worker`` service in Docker Compose)
or in-process with ``uv run trader serve --with-worker`` (RUN_SCHEDULER_IN_PROCESS=true). Run only one.

Bot schedules: a 5-field cron string evaluated in New York time (``35 9 * * 1-5`` = 09:35 ET Mon-Fri),
or ``every 30s`` / ``every 5m`` / ``every 1h`` for demos and replays.
"""
from __future__ import annotations

import logging
import re
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from trader.db import session_scope
from trader.models import Bot, Setting, utcnow
from trader.services.events import stage

log = logging.getLogger("trader.worker")
TZ = "America/New_York"


def trigger_for(schedule: str):
    s = (schedule or "").strip().lower()
    m = re.fullmatch(r"every\s+(\d+)\s*(s|sec|secs|seconds|m|min|mins|minutes|h|hour|hours)", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)[0]
        return IntervalTrigger(**{{"s": "seconds", "m": "minutes", "h": "hours"}[unit]: max(n, 5 if unit == "s" else 1)},
                               timezone=TZ)
    return CronTrigger.from_crontab(s or "35 9 * * 1-5", timezone=TZ)


def validate_schedule(schedule: str) -> str:
    trigger_for(schedule)
    return schedule.strip()


def run_bot_job(bot_id: int) -> None:
    from trader.bots.runner import run_cycle
    with session_scope() as db:
        bot = db.get(Bot, bot_id)
        if bot is None or bot.status != "running":
            return
        run_cycle(db, bot)


def always_on_config(db) -> dict:
    s = db.get(Setting, "always_on")
    return {"enabled": False, "interval_min": 60, "symbols": ["NVDA", "AAPL", "SPY"], "provider": "auto",
            "refresh_news": True, "data_mode": "auto", **((s.value if s else None) or {})}


def always_on_job() -> None:
    """The 24/7 AI agent: run the 8-agent workflow on the watch list - research, trade on paper, review, write memory."""
    from trader.agents.workflow import run_workflow
    with session_scope() as db:
        cfg = always_on_config(db)
        if not cfg["enabled"]:
            return
        stage("scheduler", "running", f"Always-on agent wake-up: {', '.join(cfg['symbols'])}", db=db)
        run = run_workflow(db, cfg["symbols"], cfg.get("provider"), mode="always_on", data_mode=cfg.get("data_mode"),
                           refresh_news=cfg.get("refresh_news", True))
        stage("scheduler", "ok", f"Always-on agent run #{run.id}: {run.status}", {"run_id": run.id}, db=db)


def process_sim_orders(db, session_override: str | None = None) -> int:
    """Simulator market: fill working orders of live-mode simulator accounts at the latest price."""
    from trader.broker import service as BRK
    from trader.models import Account, Order
    n = 0
    ids = {o.account_id for o in db.scalars(select(Order).where(Order.status.in_(BRK.OPEN_STATES - {"held"}),
                                                                 Order.broker == "sim"))}
    for aid in ids:
        acct = db.get(Account, aid)
        if acct is None or acct.sim_clock is not None:      # replay bots fill on their own bars
            continue
        br = BRK.SimBroker(db, acct)
        sess = br.session(session_override)["session"]
        for sym in {o.symbol for o in br.open_orders()}:
            px = BRK.quote(db, sym, "alpaca_paper")["last"]
            n += len(br.match(sym, px, px, px, px, session=sess))
    return n


def sim_market_job() -> None:
    with session_scope() as db:
        process_sim_orders(db)


def heartbeat_job() -> None:
    with session_scope() as db:
        s = db.get(Setting, "worker_heartbeat") or Setting(key="worker_heartbeat")
        s.value = utcnow().isoformat() + "Z"
        db.add(s)


class Worker:
    def __init__(self):
        self.sched = BackgroundScheduler(timezone=TZ, job_defaults={"coalesce": True, "max_instances": 1,
                                                                    "misfire_grace_time": 60})
        self.bot_jobs: dict[int, str] = {}
        self.always_on_interval = None

    def start(self) -> None:
        self.sched.add_job(heartbeat_job, IntervalTrigger(seconds=15), id="heartbeat", replace_existing=True)
        self.sched.add_job(self.sync, IntervalTrigger(seconds=10), id="sync", replace_existing=True)
        self.sched.add_job(sim_market_job, IntervalTrigger(seconds=60), id="sim-market", replace_existing=True)
        self.sched.start()
        self.sync()
        log.info("worker started")

    def sync(self) -> None:
        """Mirror the bots table (and the always-on setting) into scheduler jobs."""
        try:
            with session_scope() as db:
                running = {b.id: b.schedule for b in db.scalars(select(Bot).where(Bot.status == "running"))}
                ao = always_on_config(db)
        except Exception as exc:          # pragma: no cover - DB not ready yet
            log.warning("sync failed: %s", exc)
            return
        for bid in list(self.bot_jobs):
            if bid not in running or self.bot_jobs[bid] != running[bid]:
                try:
                    self.sched.remove_job(f"bot-{bid}")
                except Exception:
                    pass
                self.bot_jobs.pop(bid, None)
        for bid, sch in running.items():
            if bid in self.bot_jobs:
                continue
            try:
                self.sched.add_job(run_bot_job, trigger_for(sch), args=[bid], id=f"bot-{bid}", replace_existing=True)
                self.bot_jobs[bid] = sch
            except Exception as exc:
                log.error("bad schedule for bot %s: %s", bid, exc)
        want = int(ao["interval_min"]) if ao["enabled"] else None
        if want != self.always_on_interval:
            try:
                self.sched.remove_job("always-on")
            except Exception:
                pass
            if want:
                self.sched.add_job(always_on_job, IntervalTrigger(minutes=max(want, 1)), id="always-on",
                                   replace_existing=True)
            self.always_on_interval = want

    def shutdown(self) -> None:
        self.sched.shutdown(wait=False)


def run_forever() -> None:
    w = Worker()
    w.start()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        w.shutdown()
