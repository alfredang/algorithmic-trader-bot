"""The multi-agent desk orchestrator. See roles.py for the agents and the course taxonomy.

For every symbol:
  1. three analysts (technical, sentiment/news, fundamental-lite) - natively orchestrated by the provider
     where the SDK supports it (Claude subagents / OpenAI agents-as-tools), otherwise one agent call each
  2. bull vs bear debate - two rounds; in round 2 each researcher rebuts the other
  3. trader proposal -> risk-manager agent review (advisory)
  4. HARD risk limits enforced in code (never by a model) -> quantity, bracket stop / target
  5. portfolio manager / orchestrator final recommendation
  6. HUMAN approval before any paper order (optional auto-approve inside the hard limits)
Every agent call is one trace entry: agent, brain (provider or rules fallback), input tools, output, latency.
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.agents import live
from trader.agents import rules as RULES
from trader.agents.providers import Provider, RulesProvider, resolve
from trader.agents.roles import DEFAULT_LIMITS, ROLE_ORDER, ROLES
from trader.agents.tools import build_context
from trader.broker import service as BRK
from trader.models import AgentMemory, AgentRun, Setting
from trader.services.events import audit, emit, jsonable, stage


def desk_limits(db: Session) -> dict:
    s = db.get(Setting, "agent_limits")
    return {**DEFAULT_LIMITS, **((s.value if s else None) or {})}


def _call(provider: Provider, role_key: str, ctx: dict, reports: dict, trace: list, round_no: int = 1,
          native_out: dict | None = None, progress: live.Progress | None = None) -> dict:
    out, entry = _run_one(provider, role_key, ctx, reports, round_no, native_out, progress)
    trace.append(entry)
    return out


def _call_parallel(provider: Provider, keys: list[str], ctx: dict, reports: dict, trace: list, round_no: int = 1,
                   native_out: dict | None = None, progress: live.Progress | None = None) -> dict[str, dict]:
    """Run independent agents concurrently (each sees the same reports); trace entries keep the role order."""
    snapshot = dict(reports)
    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        futs = {k: pool.submit(_run_one, provider, k, ctx, snapshot, round_no, native_out, progress) for k in keys}
        results = {k: f.result() for k, f in futs.items()}
    for k in keys:
        trace.append(results[k][1])
    return {k: results[k][0] for k in keys}


def _run_one(provider: Provider, role_key: str, ctx: dict, reports: dict, round_no: int = 1,
             native_out: dict | None = None, progress: live.Progress | None = None) -> tuple[dict, dict]:
    role = ROLES[role_key]
    if progress:
        progress.start(ctx["symbol"], role_key, round_no)
    t0 = time.time()
    brain, err = provider.name, None
    if native_out is not None and role_key in native_out:
        out = native_out[role_key]
        brain = f"{provider.name} (native multi-agent)"
    else:
        try:
            out = provider.run_role(role, ctx, reports, round_no)
            if not isinstance(out, dict):
                raise ValueError("agent did not return a JSON object")
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:300]}"
            out = RULES.BRAINS[role_key](ctx, reports)
            brain = "rules (fallback)"
    out = _sanitize(role_key, out, ctx, reports)
    entry = {"symbol": ctx["symbol"], "agent": role_key, "title": role.title, "stage": role.stage,
             "round": round_no, "brain": brain, "model": provider.model or None, "tools": list(role.tools),
             "output": jsonable(out), "ms": int((time.time() - t0) * 1000), "error": err}
    if progress:
        progress.done(ctx["symbol"], role_key, entry)
    return out, entry


def _num(x, default=0.0, lo=None, hi=None) -> float:
    try:
        v = float(x)
        if math.isnan(v):
            v = default
    except (TypeError, ValueError):
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _sanitize(role_key: str, out: dict, ctx: dict, reports: dict) -> dict:
    """Coerce model output into the role's schema; fill anything missing from the rule brain."""
    base = RULES.BRAINS[role_key](ctx, reports) if role_key != "portfolio_manager" or "risk_limits" in reports else {}
    o = {**base, **{k: v for k, v in out.items() if v is not None}}
    if "score" in o:
        o["score"] = round(_num(o["score"], 0.0, -1, 1), 2)
    if "conviction" in o:
        o["conviction"] = round(_num(o["conviction"], 0.5, 0, 1), 2)
    if "confidence" in o:
        o["confidence"] = round(_num(o["confidence"], 0.0, 0, 1), 2)
    if "size_pct" in o:
        o["size_pct"] = round(_num(o["size_pct"], 0.0, 0, 0.25), 3)
    if role_key == "trader" and o.get("action") not in ("buy", "sell", "hold"):
        o["action"] = "hold"
    if role_key == "risk_manager" and o.get("decision") not in ("approve", "resize", "reject"):
        o["decision"] = "reject"
    if role_key == "portfolio_manager" and o.get("decision") not in ("approve", "hold", "reject"):
        o["decision"] = "hold"
    for k in ("points", "signals", "events", "risks", "notes", "watch"):
        if k in o and not isinstance(o[k], list):
            o[k] = [str(o[k])]
    return o


