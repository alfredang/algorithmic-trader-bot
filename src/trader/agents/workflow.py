"""The 8-agent workflow orchestrator. See roles.py for the agents and the course taxonomy.

    1. Lead Agent              plans the run                                   (once per run)
    2. Finance Research  ||  3. News Sentiment   in parallel - natively orchestrated by the provider where the
                                                  SDK supports it (Claude subagents / OpenAI agents-as-tools)
    4. Trading Strategy        picks algorithm(s) + weights; votes and the composite are computed in code
    5. Signal Generation       long | short | null
    6. Stock Trader            market order on the Alpaca PAPER account (simulator without keys) - automatic,
                               no human approval and no agent risk limits (owner's choice); the global kill switch,
                               session rules and paper-only still apply
    7. Performance Analysis    metrics of the agent account, computed in code            (once per run)
    8. Strategy Review         new guidance -> Setting ``agent_strategy_guidance``       (once per run)
       -> read by the Trading Strategy agent on the NEXT run (feedback loop); the Lead Agent then writes the summary.
Steps 2-6 run for every symbol. Every agent call is one trace entry: agent, brain (provider, rules or code),
tools, output, latency. The lead's plan and summary are its two rounds in one entry.
"""
from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.agents import algorithms as ALG
from trader.agents import live
from trader.agents import performance as PERF
from trader.agents import rules as RULES
from trader.agents.providers import Provider, RulesProvider, resolve
from trader.agents.roles import ALGORITHMS, DEFAULT_GUIDANCE, PARALLEL, ROLES
from trader.agents.tools import build_context
from trader.broker import service as BRK
from trader.config import get_settings
from trader.models import AgentMemory, AgentRun, PnLSnapshot, Setting, utcnow
from trader.services.events import audit, emit, jsonable, stage

log = logging.getLogger("trader.agents")

SIM_ACCOUNT = "Agent account (simulator)"
ALPACA_ACCOUNT = "Agent account (Alpaca paper)"
GUIDANCE_KEY = "agent_strategy_guidance"
POSITION_KEY = "agent_position_pct"
# the agent path sends orders WITHOUT position / value / daily-loss caps and may sell short (owner's decision);
# the kill switch, market-session rules and duplicate protection in broker.risk still apply
NO_LIMITS = {"long_only": False, "max_position_pct": 0, "max_order_value": 0, "max_order_qty": 0,
             "max_daily_loss_pct": 1.0, "allowed_symbols": []}
DATA_MODES = ("auto", "offline")


# --------------------------------------------------------------------------- settings
def position_pct(db: Session) -> float:
    s = db.get(Setting, POSITION_KEY)
    v = s.value if s is not None and s.value is not None else get_settings().agent_position_pct
    return _num(v, 0.10, 0.001, 1.0)


def set_position_pct(db: Session, value: float) -> float:
    s = db.get(Setting, POSITION_KEY) or Setting(key=POSITION_KEY)
    s.value = _num(value, 0.10, 0.001, 1.0)
    db.add(s)
    db.flush()
    return s.value


def guidance(db: Session) -> dict:
    """Latest Strategy Review guidance merged over the defaults (``run_id`` None = never reviewed yet)."""
    s = db.get(Setting, GUIDANCE_KEY)
    v = (s.value if s else None) or {}
    g = {**DEFAULT_GUIDANCE, "run_id": None, "updated_at": None, **v}
    g["weights"] = ALG.normalise_weights(g.get("weights"), DEFAULT_GUIDANCE["weights"])
    return g


def save_guidance(db: Session, review: dict, run_id: int) -> dict:
    keep = ("weights", "long_above", "short_below", "sentiment_weight", "finance_weight", "preferred_algorithms", "notes",
            "summary", "hit_rates")
    g = {k: review[k] for k in keep if k in review}
    g.update(run_id=run_id, updated_at=utcnow().isoformat(timespec="seconds"))
    s = db.get(Setting, GUIDANCE_KEY) or Setting(key=GUIDANCE_KEY)
    s.value = jsonable(g)
    db.add(s)
    db.add(AgentMemory(topic="strategy", kind="guidance", content=f"run #{run_id}: {g.get('summary', '')} "
                       f"{' '.join(g.get('notes') or [])}"[:2000], data=jsonable(g)))
    db.flush()
    return g


