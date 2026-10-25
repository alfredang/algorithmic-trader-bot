"""AI agents: the 8-agent workflow, its performance and strategy guidance, the always-on agent and memory."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.agents import live, workflow
from trader.agents import performance as PERF
from trader.agents.providers import resolve, status_all
from trader.agents.roles import ALGORITHMS, DEFAULT_GUIDANCE, PARALLEL, ROLE_ORDER, ROLES, TAXONOMY
from trader.api.schemas import AgentRunRequest, AgentSettings, AlwaysOnConfig
from trader.content.course import AGENT_RISKS, MULTI_AGENT_TRADING
from trader.db import get_db
from trader.models import AgentMemory, AgentRun, Setting
from trader.scheduler import always_on_config

router = APIRouter(prefix="/api/agents", tags=["ai agents"])


@router.get("/providers")
def providers():
    p = resolve(None)
    return {"active": p.name, "providers": status_all()}


@router.get("/roles")
def roles():
    return {"order": ROLE_ORDER, "parallel": PARALLEL, "algorithms": ALGORITHMS,
            "roles": [{"key": r.key, "title": r.title, "stage": r.stage, "scope": r.scope, "instructions": r.instructions,
                       "tools": list(r.tools), "output": r.output, "code": r.code} for r in ROLES.values()],
            "taxonomy": TAXONOMY, "risks": [{"risk": a, "example": b, "control": c} for a, b, c in AGENT_RISKS],
            "systems": [{"name": a, "description": b, "url": c} for a, b, c in MULTI_AGENT_TRADING]}


def _settings(db: Session) -> dict:
    from trader.config import get_settings
    s = get_settings()
    return {"position_pct": workflow.position_pct(db), "order_type": "market (regular session; marketable limit outside it)",
            "broker": "Alpaca paper" if s.alpaca_configured else "simulator",
            "account": workflow.ALPACA_ACCOUNT if s.alpaca_configured else workflow.SIM_ACCOUNT,
            "data_mode": s.agent_data_mode, "human_approval": False, "risk_limits": False,
            "note": "Orders are placed automatically on the PAPER account, without human approval or agent risk limits. "
                    "The global kill switch still halts everything."}


@router.get("/settings")
def get_agent_settings(db: Session = Depends(get_db)):
    return _settings(db)


@router.put("/settings")
def put_agent_settings(body: AgentSettings, db: Session = Depends(get_db)):
    workflow.set_position_pct(db, body.position_pct)
    db.commit()
    return _settings(db)


@router.post("/run")
def run(req: AgentRunRequest, db: Session = Depends(get_db)):
    if not req.symbols:
        raise HTTPException(400, "give at least one symbol")
    if req.data_mode and req.data_mode not in workflow.DATA_MODES:
        raise HTTPException(400, f"data_mode must be one of {', '.join(workflow.DATA_MODES)}")
    try:
        r = workflow.run_workflow(db, req.symbols, req.provider, orchestration=req.orchestration, data_mode=req.data_mode,
                                  live_id=req.live_id)
    except Exception:
        live.finish(req.live_id, None, "error")
        raise
    db.commit()
    return workflow.run_dict(r)


@router.get("/live/{live_id}")
def live_progress(live_id: str):
    """Agent-by-agent status of a workflow run while it is still running (polled by the AI Agents page)."""
    p = live.get(live_id)
    if p is None:
        raise HTTPException(404, "no live workflow run with that id")
    return p


@router.get("/runs")
def runs(limit: int = 30, db: Session = Depends(get_db)):
    return [workflow.run_dict(r, full=False) for r in db.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(limit))]


@router.get("/runs/{rid}")
def get_run(rid: int, db: Session = Depends(get_db)):
    r = db.get(AgentRun, rid)
    if not r:
        raise HTTPException(404, "agent run not found")
    return workflow.run_dict(r)


@router.get("/performance")
def performance(refresh: bool = False, db: Session = Depends(get_db)):
    """Latest performance of the agent account (persisted by the Performance Analysis agent); refresh=true recomputes."""
    if refresh:
        from trader.broker import service as BRK
        from trader.config import get_settings
        name = workflow.ALPACA_ACCOUNT if get_settings().alpaca_configured else workflow.SIM_ACCOUNT
        acct = BRK.get_account(db, name, create=False)
        if acct is None:
            return {"available": False, "note": "the agents have not traded yet - run the workflow first"}
        m = PERF.compute(db, acct)
        PERF.persist(db, m, (PERF.latest(db) or {}).get("run_id"))
        db.commit()
    m = PERF.latest(db)
    return {"available": True, **m} if m else {"available": False, "note": "the agents have not traded yet - run the workflow first"}


@router.get("/guidance")
def get_guidance(limit: int = 10, db: Session = Depends(get_db)):
    """The Strategy Review agent's latest guidance (read by the Trading Strategy agent next run) and its history."""
    hist = db.scalars(select(AgentMemory).where(AgentMemory.kind == "guidance").order_by(AgentMemory.created_at.desc()).limit(limit))
    return {"current": workflow.guidance(db), "default": DEFAULT_GUIDANCE,
            "history": [{"created_at": m.created_at.isoformat(), "content": m.content, "guidance": m.data} for m in hist]}


@router.get("/always-on")
def get_always_on(db: Session = Depends(get_db)):
    hb = db.get(Setting, "worker_heartbeat")
    last = db.scalar(select(AgentRun).where(AgentRun.mode == "always_on").order_by(AgentRun.id.desc()).limit(1))
    return {**always_on_config(db), "worker_heartbeat": hb.value if hb else None,
            "last_run": workflow.run_dict(last, full=False) if last else None}


@router.put("/always-on")
def put_always_on(cfg: AlwaysOnConfig, db: Session = Depends(get_db)):
    if cfg.data_mode not in workflow.DATA_MODES:
        raise HTTPException(400, f"data_mode must be one of {', '.join(workflow.DATA_MODES)}")
    s = db.get(Setting, "always_on") or Setting(key="always_on")
    s.value = cfg.model_dump()
    db.add(s)
    db.commit()
    return get_always_on(db)


@router.post("/always-on/run-now")
def always_on_now(live_id: str | None = None, db: Session = Depends(get_db)):
    cfg = always_on_config(db)
    try:
        r = workflow.run_workflow(db, cfg["symbols"], cfg.get("provider"), mode="always_on", live_id=live_id,
                                  data_mode=cfg.get("data_mode"), refresh_news=cfg.get("refresh_news", True))
    except Exception:
        live.finish(live_id, None, "error")
        raise
    db.commit()
    return workflow.run_dict(r)


@router.get("/memory")
def memory(limit: int = 50, db: Session = Depends(get_db)):
    return workflow.memory_list(db, limit)
