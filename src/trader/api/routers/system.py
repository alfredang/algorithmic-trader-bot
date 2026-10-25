"""System status, settings, integrations, TradingView webhook, Pipeline Map, events (SSE), labs and help."""
from __future__ import annotations

import asyncio
import json
import os

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from trader import __version__
from trader.config import LABS_MANIFEST, get_settings
from trader.content import course as C
from trader.core.metrics import METRIC_DEFINITIONS
from trader.db import SessionLocal, get_db
from trader.models import Backtest, Bar, Bot, Event, LabProgress, Setting, WebhookAlert
from trader.services import integrations as INT
from trader.services import pipeline as PIPE
from trader.services import webhook as WH

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)):
    s = get_settings()
    onb = db.get(Setting, "onboarding")
    from trader.agents.providers import resolve
    return {"version": __version__, "database": db.bind.dialect.name, "bars": int(db.scalar(select(func.count(Bar.id))) or 0),
            "backtests": int(db.scalar(select(func.count(Backtest.id))) or 0),
            "bots": int(db.scalar(select(func.count(Bot.id))) or 0),
            "broker": "Alpaca paper" if s.alpaca_configured else "simulator", "alpaca": s.alpaca_configured,
            "data_mode": "online (Alpaca)" if s.alpaca_configured else "offline demo data",
            "ai_provider": resolve(None).name, "onboarding": (onb.value if onb else {"done": False}),
            "paper_only": True, "scheduler_in_process": s.run_scheduler_in_process}


@router.post("/system/onboarding")
def onboarding(body: dict = Body(...), db: Session = Depends(get_db)):
    s = db.get(Setting, "onboarding") or Setting(key="onboarding")
    s.value = {"done": True, **body}
    db.add(s)
    db.commit()
    return s.value


@router.post("/system/seed")
def seed(quick: bool = False, db: Session = Depends(get_db)):
    from trader.services.seed import seed as do_seed
    logs: list[str] = []
    out = do_seed(db, quick=quick, log_fn=logs.append)
    db.commit()
    return {**out, "log": logs}


# --------------------------------------------------------------------------- settings / integrations
PREFS = {"theme": "system", "default_symbol": "SPY", "default_cost_preset": "alpaca_retail", "user": "local",
         "desk_timezone": "Asia/Singapore"}


@router.get("/settings")
def get_prefs(db: Session = Depends(get_db)):
    s = db.get(Setting, "preferences")
    s2 = get_settings()
    return {"preferences": {**PREFS, **((s.value if s else None) or {})},
            "env": {"DATABASE_URL": INT._db_url_masked(s2.database_url), "AI_PROVIDER": s2.ai_provider,
                    "CLAUDE_MODEL": s2.claude_model, "CLAUDE_MODEL_DEEP": s2.claude_model_deep,
                    "OPENAI_MODEL": s2.openai_model, "CODEX_MODEL": s2.codex_model,
                    "DEFAULT_DATA_SOURCE": s2.default_data_source, "RUN_SCHEDULER_IN_PROCESS": s2.run_scheduler_in_process,
                    "SANDBOX_TIMEOUT_S": s2.sandbox_timeout_s, "AGENT_POSITION_PCT": s2.agent_position_pct,
                    "AGENT_DATA_MODE": s2.agent_data_mode}}


@router.put("/settings")
def put_prefs(body: dict = Body(...), db: Session = Depends(get_db)):
    s = db.get(Setting, "preferences") or Setting(key="preferences")
    s.value = {**(s.value or {}), **{k: v for k, v in body.items() if k in PREFS or k == "ai_provider"}}
    db.add(s)
    db.commit()
    return get_prefs(db)


@router.get("/integrations")
def integrations(db: Session = Depends(get_db)):
    out = INT.status(db)
    db.commit()
    return out


@router.put("/integrations/{key}/keys")
def integration_keys(key: str, request: Request, body: dict = Body(...)):
    """Save API keys pasted into the Integrations page (to <DATA_DIR>/keys.env, never the DB)."""
    from trader.services import keys as K
    host = (request.client.host if request.client else "") or ""
    if os.environ.get("ALLOW_UI_KEYS", "true").lower() in ("0", "false", "no"):
        raise HTTPException(403, "Saving keys from the app is disabled (ALLOW_UI_KEYS=false); edit .env instead.")
    if not _local_client(host):
        raise HTTPException(403, "Keys can only be saved from this computer or your private network.")
    try:
        fields = K.save(key, values=body.get("values") or {}, clear=body.get("clear") or [])
    except K.KeyError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "editable": fields,
            "message": "Saved on this computer only (data/keys.env). It is used at once - no restart needed."}