def agent_account(db: Session, mode: str) -> tuple:
    """Alpaca PAPER account when keys are set (and the data mode is not offline), else the built-in simulator."""
    note = None
    if mode != "offline" and get_settings().alpaca_configured:
        acct = BRK.get_account(db, ALPACA_ACCOUNT, broker="alpaca_paper")
        try:
            br = BRK.broker_for(db, acct)
            equity = br.equity()
            try:
                br.sync()
            except Exception as exc:
                log.warning("alpaca sync failed: %s", exc)
            return acct, br, equity, None
        except Exception as exc:
            note = f"Alpaca paper account unavailable ({type(exc).__name__}: {str(exc)[:160]}) - using the simulator"
    acct = BRK.get_account(db, SIM_ACCOUNT)
    br = BRK.SimBroker(db, acct)
    return acct, br, br.equity(), note


# --------------------------------------------------------------------------- one agent call
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


def _s(x, n: int = 400) -> str:
    return ("" if x is None else str(x))[:n]


def _l(x, n: int = 8, m: int = 240) -> list[str]:
    if x is None:
        return []
    if not isinstance(x, list):
        x = [x]
    return [_s(i, m) for i in x if i not in (None, "")][:n]


def _signal(x) -> str | None:
    v = (str(x).strip().lower() if x is not None else "")
    return v if v in ("long", "short") else None


def _sanitize(role_key: str, out: dict, ctx: dict, reports: dict) -> dict:
    """Coerce model output into the agent's JSON schema. Only the schema keys are taken from the model; anything
    missing or invalid comes from the rule brain, and code-computed keys (votes, composite, metrics...) are never
    taken from the model."""
    role = ROLES[role_key]
    base = RULES.BRAINS[role_key](ctx, reports)
    o = {**base, **{k: v for k, v in out.items() if k in role.output and v is not None}}
    if role_key == "lead":
        o = {"plan": _l(o.get("plan")), "focus": _s(o.get("focus"), 300), "summary": _s(o.get("summary"), 800)}
    elif role_key in ("finance_research", "news_sentiment"):
        o["score"] = round(_num(o.get("score"), 0.0, -1, 1), 2)
        o["summary"] = _s(o.get("summary"))
        for k in ("highlights", "risks"):
            if k in role.output:
                o[k] = _l(o.get(k))
        if role_key == "news_sentiment":
            n = o.get("notable") if isinstance(o.get("notable"), dict) else {}
            o["notable"] = {src: _l(n.get(src), 5) or base["notable"][src] for src in ("reddit", "newsapi")}
    elif role_key == "trading_strategy":
        o["weights"] = ALG.normalise_weights(o.get("weights"), base["weights"])
        algos = [a for a in (o.get("algorithms") or []) if a in ALGORITHMS] if isinstance(o.get("algorithms"), list) else []
        o["algorithms"] = algos or [k for k, v in sorted(o["weights"].items(), key=lambda kv: -kv[1]) if v >= 0.1]
        o["mode"] = o.get("mode") if o.get("mode") in ("single", "mix") else base["mode"]
        o["sentiment_weight"] = round(_num(o.get("sentiment_weight"), base["sentiment_weight"], 0, 0.5), 3)
        o["finance_weight"] = round(_num(o.get("finance_weight"), base["finance_weight"], 0, 0.5), 3)
        o["rationale"] = _s(o.get("rationale"))
        votes = ctx["votes"]
        o["composite"] = ALG.composite(votes, o["weights"], (reports.get("news_sentiment") or {}).get("score", 0.0),
                                       (reports.get("finance_research") or {}).get("score", 0.0),
                                       o["sentiment_weight"], o["finance_weight"])
        o["votes"] = votes["combined"]
        o["intervals_used"] = votes["intervals_used"]
        o["guidance_run_id"] = (ctx.get("guidance") or {}).get("run_id")
    elif role_key == "signal_generation":
        o["signal"] = _signal(out["signal"]) if "signal" in out else base["signal"]
        o["confidence"] = round(_num(o.get("confidence"), base["confidence"], 0, 1), 2)
        o["rationale"] = _s(o.get("rationale"))
        g = ctx.get("guidance") or DEFAULT_GUIDANCE
        o["composite"] = (reports.get("trading_strategy") or {}).get("composite", {}).get("composite")
        o["thresholds"] = {"long_above": g["long_above"], "short_below": g["short_below"]}
    elif role_key == "performance_analysis":
        o["summary"], o["observations"] = _s(o.get("summary"), 600), _l(o.get("observations"))
        m = ctx.get("metrics") or {}
        o["metrics"] = {k: v for k, v in m.items() if k not in ("equity_curve", "daily_returns", "recent_round_trips")}
        o["metrics"]["daily_returns"] = (m.get("daily_returns") or [])[-10:]
    elif role_key == "strategy_review":
        o["weights"] = ALG.normalise_weights(o.get("weights"), base["weights"])
        o["long_above"] = round(_num(o.get("long_above"), base["long_above"], 0.05, 0.8), 3)
        o["short_below"] = round(_num(o.get("short_below"), base["short_below"], -0.8, -0.05), 3)
        o["sentiment_weight"] = round(_num(o.get("sentiment_weight"), base["sentiment_weight"], 0, 0.5), 3)
        o["finance_weight"] = round(_num(o.get("finance_weight"), base["finance_weight"], 0, 0.5), 3)
        pref = o.get("preferred_algorithms") if isinstance(o.get("preferred_algorithms"), list) else []
        o["preferred_algorithms"] = [a for a in pref if a in ALGORITHMS][:6] or base["preferred_algorithms"]
        o["notes"], o["summary"] = _l(o.get("notes")), _s(o.get("summary"), 300)
        o["hit_rates"] = base["hit_rates"]
    return o


