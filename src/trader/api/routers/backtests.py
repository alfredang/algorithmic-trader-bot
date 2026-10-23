"""Backtests, research runs, analytics and exports."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.api.schemas import BacktestRequest
from trader.core.costs import COST_PRESETS
from trader.core.metrics import METRIC_DEFINITIONS
from trader.db import get_db
from trader.models import Backtest, Bot, ResearchRun
from trader.services import backtests as BT
from trader.services import research as R
from trader.services import tearsheet as TS
from trader.services.events import stage
from trader.services.seed import SAMPLE_BACKTESTS

SAMPLE_NAMES = {b["name"] for b in SAMPLE_BACKTESTS}   # course samples the labs refer to - never deleted

router = APIRouter(prefix="/api", tags=["backtests & research"])


@router.get("/costs/presets")
def cost_presets():
    return {k: v.to_dict() for k, v in COST_PRESETS.items()}


@router.get("/metrics/definitions")
def metric_definitions():
    return METRIC_DEFINITIONS


@router.post("/backtests")
def run_backtest(req: BacktestRequest, db: Session = Depends(get_db)):
    try:
        bt = BT.run(db, req.model_dump())
    except (KeyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    if bt.status == "error":
        raise HTTPException(400, bt.error or "backtest failed")
    return BT.to_dict(bt)


@router.get("/backtests")
def list_backtests(limit: int = 100, strategy: str | None = None, db: Session = Depends(get_db)):
    q = select(Backtest).order_by(Backtest.id.desc()).limit(limit)
    if strategy:
        q = q.where(Backtest.strategy_key == strategy)
    rows = list(db.scalars(q))
    if not strategy:   # the course samples stay listed however many runs come after them
        seen = {b.id for b in rows}
        rows += [b for b in db.scalars(select(Backtest).where(Backtest.name.in_(SAMPLE_NAMES)).order_by(Backtest.id.desc()))
                 if b.id not in seen]
    return [BT.to_dict(b, full=False) | {"sample": b.name in SAMPLE_NAMES} for b in rows]


def _delete_runs(db: Session, runs: list[Backtest]) -> list[int]:
    ids = [b.id for b in runs]
    if ids:
        for bot in db.scalars(select(Bot).where(Bot.backtest_id.in_(ids))):
            bot.backtest_id = None   # the bot keeps running; it just loses its backtest-vs-forward link
        for b in runs:
            db.delete(b)
        db.commit()
    return ids


@router.post("/backtests/delete")
def delete_backtests(body: dict = Body(...), db: Session = Depends(get_db)):
    """Delete the given runs, or every run except the course samples with {"all": true}."""
    if body.get("all"):
        runs = list(db.scalars(select(Backtest).where(Backtest.name.not_in(SAMPLE_NAMES))))
    else:
        ids = [int(i) for i in body.get("ids") or []]
        runs = list(db.scalars(select(Backtest).where(Backtest.id.in_(ids)))) if ids else []
    kept = [b.id for b in runs if b.name in SAMPLE_NAMES]
    deleted = _delete_runs(db, [b for b in runs if b.name not in SAMPLE_NAMES])
    return {"deleted": deleted, "kept_samples": kept}


@router.get("/backtests/compare")
def compare(ids: str = Query(..., description="comma-separated backtest ids"), db: Session = Depends(get_db)):
    out = []
    for i in [int(x) for x in ids.split(",") if x.strip()][:6]:
        b = db.get(Backtest, i)
        if b:
            out.append({"id": b.id, "name": b.name, "metrics": b.metrics, "cost_summary": b.cost_summary,
                        "equity": (b.series or {}).get("equity", []), "drawdown": (b.series or {}).get("drawdown", [])})
    return out


@router.get("/backtests/{bid}")
def get_backtest(bid: int, db: Session = Depends(get_db)):
    b = db.get(Backtest, bid)
    if not b:
        raise HTTPException(404, "backtest not found")
    return BT.to_dict(b)


@router.delete("/backtests/{bid}")
def delete_backtest(bid: int, db: Session = Depends(get_db)):
    b = db.get(Backtest, bid)
    if not b:
        raise HTTPException(404, "backtest not found")
    if b.name in SAMPLE_NAMES:
        raise HTTPException(400, "course sample runs are kept - the labs refer to them")
    _delete_runs(db, [b])
    return {"deleted": bid}


@router.get("/backtests/{bid}/export.csv", response_class=PlainTextResponse)
def export_csv(bid: int, what: str = "equity", db: Session = Depends(get_db)):
    b = db.get(Backtest, bid)
    if not b:
        raise HTTPException(404, "backtest not found")
    body = TS.csv_trades(b) if what == "trades" else TS.csv_equity(b)
    return PlainTextResponse(body, headers={"Content-Disposition": f'attachment; filename="backtest_{bid}_{what}.csv"'})


@router.get("/backtests/{bid}/tearsheet.pdf")
def tearsheet(bid: int, db: Session = Depends(get_db)):
    b = db.get(Backtest, bid)
    if not b:
        raise HTTPException(404, "backtest not found")
    pdf = TS.pdf(b)
    stage("reporting", "ok", f"Tearsheet PDF for backtest #{bid}", {"backtest_id": bid}, ref_type="backtest", ref_id=bid, db=db)
    db.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="tearsheet_backtest_{bid}.pdf"'})


# --------------------------------------------------------------------------- research
def _done(db, rr):
    db.commit()
    if rr.status == "error":
        raise HTTPException(400, rr.error or "research run failed")
    return R.to_dict(rr)


@router.post("/research/hypothesis")
def hypothesis(body: dict = Body(..., examples=[{"symbol": "SPY", "signal": {"type": "losing_streak", "n": 3},
                                                 "horizon": 1, "alpha": 0.05, "min_edge_bps": 3}]),
               db: Session = Depends(get_db)):
    return _done(db, R.hypothesis(db, body.get("symbol", "SPY"), body.get("signal"), int(body.get("horizon", 1)),
                                  float(body.get("alpha", 0.05)), float(body.get("min_edge_bps", 3)),
                                  body.get("h0", ""), body.get("h1", ""), body.get("start"), body.get("end"),
                                  body.get("robustness_symbols")))


@router.get("/research/hypothesis/signals")
def hypothesis_signals():
    from trader.core.stats import HYPOTHESIS_SIGNALS
    return HYPOTHESIS_SIGNALS


@router.get("/research/grids")
def grids():
    return R.DEFAULT_GRIDS


@router.post("/research/grid")
def grid(body: dict = Body(..., examples=[{"strategy_key": "sma_cross", "symbol": "SPY", "split_date": "2021-12-31"}]),
         db: Session = Depends(get_db)):
    return _done(db, R.grid_search(db, body.get("strategy_key", "sma_cross"), body.get("symbol", "SPY"), body.get("grid"),
                                   body.get("split_date", "2021-12-31"), body.get("config")))


@router.post("/research/walk-forward")
def walk_forward(body: dict = Body(..., examples=[{"strategy_key": "sma_cross", "symbol": "SPY"}]),
                 db: Session = Depends(get_db)):
    return _done(db, R.walk_forward(db, body.get("strategy_key", "sma_cross"), body.get("symbol", "SPY"), body.get("grid"),
                                    int(body.get("train_bars", 756)), int(body.get("test_bars", 252)), body.get("config")))


@router.post("/research/abtest")
def abtest(body: dict = Body(..., examples=[{"a": {"strategy_key": "trend_filter"}, "b": {"strategy_key": "dip_buy"},
                                             "symbol": "SPY", "alpha": 0.05, "tried": 20}]),
           db: Session = Depends(get_db)):
    return _done(db, R.abtest(db, body["a"], body["b"], body.get("symbol", "SPY"), float(body.get("alpha", 0.05)),
                              int(body.get("tried", 20)), body.get("config")))


@router.post("/research/regime")
def regime(body: dict = Body(default={}), db: Session = Depends(get_db)):
    return _done(db, R.regimes(db, body.get("symbol", "SPY"), body.get("universe"), int(body.get("clusters", 3)),
                               body.get("base", "ema_cross"), body.get("base_params"), body.get("config")))


@router.post("/research/diagnostics")
def diagnostics(body: dict = Body(..., examples=[{"strategy_key": "custom_lab18_biased_smoothed_momentum", "symbol": "SPY"}]),
                db: Session = Depends(get_db)):
    return _done(db, R.diagnostics(db, body.get("strategy_key", "ema_cross"), body.get("symbol", "SPY"), body.get("params"),
                                   int(body.get("trials", 76)), body.get("split_date", "2021-12-31"), body.get("config")))


@router.post("/research/pairs")
def pairs(body: dict = Body(default={}), db: Session = Depends(get_db)):
    return _done(db, R.pairs_screen(db, body.get("pairs"), body.get("formation_end", "2022-12-31")))


@router.post("/research/ml")
def ml(body: dict = Body(default={}), db: Session = Depends(get_db)):
    return _done(db, R.ml_report(db, body.get("symbol", "SPY"), body.get("models"), float(body.get("threshold", 0.55)),
                                 bool(body.get("tune", True))))


@router.post("/research/execution")
def execution(body: dict = Body(default={}), db: Session = Depends(get_db)):
    return _done(db, R.execution_compare(db, body.get("symbol", "SPY"), body.get("day"), body.get("side", "buy"),
                                         float(body.get("qty", 50000)), float(body.get("participation", 0.1)),
                                         float(body.get("impact_coef", 0.1))))


@router.get("/research")
def list_research(kind: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = select(ResearchRun).order_by(ResearchRun.id.desc()).limit(limit)
    if kind:
        q = q.where(ResearchRun.kind == kind)
    return [R.to_dict(r, full=False) for r in db.scalars(q)]


@router.get("/research/{rid}")
def get_research(rid: int, db: Session = Depends(get_db)):
    r = db.get(ResearchRun, rid)
    if not r:
        raise HTTPException(404, "research run not found")
    return R.to_dict(r)


# --------------------------------------------------------------------------- analytics
@router.get("/analytics/summary")
def summary(db: Session = Depends(get_db)):
    from trader.bots.runner import bot_dict
    bts = list(db.scalars(select(Backtest).where(Backtest.status == "done").order_by(Backtest.id.desc()).limit(50)))
    best = sorted([b for b in bts if (b.metrics or {}).get("sharpe") is not None],
                  key=lambda b: -(b.metrics or {}).get("sharpe"))[:5]
    bots = [bot_dict(db, b) for b in db.scalars(select(Bot))]
    return {"backtests": len(bts), "best": [BT.to_dict(b, full=False) for b in best],
            "recent": [BT.to_dict(b, full=False) for b in bts[:8]], "bots": bots}
