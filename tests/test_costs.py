import pytest

from trader.core.costs import COST_PRESETS, FINRA_TAF, SEC_FEE, CostModel


def test_commission_minimum_and_per_share():
    cm = CostModel(commission_per_share=0.005, min_commission=1.0)
    assert cm.trade_cost(1000, 100, False)["commission"] == pytest.approx(1.0)      # 10 shares x 0.005 < min
    assert cm.trade_cost(100_000, 100, False)["commission"] == pytest.approx(5.0)   # 1000 shares


def test_spread_slippage_and_reg_fees_on_sells_only():
    cm = CostModel(spread_bps=2, slippage_bps=3, sec_fee_rate=SEC_FEE, taf_per_share=FINRA_TAF)
    buy = cm.trade_cost(10_000, 100, False)
    sell = cm.trade_cost(10_000, 100, True)
    assert buy["spread"] == pytest.approx(1.0) and buy["slippage"] == pytest.approx(3.0)
    assert buy["reg_fees"] == 0
    assert sell["reg_fees"] == pytest.approx(10_000 * SEC_FEE + 100 * FINRA_TAF)


def test_taf_cap_and_scaling_and_presets():
    cm = CostModel(taf_per_share=1.0, taf_max=8.30)
    assert cm.trade_cost(1_000_000, 1, True)["reg_fees"] == pytest.approx(8.30)
    assert CostModel(spread_bps=2).scaled(3).spread_bps == 6
    assert COST_PRESETS["zero"].trade_cost(1e6, 100, True) == {k: 0.0 for k in ["commission", "spread", "slippage", "reg_fees", "borrow"]}
    assert CostModel.from_dict("alpaca_retail").name.startswith("Alpaca")
    assert CostModel.from_dict({"preset": "zero", "slippage_bps": 5}).slippage_bps == 5
    assert CostModel(borrow_bps_annual=252).borrow_cost(10_000) == pytest.approx(1.0)
