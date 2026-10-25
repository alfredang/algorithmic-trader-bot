"""Trading algorithms of the Trading Strategy agent - every value and vote is COMPUTED IN CODE from candles.

Each algorithm returns a score in [-1, 1] (positive = bullish), a vote (-1 / 0 / +1 with a 0.1 dead band)
and the indicator values behind it. The agent (LLM or rules) only chooses which algorithms to use and how
much weight each gets; :func:`composite` turns that choice into one number.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from trader.agents.roles import ALGORITHMS
from trader.core import indicators as ta

MIN_BARS = 60
DEAD_BAND = 0.1


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) else max(lo, min(hi, v))


def _r(x, n: int = 4):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else round(v, n)


def _vote(score: float) -> int:
    return 1 if score > DEAD_BAND else -1 if score < -DEAD_BAND else 0


def evaluate(bars: pd.DataFrame) -> dict | None:
    """All six algorithms on one candle series (None if fewer than MIN_BARS bars)."""
    if bars is None or len(bars) < MIN_BARS:
        return None
    c = bars["close"].astype(float)
    last = float(c.iloc[-1])
    out: dict[str, dict] = {}

    e20, e50 = float(ta.ema(c, 20).iloc[-1]), float(ta.ema(c, 50).iloc[-1])
    s = _clip((e20 / e50 - 1) * 25) if e50 else 0.0
    out["trend"] = {"score": s, "values": {"ema20": _r(e20, 2), "ema50": _r(e50, 2)}}

    roc = float(c.iloc[-1] / c.iloc[-21] - 1) if len(c) > 21 else 0.0
    vol = float(c.pct_change().tail(60).std() or 0.0)
    s = _clip(roc / (vol * math.sqrt(20)) / 2) if vol > 0 else 0.0
    out["momentum"] = {"score": s, "values": {"roc20": _r(roc), "vol_per_bar": _r(vol, 5)}}

    bb = ta.bollinger(c)
    pct_b = float(bb["pct_b"].iloc[-1]) if not pd.isna(bb["pct_b"].iloc[-1]) else 0.5
    atr = float(ta.atr(bars, 14).iloc[-1])
    move_atr = float((c.iloc[-1] - c.iloc[-2]) / atr) if atr > 0 else 0.0
    if pct_b > 1 or move_atr > 1:
        s = 1.0 if pct_b > 1 and move_atr > 1 else 0.6
    elif pct_b < 0 or move_atr < -1:
        s = -1.0 if pct_b < 0 and move_atr < -1 else -0.6
    else:
        s = _clip((pct_b - 0.5) * 0.4)
    out["volatility"] = {"score": s, "values": {"bb_pct_b": _r(pct_b, 3), "atr14": _r(atr, 3), "move_atr": _r(move_atr, 2)}}

    vw = ta.vwap(bars) if getattr(bars.index, "tz", None) is not None else ta.vwap(bars, 20)
    v = float(vw.iloc[-1]) if not pd.isna(vw.iloc[-1]) else last
    s = _clip((last / v - 1) * 20) if v else 0.0
    out["vwap"] = {"score": s, "values": {"vwap": _r(v, 2), "close": _r(last, 2)}}

    r = float(ta.rsi(c, 14).iloc[-1])
    s = 1.0 if r < 30 else -1.0 if r > 70 else _clip((50 - r) / 40)
    out["rsi"] = {"score": s, "values": {"rsi14": _r(r, 1)}}

    m = ta.macd(c)
    hist, line, sig = float(m["hist"].iloc[-1]), float(m["macd"].iloc[-1]), float(m["signal"].iloc[-1])
    prev = float(m["hist"].iloc[-2])
    s = _clip(hist / (0.002 * last)) if last else 0.0
    out["macd"] = {"score": s, "values": {"macd": _r(line), "signal": _r(sig), "hist": _r(hist),
                                          "cross": "up" if prev <= 0 < hist else "down" if prev >= 0 > hist else "none"}}

    for v in out.values():
        v["score"] = round(v["score"], 3)
        v["vote"] = _vote(v["score"])
    return out


def votes(candles: dict[str, pd.DataFrame]) -> dict:
    """Votes per interval and the average score per algorithm over the intervals that have enough bars."""
    per_tf = {tf: res for tf, df in candles.items() if (res := evaluate(df)) is not None}
    combined = {}
    for a in ALGORITHMS:
        scores = [per_tf[tf][a]["score"] for tf in per_tf]
        sc = round(float(np.mean(scores)), 3) if scores else 0.0
        combined[a] = {"score": sc, "vote": _vote(sc), "intervals": {tf: per_tf[tf][a]["vote"] for tf in per_tf}}
    return {"intervals_used": list(per_tf), "per_interval": per_tf, "combined": combined}


def normalise_weights(weights: dict | None, fallback: dict | None = None) -> dict:
    w = {}
    for k, v in (weights or {}).items():
        if k in ALGORITHMS:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f > 0 and not math.isnan(f):
                w[k] = f
    total = sum(w.values())
    if total <= 0:
        return normalise_weights(fallback) if fallback else {k: round(1 / len(ALGORITHMS), 4) for k in ALGORITHMS}
    return {k: round(v / total, 4) for k, v in w.items()}


def composite(votes_: dict, weights: dict, sentiment: float, finance: float, sentiment_weight: float,
              finance_weight: float) -> dict:
    """Composite = (1 - sw - fw) x sum(w_a x score_a) + sw x sentiment + fw x finance, in [-1, 1]."""
    sw, fw = _clip(sentiment_weight, 0, 0.5), _clip(finance_weight, 0, 0.5)
    if sw + fw > 0.8:
        k = 0.8 / (sw + fw)
        sw, fw = sw * k, fw * k
    algo = sum(w * votes_["combined"].get(a, {}).get("score", 0.0) for a, w in weights.items())
    total = (1 - sw - fw) * algo + sw * _clip(sentiment) + fw * _clip(finance)
    return {"algorithms_score": round(algo, 3), "composite": round(_clip(total), 3), "sentiment_weight": round(sw, 3),
            "finance_weight": round(fw, 3)}
