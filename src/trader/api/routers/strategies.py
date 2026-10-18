"""Strategy library, custom-strategy builder and Pine Script export."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.api.schemas import StrategyCode, StrategySave
from trader.content.course import ALGO_BY_HORIZON, ALGO_BY_MODEL, ALGO_CLASSES, STRATEGY_FAMILIES
from trader.data import service as data
from trader.db import get_db
from trader.models import StrategyRecord
from trader.services.events import audit, stage
from trader.strategies import pine, registry
from trader.strategies.builtin import REGISTRY

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("")
def list_strategies(db: Session = Depends(get_db)):
    return registry.list_all(db)


@router.get("/taxonomy")
def taxonomy():
    return {"classes": [{"name": a, "purpose": b, "examples": c} for a, b, c in ALGO_CLASSES],
            "families": [{"name": a, "idea": b, "example": c} for a, b, c in STRATEGY_FAMILIES],
            "horizons": [{"name": a, "holding": b, "examples": c} for a, b, c in ALGO_BY_HORIZON],
            "models": [{"name": a, "description": b} for a, b in ALGO_BY_MODEL]}


@router.get("/templates")
def templates():
    return [{"key": k, **v} for k, v in registry.TEMPLATES.items()]


@router.get("/{key}")
def get_strategy(key: str, db: Session = Depends(get_db)):
    try:
        return registry.get(db, key)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


def _data_for(db, body: StrategyCode, multi: bool):
    if multi or (body.symbols and len(body.symbols) > 1):
        return data.load_panel(db, body.symbols or ["SPY", "QQQ"])
    return data.load_bars(db, (body.symbols or [body.symbol])[0])


def _is_multi(code: str) -> bool:
    return "multi_asset = True" in code.replace(" ", " ")


@router.post("/validate")
def validate(body: StrategyCode, db: Session = Depends(get_db)):
    d = _data_for(db, body, _is_multi(body.code))
    return registry.validate_code(body.code, d, body.params)


@router.post("")
def save(body: StrategySave, db: Session = Depends(get_db)):
    d = _data_for(db, body, _is_multi(body.code))
    v = registry.validate_code(body.code, d, body.params)
    if not v["ok"]:
        raise HTTPException(422, {"message": "validation failed", "issues": v["issues"]})
    if body.key and body.key in REGISTRY:
        raise HTTPException(400, "built-in strategies cannot be overwritten - clone it first")
    rec = registry.save_custom(db, body.code, v["meta"], body.key, body.info, body.parent_key, v)
    audit("strategy.saved", "strategy", rec.key, {"name": rec.name}, actor="user", db=db)
    stage("strategy", "ok", f"Custom strategy '{rec.name}' saved and validated", {"key": rec.key}, db=db)
    db.commit()
    return registry.get(db, rec.key)


@router.post("/{key}/clone")
def clone(key: str, db: Session = Depends(get_db)):
    if key not in REGISTRY:
        rec = db.scalar(select(StrategyRecord).where(StrategyRecord.key == key))
        if rec is None:
            raise HTTPException(404, "unknown strategy")
        return {"code": rec.code, "parent_key": key}
    return {"code": registry.clone_code(key), "parent_key": key}


@router.delete("/{key}")
def delete(key: str, db: Session = Depends(get_db)):
    if key in REGISTRY:
        raise HTTPException(400, "built-in strategies cannot be deleted")
    rec = db.scalar(select(StrategyRecord).where(StrategyRecord.key == key))
    if rec is None:
        raise HTTPException(404, "unknown strategy")
    db.delete(rec)
    audit("strategy.deleted", "strategy", key, {}, actor="user", db=db)
    db.commit()
    return {"deleted": key}


@router.get("/{key}/pine", response_class=PlainTextResponse)
def pine_export(key: str, fast: int | None = None, slow: int | None = None, db: Session = Depends(get_db),
                commission: float = 0.0, slippage: int = 1, params: str = ""):
    desc = registry.get(db, key)
    p = dict(desc["default_params"])
    for kv in [x for x in params.split(",") if "=" in x]:
        k, v = kv.split("=", 1)
        p[k] = v
    if fast is not None:
        p["fast"] = fast
    if slow is not None:
        p["slow"] = slow
    p = registry.coerce_params(desc, p)
    try:
        return pine.export(key, p, desc["name"], commission, slippage)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
