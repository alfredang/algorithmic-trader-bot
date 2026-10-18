import numpy as np
import pandas as pd
import pytest

from trader.core import metrics as M


def test_total_return_cagr_vol_sharpe_known_values():
    r = pd.Series([0.01, -0.02, 0.03, 0.0])
    assert M.total_return(r) == pytest.approx(1.01 * 0.98 * 1.03 - 1)
    assert M.cagr(r) == pytest.approx((1 + M.total_return(r)) ** (252 / 4) - 1)
    assert M.annual_volatility(r) == pytest.approx(r.std(ddof=1) * np.sqrt(252))
    assert M.sharpe_ratio(r) == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(252))
    downside = np.sqrt((np.minimum(r, 0) ** 2).mean())
    assert M.sortino_ratio(r) == pytest.approx(r.mean() / downside * np.sqrt(252))


def test_max_drawdown_and_calmar():
    r = pd.Series([0.10, -0.50, 0.20])       # equity 1.1 -> 0.55 -> 0.66
    assert M.max_drawdown(r) == pytest.approx(-0.5)
    assert M.calmar_ratio(r) == pytest.approx(M.cagr(r) / 0.5)
    assert M.max_drawdown_duration(r) == 2


def test_trade_statistics():
    t = pd.Series([0.10, -0.05, 0.20, -0.05])
    assert M.win_rate(t) == 0.5
    assert M.profit_factor(t) == pytest.approx(0.30 / 0.10)
    assert M.expectancy(t) == pytest.approx(t.mean())
    assert M.avg_win(t) == pytest.approx(0.15) and M.avg_loss(t) == pytest.approx(-0.05)


def test_exposure_turnover_alpha_beta():
    pos = pd.Series([0, 1, 1, 0])
    assert M.exposure(pos) == 0.5
    assert M.turnover(pos) == pytest.approx(2 * 252 / 4)
    m = pd.Series(np.random.default_rng(1).normal(0, 0.01, 500))
    alpha, beta = M.alpha_beta(2 * m + 0.001, m)
    assert beta == pytest.approx(2.0) and alpha == pytest.approx(0.252)


def test_summary_is_json_safe():
    s = M.summary(pd.Series([0.0, 0.0, 0.0]))
    assert s["sharpe"] is None and s["trades"] == 0
