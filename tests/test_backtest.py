import numpy as np
import pandas as pd
import pytest

from trader.core.backtest import BacktestConfig, break_even_bps, buy_and_hold, run_backtest
from trader.core.costs import COST_PRESETS, CostModel

ZERO = BacktestConfig(costs=CostModel())


def bars(n=60, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    o = c * (1 + rng.normal(0, 0.002, n))
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.005, "low": np.minimum(o, c) * 0.995, "close": c,
                         "volume": 1e6}, index=idx)


def test_next_open_execution_matches_lab_formula():
    b = bars()
    sig = pd.Series((np.arange(len(b)) % 10 < 5).astype(float), index=b.index)
    res = run_backtest({"X": b}, sig, ZERO)
    o, c = b["open"].values, b["close"].values
    pos_new, pos_old = sig.shift(1).fillna(0).values, sig.shift(2).fillna(0).values
    overnight = np.nan_to_num(o / np.r_[np.nan, c[:-1]] - 1)
    gross = (1 + pos_old * overnight) * (1 + pos_new * (c / o - 1)) - 1
    assert np.allclose(res.returns.values, gross, atol=1e-10)


def test_no_lookahead_signal_is_held_one_bar_later():
    """A perfect-foresight signal decided at t (tomorrow up?) must NOT earn the move of bar t."""
    b = bars(300, 3)
    future_up = (b["close"].shift(-1) > b["close"]).astype(float).fillna(0)
    res = run_backtest({"X": b}, future_up, BacktestConfig(costs=CostModel(), execution="next_close"))
    # next_close: the weight held after the close of bar t is the signal decided at the close of t-1,
    # so the position over bar t+1 only knew the direction of bar t - never of bar t+1
    held_after_close = (res.weights["X"] > 0.5).astype(float)
    assert (held_after_close.iloc[2:] == future_up.shift(1).iloc[2:]).mean() > 0.99
    same_bar = (future_up.shift(1) * b["close"].pct_change()).fillna(0)
    assert res.metrics()["sharpe"] < (same_bar.mean() / same_bar.std() * np.sqrt(252))


def test_costs_reduce_equity_and_breakdown_adds_up():
    b = bars(200, 2)
    sig = pd.Series((np.arange(len(b)) % 6 < 3).astype(float), index=b.index)
    g = run_backtest({"X": b}, sig, ZERO)
    n = run_backtest({"X": b}, sig, BacktestConfig(costs=COST_PRESETS["high_cost"]))
    assert n.equity.iloc[-1] < g.equity.iloc[-1]
    cs = n.cost_summary()
    assert cs["total"] == pytest.approx(sum(cs[k] for k in ("commission", "spread", "slippage", "reg_fees", "borrow")))
    assert n.equity_gross.iloc[-1] == pytest.approx(g.equity.iloc[-1])
    assert cs["reg_fees"] > 0 and cs["commission"] > 0


def test_break_even_cost_positive_for_profitable_strategy(spy):
    sig = (spy["close"] > spy["close"].rolling(200).mean()).astype(float)
    be = break_even_bps({"SPY": spy}, sig, BacktestConfig(), iterations=10)
    assert be > 1


def test_stop_loss_exits_and_stays_out():
    b = bars(40, 5)
    b.iloc[10:, :4] = b.iloc[10:, :4] * 0.8          # crash after entry
    sig = pd.Series(1.0, index=b.index)
    res = run_backtest({"X": b}, sig, BacktestConfig(costs=CostModel(), stop_loss_pct=0.05))
    assert any(t.startswith("stop_loss") for t in res.trades["exit_reason"])
    assert len(res.trades) == 1                      # signal never changes -> stays out after the stop


def test_long_short_and_borrow_cost():
    b = bars(100, 7)
    sig = pd.Series(-1.0, index=b.index)
    res = run_backtest({"X": b}, sig, BacktestConfig(costs=CostModel(borrow_bps_annual=300), allow_short=True))
    assert res.weights["X"].iloc[-1] < 0 and res.cost_summary()["borrow"] > 0
    flat = run_backtest({"X": b}, sig, BacktestConfig(costs=CostModel()))          # long-only clips shorts
    assert (flat.weights["X"] == 0).all()


def test_multi_asset_weights_and_buy_and_hold(spy):
    from tests.conftest import demo
    panel = {"SPY": spy, "TLT": demo("TLT")}
    w = pd.DataFrame(0.5, index=spy.index, columns=["SPY", "TLT"])
    res = run_backtest(panel, w, ZERO)
    assert res.exposure.iloc[-1] == pytest.approx(1.0, abs=0.06)
    bh = buy_and_hold({"SPY": spy}, ZERO)
    assert bh.metrics()["total_return"] == pytest.approx(spy["close"].iloc[-1] / spy["open"].iloc[1] - 1, rel=1e-6)


def test_vol_target_sizing_scales_down(spy):
    sig = pd.Series(1.0, index=spy.index)
    res = run_backtest({"SPY": spy}, sig, BacktestConfig(sizing="vol_target", vol_target=0.05, costs=CostModel()))
    assert res.exposure.iloc[300:].mean() < 0.6