def _local_client(host: str) -> bool:
    import ipaddress
    if host in ("localhost", "testclient", ""):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


@router.post("/integrations/{key}/test")
def integration_test(key: str, db: Session = Depends(get_db)):
    out = INT.test(db, key)
    db.commit()
    return out


# --------------------------------------------------------------------------- TradingView webhook
@router.post("/webhooks/tradingview", tags=["webhooks"])
async def tradingview(request: Request):
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")        # TradingView may send text/plain - parse anyway
    except json.JSONDecodeError:
        payload = raw.decode(errors="replace")
    db = SessionLocal()
    try:
        code, body = WH.handle(db, payload, client=request.client.host if request.client else "", raw=raw)
        db.commit()
    finally:
        db.close()
    from fastapi.responses import JSONResponse
    return JSONResponse(body, status_code=code)


@router.get("/webhooks/template", tags=["webhooks"])
def webhook_template(reveal: bool = False, db: Session = Depends(get_db)):
    out = WH.template(db, reveal)
    db.commit()
    return out


@router.put("/webhooks/config", tags=["webhooks"])
def webhook_config(body: dict = Body(...), db: Session = Depends(get_db)):
    s = db.get(Setting, "webhook") or Setting(key="webhook")
    s.value = {**(s.value or {}), **{k: v for k, v in body.items() if k in WH.DEFAULTS}}
    db.add(s)
    db.commit()
    return WH.config(db)


