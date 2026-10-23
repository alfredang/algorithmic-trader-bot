"""Live progress of a running desk - which agent is waiting, running or done, per symbol - so the AI Agents page
can draw the agent flow while the run is still in progress. In memory (API process only): the finished run keeps
its full trace in the database, so nothing here needs to survive a restart."""
from __future__ import annotations

import threading
import time

from trader.services.events import jsonable

NODES = ["technical_analyst", "sentiment_analyst", "fundamental_analyst", "bull_researcher", "bear_researcher",
         "trader", "risk_manager", "risk_limits", "portfolio_manager"]
KEEP = 20

_lock = threading.Lock()
_runs: dict[str, dict] = {}


class Progress:
    """Handle the desk calls as agents start and finish (thread-safe: the analysts and the debate run in parallel)."""

    def __init__(self, live_id: str, symbols: list[str], provider: str):
        self.id = live_id
        with _lock:
            _runs[live_id] = {"live_id": live_id, "status": "running", "provider": provider, "run_id": None,
                              "started": time.time(), "current": None, "symbols": symbols,
                              "nodes": {s: {n: {"state": "waiting"} for n in NODES} for s in symbols}}
            for old in sorted(_runs, key=lambda k: _runs[k]["started"])[:-KEEP]:
                _runs.pop(old, None)

    def symbol(self, symbol: str) -> None:
        with _lock:
            _runs[self.id]["current"] = symbol

    def start(self, symbol: str, node: str, round_no: int = 1) -> None:
        with _lock:
            _runs[self.id]["nodes"][symbol][node] = {"state": "running", "round": round_no, "since": time.time()}

    def done(self, symbol: str, node: str, entry: dict) -> None:
        state = "fallback" if (entry.get("brain") or "").startswith("rules (fallback") else "done"
        with _lock:
            _runs[self.id]["nodes"][symbol][node] = {"state": state, "round": entry.get("round", 1),
                                                     "brain": entry.get("brain"), "ms": entry.get("ms", 0),
                                                     "output": jsonable(entry.get("output") or {}),
                                                     "error": entry.get("error")}

    def fail(self, symbol: str, error: str) -> None:
        with _lock:
            for n in _runs[self.id]["nodes"][symbol].values():
                if n["state"] in ("waiting", "running"):
                    n.update(state="skipped", error=error)

    def finish(self, run_id: int | None, status: str) -> None:
        finish(self.id, run_id, status)


def finish(live_id: str | None, run_id: int | None, status: str) -> None:
    with _lock:
        if live_id in _runs:
            _runs[live_id].update(status=status, run_id=run_id, current=None, ended=time.time())


def get(live_id: str) -> dict | None:
    with _lock:
        r = _runs.get(live_id)
        if r is None:
            return None
        now = time.time()
        nodes = {s: {n: {**v, "ms": int((now - v["since"]) * 1000)} if v["state"] == "running" else dict(v)
                     for n, v in ns.items()} for s, ns in r["nodes"].items()}
        return {**r, "elapsed_ms": int(((r.get("ended") or now) - r["started"]) * 1000), "nodes": nodes}
