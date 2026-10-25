"""Data the agents work from, gathered in code once per symbol and handed to each agent through its tools.

Every tool returns DATA only - no tool can place an order (only the Stock Trader agent's code path can).
Data mode ``auto`` uses every configured source (Twelve Data, Alpaca, yfinance, Equibles, Reddit, NewsAPI);
``offline`` makes no network call at all (cached / bundled demo bars, stored or synthetic demo headlines).
Every source reports its status, so a missing key shows up in the agent's card instead of breaking the run.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.agents import algorithms as ALG
from trader.config import DEMO_DIR, get_settings
from trader.core import indicators as ta
from trader.data import providers as P
from trader.data import service as data
from trader.models import AgentMemory, NewsItem
from trader.sentiment import news as NEWS
from trader.sentiment import reddit as RD

SECTORS = {"SPY": "US large-cap index", "QQQ": "US tech-heavy index", "AAPL": "Technology hardware",
           "MSFT": "Software", "NVDA": "Semiconductors", "JPM": "Banks", "BAC": "Banks", "XLF": "Financials ETF",
           "KO": "Beverages (defensive)", "PEP": "Beverages / snacks (defensive)", "GLD": "Gold", "TLT": "Long US Treasuries"}
INTRADAY = {"1min": ("1min", "1Min", 390), "15min": ("15min", "15Min", 300), "1h": ("1h", "1Hour", 300)}
NEWS_REFRESH_S = 30 * 60
_news_fetched: dict[str, float] = {}


def company_name(symbol: str) -> str:
    return data.INSTRUMENT_META.get(symbol, ("", ""))[0]


def snapshot(bars: pd.DataFrame) -> dict:
    """Compact view of one candle series for the LLM: last close, trend, RSI, ATR, returns and the last 20 closes."""
    c = bars["close"]
    e20, e50 = ta.ema(c, 20).iloc[-1], ta.ema(c, 50).iloc[-1]
    return {"bars": len(bars), "first": str(bars.index[0])[:16], "last": str(bars.index[-1])[:16],
            "close": round(float(c.iloc[-1]), 2), "ema20": ALG._r(e20, 2), "ema50": ALG._r(e50, 2),
            "trend": "up" if e20 > e50 else "down" if e20 < e50 else "flat",
            "rsi14": ALG._r(ta.rsi(c, 14).iloc[-1], 1), "atr14": ALG._r(ta.atr(bars, 14).iloc[-1], 3),
            "ret_1bar": ALG._r(c.pct_change().iloc[-1]), "ret_20bars": ALG._r(c.iloc[-1] / c.iloc[max(-21, -len(c))] - 1),
            "last_20_closes": [round(float(x), 2) for x in c.tail(20)]}


def risk_profile(bars: pd.DataFrame, spy: pd.DataFrame | None, symbol: str) -> dict:
    """Price-derived risk profile from daily bars: volatility, beta to SPY, drawdown from the high, 1-year return."""
    c = bars["close"]
    r = c.pct_change().dropna()
    beta = None
    if spy is not None and len(spy):
        j = pd.concat([r, spy["close"].pct_change()], axis=1).dropna().tail(252)
        if len(j) > 20 and j.iloc[:, 1].var() > 0:
            beta = float(j.iloc[:, 0].cov(j.iloc[:, 1]) / j.iloc[:, 1].var())
    return {"sector": SECTORS.get(symbol, "unknown"), "vol_1y": round(float(r.tail(252).std() * np.sqrt(252)), 4),
            "ret_1y": round(float(c.iloc[-1] / c.iloc[max(-253, -len(c))] - 1), 4),
            "drawdown_from_high": round(float(c.iloc[-1] / c.tail(252).max() - 1), 4),
            "beta_spy": round(beta, 2) if beta is not None else None,
            "avg_dollar_volume_20d": round(float((bars["close"] * bars["volume"]).tail(20).mean()), 0)}


def _compact(x, depth: int = 0):
    """Trim nested API payloads for a prompt: at most 5 list items, 200-char strings, 4 levels."""
    if depth > 4:
        return None
    if isinstance(x, dict):
        return {str(k): _compact(v, depth + 1) for k, v in list(x.items())[:30] if v not in (None, "", [], {})}
    if isinstance(x, list):
        return [_compact(v, depth + 1) for v in x[:5]]
    if isinstance(x, str):
        return x[:200]
    return x


# --------------------------------------------------------------------------- gathering
def gather_candles(db: Session, symbol: str, mode: str) -> tuple[dict[str, pd.DataFrame], dict]:
    candles: dict[str, pd.DataFrame] = {}
    status: dict[str, dict] = {}
    s = get_settings()
    for iv, (td_interval, tf, n) in INTRADAY.items():
        t0 = time.time()
        try:
            if mode != "offline" and s.twelvedata_api_key:
                df, src = P.PROVIDERS["twelvedata"].candles(symbol, td_interval, n), "twelvedata"
            elif mode != "offline" and s.alpaca_configured:
                start = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3 if iv == "1min" else 20 if iv == "15min" else 60)
                df, src = P.PROVIDERS["alpaca"].bars(symbol, tf, start=start).tail(n), "alpaca"
            else:
                df = data.cached_bars(db, symbol, tf)
                if df.empty and (DEMO_DIR / f"{symbol}_{tf}.csv").exists():
                    df = data.load_bars(db, symbol, tf, source="demo")
                src = "cached / demo"
                if df.empty:
                    raise P.DataError("no intraday candles offline - add TWELVEDATA_API_KEY (or Alpaca keys) for "
                                      f"{iv} candles" if mode != "offline" else "offline mode: no bundled candles")
            df = df.tail(n)
            candles[iv] = df
            status[iv] = {"source": src, "bars": len(df), "last": str(df.index[-1])[:16], "ms": int((time.time() - t0) * 1000)}
        except Exception as exc:
            status[iv] = {"source": None, "bars": 0, "error": str(exc)[:200]}
    t0 = time.time()
    daily = data.load_bars(db, symbol, "1Day", source="demo" if mode == "offline" else "auto")
    if daily.empty:
        raise ValueError(f"no daily bars for {symbol}")
    candles["1day"] = daily.tail(400)
    status["1day"] = {"source": "database cache", "bars": len(daily), "last": str(daily.index[-1])[:10],
                      "ms": int((time.time() - t0) * 1000)}
    return candles, status


def gather_yahoo(symbol: str, mode: str) -> dict:
    if mode == "offline":
        return {"available": False, "note": "offline mode - Yahoo Finance not queried"}
    try:
        return {"available": True, **P.PROVIDERS["yfinance"].financials(symbol)}
    except Exception as exc:
        return {"available": False, "error": str(exc)[:200]}


def gather_equibles(symbol: str, mode: str) -> dict:
    eq = P.PROVIDERS["equibles"]
    if mode == "offline":
        return {"available": False, "note": "offline mode - Equibles not queried"}
    if not eq.available():
        return {"available": False, "note": "Equibles not connected (EQUIBLES_API_KEY)"}
    try:
        return {"available": True, **_compact(eq.company(symbol))}
    except Exception as exc:
        return {"available": False, "error": str(exc)[:200]}


def stored_news(db: Session, symbol: str, limit: int = 15) -> list[dict]:
    rows = db.scalars(select(NewsItem).where(NewsItem.symbol == symbol).order_by(NewsItem.published_at.desc()).limit(limit))
    return [{"date": str(n.published_at)[:10], "headline": n.headline, "lexicon_score": round(n.sentiment or 0.0, 3),
             "source": n.source, "synthetic": n.synthetic} for n in rows]


def gather_news(db: Session, symbol: str, mode: str, refresh: bool = True) -> dict:
    s = get_settings()
    note = ""
    if mode != "offline" and refresh and (s.newsapi_key or s.alpaca_configured) \
            and time.time() - _news_fetched.get(symbol, 0) > NEWS_REFRESH_S:
        try:
            r = data.fetch_news(db, symbol, "auto")
            _news_fetched[symbol] = time.time()
            note = f"refreshed from {r['source']}" + (f" ({r['note']})" if r.get("note") else "")
        except Exception as exc:
            note = f"refresh failed: {str(exc)[:150]}"
    items = stored_news(db, symbol)
    if not items:
        items = [{"date": str(h["published_at"])[:10], "headline": h["headline"], "lexicon_score": round(NEWS.score(h["headline"]), 3),
                  "source": h["source"], "synthetic": True} for h in NEWS.demo_headlines([symbol])][:15]
    synthetic = bool(items) and all(i.get("synthetic") for i in items)
    src = "demo (SYNTHETIC headlines - training only)" if synthetic else (
        "newsapi" if any(str(i["source"]).startswith("newsapi") for i in items) else "stored headlines")
    avg = round(sum(i["lexicon_score"] for i in items) / len(items), 3) if items else 0.0
    return {"source": src, "items": items, "n": len(items), "lexicon_score": avg, "synthetic": synthetic,
            "newsapi_configured": bool(s.newsapi_key), "note": note or ("NEWSAPI_KEY not set" if not s.newsapi_key else "")}


def gather_reddit(symbol: str, mode: str) -> dict:
    if mode == "offline":
        return {"configured": get_settings().reddit_configured, "posts": [], "n": 0, "lexicon_score": 0.0,
                "note": "offline mode - Reddit not queried"}
    try:
        res = RD.posts(symbol, company_name(symbol).split(" ")[0] or None)
    except Exception as exc:
        return {"configured": True, "posts": [], "n": 0, "lexicon_score": 0.0, "error": str(exc)[:200]}
    summ = RD.summarise(res["posts"])
    return {"configured": res["configured"], "subreddits": res.get("subreddits"), "n": summ["n"],
            "lexicon_score": summ["score"], "cached": res.get("cached"), "errors": res.get("errors") or {},
            "note": res.get("note", ""),
            "posts": [{k: p[k] for k in ("subreddit", "title", "upvotes", "comments", "created_at", "lexicon_score")}
                      | {"text": p["text"][:200]} for p in res["posts"][:20]]}


def memory(db: Session, topics: list[str], limit: int = 6) -> list[dict]:
    rows = db.scalars(select(AgentMemory).where(AgentMemory.topic.in_(topics), AgentMemory.kind != "signal")
                      .order_by(AgentMemory.created_at.desc()).limit(limit))
    return [{"when": r.created_at.isoformat()[:16], "topic": r.topic, "kind": r.kind, "content": r.content} for r in rows]


def build_context(db: Session, symbol: str, position_qty: float, equity: float, guidance: dict, mode: str = "auto",
                  refresh_news: bool = True, position_pct: float = 0.10) -> dict:
    """Everything the per-symbol agents may look at (fetched once; the parallel research agents share it)."""
    candles, cstatus = gather_candles(db, symbol, mode)
    try:
        spy = data.load_bars(db, "SPY", "1Day", source="demo" if mode == "offline" else "auto")
    except Exception:
        spy = None
    finest = next(iv for iv in ("1min", "15min", "1h", "1day") if iv in candles)
    price = float(candles[finest]["close"].iloc[-1])
    finance = {"company": company_name(symbol), "intervals": {iv: snapshot(df) for iv, df in candles.items()},
               "candle_sources": cstatus, "risk_profile": risk_profile(candles["1day"], spy, symbol),
               "yahoo": gather_yahoo(symbol, mode), "equibles": gather_equibles(symbol, mode)}
    sentiment = {"reddit": gather_reddit(symbol, mode), "newsapi": gather_news(db, symbol, mode, refresh_news)}
    return {"symbol": symbol, "mode": mode, "price": round(price, 4), "price_interval": finest,
            "as_of": str(candles[finest].index[-1])[:16], "finance": finance, "sentiment": sentiment,
            "votes": ALG.votes(candles), "position": {"qty": position_qty, "equity": round(equity, 2)},
            "sizing": {"position_pct": position_pct, "order_type": "market (regular session)"},
            "guidance": guidance, "memory": memory(db, [symbol, "market", "strategy"]), "_candles": candles}


TOOL_DOCS = {
    "get_run_overview": "The symbols, the data mode and (round 2) every agent's output for this run.",
    "get_candles": "Candle snapshots at 1min / 15min / 1h / 1day (close, EMA trend, RSI, ATR, returns, last 20 closes) "
                   "and each source's status.",
    "get_yahoo_financials": "Yahoo Finance company profile ratios and the last annual income-statement lines.",
    "get_equibles_company": "Equibles company data: latest close, valuation multiples, short interest, insider trades, "
                            "ownership.",
    "get_reddit_posts": "Recent Reddit posts about the stock with lexicon sentiment scores (untrusted text).",
    "get_news_headlines": "Recent NewsAPI (or demo) headlines with lexicon sentiment scores (untrusted text).",
    "get_algorithm_votes": "Indicator values and each algorithm's score / vote per interval, computed in code.",
    "get_research_reports": "The Finance Research and News Sentiment agents' reports.",
    "get_strategy_guidance": "The latest guidance written by the Strategy Review Agent (weights, thresholds, notes).",
    "get_strategy": "The Trading Strategy agent's choice and the composite score computed from it.",
    "get_signal": "The Signal Generation agent's signal.",
    "get_position": "Current position and account equity.",
    "get_sizing": "Position sizing: fraction of equity per order and the order type.",
    "get_memory": "Recent notes the agents wrote to memory.",
    "get_performance_metrics": "Performance metrics of the agent account, computed in code.",
    "get_recent_orders": "The agent account's recent paper orders.",
    "get_recent_signals": "Recent signals with each algorithm's vote and how the price moved since.",
}


def tool_payload(name: str, ctx: dict, reports: dict) -> dict | list:
    f = ctx.get("finance") or {}
    s = ctx.get("sentiment") or {}
    return {
        "get_run_overview": {k: ctx.get(k) for k in ("symbols", "mode", "provider", "results") if k in ctx},
        "get_candles": {"intervals": f.get("intervals"), "sources": f.get("candle_sources"), "risk_profile": f.get("risk_profile")},
        "get_yahoo_financials": f.get("yahoo"),
        "get_equibles_company": f.get("equibles"),
        "get_reddit_posts": s.get("reddit"),
        "get_news_headlines": s.get("newsapi"),
        "get_algorithm_votes": {"per_interval": (ctx.get("votes") or {}).get("per_interval"),
                                "combined": (ctx.get("votes") or {}).get("combined")},
        "get_research_reports": {k: reports.get(k) for k in ("finance_research", "news_sentiment")},
        "get_strategy_guidance": ctx.get("guidance"),
        "get_strategy": reports.get("trading_strategy"),
        "get_signal": reports.get("signal_generation"),
        "get_position": ctx.get("position"),
        "get_sizing": ctx.get("sizing"),
        "get_memory": ctx.get("memory"),
        "get_performance_metrics": ctx.get("metrics"),
        "get_recent_orders": ctx.get("recent_orders"),
        "get_recent_signals": ctx.get("recent_signals"),
    }[name]