@router.get("/webhooks/alerts", tags=["webhooks"])
def webhook_alerts(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.scalars(select(WebhookAlert).order_by(WebhookAlert.id.desc()).limit(limit))
    return [{"id": a.id, "received_at": a.received_at.isoformat(), "alert_id": a.alert_id, "client": a.client,
             "ticker": a.ticker, "action": a.action, "qty": a.qty, "http": a.http_status, "result": a.result,
             "detail": a.detail, "pipeline_signal": a.pipeline_signal, "order_id": a.order_id, "payload": a.payload}
            for a in rows]


# --------------------------------------------------------------------------- Pipeline Map
@router.get("/pipeline/status", tags=["pipeline"])
def pipeline_status(db: Session = Depends(get_db)):
    return PIPE.status(db)


@router.get("/pipeline/events", tags=["pipeline"])
def pipeline_events(stage: str, limit: int = 30, db: Session = Depends(get_db)):
    return PIPE.events(db, stage, limit)


@router.get("/pipeline/lifecycle", tags=["pipeline"])
def pipeline_lifecycle(strategy_key: str = "ema_cross", sharpe_gate: float = 0.5, db: Session = Depends(get_db)):
    try:
        return PIPE.lifecycle(db, strategy_key, sharpe_gate)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# --------------------------------------------------------------------------- events (SSE)
@router.get("/events", tags=["events"])
def events(after: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    if after == 0:
        last = db.scalar(select(func.max(Event.id))) or 0
        return {"last_id": last, "events": []}
    rows = db.scalars(select(Event).where(Event.id > after).order_by(Event.id).limit(limit)).all()
    return {"last_id": rows[-1].id if rows else after,
            "events": [{"id": e.id, "ts": e.ts.isoformat() + "Z", "kind": e.kind, "payload": e.payload} for e in rows]}


@router.get("/events/stream", tags=["events"])
async def stream(request: Request, after: int | None = None):
    """Server-Sent Events: live bot / order / pipeline updates (tails the events table, works across processes)."""
    async def gen():
        db = SessionLocal()
        try:
            last = after if after is not None else (db.scalar(select(func.max(Event.id))) or 0)
            yield f"event: hello\ndata: {json.dumps({'last_id': last})}\n\n"
            idle = 0
            while True:
                if await request.is_disconnected():
                    break
                db.expire_all()
                rows = db.scalars(select(Event).where(Event.id > last).order_by(Event.id).limit(200)).all()
                db.rollback()
                for e in rows:
                    last = e.id
                    yield f"id: {e.id}\nevent: {e.kind}\ndata: {json.dumps({'id': e.id, 'kind': e.kind, 'payload': e.payload, 'ts': e.ts.isoformat() + 'Z'})}\n\n"
                idle = 0 if rows else idle + 1
                if idle >= 15:
                    yield ": keep-alive\n\n"
                    idle = 0
                await asyncio.sleep(1.0)
        finally:
            db.close()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- Course labs
def _manifest() -> dict:
    if not LABS_MANIFEST.exists():
        raise HTTPException(404, f"labs manifest not found at {LABS_MANIFEST}")
    return yaml.safe_load(LABS_MANIFEST.read_text())


def _user(db, user: str | None) -> str:
    if user:
        return user[:64]
    s = db.get(Setting, "preferences")
    return ((s.value if s else None) or {}).get("user", "local")


@router.get("/labs", tags=["labs"])
def labs(user: str | None = None, db: Session = Depends(get_db)):
    m = _manifest()
    u = _user(db, user)
    done = {(p.lab_id, p.step_index): p for p in db.scalars(select(LabProgress).where(LabProgress.user == u))}
    out = []
    for lab in m["labs"]:
        steps = lab.get("steps", [])
        completed = sum(1 for i in range(len(steps)) if (lab["id"], i) in done)
        out.append({**{k: v for k, v in lab.items() if k != "steps"}, "n_steps": len(steps), "completed": completed})
    return {"course": m.get("course"), "topics": m.get("topics"), "labs": out, "user": u}


@router.get("/labs/{lab_id}", tags=["labs"])
def lab(lab_id: int, user: str | None = None, db: Session = Depends(get_db)):
    m = _manifest()
    u = _user(db, user)
    lab = next((x for x in m["labs"] if int(x["id"]) == lab_id), None)
    if not lab:
        raise HTTPException(404, "lab not found")
    done = {p.step_index: p for p in db.scalars(select(LabProgress).where(LabProgress.user == u, LabProgress.lab_id == lab_id))}
    steps = [{**s, "index": i, "done": i in done, "completed_at": done[i].completed_at.isoformat() + "Z" if i in done else None}
             for i, s in enumerate(lab.get("steps", []))]
    return {**lab, "steps": steps, "user": u}


@router.post("/labs/{lab_id}/steps/{idx}", tags=["labs"])
def lab_step(lab_id: int, idx: int, body: dict = Body(default={"done": True}), user: str | None = None,
             db: Session = Depends(get_db)):
    u = _user(db, user)
    row = db.scalar(select(LabProgress).where(LabProgress.user == u, LabProgress.lab_id == lab_id, LabProgress.step_index == idx))
    if body.get("done", True):
        if row is None:
            db.add(LabProgress(user=u, lab_id=lab_id, step_index=idx, done=True, note=str(body.get("note", ""))[:500]))
    elif row is not None:
        db.delete(row)
    db.commit()
    return lab(lab_id, u, db)


@router.post("/labs/{lab_id}/reset", tags=["labs"])
def lab_reset(lab_id: int, user: str | None = None, db: Session = Depends(get_db)):
    u = _user(db, user)
    db.execute(delete(LabProgress).where(LabProgress.user == u, LabProgress.lab_id == lab_id))
    db.commit()
    return lab(lab_id, u, db)


# --------------------------------------------------------------------------- help / glossary
@router.get("/glossary", tags=["help"])
def glossary():
    return {"metrics": METRIC_DEFINITIONS, "topics": C.TOPICS, "algo_explain": C.ALGO_EXPLAIN,
            "algo_classes": [{"name": a, "purpose": b, "examples": c} for a, b, c in C.ALGO_CLASSES],
            "strategy_families": [{"name": a, "idea": b, "example": c} for a, b, c in C.STRATEGY_FAMILIES],
            "agentic_vs_agents": C.AGENTIC_VS_AGENTS, "definitions": C.ALGO_DEFINITIONS, "visuals": C.VISUALS,
            "course": {"title": C.COURSE_TITLE, "provider": C.PROVIDER, "tsc": C.TSC}}