def hard_limits(ctx: dict, reports: dict, limits: dict) -> dict:
    """Deterministic risk gate - coded OUTSIDE the LLM. A model can never loosen these limits."""
    p, rm, t = reports["trader"], reports["risk_manager"], ctx["technical"]
    equity, held = ctx["position"]["equity"], ctx["position"]["qty"]
    sym = ctx["symbol"]
    notes = []
    if p["action"] == "hold":
        return {"decision": "NO TRADE", "qty": 0, "notes": ["trader proposes hold"]}
    allowed = [s.upper() for s in limits.get("allowed_symbols") or []]
    if allowed and sym not in allowed:
        return {"decision": "REJECTED", "qty": 0, "notes": [f"{sym} not on the agent allow-list"]}
    if p["action"] == "sell":
        if held <= 0:
            return {"decision": "REJECTED", "qty": 0, "notes": ["no position to sell (long-only desk)"]}
        return {"decision": "APPROVED", "qty": int(held), "side": "sell", "notes": ["exit the full position"]}
    if p["confidence"] < limits["min_confidence"]:
        return {"decision": "REJECTED", "qty": 0, "notes": [f"confidence {p['confidence']} < {limits['min_confidence']}"]}
    if rm.get("decision") == "reject":
        return {"decision": "REJECTED", "qty": 0, "notes": ["risk-manager agent rejected the proposal"]}
    size = min(p.get("size_pct", 0.0), rm.get("size_pct", p.get("size_pct", 0.0)) or p.get("size_pct", 0.0),
               limits["max_position_pct"])
    cap = min(equity * size, limits["max_order_value"])
    qty = math.floor(cap / t["close"]) if t["close"] > 0 else 0
    if qty < 1:
        return {"decision": "REJECTED", "qty": 0, "notes": ["size rounds to zero shares under the limits"]}
    if equity * p.get("size_pct", 0) > cap + 1:
        notes.append(f"resized to {qty} shares (cap USD {cap:,.0f}: max {limits['max_position_pct']:.0%} of equity, "
                     f"max order USD {limits['max_order_value']:,.0f})")
    stop_atr = min(_num(rm.get("stop_atr"), limits["stop_atr"], 0.5, 5.0), limits["stop_atr"] * 1.5)
    target_atr = _num(rm.get("target_atr"), limits["target_atr"], 0.5, 10.0)
    stop = round(t["close"] - stop_atr * t["atr14"], 2)
    target = round(t["close"] + target_atr * t["atr14"], 2)
    notes.append(f"bracket: stop {stop} ({stop_atr:g} ATR) / target {target} ({target_atr:g} ATR)")
    return {"decision": "APPROVED", "qty": qty, "side": "buy", "stop_loss": stop, "take_profit": target,
            "price": t["close"], "notes": notes}


