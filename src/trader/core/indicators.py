"""Classic technical indicators written with plain pandas.

Ported from the course lab library (``labs/common/indicators.py``). Every
function only uses data up to and including bar t to compute the value at bar t
(no centred windows, no ``shift(-1)``), so the values are safe to use as signals
that are then traded on the NEXT bar.

Definitions match TradingView's built-ins (``ta.sma``, ``ta.ema``, ``ta.rsi``,
``ta.macd``, ``ta.bb``, ``ta.atr``, ``ta.vwap``, ``ta.obv``) so learners can
cross-check Python against their Pine Script charts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average: mean of the last ``window`` values."""
    return series.rolling(int(window), min_periods=int(window)).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average with alpha = 2 / (span + 1) (TradingView ``ta.ema``)."""
    return series.ewm(span=int(span), adjust=False, min_periods=int(span)).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index with Wilder smoothing (alpha = 1 / window).

    RS = Wilder-average(gains) / Wilder-average(losses); RSI = 100 - 100 / (1 + RS).
    """
    window = int(window)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.where(avg_loss != 0.0, 100.0).where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line = EMA(fast) - EMA(slow); signal = EMA(signal) of MACD; hist = MACD - signal."""
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=int(signal), adjust=False, min_periods=int(signal)).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, window: int = 20, k: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands: middle = SMA(window); upper/lower = middle +/- k * population stdev."""
    mid = sma(close, window)
    sd = close.rolling(int(window), min_periods=int(window)).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    return pd.DataFrame({"middle": mid, "upper": upper, "lower": lower,
                         "pct_b": (close - lower) / (upper - lower),
                         "width": (upper - lower) / mid})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"],
                      (df["high"] - prev_close).abs(),
                      (df["low"] - prev_close).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range (Wilder). True range = max(H-L, |H-prevC|, |L-prevC|)."""
    window = int(window)
    return true_range(df).ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def donchian(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Donchian channel of the PREVIOUS ``window`` bars (shifted one bar, so no look-ahead)."""
    upper = df["high"].rolling(int(window)).max().shift(1)
    lower = df["low"].rolling(int(window)).min().shift(1)
    return pd.DataFrame({"upper": upper, "lower": lower, "middle": (upper + lower) / 2})


def vwap(df: pd.DataFrame, window: int | None = None) -> pd.Series:
    """Volume-weighted average price of the typical price (H+L+C)/3.

    Intraday bars (tz-aware index) reset every session like ``ta.vwap``; daily bars
    use a rolling ``window``-day VWAP (default 20).
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    if window is None and getattr(df.index, "tz", None) is not None:
        session = df.index.date
        return pv.groupby(session).cumsum() / df["volume"].groupby(session).cumsum()
    window = int(window or 20)
    return pv.rolling(window).sum() / df["volume"].rolling(window).sum()


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume: running total of +volume on up days and -volume on down days."""
    direction = np.sign(df["close"].diff()).fillna(0.0)
    return (direction * df["volume"]).cumsum()


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    """Stochastic oscillator %K = (C - LL) / (HH - LL) x 100 and %D = SMA(%K, d)."""
    ll = df["low"].rolling(int(k)).min()
    hh = df["high"].rolling(int(k)).max()
    pct_k = 100 * (df["close"] - ll) / (hh - ll)
    return pd.DataFrame({"k": pct_k, "d": pct_k.rolling(int(d)).mean()})


def realized_vol(close: pd.Series, window: int = 21, periods: int = 252) -> pd.Series:
    """Annualised rolling volatility of simple returns."""
    return close.pct_change().rolling(int(window)).std() * np.sqrt(periods)


def losing_streak(close: pd.Series) -> pd.Series:
    """Number of consecutive down closes ending at each bar (0 if the bar closed up)."""
    down = close.diff() < 0
    return down.groupby((~down).cumsum()).cumsum().astype(int)


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of an OHLCV frame with the standard course indicator columns added."""
    out = df.copy()
    out["sma_50"], out["sma_200"] = sma(out["close"], 50), sma(out["close"], 200)
    out["ema_20"], out["ema_50"] = ema(out["close"], 20), ema(out["close"], 50)
    out["rsi_14"] = rsi(out["close"], 14)
    out = out.join(macd(out["close"]))
    out = out.join(bollinger(out["close"]).add_prefix("bb_"))
    out["atr_14"] = atr(out, 14)
    out["vwap_20"] = vwap(out, 20)
    out["obv"] = obv(out)
    return out


# Registry used by the chart API: name -> (callable(df, **params) -> DataFrame|Series, defaults, pane)
def _series(name, fn):
    return lambda df, **p: fn(df, **p).rename(name) if isinstance(fn(df, **p), pd.Series) else fn(df, **p)


INDICATORS = {
    "sma": (lambda df, window=20: sma(df["close"], window), {"window": 20}, "price"),
    "ema": (lambda df, window=20: ema(df["close"], window), {"window": 20}, "price"),
    "bollinger": (lambda df, window=20, k=2.0: bollinger(df["close"], window, k)[["upper", "middle", "lower"]],
                  {"window": 20, "k": 2.0}, "price"),
    "donchian": (lambda df, window=20: donchian(df, window)[["upper", "lower"]], {"window": 20}, "price"),
    "vwap": (lambda df, window=20: vwap(df, window), {"window": 20}, "price"),
    "rsi": (lambda df, window=14: rsi(df["close"], window), {"window": 14}, "oscillator"),
    "macd": (lambda df, fast=12, slow=26, signal=9: macd(df["close"], fast, slow, signal),
             {"fast": 12, "slow": 26, "signal": 9}, "oscillator"),
    "atr": (lambda df, window=14: atr(df, window), {"window": 14}, "oscillator"),
    "obv": (lambda df: obv(df), {}, "oscillator"),
    "stochastic": (lambda df, k=14, d=3: stochastic(df, k, d), {"k": 14, "d": 3}, "oscillator"),
}


def compute(df: pd.DataFrame, name: str, **params) -> pd.DataFrame:
    """Compute a registered indicator; always returns a DataFrame of named columns."""
    fn, defaults, _ = INDICATORS[name]
    out = fn(df, **{**defaults, **params})
    if isinstance(out, pd.Series):
        out = out.to_frame(name)
    return out
