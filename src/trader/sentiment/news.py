"""News headlines and sentiment scoring.

Sources: NewsAPI.org (``/v2/everything``, key in NEWSAPI_KEY), Alpaca News, and the
bundled SYNTHETIC sample headlines (training only - not real news).
Scoring: VADER lexicon (offline, deterministic) - compound score in [-1, 1].
Headlines are untrusted text: they are only ever scored or passed to an LLM as DATA.
"""
from __future__ import annotations

import json
from functools import lru_cache

import httpx
import numpy as np
import pandas as pd

from trader.config import DEMO_DIR, get_settings

FINANCE_LEXICON = {   # finance-specific tweaks on top of VADER's general lexicon
    "upgrade": 2.0, "downgrade": -2.0, "beat": 1.5, "beats": 1.5, "miss": -1.5, "misses": -1.5, "record": 1.2,
    "probe": -1.5, "lawsuit": -1.8, "restrictions": -1.2, "delinquencies": -1.5, "provisions": -0.8,
    "bullish": 2.0, "bearish": -2.0, "rally": 1.5, "selloff": -1.8, "plunge": -2.2, "soar": 2.0, "surge": 1.8,
    "guidance cut": -2.0, "backlog": 0.8, "headwinds": -1.2, "tailwinds": 1.2, "weak": -1.4, "strong": 1.4,
}


@lru_cache
def _vader():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    a = SentimentIntensityAnalyzer()
    a.lexicon.update(FINANCE_LEXICON)
    return a


def score(text: str) -> float:
    """VADER compound score in [-1, 1]."""
    if not text:
        return 0.0
    return float(_vader().polarity_scores(text)["compound"])


def demo_headlines(symbols: list[str] | None = None) -> list[dict]:
    data = json.loads((DEMO_DIR / "sample_headlines.json").read_text())
    rows = []
    for h in data["headlines"]:
        if symbols and h["symbol"] not in symbols:
            continue
        rows.append({"symbol": h["symbol"], "published_at": pd.Timestamp(h["date"]) + pd.Timedelta(hours=12),
                     "headline": h["headline"], "summary": "", "url": "", "source": "demo (synthetic)", "synthetic": True})
    return rows


def newsapi_headlines(query: str, symbol: str, days: int = 7, page_size: int = 50) -> list[dict]:
    key = get_settings().newsapi_key
    if not key:
        raise RuntimeError("NEWSAPI_KEY is not set")
    params = {"q": query, "language": "en", "sortBy": "publishedAt", "pageSize": min(page_size, 100),
              "from": (pd.Timestamp.utcnow() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")}
    r = httpx.get("https://newsapi.org/v2/everything", params=params, headers={"X-Api-Key": key}, timeout=20)
    js = r.json()
    if js.get("status") != "ok":
        raise RuntimeError(f"NewsAPI error: {js.get('code')}: {js.get('message')}")
    out = []
    for a in js.get("articles", []):
        if not a.get("title"):
            continue
        out.append({"symbol": symbol, "published_at": pd.Timestamp(a["publishedAt"]).tz_convert("UTC").tz_localize(None),
                    "headline": a["title"][:500], "summary": (a.get("description") or "")[:2000],
                    "url": a.get("url") or "", "source": f"newsapi:{(a.get('source') or {}).get('name', '')}"[:64],
                    "synthetic": False})
    return out


def newsapi_test() -> dict:
    key = get_settings().newsapi_key
    r = httpx.get("https://newsapi.org/v2/everything", params={"q": "stocks", "pageSize": 1},
                  headers={"X-Api-Key": key}, timeout=15)
    js = r.json()
    if js.get("status") != "ok":
        raise RuntimeError(f"{js.get('code')}: {js.get('message')}")
    return {"totalResults": js.get("totalResults")}


def daily_scores(items: list[dict]) -> pd.DataFrame:
    """Aggregate headline scores to (symbol, day) means."""
    if not items:
        return pd.DataFrame(columns=["symbol", "day", "score", "n_items"])
    df = pd.DataFrame(items)
    df["day"] = pd.to_datetime(df["published_at"]).dt.date
    g = df.groupby(["symbol", "day"])["sentiment"].agg(["mean", "count"]).reset_index()
    return g.rename(columns={"mean": "score", "count": "n_items"})


def synthetic_sentiment(close: pd.Series, symbol: str) -> pd.Series:
    """SYNTHETIC demo sentiment for offline backtests - NOT real news.

    Simulates news flow that reacts to recent price moves (known at the close, so no look-ahead):
    tanh(10 x 5-day return) x 0.6 + seeded noise x 0.35, clipped to [-1, 1].
    """
    rng = np.random.default_rng(sum(map(ord, symbol)))
    r5 = close.pct_change(5).fillna(0.0)
    noise = rng.normal(0, 1, len(close))
    return pd.Series(np.clip(np.tanh(10 * r5.values) * 0.6 + noise * 0.35, -1, 1), index=close.index, name="sentiment")
