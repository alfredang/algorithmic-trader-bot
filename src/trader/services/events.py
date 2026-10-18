"""Events (SSE stream), audit log and Pipeline Map stage events - all persisted in the DB so the
API process and the worker process share one live view."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from trader.db import session_scope
from trader.models import AuditLog, Event, StageEvent

log = logging.getLogger("trader")


def _write(obj, db: Session | None):
    if db is not None:
        db.add(obj)
        db.flush()
        return
    try:
        with session_scope() as s:
            s.add(obj)
    except Exception as exc:          # pragma: no cover - never let telemetry break a trade path
        log.warning("event write failed: %s", exc)


def emit(kind: str, payload: dict | None = None, db: Session | None = None) -> None:
    _write(Event(kind=kind, payload=_jsonable(payload or {})), db)


def audit(action: str, entity: str = "", entity_id="", detail: dict | None = None, actor: str = "system",
          db: Session | None = None) -> None:
    _write(AuditLog(action=action, entity=entity, entity_id=str(entity_id), detail=_jsonable(detail or {}), actor=actor), db)


def stage(stage: str, status: str = "ok", message: str = "", metrics: dict | None = None, ref_type: str | None = None,
          ref_id=None, run_id: str | None = None, db: Session | None = None) -> None:
    """Record activity of a Pipeline Map stage and broadcast it."""
    m = _jsonable(metrics or {})
    _write(StageEvent(stage=stage, status=status, message=message[:2000], metrics=m, ref_type=ref_type,
                      ref_id=str(ref_id) if ref_id is not None else None, run_id=run_id), db)
    _write(Event(kind="stage", payload={"stage": stage, "status": status, "message": message[:300], "metrics": m,
                                        "ref_type": ref_type, "ref_id": ref_id, "run_id": run_id}), db)


def _jsonable(x):
    import math
    from datetime import date, datetime

    import numpy as np
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return x


jsonable = _jsonable
