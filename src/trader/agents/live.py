"""Live progress of a running workflow - which agent is waiting, running or done - so the AI Agents page can draw
the agent flow while the run is still in progress. Per-symbol agents have one node per symbol; the run-level agents
(lead, performance analysis, strategy review) live under the pseudo-symbol ``*``. In memory (API process only):
the finished run keeps its full trace in the database, so nothing here needs to survive a restart."""
from __future__ import annotations

import threading
import time

from trader.agents.roles import ROLE_ORDER, SYMBOL_AGENTS
from trader.services.events import jsonable

RUN_AGENTS = [k for k in ROLE_ORDER if k not in SYMBOL_AGENTS]
KEEP = 20

_lock = threading.Lock()
_runs: dict[str, dict] = {}


class Progress:
    """Handle the workflow calls as agents start and finish (thread-safe: the two research agents run in parallel)."""

    def __init__(self, live_id: str, symbols: list[str], provider: str):
        self.id = live_id
        with _lock:
            _runs[live_id] = {"live_id": live_id, "status": "running", "provider": provider, "run_id": None,
                              "started": time.time(), "current": None, "symbols": symbols,
                              "nodes": {"*": {n: {"state": "waiting"} for n in RUN_AGENTS},
                                        **{s: {n: {"state": "waiting"} for n in SYMBOL_AGENTS} for s in symbols}}}
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
