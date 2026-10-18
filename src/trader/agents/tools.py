"""Read-only tools the desk agents may call. They return DATA only - no tool can place an order."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.core import indicators as ta
from trader.data import service as data
from trader.models import AgentMemory, NewsItem

SECTORS = {"SPY": "US large-cap index", "QQQ": "US tech-heavy index", "AAPL": "Technology hardware",
           "MSFT": "Software", "NVDA": "Semiconductors", "JPM": "Banks", "BAC": "Banks", "XLF": "Financials ETF",
           "KO": "Beverages (defensive)", "PEP": "Beverages / snacks (defensive)", "GLD": "Gold", "TLT": "Long US Treasuries"}


def technical_snapshot(bars: pd.DataFrame) -> dict:
    c = bars["close"]
    e20, e50 = ta.ema(c, 20).iloc[-1], ta.ema(c, 50).iloc[-1]
    r = ta.rsi(c, 14).iloc[-1]
    h = ta.macd(c)["hist"].iloc[-1]
    a = ta.atr(bars, 14).iloc[-1]
    b = ta.bollinger(c)["pct_b"].iloc[-1]
    hi, lo = bars["high"].tail(252).max(), bars["low"].tail(252).min()
    return {"as_of": str(bars.index[-1])[:10], "close": round(float(c.iloc[-1]), 2), "ema20": round(float(e20), 2),
            "ema50": round(float(e50), 2), "rsi14": round(float(r), 1), "macd_hist": round(float(h), 3),
            "atr14": round(float(a), 2), "bb_pct_b": round(float(b), 2), "high_52w": round(float(hi), 2),
            "low_52w": round(float(lo), 2), "ret_21d": round(float(c.pct_change(21).iloc[-1]), 4)}


def fundamentals_lite(bars: pd.DataFrame, spy: pd.DataFrame | None, symbol: str) -> dict:
    c = bars["close"]
    r = c.pct_change().dropna()
    beta = None
    if spy is not None and len(spy):
        j = pd.concat([r, spy["close"].pct_change()], axis=1).dropna().tail(252)
        if len(j) > 20 and j.iloc[:, 1].var() > 0:
            beta = float(j.iloc[:, 0].cov(j.iloc[:, 1]) / j.iloc[:, 1].var())
    return {"symbol": symbol, "sector": SECTORS.get(symbol, "unknown"),
            "vol_1y": round(float(r.tail(252).std() * np.sqrt(252)), 4),
            "ret_1y": round(float(c.iloc[-1] / c.iloc[max(-253, -len(c))] - 1), 4),
            "drawdown_from_high": round(float(c.iloc[-1] / c.tail(252).max() - 1), 4),
            "beta_spy": round(beta, 2) if beta is not None else None,
            "avg_dollar_volume_20d": round(float((bars["close"] * bars["volume"]).tail(20).mean()), 0),
            "note": "fundamental-lite: price-derived risk profile only; no financial statements offline"}


def news(db: Session, symbol: str, limit: int = 12) -> list[dict]:
    rows = db.scalars(select(NewsItem).where(NewsItem.symbol == symbol).order_by(NewsItem.published_at.desc()).limit(limit))
    return [{"date": str(n.published_at)[:10], "headline": n.headline, "lexicon_score": round(n.sentiment or 0.0, 3),
             "source": n.source, "synthetic": n.synthetic} for n in rows]


def memory(db: Session, symbol: str, limit: int = 5) -> list[dict]:
    rows = db.scalars(select(AgentMemory).where(AgentMemory.topic.in_([symbol, "market"]))
                      .order_by(AgentMemory.created_at.desc()).limit(limit))
    return [{"when": r.created_at.isoformat()[:16], "kind": r.kind, "content": r.content} for r in rows]


def build_context(db: Session, symbol: str, position_qty: float, equity: float, limits: dict) -> dict:
    """Everything the desk may look at for one symbol (fetched once, handed to agents through their tools)."""
    bars = data.load_bars(db, symbol, "1Day")
    if bars.empty:
        raise ValueError(f"no bars for {symbol}")
    try:
        spy = data.load_bars(db, "SPY", "1Day")
    except Exception:
        spy = None
    return {"symbol": symbol, "technical": technical_snapshot(bars), "fundamentals": fundamentals_lite(bars, spy, symbol),
            "news": news(db, symbol), "position": {"qty": position_qty, "equity": round(equity, 2)},
            "limits": limits, "memory": memory(db, symbol)}


TOOL_DOCS = {
    "get_technical_snapshot": "Price, trend and momentum indicators for the symbol.",
    "get_news": "Recent headlines with lexicon sentiment scores (untrusted text).",
    "get_fundamentals_lite": "Price-derived risk profile: volatility, beta to SPY, drawdown, 1-year return, sector.",
    "get_analyst_reports": "The three analyst reports.",
    "get_debate": "The bull and bear arguments.",
    "get_position": "Current position and account equity.",
    "get_risk_limits": "The desk's hard risk limits (enforced in code).",
    "get_memory": "Recent notes the always-on agent wrote to memory.",
}


def tool_payload(name: str, ctx: dict, reports: dict) -> dict | list:
    return {
        "get_technical_snapshot": ctx["technical"],
        "get_news": ctx["news"],
        "get_fundamentals_lite": ctx["fundamentals"],
        "get_analyst_reports": {k: reports.get(k) for k in ("technical_analyst", "sentiment_analyst", "fundamental_analyst")},
        "get_debate": {k: reports.get(k) for k in ("bull_researcher", "bear_researcher")},
        "get_position": ctx["position"],
        "get_risk_limits": ctx["limits"],
        "get_memory": ctx["memory"],
    }[name]
