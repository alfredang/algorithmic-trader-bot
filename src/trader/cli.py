"""Command line: ``trader serve | worker | seed | migrate | backtest | agents | status``."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from trader import __version__


def _setup_logging(level: str = "info") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def cmd_serve(a) -> int:
    import uvicorn

    from trader.config import get_settings
    s = get_settings()
    if a.with_worker:
        import os
        os.environ["RUN_SCHEDULER_IN_PROCESS"] = "true"
        from trader.config import reset_settings
        reset_settings()
    host, port = a.host or s.host, a.port or s.port
    print(f"Quant Trading Simulator {__version__} - PAPER TRADING ONLY\n  App:      http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
          f"\n  API docs: http://localhost:{port}/docs\n  Database: {s.database_url.split('@')[-1]}"
          f"\n  Worker:   {'in-process' if a.with_worker or s.run_scheduler_in_process else 'not running - start `uv run trader worker` (or use --with-worker)'}")
    uvicorn.run("trader.api.app:create_app", factory=True, host=host, port=port, reload=a.reload,
                log_level=s.log_level.lower())
    return 0


def cmd_worker(a) -> int:
    from trader.db import migrate
    migrate()
    print("Worker: bots on their schedules, the always-on AI agent, simulator order matching. Ctrl+C to stop.")
    from trader.scheduler import run_forever
    run_forever()
    return 0


def cmd_migrate(a) -> int:
    from trader.db import migrate
    migrate()
    print("Database is at the latest migration.")
    return 0


def cmd_seed(a) -> int:
    from trader.db import migrate, session_scope
    migrate()
    from trader.services.seed import seed
    with session_scope() as db:
        seed(db, quick=a.quick)
    print("Seed complete. Start the app with: uv run trader serve")
    return 0


def cmd_backtest(a) -> int:
    from trader.db import migrate, session_scope
    from trader.services import backtests as BT
    migrate()
    params = dict(kv.split("=", 1) for kv in a.param or [])
    with session_scope() as db:
        bt = BT.run(db, {"strategy_key": a.strategy, "symbols": a.symbols, "params": params,
                         "config": {"costs": a.costs}, "start": a.start, "end": a.end})
        m = bt.metrics or {}
        print(json.dumps({"id": bt.id, "status": bt.status, "error": bt.error,
                          **{k: m.get(k) for k in ("total_return", "cagr", "sharpe", "max_drawdown", "trades")}}, indent=2))
    return 0 if bt.status == "done" else 1


def cmd_agents(a) -> int:
    from trader.agents.workflow import run_dict, run_workflow
    from trader.db import migrate, session_scope
    migrate()
    with session_scope() as db:
        r = run_workflow(db, a.symbols, a.provider, data_mode=a.data)
        d = run_dict(r)
        for t in d["trace"]:
            print(f"[{t['symbol']}] {t['title']:<28} ({t['brain']}): {json.dumps(t['output'], default=str)[:140]}")
        print(f"status {d['status']}; signals {[(s['symbol'], s['signal']) for s in d['signals']]}; "
              f"orders {[(o['symbol'], o['side'], o['qty'], o.get('status')) for o in d['orders']]}")
    return 0 if d["status"] != "error" else 1


def cmd_status(a) -> int:
    from trader.agents.providers import status_all
    from trader.config import get_settings, mask
    s = get_settings()
    alpaca = f"configured {mask(s.alpaca_key_id)}" if s.alpaca_configured else "not configured (simulator + demo data)"
    print(f"version {__version__}\ndatabase {s.database_url.split('@')[-1]}\nalpaca {alpaca}")
    for p in status_all():
        print(f"AI {p['name']:<7} {'OK ' if p['available'] else '-- '} {p['message']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trader", description="Quant / algorithmic trading simulator (paper trading only)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("serve", help="serve the API + web app (default)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--with-worker", action="store_true", help="also run the scheduler / agents in this process")
    p.add_argument("--reload", action="store_true")
    p.set_defaults(fn=cmd_serve)
    sub.add_parser("worker", help="run the scheduler: bots, always-on agent, simulator matching").set_defaults(fn=cmd_worker)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=cmd_migrate)
    p = sub.add_parser("seed", help="load the offline demo data and run sample backtests")
    p.add_argument("--quick", action="store_true", help="fewer sample backtests, no research runs")
    p.set_defaults(fn=cmd_seed)
    p = sub.add_parser("backtest", help="run one backtest from the command line")
    p.add_argument("strategy")
    p.add_argument("--symbols", nargs="+", default=["SPY"])
    p.add_argument("--param", nargs="*", help="name=value")
    p.add_argument("--costs", default="alpaca_retail")
    p.add_argument("--start")
    p.add_argument("--end")
    p.set_defaults(fn=cmd_backtest)
    p = sub.add_parser("agents", help="run the 8-agent workflow once (trades on the paper account)")
    p.add_argument("--symbols", nargs="+", default=["NVDA", "AAPL", "SPY"])
    p.add_argument("--provider", default=None)
    p.add_argument("--data", choices=["auto", "offline"], default=None, help="data mode (default AGENT_DATA_MODE)")
    p.set_defaults(fn=cmd_agents)
    sub.add_parser("status", help="show configuration and AI provider status").set_defaults(fn=cmd_status)
    a = ap.parse_args(argv)
    _setup_logging()
    if not getattr(a, "fn", None):
        a = ap.parse_args(["serve", *(argv or [])])
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