def _entry(role_key: str, ctx: dict, provider: Provider, brain: str, out: dict, ms: int, err: str | None,
           round_no: int = 1) -> dict:
    role = ROLES[role_key]
    return {"symbol": ctx["symbol"], "agent": role_key, "title": role.title, "stage": role.stage, "scope": role.scope,
            "round": round_no, "brain": brain, "model": provider.model or None, "tools": list(role.tools),
            "output": jsonable(out), "ms": ms, "error": err}


def _run_one(provider: Provider, role_key: str, ctx: dict, reports: dict, round_no: int = 1,
             native_out: dict | None = None, progress: live.Progress | None = None) -> tuple[dict, dict]:
    if progress:
        progress.start(ctx["symbol"], role_key, round_no)
    t0 = time.time()
    brain, err = provider.name, None
    if native_out is not None and role_key in native_out:
        out, brain = native_out[role_key], f"{provider.name} (native multi-agent)"
    else:
        try:
            out = provider.run_role(ROLES[role_key], ctx, reports, round_no)
            if not isinstance(out, dict):
                raise ValueError("agent did not return a JSON object")
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:300]}"
            out, brain = RULES.BRAINS[role_key](ctx, reports), "rules (fallback)"
    out = _sanitize(role_key, out, ctx, reports)
    entry = _entry(role_key, ctx, provider, brain, out, int((time.time() - t0) * 1000), err, round_no)
    if progress:
        progress.done(ctx["symbol"], role_key, entry)
    return out, entry


def _call(provider, role_key, ctx, reports, trace, progress=None) -> dict:
    out, entry = _run_one(provider, role_key, ctx, reports, progress=progress)
    trace.append(entry)
    return out


def _call_parallel(provider, keys, ctx, reports, trace, native_out=None, progress=None) -> dict[str, dict]:
    """Run independent agents concurrently (each sees the same reports); trace entries keep the role order."""
    snapshot = dict(reports)
    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        futs = {k: pool.submit(_run_one, provider, k, ctx, snapshot, 1, native_out, progress) for k in keys}
        results = {k: f.result() for k, f in futs.items()}
    for k in keys:
        trace.append(results[k][1])
    return {k: results[k][0] for k in keys}


