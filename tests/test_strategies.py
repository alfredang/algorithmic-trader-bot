import pandas as pd
import pytest

from trader.core.signal_checks import lookahead_check
from trader.strategies import registry, sandbox
from trader.strategies.builtin import REGISTRY

FAST = ["sma_cross", "ema_cross", "trend_filter", "macd_cross", "rsi_threshold", "rsi2_reversion", "bollinger_reversion",
        "bollinger_breakout", "dip_buy", "donchian_breakout", "ts_momentum", "agentic_desk"]


@pytest.mark.parametrize("key", FAST)
def test_builtin_signals_have_no_lookahead(key, spy):
    cls = REGISTRY[key]
    res = lookahead_check(lambda b: cls().run(b), spy.iloc[-700:], checks=4)
    assert res["status"] == "PASS", res


def test_ml_and_regime_strategies_are_walk_forward_safe(spy):
    for key in ("ml_logistic", "regime_filtered"):
        res = lookahead_check(lambda b, k=key: REGISTRY[k]().run(b), spy, checks=2)
        assert res["status"] == "PASS", (key, res)


def test_every_strategy_has_explanation_and_tags():
    assert len(REGISTRY) >= 24
    for key, cls in REGISTRY.items():
        d = registry.builtin_descriptor(cls)
        assert d["how"] and d["watch_out"] and d["tags"]["category"], key


def test_multi_asset_strategies(spy):
    from tests.conftest import demo
    w = REGISTRY["xs_momentum"](top_k=1).run({"SPY": spy, "TLT": demo("TLT"), "QQQ": demo("QQQ")})
    assert (w.sum(axis=1) <= 1.0 + 1e-9).all() and w.iloc[-1].sum() == pytest.approx(1.0)
    p = REGISTRY["pairs_cointegration"]().run({"KO": demo("KO"), "PEP": demo("PEP")})
    assert (p.iloc[:756] == 0).all().all() and set(p.columns) == {"KO", "PEP"}


def test_params_are_validated():
    with pytest.raises(ValueError):
        REGISTRY["ema_cross"](fast=1)
    with pytest.raises(ValueError):
        REGISTRY["ema_cross"](nope=3)


GOOD = '''
from trader.strategies.base import Strategy
from trader.core import indicators as ta
class Mine(Strategy):
    name = "Mine"
    params = {"n": {"default": 10, "min": 2}}
    def generate_signals(self, data):
        return (data["close"] > ta.sma(data["close"], self.p.n)).astype(float)
'''


def test_custom_strategy_validation_and_sandbox(spy):
    v = registry.validate_code(GOOD, spy.iloc[-400:])
    assert v["ok"] and v["meta"]["params_schema"][0]["name"] == "n" and v["lookahead"]["status"] == "PASS"
    for bad, msg in [("import os\n" + GOOD, "import of 'os'"), (GOOD + "\nopen('x')", "open"),
                     (GOOD.replace("astype(float)", "astype(float).__class__"), "__class__")]:
        out = registry.validate_code(bad, spy.iloc[-100:])
        assert not out["ok"] and msg in out["issues"][0]["message"]
    with pytest.raises(sandbox.SandboxError):
        sandbox.run(GOOD.replace("return (", "while True:\n            pass\n        return ("), spy.iloc[-50:], timeout=2)


def test_biased_exhibit_fails_lookahead(spy):
    res = lookahead_check(lambda b: sandbox.run(registry.BIASED_CODE, b)["signals"], spy.iloc[-300:], checks=2)
    assert res["status"] == "FAIL"


def test_clone_code_is_valid(spy):
    for key in ("ema_cross", "ml_logistic", "regime_filtered", "pairs_cointegration"):
        assert not sandbox.check_source(registry.clone_code(key)), key


def test_pine_export():
    from trader.strategies import pine
    code = pine.export("ema_cross", {"fast": 10, "slow": 30}, "EMA crossover")
    assert code.startswith("//@version=6") and "process_orders_on_close = false" in code and "ta.ema" in code
    with pytest.raises(KeyError):
        pine.export("xs_momentum", {}, "x")


def test_sentiment_requires_column(spy):
    with pytest.raises(ValueError):
        REGISTRY["sentiment"]().run(spy)
    s = spy.assign(sentiment=0.5)
    assert REGISTRY["sentiment"](trend_filter=False).run(s).iloc[-1] == 1.0
    assert isinstance(pd.Series, type)
