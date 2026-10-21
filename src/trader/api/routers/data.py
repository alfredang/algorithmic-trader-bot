"""Market data, instruments, data quality, news and sentiment."""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trader.api.schemas import FetchRequest, NewsFetchRequest
from trader.core import data_quality as DQ
from trader.core import indicators as ta
from trader.data import providers as P
from trader.data import service as data
from trader.db import get_db
from trader.models import Bar, Instrument, NewsItem, SentimentDaily

router = APIRouter(prefix="/api", tags=["data"])


def _ts(t) -> int | str:
    t = pd.Timestamp(t)
    if t.tzinfo is not None:
        return int(t.tz_convert("UTC").timestamp())
    return t.strftime("%Y-%m-%d")


@router.get("/data/sources")
def sources():
    return [{"name": p.name, "label": p.label, "available": p.available()} for p in P.PROVIDERS.values()]


@router.get("/instruments")
def instruments(db: Session = Depends(get_db)):
    rows = db.scalars(select(Instrument).order_by(Instrument.symbol)).all()
    counts = dict(db.execute(select(Bar.symbol, func.count(Bar.id)).group_by(Bar.symbol)).all())
    return [{"symbol": i.symbol, "name": i.name, "exchange": i.exchange, "currency": i.currency,
             "tradingview_symbol": i.tradingview_symbol, "source": i.source,
             "first_bar": i.first_bar.isoformat()[:10] if i.first_bar else None,
             "last_bar": i.last_bar.isoformat()[:10] if i.last_bar else None,
             "bars": int(counts.get(i.symbol, 0)), "quality": (i.quality or {}).get("status"),
             "updated_at": i.updated_at.isoformat() if i.updated_at else None} for i in rows]


@router.post("/data/fetch")
def fetch(req: FetchRequest, db: Session = Depends(get_db)):
    try:
        r = data.ingest(db, req.symbol, req.timeframe, req.start, req.end, req.source)
        db.commit()
        return r
    except Exception as exc:
        db.commit()
        raise HTTPException(400, str(exc)) from exc


@router.get("/data/bars")
def bars(symbol: str, timeframe: str = "1Day", start: str | None = None, end: str | None = None,
         indicators: str = Query("", description="comma list, e.g. sma:20,ema:50,bollinger,rsi,macd"),
         limit: int = 5000, db: Session = Depends(get_db)):
    try:
        full = data.load_bars(db, symbol, timeframe, None, end)      # indicators need the warm-up history
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    if full.empty:
        raise HTTPException(404, f"no {timeframe} bars for {symbol}")
    tz = getattr(full.index, "tz", None)
    keep = full.index >= (pd.Timestamp(start, tz=tz) if start else full.index[0])
    df = full[keep]
    if df.empty:
        raise HTTPException(404, f"no {timeframe} bars for {symbol} after {start}")
    out_ind = {}
    for spec in [s for s in indicators.split(",") if s.strip()]:
        name, *args = spec.strip().split(":")
        if name not in ta.INDICATORS:
            continue
        defaults = ta.INDICATORS[name][1]
        params = dict(zip(defaults, [float(a) if "." in a else int(a) for a in args], strict=False))
        res = ta.compute(full, name, **params)[keep]
        out_ind[spec] = {"pane": ta.INDICATORS[name][2], "params": {**defaults, **params},
                         "series": {c: [[_ts(t), None if pd.isna(v) else round(float(v), 4)] for t, v in res[c].tail(limit).items()]
                                    for c in res.columns}}
    tail = df.tail(limit)
    return {"symbol": symbol.upper(), "timeframe": timeframe, "count": len(tail),
            "bars": [{"time": _ts(t), "open": round(r.open, 4), "high": round(r.high, 4), "low": round(r.low, 4),
                      "close": round(r.close, 4), "volume": float(r.volume)} for t, r in tail.iterrows()],
            "indicators": out_ind}


@router.get("/data/company/{symbol}")
def company(symbol: str, refresh: bool = False):
    """Equibles company snapshot (cached 6 h per symbol; refresh=true spends 5 requests of the daily allowance)."""
    eq = P.PROVIDERS["equibles"]
    if not eq.available():
        raise HTTPException(400, "Equibles is not connected - paste your API key on the Integrations page")
    try:
        return eq.company(symbol, refresh)
    except P.DataError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/data/quality")
def quality(symbol: str, timeframe: str = "1Day", max_move: float = 0.08, db: Session = Depends(get_db)):
    df = data.load_bars(db, symbol, timeframe)
    if df.empty:
        raise HTTPException(404, "no bars")
    return {"symbol": symbol.upper(), "timeframe": timeframe,
            **DQ.check(df, timeframe, max_move, as_of=df.index[-1] if df.index.tz is None else None)}


@router.get("/data/indicators")
def indicator_catalog():
    return [{"name": k, "defaults": v[1], "pane": v[2]} for k, v in ta.INDICATORS.items()]


@router.get("/data/reference/{symbol}")
def reference(symbol: str, date: str = "2025-12-31", db: Session = Depends(get_db)):
    """Lab 02: RAW (TradingView default, dividend-unadjusted) vs ADJUSTED research bars for one date."""
    raw = P.PROVIDERS["demo"].raw_reference(symbol.upper())
    if raw is None:
        raise HTTPException(404, "reference bars bundled for AAPL and D05.SI only")
    d = pd.Timestamp(date)
    if d not in raw.index:
        d = raw.index[raw.index <= d][-1]
    r = raw.loc[d]
    adj = data.cached_bars(db, symbol.upper(), "1Day", str(d.date()), str(d.date()))
    factor = float(r["adj_close"] / r["close"])
    a = (adj.iloc[0].to_dict() if len(adj) else {k: float(r[k]) * factor for k in ("open", "high", "low", "close")})
    tv = {"AAPL": "NASDAQ:AAPL", "D05.SI": "SGX:D05"}.get(symbol.upper(), symbol.upper())
    return {"symbol": symbol.upper(), "tradingview_symbol": tv, "date": str(d.date()),
            "raw": {k: float(r[k]) for k in ("open", "high", "low", "close", "volume")},
            "adjusted": {k: round(float(a[k]), 4) for k in ("open", "high", "low", "close")},
            "adj_factor": round(factor, 4),
            "note": "TradingView's default chart is split-adjusted but NOT dividend-adjusted, so it should match RAW to "
                    "the cent. Backtests use ADJUSTED bars; never mix the two without converting."}


@router.post("/news/fetch")
def news_fetch(req: NewsFetchRequest, db: Session = Depends(get_db)):
    r = data.fetch_news(db, req.symbol, req.source, req.query, req.days)
    db.commit()
    return r


@router.get("/news")
def news(symbol: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = select(NewsItem).order_by(NewsItem.published_at.desc()).limit(limit)
    if symbol:
        q = q.where(NewsItem.symbol == symbol.upper())
    return [{"id": n.id, "symbol": n.symbol, "published_at": n.published_at.isoformat(), "headline": n.headline,
             "url": n.url, "source": n.source, "sentiment": n.sentiment, "synthetic": n.synthetic} for n in db.scalars(q)]


@router.get("/sentiment")
def sentiment(symbol: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(SentimentDaily).where(SentimentDaily.symbol == symbol.upper()).order_by(SentimentDaily.day))
    return [{"day": r.day.isoformat(), "score": r.score, "n": r.n_items, "synthetic": r.synthetic} for r in rows]


@router.post("/sentiment/score")
def score_text(body: dict):
    from trader.sentiment.news import score
    return {"text": body.get("text", ""), "score": score(body.get("text", ""))}
