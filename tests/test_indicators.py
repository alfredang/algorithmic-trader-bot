import numpy as np
import pandas as pd

from trader.core import indicators as ta


def test_sma_ema_known_values():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert ta.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert np.isnan(ta.sma(s, 3).iloc[1])
    e = ta.ema(s, 3)                       # alpha = 0.5, seeded with the first value (adjust=False)
    assert abs(e.iloc[2] - 2.25) < 1e-12 and abs(e.iloc[4] - 4.0625) < 1e-12


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert ta.rsi(up, 14).dropna().eq(100).all()          # only gains -> RSI 100
    down = pd.Series(np.arange(40, 1, -1, dtype=float))
    assert ta.rsi(down, 14).dropna().abs().lt(1e-9).all()  # only losses -> RSI 0
    r = ta.rsi(pd.Series(np.random.default_rng(0).normal(0, 1, 300)).cumsum() + 100, 14).dropna()
    assert r.between(0, 100).all()


def test_macd_hist_and_bollinger_population_std(spy):
    m = ta.macd(spy["close"])
    assert np.allclose((m["macd"] - m["signal"]).dropna(), m["hist"].dropna())
    b = ta.bollinger(spy["close"], 20, 2.0)
    window = spy["close"].iloc[-20:]
    assert abs(b["upper"].iloc[-1] - (window.mean() + 2 * window.std(ddof=0))) < 1e-9


def test_atr_and_donchian_use_past_only(spy):
    a = ta.atr(spy, 14).dropna()
    assert (a > 0).all()
    d = ta.donchian(spy, 20)
    assert d["upper"].iloc[25] == spy["high"].iloc[5:25].max()      # previous 20 bars, excluding bar 25


def test_no_lookahead_in_indicators(spy):
    full = ta.ema(spy["close"], 20)
    part = ta.ema(spy["close"].iloc[:1000], 20)
    assert np.allclose(full.iloc[:1000].dropna(), part.dropna())