# --------------------------------------------------------------------------- per-symbol steps
def research_and_signal(provider: Provider, ctx: dict, trace: list, orchestration: str,
                        progress: live.Progress | None = None) -> dict:
    """Finance Research || News Sentiment -> Trading Strategy -> Signal Generation for one symbol."""
    reports: dict = {}
    native_out = None
    if provider.supports_native and orchestration == "native":
        if progress:                      # one native call answers for both research agents
            for k in PARALLEL:
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
    reports.update(_call_parallel(provider, PARALLEL, ctx, reports, trace, native_out, progress))
    reports["trading_strategy"] = _call(provider, "trading_strategy", ctx, reports, trace, progress)
    reports["signal_generation"] = _call(provider, "signal_generation", ctx, reports, trace, progress)
    return reports


def execute(db: Session, acct, br, run_id: int, ctx: dict, reports: dict, session_override: str | None = None,
            progress: live.Progress | None = None) -> tuple[dict, dict]:
    """Stock Trader agent: deterministic code - turns the signal into PAPER market orders through the broker service."""
    sym = ctx["symbol"]
    if progress:
        progress.start(sym, "stock_trader")
    t0 = time.time()
    sig = reports["signal_generation"]["signal"]
    if acct.broker == "sim":
        br.mark(sym, ctx["price"])                  # fill the simulator at the price the agents just looked at
    # unfilled orders from earlier runs (queued while the market was closed) are replaced by this run's decision,
    # otherwise every run would queue another order on top of the last one
    stale = [o for o in br.open_orders(sym) if o.source == "agent"]
    cancelled = []
    for o in stale:
        try:
            br.cancel(o)
            cancelled.append(f"{o.side} {o.qty:g}")
        except Exception as exc:
            log.warning("could not cancel order %s: %s", o.id, exc)
    pos = br.position(sym)
    held = float(pos.qty) if pos else 0.0
    equity = br.equity()
    plan = RULES.plan_trade(sig, held, ctx["price"], equity, ctx["sizing"]["position_pct"])
    orders, notes = [], list(plan["notes"])
    if cancelled:
        notes.insert(0, f"cancelled {len(cancelled)} unfilled agent order(s) from earlier runs: {', '.join(cancelled)}")
    why = reports["signal_generation"].get("rationale", "")
    for leg in plan["legs"]:
        req = BRK.OrderRequest(symbol=sym, side=leg["side"], qty=float(leg["qty"]), type="auto",
                               client_order_id=BRK.client_id(f"agent{run_id}{leg['purpose'][0]}", sym, leg["side"], leg["qty"]),
                               note=f"agent run #{run_id} ({leg['purpose']}, signal {sig}): {why}"[:300],
                               meta={"run_id": f"agent-{run_id}"})
        rec = {"purpose": leg["purpose"], "side": leg["side"], "qty": leg["qty"]}
        try:
            r = BRK.place_order(db, acct, req, source="agent", limits=NO_LIMITS, broker=br,
                                session_override=session_override if acct.broker == "sim" else None)
            o = r["order"] or {}
            rec.update(ok=r["ok"], status=o.get("status"), type=o.get("type"), time_in_force=o.get("time_in_force"),
                       order_id=o.get("id"), filled_avg_price=o.get("filled_avg_price"), session=r["session"]["session"])
            if not r["ok"]:
                rec["error"] = (o.get("note") if o.get("status") == "rejected" else None) or r["risk"]["reason"]
        except Exception as exc:                     # e.g. the broker refuses to short this symbol
            rec.update(ok=False, status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        orders.append(rec)
        if not rec["ok"]:
            notes.append(f"{leg['side']} {leg['qty']:g} {sym} not placed: {rec.get('error')}")
            break                                    # never open a new position if closing the old one failed
    if acct.broker == "alpaca_paper" and orders:
        try:
            br.sync()
        except Exception as exc:
            notes.append(f"Alpaca sync failed: {str(exc)[:120]}")
    after = br.position(sym)
    out = {"action": plan["action"] if all(o["ok"] for o in orders) else "failed", "orders": orders, "notes": notes,
           "signal": sig, "position_before": held, "position_after": float(after.qty) if after else 0.0,
           "price": ctx["price"], "equity": round(equity, 2), "account": acct.name, "broker": acct.broker}
    entry = {"symbol": sym, "agent": "stock_trader", "title": ROLES["stock_trader"].title, "stage": "execution",
             "scope": "symbol", "round": 1, "brain": f"deterministic code ({'Alpaca paper' if acct.broker == 'alpaca_paper' else 'simulator'})",
             "model": None, "tools": list(ROLES["stock_trader"].tools), "output": jsonable(out),
             "ms": int((time.time() - t0) * 1000), "error": next((o.get("error") for o in orders if not o["ok"]), None)}
    if progress:
        progress.done(sym, "stock_trader", entry)
    return out, entry


def recent_signals(db: Session, prices: dict[str, float], exclude_run: int | None = None, limit: int = 40) -> list[dict]:
    """Past signals with how the price moved since (the Strategy Review agent's evidence)."""
    rows = db.scalars(select(AgentMemory).where(AgentMemory.kind == "signal").order_by(AgentMemory.created_at.desc()).limit(limit))
    out = []
    for r in rows:
        d = r.data or {}
        if exclude_run is not None and d.get("run_id") == exclude_run or not d.get("price"):
            continue
        now = prices.get(r.topic)
        if now is None:
            try:
                now = BRK.latest_price(db, r.topic)
            except Exception:
                now = None
        out.append({"symbol": r.topic, "run_id": d.get("run_id"), "when": r.created_at.isoformat()[:16],
                    "signal": d.get("signal"), "composite": d.get("composite"), "price_then": d["price"], "price_now": now,
                    "ret": round(now / d["price"] - 1, 5) if now else None, "votes": d.get("votes") or {},
                    "sentiment": d.get("sentiment"), "finance": d.get("finance")})
    return out


def _brief(rep: dict) -> dict:
    """One symbol's results, small enough for the lead's summary prompt."""
    fr, ns, ts = rep["finance_research"], rep["news_sentiment"], rep["trading_strategy"]
    sg, tr = rep["signal_generation"], rep["stock_trader"]
    return {"finance_research": {"score": fr["score"], "summary": fr["summary"]},
            "news_sentiment": {"score": ns["score"], "summary": ns["summary"]},
            "trading_strategy": {"mode": ts["mode"], "algorithms": ts["algorithms"], "composite": ts["composite"]["composite"]},
            "signal_generation": {"signal": sg["signal"], "confidence": sg["confidence"]},
            "stock_trader": {"action": tr["action"], "orders": [{k: o.get(k) for k in ("side", "qty", "ok", "status", "error")}
                                                                for o in tr["orders"]]}}


# --------------------------------------------------------------------------- the run
def run_workflow(db: Session, symbols: list[str], provider_name: str | None = None, mode: str = "manual",
                 orchestration: str = "native", provider: Provider | None = None, data_mode: str | None = None,
                 live_id: str | None = None, refresh_news: bool = True, session_override: str | None = None) -> AgentRun:
    t0 = time.time()
    syms = list(dict.fromkeys(s.upper().strip() for s in symbols if s and s.strip()))
    data_mode = (data_mode or get_settings().agent_data_mode or "auto").lower()
    if data_mode not in DATA_MODES:
        raise ValueError(f"data_mode must be one of {', '.join(DATA_MODES)}")
    provider = provider or resolve(provider_name)
    ok, why = provider.available()
    trace: list[dict] = []
    if not ok:
        trace.append({"symbol": "*", "agent": "orchestrator", "title": "Provider selection", "stage": "orchestration",
                      "brain": "deterministic code", "output": {"note": f"{provider.label} unavailable ({why}) - using the "
                                                                         "rule-based agents"},
                      "ms": 0, "error": None, "control": True})
        provider = RulesProvider()
    progress = live.Progress(live_id, syms, provider.name) if live_id else None
    run = AgentRun(mode=mode, provider=provider.name, auth_mode=provider.auth_mode, model=provider.model or "",
                   orchestration=orchestration if provider.supports_native else "pipeline", symbols=syms, status="running")
    db.add(run)
    db.flush()
    stage("agents", "running", f"Multi-agent workflow ({provider.name}) on {', '.join(syms)}", {"run_id": run.id},
          ref_type="agent_run", ref_id=run.id, db=db)
    results: dict[str, dict] = {}
    try:
        acct, br, equity, note = agent_account(db, data_mode)
        if note:
            trace.append({"symbol": "*", "agent": "orchestrator", "title": "Broker", "stage": "orchestration",
                          "brain": "deterministic code", "output": {"note": note}, "ms": 0, "error": None, "control": True})
        if not db.scalar(select(PnLSnapshot.id).where(PnLSnapshot.account_id == acct.id).limit(1)):
            acct.starting_cash = acct.last_equity = round(equity, 2)     # first agent run: today's equity is the base
        pct = position_pct(db)
        g = guidance(db)
        run_ctx = {"symbol": "*", "symbols": syms, "mode": data_mode, "provider": provider.name, "guidance": g,
                   "position_pct": pct, "account": acct.name, "phase": "plan",
                   "memory": [{"when": m.created_at.isoformat()[:16], "topic": m.topic, "kind": m.kind, "content": m.content}
                              for m in db.scalars(select(AgentMemory).where(AgentMemory.kind != "signal")
                                                  .order_by(AgentMemory.created_at.desc()).limit(6))]}
        # 1. lead: plan
        lead_plan, lead_entry = _run_one(provider, "lead", run_ctx, {}, 1, progress=progress)
        trace.append(lead_entry)
        # 2-6 per symbol
        prices: dict[str, float] = {}
        for sym in syms:
            if progress:
                progress.symbol(sym)
            pos = br.position(sym)
            try:
                ctx = build_context(db, sym, float(pos.qty) if pos else 0.0, br.equity(), g, data_mode, refresh_news, pct)
            except Exception as exc:
                trace.append({"symbol": sym, "agent": "orchestrator", "title": "Data", "stage": "orchestration",
                              "brain": "code", "output": {}, "ms": 0, "error": str(exc)[:300], "control": True})
                if progress:
                    progress.fail(sym, str(exc))
                continue
            prices[sym] = ctx["price"]
            reports = research_and_signal(provider, ctx, trace, orchestration, progress)
            reports["stock_trader"], entry = execute(db, acct, br, run.id, ctx, reports, session_override, progress)
            trace.append(entry)
            br.snapshot()
            results[sym] = {"ctx": ctx, "reports": reports}
        if progress:
            progress.symbol(None)
        # 7. performance analysis (account level)
        for p in br.positions():
            if acct.broker == "sim":
                try:
                    br.mark(p.symbol, prices.get(p.symbol) or BRK.latest_price(db, p.symbol))
                except Exception:
                    pass
        br.snapshot()
        metrics = PERF.compute(db, acct)
        run_ctx.update(metrics=metrics, recent_orders=PERF.recent_orders(db, acct))
        perf = _call(provider, "performance_analysis", run_ctx, {}, trace, progress)
        PERF.persist(db, metrics, run.id)
        # 8. strategy review -> guidance for the next run
        run_ctx["recent_signals"] = recent_signals(db, prices, exclude_run=run.id)
        review = _call(provider, "strategy_review", run_ctx, {"performance_analysis": perf}, trace, progress)
        new_g = save_guidance(db, review, run.id)
        # memory: one signal record per symbol (evaluated by later reviews) + a readable note
        for sym, r in results.items():
            rep, ctx = r["reports"], r["ctx"]
            sg, ts, tr = rep["signal_generation"], rep["trading_strategy"], rep["stock_trader"]
            db.add(AgentMemory(topic=sym, kind="signal", content=f"{ctx['as_of']}: {sg['signal'] or 'null'} "
                               f"(composite {ts['composite']['composite']:+.2f}) -> {tr['action']}",
                               data=jsonable({"run_id": run.id, "price": ctx["price"], "as_of": ctx["as_of"],
                                              "signal": sg["signal"], "composite": ts["composite"]["composite"],
                                              "votes": {a: v["score"] for a, v in ts["votes"].items()},
                                              "sentiment": rep["news_sentiment"]["score"],
                                              "finance": rep["finance_research"]["score"]})))
            db.add(AgentMemory(topic=sym, kind="decision" if mode == "always_on" else "observation",
                               content=f"{ctx['as_of']}: {sg['signal'] or 'null'} -> {tr['action']}. {sg.get('rationale', '')}"[:2000],
                               data={"run_id": run.id, "signal": sg["signal"], "action": tr["action"]}))
        # 1 (round 2). lead: summary
        run_ctx.update(phase="summary", review=review, results={s: _brief(r["reports"]) for s, r in results.items()})
        summ, summ_entry = _run_one(provider, "lead", run_ctx, {}, 2, progress=None)
        lead_entry.update(output=jsonable({**lead_plan, "summary": summ["summary"]}), round=2,
                          rounds=[jsonable(lead_plan), jsonable(summ)], ms=lead_entry["ms"] + summ_entry["ms"],
                          error=lead_entry["error"] or summ_entry["error"],
                          brain=lead_entry["brain"] if lead_entry["brain"] == summ_entry["brain"]
                          else f"{lead_entry['brain']} / {summ_entry['brain']}")
        if progress:
            progress.done("*", "lead", lead_entry)
        orders = [{"symbol": s, **o} for s, r in results.items() for o in r["reports"]["stock_trader"]["orders"]]
        run.proposals = jsonable([{"symbol": s, "signal": r["reports"]["signal_generation"]["signal"],
                                   "confidence": r["reports"]["signal_generation"]["confidence"],
                                   "composite": r["reports"]["trading_strategy"]["composite"]["composite"],
                                   "price": r["ctx"]["price"], "action": r["reports"]["stock_trader"]["action"],
                                   "rationale": r["reports"]["signal_generation"].get("rationale")} for s, r in results.items()])
        run.orders = jsonable(orders)
        run.status = "executed" if any(o["ok"] for o in orders) else "no_trade"
        msg = (f"Workflow run #{run.id} ({provider.name}): {sum(o['ok'] for o in orders)} paper order(s); guidance "
               f"updated (run #{new_g['run_id']})")
    except Exception as exc:
        log.exception("agent workflow failed")
        run.status, run.error = "error", f"{type(exc).__name__}: {str(exc)[:500]}"
        msg = f"Workflow run #{run.id} failed: {run.error}"
    run.trace = jsonable(trace)
    run.duration_ms = int((time.time() - t0) * 1000)
    db.flush()
    audit("agents.run", "agent_run", run.id, {"provider": provider.name, "symbols": syms, "status": run.status,
                                              "orders": len(run.orders or [])}, db=db)
    stage("agents", "error" if run.status == "error" else "ok", msg,
          {"run_id": run.id, "orders": len(run.orders or []), "provider": provider.name}, ref_type="agent_run",
          ref_id=run.id, db=db)
    emit("agents.run", {"id": run.id, "status": run.status, "orders": len(run.orders or [])}, db=db)
    if progress:
        progress.finish(run.id, run.status)
    return run


def run_dict(r: AgentRun, full: bool = True) -> dict:
    lead = next((t for t in (r.trace or []) if t.get("agent") == "lead"), None)
    d = {"id": r.id, "mode": r.mode, "provider": r.provider, "auth_mode": r.auth_mode, "model": r.model,
         "orchestration": r.orchestration, "symbols": r.symbols, "status": r.status, "signals": r.proposals or [],
         "orders": r.orders or [], "duration_ms": r.duration_ms, "error": r.error,
         "summary": ((lead or {}).get("output") or {}).get("summary"),
         "created_at": r.created_at.isoformat() if r.created_at else None,
         "agents": len([t for t in (r.trace or []) if not t.get("control")])}
    if full:
        d["trace"] = r.trace
    return d


def memory_list(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(AgentMemory).order_by(AgentMemory.created_at.desc()).limit(limit))
    return [{"id": m.id, "topic": m.topic, "kind": m.kind, "content": m.content, "data": m.data,
             "created_at": m.created_at.isoformat()} for m in rows]
