"""AI agents: the multi-agent desk, approvals, the always-on agent and memory."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.agents import desk
from trader.agents.providers import resolve, status_all
from trader.agents.roles import DEFAULT_LIMITS, ROLE_ORDER, ROLES, TAXONOMY
from trader.api.schemas import AgentRunRequest, AlwaysOnConfig
from trader.content.course import AGENT_RISKS, MULTI_AGENT_TRADING
from trader.db import get_db
from trader.models import AgentRun, Setting
from trader.scheduler import always_on_config

router = APIRouter(prefix="/api/agents", tags=["ai agents"])


@router.get("/providers")
def providers():
    p = resolve(None)
    return {"active": p.name, "providers": status_all()}


@router.get("/roles")
def roles():
    return {"order": ROLE_ORDER, "roles": [{"key": r.key, "title": r.title, "stage": r.stage, "instructions": r.instructions,
                                            "tools": list(r.tools), "output": r.output} for r in ROLES.values()],
            "taxonomy": TAXONOMY, "risks": [{"risk": a, "example": b, "control": c} for a, b, c in AGENT_RISKS],
            "systems": [{"name": a, "description": b, "url": c} for a, b, c in MULTI_AGENT_TRADING]}


@router.get("/limits")
def limits(db: Session = Depends(get_db)):
    return {**desk.desk_limits(db), "auto_approve": desk.desk_auto_approve(db)}


@router.put("/limits")
def set_limits(body: dict = Body(...), db: Session = Depends(get_db)):
    lim = {k: body[k] for k in DEFAULT_LIMITS if k in body}
    s = db.get(Setting, "agent_limits") or Setting(key="agent_limits")
    s.value = {**(s.value or {}), **lim}
    db.add(s)
    if "auto_approve" in body:
        a = db.get(Setting, "agent_auto_approve") or Setting(key="agent_auto_approve")
        a.value = bool(body["auto_approve"])
        db.add(a)
    db.commit()
    return {**desk.desk_limits(db), "auto_approve": desk.desk_auto_approve(db)}


@router.post("/run")
def run(req: AgentRunRequest, db: Session = Depends(get_db)):
    if not req.symbols:
        raise HTTPException(400, "give at least one symbol")
    r = desk.run_desk(db, req.symbols, req.provider, orchestration=req.orchestration)
    db.commit()
    return desk.run_dict(r)


@router.get("/runs")
def runs(limit: int = 30, db: Session = Depends(get_db)):
    return [desk.run_dict(r, full=False) for r in db.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(limit))]


@router.get("/runs/{rid}")
def get_run(rid: int, db: Session = Depends(get_db)):
    r = db.get(AgentRun, rid)
    if not r:
        raise HTTPException(404, "agent run not found")
    return desk.run_dict(r)


@router.post("/runs/{rid}/{action}")
def decide(rid: int, action: str, db: Session = Depends(get_db)):
    r = db.get(AgentRun, rid)
    if not r:
        raise HTTPException(404, "agent run not found")
    try:
        if action == "approve":
            desk.approve(db, r, actor="user (human approval)")
        elif action == "reject":
            desk.reject(db, r)
        else:
            raise HTTPException(400, "action must be approve or reject")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return desk.run_dict(r)


@router.get("/always-on")
def get_always_on(db: Session = Depends(get_db)):
    hb = db.get(Setting, "worker_heartbeat")
    last = db.scalar(select(AgentRun).where(AgentRun.mode == "always_on").order_by(AgentRun.id.desc()).limit(1))
    return {**always_on_config(db), "worker_heartbeat": hb.value if hb else None,
            "last_run": desk.run_dict(last, full=False) if last else None}


@router.put("/always-on")
def put_always_on(cfg: AlwaysOnConfig, db: Session = Depends(get_db)):
    s = db.get(Setting, "always_on") or Setting(key="always_on")
    s.value = cfg.model_dump()
    db.add(s)
    db.commit()
    return get_always_on(db)


@router.post("/always-on/run-now")
def always_on_now(db: Session = Depends(get_db)):
    cfg = always_on_config(db)
    from trader.data import service as data
    for s in cfg["symbols"]:
        try:
            data.fetch_news(db, s)
        except Exception:
            pass
    r = desk.run_desk(db, cfg["symbols"], cfg.get("provider"), mode="always_on")
    db.commit()
    return desk.run_dict(r)


@router.get("/memory")
def memory(limit: int = 50, db: Session = Depends(get_db)):
    return desk.memory_list(db, limit)
