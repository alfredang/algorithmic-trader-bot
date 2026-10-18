"""Bars cache, ingestion with data-quality checks, news and sentiment storage."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from trader.core import data_quality as DQ
from trader.data import providers as P
from trader.models import Bar, Instrument, NewsItem, SentimentDaily, utcnow
from trader.sentiment import news as NEWS
from trader.services.events import emit, stage

STORED_TF = {"1Day": "1Day", "1Week": "1Day", "1Month": "1Day", "1Hour": "1Hour"}
INSTRUMENT_META = {
    "SPY": ("SPDR S&P 500 ETF", "AMEX:SPY"), "QQQ": ("Invesco QQQ (Nasdaq-100)", "NASDAQ:QQQ"),
    "AAPL": ("Apple Inc.", "NASDAQ:AAPL"), "MSFT": ("Microsoft Corp.", "NASDAQ:MSFT"),
    "NVDA": ("NVIDIA Corp.", "NASDAQ:NVDA"), "JPM": ("JPMorgan Chase & Co.", "NYSE:JPM"),
    "XLF": ("Financial Select Sector SPDR", "AMEX:XLF"), "KO": ("Coca-Cola Co.", "NYSE:KO"),
    "PEP": ("PepsiCo Inc.", "NASDAQ:PEP"), "BAC": ("Bank of America", "NYSE:BAC"),
    "GLD": ("SPDR Gold Shares", "AMEX:GLD"), "TLT": ("iShares 20+ Year Treasury Bond", "NASDAQ:TLT"),
    "D05.SI": ("DBS Group Holdings (SGX)", "SGX:D05"),
}


def _to_naive(ts) -> datetime:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("America/New_York").tz_localize(None)
    return t.to_pydatetime()


def store_bars(db: Session, symbol: str, timeframe: str, df: pd.DataFrame, source: str) -> int:
    """Replace the cached bars of (symbol, timeframe) with ``df``. Intraday timestamps are stored as ET wall time."""
    db.execute(delete(Bar).where(Bar.symbol == symbol, Bar.timeframe == timeframe))
    rows = [{"symbol": symbol, "timeframe": timeframe, "ts": _to_naive(t), "open": float(r.open), "high": float(r.high),
             "low": float(r.low), "close": float(r.close), "volume": float(r.volume), "source": source}
            for t, r in df.iterrows()]
    if rows:
        db.execute(Bar.__table__.insert(), rows)
    return len(rows)


def cached_bars(db: Session, symbol: str, timeframe: str = "1Day", start=None, end=None) -> pd.DataFrame:
    tf = STORED_TF.get(timeframe, timeframe)
    q = select(Bar.ts, Bar.open, Bar.high, Bar.low, Bar.close, Bar.volume).where(Bar.symbol == symbol, Bar.timeframe == tf)
    if start:
        q = q.where(Bar.ts >= pd.Timestamp(start).to_pydatetime())
    if end:
        q = q.where(Bar.ts <= (pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59)).to_pydatetime())
    rows = db.execute(q.order_by(Bar.ts)).all()
    if not rows:
        return pd.DataFrame(columns=P.COLUMNS)
    df = pd.DataFrame(rows, columns=["timestamp", *P.COLUMNS]).set_index("timestamp")
    df.index = pd.DatetimeIndex(df.index)
    if tf.endswith(("Hour", "Min")):
        df.index = df.index.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
        df = df[df.index.notna()]
    return P.resample(df.astype(float), timeframe)


def ingest(db: Session, symbol: str, timeframe: str = "1Day", start=None, end=None, source: str = "auto") -> dict:
    """Fetch -> data-quality check -> clean -> cache, and update the instrument record."""
    symbol = symbol.upper().strip()
    tf = STORED_TF.get(timeframe, timeframe)
    stage("ingestion", "running", f"Fetching {symbol} {tf} from {source}", db=db)
    try:
        df, used = P.fetch(symbol, tf, start, end, source)
    except Exception as exc:
        stage("ingestion", "error", str(exc), {"symbol": symbol}, db=db)
        raise
    q = DQ.check(df, tf, as_of=df.index[-1] if used == "demo" and len(df) else None)
    df = DQ.clean(df)
    n = store_bars(db, symbol, tf, df, used)
    inst = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    name, tv = INSTRUMENT_META.get(symbol, ("", ""))
    if inst is None:
        inst = Instrument(symbol=symbol, name=name, tradingview_symbol=tv)
        db.add(inst)
    inst.source = used
    if tf == "1Day" and len(df):
        inst.first_bar, inst.last_bar = _to_naive(df.index[0]), _to_naive(df.index[-1])
        inst.quality = q
    elif inst.quality is None:
        inst.quality = q
    inst.updated_at = utcnow()
    db.flush()
    stage("ingestion", "ok", f"{symbol} {tf}: {n} bars from {used}", {"symbol": symbol, "bars": n, "source": used}, db=db)
    stage("quality", {"OK": "ok", "CHECK": "warning", "FAIL": "error"}[q["status"]],
          f"{symbol} {tf}: {q['status']} - {'; '.join(q['notes'])}", {"symbol": symbol, "status": q["status"]}, db=db)
    emit("data.ingested", {"symbol": symbol, "timeframe": tf, "bars": n, "source": used}, db=db)
    return {"symbol": symbol, "timeframe": tf, "bars": n, "source": used, "quality": q}


def load_bars(db: Session, symbol: str, timeframe: str = "1Day", start=None, end=None, source: str = "auto",
              refresh: bool = False) -> pd.DataFrame:
    """Bars from the DB cache; fetched (and cached) on first use."""
    symbol = symbol.upper()
    tf = STORED_TF.get(timeframe, timeframe)
    if not refresh:
        df = cached_bars(db, symbol, timeframe, start, end)
        if len(df):
            return df
        has_any = db.scalar(select(func.count(Bar.id)).where(Bar.symbol == symbol, Bar.timeframe == tf))
        if has_any:
            return df              # cached but outside the requested window
    ingest(db, symbol, tf, None if tf == "1Hour" else "2018-01-01", None, source)
    db.commit()
    return cached_bars(db, symbol, timeframe, start, end)


def load_panel(db: Session, symbols: list[str], timeframe: str = "1Day", start=None, end=None) -> dict[str, pd.DataFrame]:
    return {s.upper(): load_bars(db, s, timeframe, start, end) for s in symbols}


def bar_counts(db: Session) -> int:
    return int(db.scalar(select(func.count(Bar.id))) or 0)


# --------------------------------------------------------------------------- news & sentiment
def store_news(db: Session, items: list[dict], model: str = "vader") -> int:
    n = 0
    for it in items:
        exists = db.scalar(select(NewsItem.id).where(NewsItem.symbol == it["symbol"], NewsItem.headline == it["headline"][:500],
                                                     NewsItem.published_at == _to_naive(it["published_at"])))
        if exists:
            continue
        s = NEWS.score(f"{it['headline']}. {it.get('summary', '')}")
        db.add(NewsItem(symbol=it["symbol"], published_at=_to_naive(it["published_at"]), headline=it["headline"][:500],
                        summary=it.get("summary", "")[:2000], url=it.get("url", "")[:1000], source=it.get("source", "")[:64],
                        sentiment=s, sentiment_model=model, synthetic=bool(it.get("synthetic", False))))
        n += 1
    db.flush()
    return n


def rebuild_daily_sentiment(db: Session, symbol: str) -> int:
    rows = db.execute(select(NewsItem.published_at, NewsItem.sentiment, NewsItem.synthetic)
                      .where(NewsItem.symbol == symbol)).all()
    db.execute(delete(SentimentDaily).where(SentimentDaily.symbol == symbol, SentimentDaily.model == "vader"))
    if not rows:
        return 0
    df = pd.DataFrame(rows, columns=["ts", "s", "syn"])
    df["day"] = pd.to_datetime(df["ts"]).dt.date
    g = df.groupby("day").agg(score=("s", "mean"), n=("s", "count"), syn=("syn", "all")).reset_index()
    for r in g.itertuples():
        db.add(SentimentDaily(symbol=symbol, day=r.day, score=float(r.score), n_items=int(r.n), model="vader",
                              synthetic=bool(r.syn)))
    db.flush()
    return len(g)


def fetch_news(db: Session, symbol: str, source: str = "auto", query: str | None = None, days: int = 7) -> dict:
    symbol = symbol.upper()
    stage("news", "running", f"Fetching headlines for {symbol}", db=db)
    items, used, note = [], source, ""
    try:
        if source in ("auto", "newsapi") and P.get_settings().newsapi_key:
            name = INSTRUMENT_META.get(symbol, ("", ""))[0].split(" ")[0]
            items, used = NEWS.newsapi_headlines(query or f'"{symbol}" OR "{name}"' if name else symbol, symbol, days), "newsapi"
        elif source in ("auto", "alpaca") and P.PROVIDERS["alpaca"].available():
            items, used = P.PROVIDERS["alpaca"].news(symbol, days), "alpaca"
        else:
            items, used = NEWS.demo_headlines([symbol]), "demo"
            note = "bundled SYNTHETIC headlines (training only - not real news)"
    except Exception as exc:
        stage("news", "error", f"{symbol}: {exc}", db=db)
        items, used, note = NEWS.demo_headlines([symbol]), "demo", f"{exc} - fell back to synthetic sample headlines"
    n = store_news(db, items)
    days_n = rebuild_daily_sentiment(db, symbol)
    stage("news", "ok" if used != "demo" else "warning", f"{symbol}: {n} new headlines from {used}. {note}".strip(),
          {"symbol": symbol, "new": n, "days": days_n, "source": used}, db=db)
    return {"symbol": symbol, "source": used, "new_items": n, "sentiment_days": days_n, "note": note}


def sentiment_series(db: Session, symbol: str, close: pd.Series, allow_synthetic: bool = True) -> tuple[pd.Series, str]:
    """Daily sentiment aligned to ``index``: real stored news first, else SYNTHETIC demo sentiment."""
    index = close.index
    rows = db.execute(select(SentimentDaily.day, SentimentDaily.score, SentimentDaily.synthetic)
                      .where(SentimentDaily.symbol == symbol.upper())).all()
    real = pd.Series({pd.Timestamp(d): s for d, s, syn in rows if not syn}, dtype=float)
    covered = real.reindex(index.normalize() if getattr(index, "tz", None) is None else index.tz_localize(None).normalize())
    if real.notna().sum() >= 20:
        return pd.Series(covered.values, index=index).fillna(0.0), "news (VADER)"
    if not allow_synthetic:
        return pd.Series(covered.values, index=index).fillna(0.0), "news (sparse)"
    return NEWS.synthetic_sentiment(close, symbol), "synthetic"