def analyse_symbol(provider: Provider, ctx: dict, limits: dict, trace: list, orchestration: str,
                   progress: live.Progress | None = None) -> dict:
    reports: dict = {}
    native_out = None
    if provider.supports_native and orchestration == "native":
        if progress:                      # one native call answers for all three analysts
            for k in ROLE_ORDER[:3]:
                progress.start(ctx["symbol"], k)
        t0 = time.time()
        try:
            native_out = provider.run_native(ctx, reports)
        except Exception as exc:
            trace.append({"symbol": ctx["symbol"], "agent": "orchestrator", "title": "Native orchestration",
                          "stage": "orchestration", "brain": provider.name, "output": {},
                          "ms": int((time.time() - t0) * 1000), "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                          "control": True})
            native_out = None
    reports.update(_call_parallel(provider, ROLE_ORDER[:3], ctx, reports, trace, native_out=native_out, progress=progress))
    # bull vs bear debate: round 1 in parallel, then round 2 where each rebuts the other's round-1 case
    reports.update(_call_parallel(provider, ["bull_researcher", "bear_researcher"], ctx, reports, trace, 1, progress=progress))
    first = {e["agent"]: e for e in trace[-2:]}
    reports.update(_call_parallel(provider, ["bull_researcher", "bear_researcher"], ctx, reports, trace, 2, progress=progress))
    for k in ("bull_researcher", "bear_researcher"):
        second = trace.pop() if trace[-1]["agent"] == k else trace.pop(-2)
        f = first[k]
        f.update(output=second["output"], rounds=[f["output"], second["output"]], round=2, ms=f["ms"] + second["ms"],
                 error=f["error"] or second["error"],
                 brain=f["brain"] if f["brain"] == second["brain"] else f"{f['brain']} / {second['brain']}")
        if progress:
            progress.done(ctx["symbol"], k, f)
    reports["trader"] = _call(provider, "trader", ctx, reports, trace, progress=progress)
    reports["risk_manager"] = _call(provider, "risk_manager", ctx, reports, trace, progress=progress)
    gate = hard_limits(ctx, reports, limits)
    reports["risk_limits"] = gate
    trace.append({"symbol": ctx["symbol"], "agent": "risk_limits", "title": "Hard risk limits (code)", "stage": "control",
                  "brain": "deterministic code", "output": gate, "ms": 0, "error": None, "control": True})
    if progress:
        progress.done(ctx["symbol"], "risk_limits", trace[-1])
    reports["portfolio_manager"] = _call(provider, "portfolio_manager", ctx, reports, trace, progress=progress)
    final = reports["portfolio_manager"]
    approved = gate["decision"] == "APPROVED" and final.get("decision") == "approve"
    return {"symbol": ctx["symbol"], "as_of": ctx["technical"]["as_of"], "reports": reports, "gate": gate,
            "final": final, "approved_by_desk": approved,
            "proposal": ({"symbol": ctx["symbol"], "side": gate.get("side"), "qty": gate.get("qty"),
                          "stop_loss": gate.get("stop_loss"), "take_profit": gate.get("take_profit"),
                          "price": gate.get("price"), "rationale": reports["trader"].get("rationale")} if approved else None)}


def run_desk(db: Session, symbols: list[str], provider_name: str | None = None, mode: str = "desk",
             orchestration: str = "native", provider: Provider | None = None, account_name: str = "Agent desk account",
             auto_approve: bool | None = None, live_id: str | None = None) -> AgentRun:
    t0 = time.time()
    provider = provider or resolve(provider_name)
    ok, why = provider.available()
    fallback_note = None
    if not ok:
        fallback_note = f"{provider.label} unavailable ({why}) - using the rule-based desk"
        provider = RulesProvider()
    progress = live.Progress(live_id, [s.upper() for s in symbols], provider.name) if live_id else None
    limits = desk_limits(db)
    acct = BRK.get_account(db, account_name)
    br = BRK.broker_for(db, acct)
    equity = br.equity()
    run = AgentRun(mode=mode, provider=provider.name, auth_mode=provider.auth_mode, model=provider.model or "",
                   orchestration=orchestration if provider.supports_native else "pipeline",
                   symbols=[s.upper() for s in symbols], status="running")
    db.add(run)
    db.flush()
    stage("agents", "running", f"Multi-agent desk ({provider.name}) on {', '.join(symbols)}", {"run_id": run.id},
          ref_type="agent_run", ref_id=run.id, db=db)
    trace: list[dict] = []
    if fallback_note:
        trace.append({"symbol": "*", "agent": "orchestrator", "title": "Provider selection", "stage": "orchestration",
                      "brain": "deterministic code", "output": {"note": fallback_note}, "ms": 0, "error": None,
                      "control": True})
    results = []
    for s in symbols:
        sym = s.upper()
        if progress:
            progress.symbol(sym)
        pos = br.position(sym)
        try:
            ctx = build_context(db, sym, float(pos.qty) if pos else 0.0, equity, limits)
        except Exception as exc:
            trace.append({"symbol": sym, "agent": "orchestrator", "title": "Data", "stage": "orchestration",
                          "brain": "code", "output": {}, "ms": 0, "error": str(exc), "control": True})
            if progress:
                progress.fail(sym, str(exc))
            continue
        results.append(analyse_symbol(provider, ctx, limits, trace, orchestration, progress))
    proposals = [r["proposal"] for r in results if r["proposal"]]
    run.trace = jsonable(trace)
    run.proposals = jsonable(proposals)
    run.status = "proposed" if proposals else "no_trade"
    run.duration_ms = int((time.time() - t0) * 1000)
    for r in results:
        db.add(AgentMemory(topic=r["symbol"], kind="decision" if mode == "always_on" else "observation",
                           content=f"{r['as_of']}: {r['final'].get('decision')} - {r['final'].get('summary', '')}"[:2000],
                           data={"run_id": run.id, "gate": r["gate"]["decision"],
                                 "tech": r["reports"]["technical_analyst"].get("score"),
                                 "news": r["reports"]["sentiment_analyst"].get("score")}))
    db.flush()
    audit("agents.run", "agent_run", run.id, {"provider": provider.name, "symbols": symbols, "proposals": len(proposals)}, db=db)
    stage("agents", "ok", f"Desk run #{run.id} ({provider.name}): {len(proposals)} proposal(s) awaiting human approval"
          if proposals else f"Desk run #{run.id} ({provider.name}): no trade", {"run_id": run.id, "proposals": len(proposals),
                                                                             "provider": provider.name},
          ref_type="agent_run", ref_id=run.id, db=db)
    emit("agents.run", {"id": run.id, "status": run.status, "proposals": len(proposals)}, db=db)
    auto = desk_auto_approve(db) if auto_approve is None else auto_approve
    if proposals and auto:
        approve(db, run, actor="auto-approve (within hard limits)")
    if progress:
        progress.finish(run.id, run.status)
    return run


def desk_auto_approve(db: Session) -> bool:
    s = db.get(Setting, "agent_auto_approve")
    if s is not None:
        return bool(s.value)
    from trader.config import get_settings
    return get_settings().agent_auto_approve


def approve(db: Session, run: AgentRun, actor: str = "user", account_name: str = "Agent desk account") -> AgentRun:
    """HUMAN APPROVAL: send the desk's approved proposals as PAPER orders (bracket in the regular session)."""
    if run.status not in ("proposed",):
        raise ValueError(f"run is {run.status}; only proposed runs can be approved")
    acct = BRK.get_account(db, account_name)
    limits = desk_limits(db)
    orders = []
    for p in run.proposals or []:
        req = BRK.OrderRequest(symbol=p["symbol"], side=p["side"], qty=float(p["qty"]), type="auto",
                               client_order_id=BRK.client_id(f"agent{run.id}", p["symbol"], p["side"], p["qty"]),
                               note=f"agent run #{run.id}: {p.get('rationale', '')}"[:300])
        br = BRK.broker_for(db, acct)
        if p["side"] == "buy" and p.get("stop_loss") and br.session()["session"] == "regular":
            req.order_class, req.take_profit, req.stop_loss = "bracket", p["take_profit"], p["stop_loss"]
        r = BRK.place_order(db, acct, req, source="agent",
                            limits={"max_position_pct": limits["max_position_pct"], "max_order_value": limits["max_order_value"],
                                    "allowed_symbols": limits.get("allowed_symbols") or []}, broker=br)
        orders.append({"symbol": p["symbol"], "ok": r["ok"], "order": r["order"], "reason": r["risk"]["reason"]})
    run.orders = jsonable(orders)
    run.status = "executed" if any(o["ok"] for o in orders) else "rejected"
    run.approved_by = actor
    audit("agents.approve", "agent_run", run.id, {"actor": actor, "orders": len(orders)}, actor=actor, db=db)
    stage("agents", "ok", f"Run #{run.id} approved by {actor}: {sum(o['ok'] for o in orders)} paper order(s)",
          {"run_id": run.id}, ref_type="agent_run", ref_id=run.id, db=db)
    emit("agents.approved", {"id": run.id, "orders": len(orders)}, db=db)
    return run


def reject(db: Session, run: AgentRun, actor: str = "user") -> AgentRun:
    if run.status != "proposed":
        raise ValueError(f"run is {run.status}")
    run.status, run.approved_by = "rejected", actor
    audit("agents.reject", "agent_run", run.id, {"actor": actor}, actor=actor, db=db)
    emit("agents.rejected", {"id": run.id}, db=db)
    return run


def run_dict(r: AgentRun, full: bool = True) -> dict:
    d = {"id": r.id, "mode": r.mode, "provider": r.provider, "auth_mode": r.auth_mode, "model": r.model,
         "orchestration": r.orchestration, "symbols": r.symbols, "status": r.status, "approved_by": r.approved_by,
         "proposals": r.proposals, "duration_ms": r.duration_ms, "error": r.error,
         "created_at": r.created_at.isoformat() if r.created_at else None,
         "agents": len({(t["symbol"], t["agent"]) for t in (r.trace or []) if not t.get("control")})}
    if full:
        d["trace"], d["orders"] = r.trace, r.orders
    return d


def memory_list(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(limit))
    return [{"id": m.id, "topic": m.topic, "kind": m.kind, "content": m.content, "data": m.data,
             "created_at": m.created_at.isoformat()} for m in rows]
