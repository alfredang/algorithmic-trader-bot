"""Execution-algorithm simulation: TWAP, VWAP and POV (course Topic 2.2).

A parent order of ``qty`` shares is worked over one session of intraday bars.
Each child order fills at the bar's typical price plus a temporary market-impact
cost from a square-root model:

    impact_bps = impact_coef x sqrt(child_qty / bar_volume) x 1e4   (paid on top of the price)

Results are benchmarked against the arrival price (implementation shortfall) and
the session VWAP - the standard execution-quality measures.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _schedule(algo: str, bars: pd.DataFrame, qty: float, participation: float, profile: pd.Series | None) -> np.ndarray:
    n = len(bars)
    if algo == "twap":
        return np.full(n, qty / n)
    if algo == "vwap":
        w = profile.values if profile is not None and len(profile) == n else bars["volume"].values
        w = np.asarray(w, float)
        return qty * w / w.sum()
    if algo == "pov":
        return np.minimum(bars["volume"].values * participation, np.inf)
    raise ValueError("algo must be twap, vwap or pov")


def volume_profile(intraday: pd.DataFrame) -> pd.Series:
    """Average share of the day's volume traded in each bar slot (the U-shaped volume curve)."""
    df = intraday.copy()
    df["slot"] = [t.strftime("%H:%M") for t in df.index]
    df["day"] = [t.date() for t in df.index]
    share = df["volume"] / df.groupby("day")["volume"].transform("sum")
    return share.groupby(df["slot"]).mean()


def simulate(intraday: pd.DataFrame, day: str | None = None, algo: str = "vwap", side: str = "buy",
             qty: float = 50_000, participation: float = 0.10, impact_coef: float = 0.1,
             use_history_profile: bool = True) -> dict:
    df = intraday.sort_index()
    days = sorted({t.date() for t in df.index})
    if not days:
        raise ValueError("no intraday bars")
    d = pd.Timestamp(day).date() if day else days[-1]
    if d not in days:
        d = days[-1]
    session = df[[t.date() == d for t in df.index]]
    hist = df[[t.date() < d for t in df.index]]
    profile = None
    if use_history_profile and len(hist):
        prof = volume_profile(hist.tail(20 * 7))
        slots = [t.strftime("%H:%M") for t in session.index]
        profile = prof.reindex(slots).fillna(prof.mean())
    sched = _schedule(algo, session, qty, participation, profile)
    remaining = qty
    sign = 1 if side == "buy" else -1
    rows = []
    for (t, bar), planned in zip(session.iterrows(), sched, strict=False):
        child = min(planned, remaining)
        if child <= 0:
            continue
        typical = (bar["high"] + bar["low"] + bar["close"]) / 3
        part = child / max(bar["volume"], 1)
        impact_bps = impact_coef * np.sqrt(part) * 1e4
        px = typical * (1 + sign * impact_bps / 1e4)
        rows.append({"time": t.isoformat(), "child_qty": float(child), "price": float(px), "typical": float(typical),
                     "participation": float(part), "impact_bps": float(impact_bps), "bar_volume": float(bar["volume"])})
        remaining -= child
    fills = pd.DataFrame(rows)
    filled = float(fills["child_qty"].sum()) if len(fills) else 0.0
    avg = float((fills["child_qty"] * fills["price"]).sum() / filled) if filled else None
    typical = (session["high"] + session["low"] + session["close"]) / 3
    vwap = float((typical * session["volume"]).sum() / session["volume"].sum())
    arrival = float(session["open"].iloc[0])
    slip_vwap = sign * (avg / vwap - 1) * 1e4 if avg else None
    shortfall = sign * (avg / arrival - 1) * 1e4 if avg else None
    return {"algo": algo, "side": side, "day": str(d), "parent_qty": qty, "filled_qty": filled,
            "fill_rate": filled / qty if qty else None, "avg_price": avg, "session_vwap": vwap,
            "arrival_price": arrival, "slippage_vs_vwap_bps": slip_vwap, "implementation_shortfall_bps": shortfall,
            "n_children": int(len(fills)), "max_participation": float(fills["participation"].max()) if len(fills) else None,
            "children": rows, "days_available": [str(x) for x in days[-30:]]}


def compare(intraday: pd.DataFrame, day: str | None = None, side: str = "buy", qty: float = 50_000,
            participation: float = 0.10, impact_coef: float = 0.1) -> list[dict]:
    out = []
    for algo in ("twap", "vwap", "pov"):
        r = simulate(intraday, day, algo, side, qty, participation, impact_coef)
        out.append({k: r[k] for k in ("algo", "avg_price", "session_vwap", "arrival_price", "slippage_vs_vwap_bps",
                                      "implementation_shortfall_bps", "fill_rate", "n_children", "max_participation")})
    return out
