"""Pipeline Map: live state of every stage of the end-to-end pipeline (course Topic 4.1) and the
per-strategy lifecycle with pass/fail gates."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trader.config import get_settings
from trader.models import (
    AgentRun,
    Backtest,
    Bar,
    Bot,
    Instrument,
    NewsItem,
    Order,
    Position,
    ResearchRun,
    Setting,
    StageEvent,
    StrategyRecord,
    WebhookAlert,
    utcnow,
)

STAGES = [
    ("ingestion", "Data ingestion", "Alpaca · Twelve Data · yfinance / offline demo", "data",
     "Fetch OHLCV bars at several timeframes from Alpaca Market Data, Twelve Data or yfinance (offline: the bundled "
     "demo files) and cache them in the database so every later stage reads the same data."),
    ("quality", "Data quality", "gaps · splits · duplicates · timezone", "data",
     "Prove the prices are right before anything is built on them: missing values, duplicate timestamps, gaps, "
     "moves that look like unadjusted splits, stale data and timezone consistency."),
    ("news", "News & sentiment", "NewsAPI · Alpaca News · VADER", "data",
     "Unstructured text becomes a signal: headlines are scored by a lexicon model (VADER) and stored per symbol "
     "per day for the sentiment strategy and the news analyst agent."),
    ("features", "Features & indicators", "SMA/EMA · RSI · MACD · Bollinger · ATR", "chart",
     "Indicators and ML features computed from completed bars only - no centred windows, no future data."),
    ("strategy", "Strategy selection", "built-in library + custom Python", "strategies",
     "Choose a strategy from the library (trend, mean reversion, momentum, breakout, pairs, ML, sentiment, "
     "agentic) or write your own in the Strategy Builder; signals are target positions decided at the close."),
    ("search", "Strategy search", "grid · walk-forward · regimes", "research/grid",
     "Grid-search parameters in-sample, rank them, and check how the ranking decays out of sample; walk-forward "
     "re-fits as time advances."),
    ("backtest", "Backtesting", "next-bar fills · costs · break-even", "backtest",
     "Replay the strategy on history with next-bar execution and realistic costs (commission, spread, slippage, "
     "SEC/FINRA fees, borrow): gross vs net, cost breakdown and break-even cost."),
    ("abtest", "A/B test & diagnostics", "Welch · paired · bootstrap · bias checks", "research/abtest",
     "Decide statistically before capital moves (Welch, paired t-test, block-bootstrap Sharpe CI) and run the bias "
     "diagnostics: look-ahead, cost drag, overfitting, survivorship."),
    ("agents", "Multi-agent desk", "analysts → debate → trader → risk → PM", "agents",
     "Agentic AI: technical, sentiment and fundamental analysts, a bull/bear debate, a trader, a risk manager and a "
     "portfolio manager propose a trade; a human approves before any paper order."),
    ("risk", "Pre-trade risk checks", "limits · market clock · kill switch", "trading",
     "Deterministic code that no model can loosen: kill switch, session rules, allow-list, max order value, max "
     "position, max daily loss, duplicate client_order_id."),
    ("forward", "Forward test / paper trading", "bots · Alpaca paper or simulator", "trading",
     "Bots run the strategy on a schedule on data they have never seen and place paper orders - the bridge "
     "between a backtest and live capital."),
    ("execution", "Execution & order lifecycle", "market · limit · bracket · 24/5 extended hours", "trading/orders",
     "Session-aware orders: market in the regular session, extended-hours limit orders overnight (Alpaca 24/5), "
     "GTC limits queued when closed; every status change is recorded."),
    ("analytics", "Performance analytics", "Sharpe · Sortino · Calmar · alpha/beta", "analytics",
     "All the course metrics for every backtest and bot, equity vs benchmark, drawdown, monthly returns, rolling "
     "Sharpe, costs, and backtest vs forward-test comparison."),
    ("reporting", "Reporting / tearsheet", "CSV · PDF tearsheet", "analytics",
     "A one-page tearsheet: equity vs benchmark, drawdown, monthly heatmap, rolling Sharpe, metrics and cost table."),
]
SIDE_INPUTS = [
    ("webhook", "TradingView webhook alerts", "feeds signals + risk", "integrations",
     "TradingView alerts POST JSON to /api/webhooks/tradingview; the app checks the secret, confirms with its own "
     "signal, runs the risk checks and places a paper order.", ["strategy", "risk"]),
    ("scheduler", "Always-on AI agent & scheduler", "drives the loop 24/7", "agents",
     "An AI agent is agentic AI that stands by 24/7: the worker runs bots on their schedules and the always-on agent "
     "monitors markets and news, writes memory and proposes trades within limits.", ["forward", "agents"]),
]
ALIASES = {"signals": "strategy", "positions": "forward"}


def _latest(db: Session, stage: str) -> StageEvent | None:
    names = [stage] + [k for k, v in ALIASES.items() if v == stage]
    return db.scalar(select(StageEvent).where(StageEvent.stage.in_(names)).order_by(StageEvent.id.desc()).limit(1))


def _last_error(db: Session, stage: str) -> StageEvent | None:
    names = [stage] + [k for k, v in ALIASES.items() if v == stage]
    return db.scalar(select(StageEvent).where(StageEvent.stage.in_(names), StageEvent.status == "error")
                     .order_by(StageEvent.id.desc()).limit(1))


def _count(db, q) -> int:
    return int(db.scalar(q) or 0)


def _figures(db: Session) -> dict[str, dict]:
    s = get_settings()
    today = utcnow() - timedelta(hours=24)
    bars = _count(db, select(func.count(Bar.id)))
    inst = list(db.scalars(select(Instrument)))
    q_ok = sum(1 for i in inst if (i.quality or {}).get("status") == "OK")
    q_chk = sum(1 for i in inst if (i.quality or {}).get("status") == "CHECK")
    q_fail = sum(1 for i in inst if (i.quality or {}).get("status") == "FAIL")
    news_n = _count(db, select(func.count(NewsItem.id)))
    news_real = _count(db, select(func.count(NewsItem.id)).where(NewsItem.synthetic.is_(False)))
    custom = _count(db, select(func.count(StrategyRecord.id)).where(StrategyRecord.builtin.is_(False)))
    from trader.strategies.builtin import REGISTRY
    grids = _count(db, select(func.count(ResearchRun.id)).where(ResearchRun.kind.in_(["grid", "walk_forward", "regime"])))
    bt = next((b for b in db.scalars(select(Backtest).where(Backtest.status == "done").order_by(Backtest.id.desc()).limit(30))
               if (b.extra or {}).get("kind", "signal") not in ("execution", "market_making")), None)
    n_bt = _count(db, select(func.count(Backtest.id)))
    ab = db.scalar(select(ResearchRun).where(ResearchRun.kind == "abtest", ResearchRun.status == "done")
                   .order_by(ResearchRun.id.desc()).limit(1))
    dg = db.scalar(select(ResearchRun).where(ResearchRun.kind == "diagnostics", ResearchRun.status == "done")
                   .order_by(ResearchRun.id.desc()).limit(1))
    ar = db.scalar(select(AgentRun).order_by(AgentRun.id.desc()).limit(1))
    pending = _count(db, select(func.count(AgentRun.id)).where(AgentRun.status == "proposed"))
    kill = db.get(Setting, "kill_switch")
    bots_running = _count(db, select(func.count(Bot.id)).where(Bot.status == "running"))
    bots = list(db.scalars(select(Bot)))
    orders_today = _count(db, select(func.count(Order.id)).where(Order.submitted_at >= today))
    filled_today = _count(db, select(func.count(Order.id)).where(Order.submitted_at >= today, Order.status == "filled"))
    open_orders = _count(db, select(func.count(Order.id)).where(Order.status.in_(["new", "accepted", "held", "partially_filled"])))
    rejected = _count(db, select(func.count(Order.id)).where(Order.submitted_at >= today, Order.status == "rejected"))
    open_pos = _count(db, select(func.count(Position.id)).where(Position.qty != 0))
    pnl = 0.0
    from trader.bots.runner import bot_dict
    for b in bots:
        d = bot_dict(db, b)
        if d["equity"] is not None and d["starting_cash"]:
            pnl += d["equity"] - d["starting_cash"]
    alerts = _count(db, select(func.count(WebhookAlert.id)))
    last_alert = db.scalar(select(WebhookAlert).order_by(WebhookAlert.id.desc()).limit(1))
    hb = db.get(Setting, "worker_heartbeat")
    ao = db.get(Setting, "always_on")
    reports = _count(db, select(func.count(StageEvent.id)).where(StageEvent.stage == "reporting"))
    from trader.agents.providers import resolve
    prov = resolve(None)
    m = (bt.metrics or {}) if bt else {}
    return {
        "ingestion": {"bars_cached": bars, "instruments": len(inst),
                      "source": "Alpaca" if s.alpaca_configured else "offline demo / yfinance"},
        "quality": {"ok": q_ok, "check": q_chk, "fail": q_fail},
        "news": {"headlines": news_n, "real_headlines": news_real,
                 "_disabled": not (s.newsapi_key or s.alpaca_configured),
                 "_hint": "Add NEWSAPI_KEY or Alpaca keys for real headlines (offline: synthetic sample headlines)"},
        "features": {"indicators": 10, "ml_features": 14},
        "strategy": {"built_in": len(REGISTRY), "custom": custom},
        "search": {"runs": grids},
        "backtest": {"runs": n_bt, "last_id": bt.id if bt else None, "last": bt.name if bt else None,
                     "cagr": m.get("cagr"), "sharpe": m.get("sharpe"), "max_drawdown": m.get("max_drawdown"),
                     "trades": m.get("trades")},
        "abtest": {"last_ab": (ab.result or {}).get("decision") if ab else None, "ab_id": ab.id if ab else None,
                   "last_diagnostics": (dg.result or {}).get("verdict") if dg else None, "diag_id": dg.id if dg else None},
        "agents": {"provider": prov.name, "last_status": ar.status if ar else None, "last_id": ar.id if ar else None,
                   "pending_approval": pending, "_disabled": prov.name == "rules",
                   "_hint": "No AI login: the deterministic multi-role desk runs. Log in with `codex login` or add an API "
                            "key on the Integrations page."},
        "risk": {"kill_switch": bool(kill and kill.value), "blocked_today": _count(db, select(func.count(StageEvent.id)).where(
            StageEvent.stage == "risk", StageEvent.status == "warning", StageEvent.ts >= today))},
        "forward": {"bots": len(bots), "running": bots_running, "orders_today": orders_today, "open_positions": open_pos,
                    "pnl": round(pnl, 2), "broker": "Alpaca paper" if s.alpaca_configured else "simulator"},
        "execution": {"orders_today": orders_today, "filled_today": filled_today, "open": open_orders, "rejected_today": rejected},
        "analytics": {k: m.get(k) for k in ("total_return", "cagr", "volatility", "sharpe", "sortino", "calmar",
                                            "max_drawdown", "win_rate", "profit_factor", "expectancy", "exposure",
                                            "turnover", "alpha", "beta")} | {"backtest_id": bt.id if bt else None},
        "reporting": {"tearsheets": reports},
        "webhook": {"alerts": alerts, "last_http": last_alert.http_status if last_alert else None},
        "scheduler": {"worker_heartbeat": (hb.value if hb else None),
                      "always_on": bool(ao and (ao.value or {}).get("enabled")),
                      "in_process": s.run_scheduler_in_process},
    }


def status(db: Session) -> dict:
    figs = _figures(db)
    now = utcnow()
    nodes = []
    for i, (key, title, sub, route, tip, *rest) in enumerate(STAGES + SIDE_INPUTS):
        ev = _latest(db, key)
        err = _last_error(db, key)
        f = figs.get(key, {})
        st = "idle"
        if ev is not None:
            st = ev.status
            if st == "running" and now - ev.ts > timedelta(minutes=3):
                st = "warning"
        if key == "risk" and f.get("kill_switch"):
            st = "error"
        if key == "scheduler":
            hb = f.get("worker_heartbeat")
            st = "ok" if hb or f.get("in_process") else "idle"
        disabled = bool(f.pop("_disabled", False))
        hint = f.pop("_hint", None)
        nodes.append({"key": key, "order": i + 1 if i < len(STAGES) else None, "title": title, "subtitle": sub,
                      "route": route, "tooltip": tip, "side_input": i >= len(STAGES),
                      "feeds": rest[0] if rest else None,
                      "status": st, "disabled": disabled, "hint": hint if disabled else None,
                      "last_run": ev.ts.isoformat() + "Z" if ev else None, "message": ev.message if ev else "",
                      "ref_type": ev.ref_type if ev else None, "ref_id": ev.ref_id if ev else None,
                      "last_error": ({"ts": err.ts.isoformat() + "Z", "message": err.message} if err else None),
                      "metrics": f})
    recent = db.scalars(select(StageEvent).where(StageEvent.ts >= now - timedelta(seconds=90), StageEvent.run_id.is_not(None))
                        .order_by(StageEvent.id.desc()).limit(80)).all()
    active_run = recent[0].run_id if recent else None
    active = sorted({ALIASES.get(e.stage, e.stage) for e in recent if e.run_id == active_run}) if active_run else []
    return {"stages": nodes, "edges": [[STAGES[i][0], STAGES[i + 1][0]] for i in range(len(STAGES) - 1)],
            "active_run": active_run, "active_path": active, "generated_at": now.isoformat() + "Z"}


def events(db: Session, stage: str, limit: int = 30) -> list[dict]:
    names = [stage] + [k for k, v in ALIASES.items() if v == stage]
    rows = db.scalars(select(StageEvent).where(StageEvent.stage.in_(names)).order_by(StageEvent.id.desc()).limit(limit))
    return [{"id": e.id, "ts": e.ts.isoformat() + "Z", "stage": e.stage, "status": e.status, "message": e.message,
             "metrics": e.metrics, "ref_type": e.ref_type, "ref_id": e.ref_id, "run_id": e.run_id} for e in rows]


# --------------------------------------------------------------------------- strategy lifecycle
def lifecycle(db: Session, strategy_key: str, sharpe_gate: float = 0.5, min_cycles: int = 20) -> dict:
    from trader.strategies import registry
    desc = registry.get(db, strategy_key)
    steps = []

    def add(key, title, status, gate, figures, route, ref=None):
        steps.append({"key": key, "title": title, "status": status, "gate": gate, "figures": figures, "route": route,
                      "ref": ref})
    hyp = db.scalar(select(ResearchRun).where(ResearchRun.kind == "hypothesis", ResearchRun.status == "done")
                    .order_by(ResearchRun.id.desc()).limit(1))
    add("idea", "Idea / hypothesis", "pass", "Hypothesis written before the test (H0 / H1)",
        {"strategy": desc["name"], "hypothesis_run": hyp.id if hyp else None,
         "decision": (hyp.result or {}).get("decision") if hyp else None}, "research/hypothesis")
    bt = db.scalar(select(Backtest).where(Backtest.strategy_key == strategy_key, Backtest.status == "done")
                   .order_by(Backtest.id.desc()).limit(1))
    if bt:
        sh = (bt.metrics or {}).get("sharpe")
        ok = sh is not None and sh >= sharpe_gate
        add("backtest", "Backtest (net of costs)", "pass" if ok else "fail", f"net Sharpe >= {sharpe_gate}",
            {k: (bt.metrics or {}).get(k) for k in ("cagr", "sharpe", "max_drawdown", "trades")}, f"backtest?id={bt.id}", bt.id)
    else:
        add("backtest", "Backtest (net of costs)", "pending", f"net Sharpe >= {sharpe_gate}", {}, f"backtest?strategy={strategy_key}")
    abs_ = [r for r in db.scalars(select(ResearchRun).where(ResearchRun.kind == "abtest", ResearchRun.status == "done")
                                  .order_by(ResearchRun.id.desc()).limit(50))
            if strategy_key in (((r.config or {}).get("a") or {}).get("strategy_key"), ((r.config or {}).get("b") or {}).get("strategy_key"))]
    if abs_:
        r = abs_[0].result or {}
        add("abtest", "A/B test", "pass" if r.get("reject_h0") else "fail", "paired test AND bootstrap Sharpe CI reject H0",
            {"sharpe_diff": r.get("sharpe_diff"), "paired_p": r.get("paired_p"), "decision": r.get("decision")},
            f"research/abtest?id={abs_[0].id}", abs_[0].id)
    else:
        add("abtest", "A/B test", "pending", "paired test AND bootstrap Sharpe CI reject H0", {}, "research/abtest")
    dg = [r for r in db.scalars(select(ResearchRun).where(ResearchRun.kind == "diagnostics", ResearchRun.status == "done")
                                .order_by(ResearchRun.id.desc()).limit(50)) if (r.config or {}).get("strategy_key") == strategy_key]
    if dg:
        r = dg[0].result or {}
        add("diagnostics", "Diagnostics", "pass" if r.get("fails", 1) == 0 else "fail", "no FAIL (look-ahead, cost drag, overfit)",
            {"verdict": r.get("verdict"), "fails": r.get("fails"), "warns": r.get("warns")}, f"research/diagnostics?id={dg[0].id}", dg[0].id)
    else:
        add("diagnostics", "Diagnostics", "pending", "no FAIL (look-ahead, cost drag, overfit)", {}, "research/diagnostics")
    bots = list(db.scalars(select(Bot).where(Bot.strategy_key == strategy_key).order_by(Bot.id.desc())))
    sim = next((b for b in bots if b.broker == "sim"), None)
    if sim:
        from trader.bots.runner import bot_dict
        d = bot_dict(db, sim)
        ret = (d["equity"] / d["starting_cash"] - 1) if d["equity"] and d["starting_cash"] else None
        ok = sim.cycles >= min_cycles and (ret or 0) > -0.05
        add("forward", "Forward test (simulator)", "pass" if ok else ("running" if sim.status == "running" else "fail"),
            f">= {min_cycles} cycles, no >5% loss", {"bot": sim.name, "cycles": sim.cycles, "return": ret, "status": sim.status},
            f"trading?bot={sim.id}", sim.id)
    else:
        add("forward", "Forward test (simulator)", "pending", f">= {min_cycles} cycles, no >5% loss", {}, "trading")
    live = next((b for b in bots if b.broker == "alpaca_paper"), None)
    approved = db.scalar(select(func.count(AgentRun.id)).where(AgentRun.status == "executed"))
    if live:
        add("live_paper", "Live paper (Alpaca)", "pass" if live.cycles else "running", "human approval to go live-paper",
            {"bot": live.name, "cycles": live.cycles}, f"trading?bot={live.id}", live.id)
    else:
        add("live_paper", "Live paper (Alpaca)", "pending", "human approval to go live-paper",
            {"alpaca_configured": get_settings().alpaca_configured, "agent_runs_executed": approved}, "trading")
    add("analytics", "Analytics & report", "pass" if (bt and sim) else "pending", "backtest vs forward explained",
        {"backtest_id": bt.id if bt else None, "bot_id": sim.id if sim else None},
        f"analytics?backtest={bt.id if bt else ''}&bot={sim.id if sim else ''}")
    return {"strategy": desc["key"], "name": desc["name"], "steps": steps}
