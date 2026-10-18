"""Data-quality checks on OHLCV bars (course Topic 1.5 / Lab 03).

Checks: missing values, duplicate timestamps, unsorted index, high < low, close
outside [low, high], zero volume, calendar gaps, suspicious big moves (possible
unadjusted split), stale data and timezone consistency.
"""
from __future__ import annotations

import pandas as pd

BLOCKING = ["missing_values", "duplicate_timestamps", "not_sorted", "high_below_low", "close_outside_range"]
SPLIT_RATIOS = [2, 3, 4, 5, 10, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 1.5, 2 / 3]


def check(df: pd.DataFrame, timeframe: str = "1Day", max_move: float = 0.08, stale_days: int = 5,
          as_of: pd.Timestamp | None = None) -> dict:
    idx = df.index
    daily = timeframe in ("1Day", "1Week", "1Month")
    rets = df["close"].pct_change()
    gaps = idx.to_series().diff().dt.days if (daily and len(idx) > 1) else pd.Series(dtype=float)
    big = rets[rets.abs() > max_move]
    ratio = (df["close"] / df["close"].shift(1)).loc[big.index]
    split_like = [str(t)[:10] for t, r in ratio.items() if any(abs(r - s) / s < 0.03 for s in SPLIT_RATIOS)]
    tz = str(getattr(idx, "tz", None) or "naive")
    stale = False
    if daily and len(idx):
        ref = as_of or pd.Timestamp.now().normalize()
        stale = bool(idx[-1] < ref - pd.Timedelta(days=stale_days))
    res = {
        "rows": int(len(df)), "first": str(idx[0])[:19] if len(df) else None, "last": str(idx[-1])[:19] if len(df) else None,
        "missing_values": int(df[["open", "high", "low", "close"]].isna().sum().sum()),
        "duplicate_timestamps": int(idx.duplicated().sum()),
        "not_sorted": int(not idx.is_monotonic_increasing),
        "high_below_low": int((df["high"] < df["low"]).sum()),
        "close_outside_range": int(((df["close"] > df["high"] * (1 + 1e-6)) | (df["close"] < df["low"] * (1 - 1e-6))).sum()),
        "zero_volume": int((df["volume"] == 0).sum()),
        "gaps_over_4_days": int((gaps > 4).sum()) if daily else 0,
        "big_moves": int(len(big)),
        "possible_splits": split_like[:20],
        "stale": stale, "timezone": tz,
        "big_move_dates": [str(t)[:10] for t in big.index[:20]],
    }
    if any(res[k] for k in BLOCKING):
        res["status"] = "FAIL"
    elif res["big_moves"] or res["zero_volume"] or res["possible_splits"] or res["gaps_over_4_days"]:
        res["status"] = "CHECK"
    else:
        res["status"] = "OK"
    res["notes"] = _notes(res)
    return res


def _notes(r: dict) -> list[str]:
    n = []
    if r["duplicate_timestamps"]:
        n.append("Duplicate timestamps - de-duplicate before any calculation.")
    if r["possible_splits"]:
        n.append("Moves that look like split ratios: confirm the series is split-adjusted.")
    if r["big_moves"]:
        n.append(f"{r['big_moves']} moves larger than the threshold - check against news / corporate actions.")
    if r["gaps_over_4_days"]:
        n.append("Calendar gaps longer than a long weekend - check for missing sessions.")
    if r["stale"]:
        n.append("Data is stale relative to today - offline demo data ends 2025-12-31.")
    if r["timezone"] == "naive":
        n.append("Daily bars are tz-naive exchange dates (America/New_York sessions).")
    return n or ["Clean."]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Sort, drop duplicate timestamps (keep last) and rows with missing prices."""
    out = df[~df.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=["open", "high", "low", "close"])
