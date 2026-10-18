import numpy as np
import pandas as pd

from trader.core import pairs as PR
from trader.core import stats as ST


def test_engle_granger_detects_cointegration():
    rng = np.random.default_rng(42)
    b = np.cumsum(rng.normal(0, 0.01, 1500)) + 4
    a = 0.5 + 1.2 * b + rng.normal(0, 0.01, 1500)           # stationary spread
    alpha, beta, t = PR.engle_granger(pd.Series(a), pd.Series(b))
    assert abs(beta - 1.2) < 0.05 and t < PR.EG_CRIT["5%"]
    c = np.cumsum(rng.normal(0, 0.01, 1500)) + 4          # independent random walk
    _, _, t2 = PR.engle_granger(pd.Series(c), pd.Series(b))
    assert t2 > PR.EG_CRIT["1%"]


def test_spread_state_machine_and_leg_weights():
    z = pd.Series([0, 2.5, 1.0, 0.2, -2.5, -1, 0.1])
    st = PR.spread_state(z, 2.0, 0.5)
    assert st.tolist() == [0, -1, -1, 0, 1, 1, 0]
    w = PR.leg_weights(pd.Series([1.0]), 1.5, "A", "B")
    assert abs(w["A"].iloc[0]) + abs(w["B"].iloc[0]) == 1.0 and w["B"].iloc[0] < 0


def test_ab_test_identical_vs_different():
    rng = np.random.default_rng(3)
    a = pd.Series(rng.normal(0.0005, 0.01, 1500))
    r = ST.ab_test(a, a.copy() + 0.0, n_boot=200)
    assert not r["reject_h0"]
    b = pd.Series(rng.normal(0.0005, 0.01, 1500))
    strong = ST.ab_test(a + 0.003, a, n_boot=300)
    assert strong["reject_h0"] and strong["winner"] == "A" and strong["paired_p"] < 0.001
    assert ST.ab_test(a, b, n_boot=200)["bonferroni_alpha"] == 0.05 / 20


def test_hypothesis_test_shape(spy):
    r = ST.hypothesis_test(spy, {"type": "losing_streak", "n": 3}, horizon=1, n_boot=500)
    assert r["signal_days"] > 50 and 0 <= r["p_value"] <= 1 and len(r["ci"]) == 2
    assert r["decision"].startswith(("SUPPORTED", "NOT SUPPORTED"))
