"""Strategy library service: built-in classes + user custom strategies stored in the DB."""
from __future__ import annotations

import ast
import inspect
import re
import textwrap

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.models import StrategyRecord
from trader.strategies import sandbox
from trader.strategies.base import Strategy, parse_params
from trader.strategies.builtin import REGISTRY

CATEGORY_TAGS = ["Execution algorithms", "Market making", "Arbitrage", "Directional / alpha",
                 "Statistical arbitrage and pairs", "Factor and portfolio", "Hedging and risk"]


def builtin_descriptor(cls: type[Strategy]) -> dict:
    info = cls.info
    schema = cls.schema_dict()
    return {"key": info.key, "name": info.name, "kind": info.kind, "builtin": True, "custom": False,
            "params_schema": schema, "default_params": {p["name"]: p.get("default") for p in schema},
            "multi_asset": cls.multi_asset, "allow_short": cls.allow_short or any(p["name"] == "allow_short" for p in schema),
            "default_symbols": info.default_symbols, "needs": info.needs, "pine": info.pine,
            "tags": {"category": info.category, "family": info.family, "holding_period": info.holding_period,
                     "model_type": info.model_type},
            "summary": info.summary, "how": info.how, "rule": info.rule, "works_best": info.works_best,
            "watch_out": info.watch_out, "course_ref": info.course_ref}


def custom_descriptor(r: StrategyRecord) -> dict:
    info = r.info or {}
    return {"key": r.key, "name": r.name, "kind": r.kind or "signal", "builtin": False, "custom": True,
            "params_schema": r.params_schema or [], "default_params": r.default_params or {},
            "multi_asset": r.multi_asset, "allow_short": bool(info.get("allow_short", False)),
            "default_symbols": info.get("default_symbols", ["SPY"]), "needs": info.get("needs", []), "pine": False,
            "tags": {"category": info.get("category", "Directional / alpha"), "family": info.get("family", "Custom"),
                     "holding_period": info.get("holding_period", "Swing"), "model_type": info.get("model_type", "Rule-based")},
            "summary": info.get("summary", "User-defined Python strategy."), "how": info.get("how", ""),
            "rule": info.get("rule", ""), "works_best": info.get("works_best", ""), "watch_out": info.get("watch_out", ""),
            "course_ref": info.get("course_ref", ""), "code": r.code, "parent_key": r.parent_key,
            "validated": r.validated, "validation": r.validation,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def list_all(db: Session) -> list[dict]:
    out = [builtin_descriptor(c) for c in REGISTRY.values()]
    out += [custom_descriptor(r) for r in db.scalars(select(StrategyRecord).where(StrategyRecord.builtin.is_(False))
                                                     .order_by(StrategyRecord.created_at))]
    return out


def get(db: Session, key: str) -> dict:
    if key in REGISTRY:
        return builtin_descriptor(REGISTRY[key])
    r = db.scalar(select(StrategyRecord).where(StrategyRecord.key == key))
    if r is None:
        raise KeyError(f"unknown strategy '{key}'")
    return custom_descriptor(r)


def coerce_params(desc: dict, params: dict | None) -> dict:
    schema = parse_params({p["name"]: p for p in desc["params_schema"]})
    params = params or {}
    unknown = set(params) - set(schema)
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    return {n: p.coerce(params.get(n, p.default)) for n, p in schema.items()}


def compute_signals(db: Session, key: str, data, params: dict | None = None) -> tuple[pd.Series | pd.DataFrame, dict]:
    """Target positions / weights for a strategy (built-in in-process, custom in the sandbox)."""
    desc = get(db, key)
    params = coerce_params(desc, params)
    if desc["builtin"]:
        inst = REGISTRY[key](**params)
        sig = inst.run(data)
        extra = {}
        for attr in ("diagnostics",):
            if hasattr(inst, attr):
                extra[attr] = getattr(inst, attr)
        if hasattr(inst, "folds"):
            extra["folds"] = inst.folds.to_dict("records")
        if hasattr(inst, "regimes"):
            vc = inst.regimes.value_counts()
            extra["regimes"] = {str(k): int(v) for k, v in vc.items()}
        return sig, extra
    res = sandbox.run(desc["code"], data, params)
    return res["signals"], {"sandbox": True}


# --------------------------------------------------------------------------- custom strategies
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"custom_{s or 'strategy'}"[:60]


def validate_code(code: str, data, params: dict | None = None) -> dict:
    """Static checks + a test run in the sandbox. Returns meta and a short signal summary."""
    issues = sandbox.check_source(code)
    if issues:
        return {"ok": False, "issues": [{"line": i.line, "message": i.message} for i in issues]}
    try:
        res = sandbox.run(code, data, params)
    except sandbox.SandboxError as exc:
        return {"ok": False, "issues": [{"line": 0, "message": str(exc)}]}
    sig = res["signals"]
    s = sig if isinstance(sig, pd.Series) else sig.abs().sum(axis=1)
    summary = {"bars": int(len(s)), "exposure": float((s != 0).mean()), "changes": int((s.diff().fillna(0) != 0).sum()),
               "latest": float(s.iloc[-1]) if len(s) else None, "min": float(s.min()), "max": float(s.max())}
    from trader.core.signal_checks import lookahead_check
    la = lookahead_check(lambda d: sandbox.run(code, d, params)["signals"], data, checks=3) if not res["multi"] else None
    return {"ok": True, "issues": [], "meta": res["meta"], "summary": summary, "lookahead": la}


def save_custom(db: Session, code: str, meta: dict, key: str | None = None, info: dict | None = None,
                parent_key: str | None = None, validation: dict | None = None) -> StrategyRecord:
    rec = db.scalar(select(StrategyRecord).where(StrategyRecord.key == key)) if key else None
    if rec is None:
        base = slugify(meta.get("name") or "strategy")
        k, i = base, 2
        while db.scalar(select(StrategyRecord.id).where(StrategyRecord.key == k)) or k in REGISTRY:
            k, i = f"{base}_{i}", i + 1
        rec = StrategyRecord(key=k, builtin=False)
        db.add(rec)
    rec.name = meta.get("name") or rec.key
    rec.code = code
    rec.params_schema = meta.get("params_schema", [])
    rec.default_params = meta.get("default_params", {})
    rec.multi_asset = bool(meta.get("multi_asset", False))
    rec.kind = "portfolio" if rec.multi_asset else "signal"
    merged = {**(rec.info or {}), **(info or {}), "allow_short": bool(meta.get("allow_short", False))}
    rec.info = merged
    rec.parent_key = parent_key or rec.parent_key
    rec.validated = bool(validation and validation.get("ok"))
    rec.validation = validation
    db.flush()
    return rec


HEADER = '''"""{name} - cloned from the built-in '{key}' strategy. Edit freely, then Validate and Save."""
from trader.core import indicators as ta
from trader.core import ml as ML
from trader.core import pairs as PR
from trader.core import regime as RG
from trader.strategies.base import Strategy, enter_exit, flat_until_ready
'''


def clone_code(key: str) -> str:
    """Editable source of a built-in strategy (its class body, minus the library metadata)."""
    cls = REGISTRY[key]
    chain = [c for c in cls.__mro__ if c not in (Strategy, object)]
    src_parts = []
    for c in reversed(chain):
        src = textwrap.dedent(inspect.getsource(c))
        tree = ast.parse(src)
        node = tree.body[0]
        node.body = [n for n in node.body if not (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "info" for t in n.targets))]
        if c is cls:
            node.name = f"My{cls.__name__.lstrip('_')}"
        src_parts.append(ast.unparse(node))
    code = "\n\n\n".join(src_parts)
    code = re.sub(r"REGISTRY\[self\.p\.base\]\(\)", "__base_strategy(self.p.base)", code)
    hdr = HEADER.format(name=cls.info.name, key=key)
    if "__base_strategy" in code:
        hdr += "from trader.strategies.builtin import REGISTRY as _LIB\n\n\ndef _base(key):\n    return _LIB[key]()\n"
        code = code.replace("__base_strategy(self.p.base)", "_base(self.p.base)")
    if "mm." in code:
        hdr += "from trader.core import market_making as mm\n"
    if "np." in code:
        hdr += "import numpy as np\n"
    if "pd." in code:
        hdr += "import pandas as pd\n"
    if "SIGNAL_BASES" in code:
        hdr += "from trader.strategies.builtin import SIGNAL_BASES\n"
    code = code.replace(f"name = '{cls.info.name}'", f"name = 'My {cls.info.name}'")
    return hdr + "\n\n" + code + "\n"


TEMPLATES = {
    "blank": {"title": "Blank single-asset strategy", "code": '''from trader.core import indicators as ta
from trader.strategies.base import Strategy


class MyStrategy(Strategy):
    """Describe your idea here: the hypothesis, the rule and when it should work."""
    name = "My strategy"
    params = {
        "window": {"default": 20, "min": 2, "max": 200, "help": "Lookback in bars"},
    }

    def generate_signals(self, data):
        # data: OHLCV DataFrame. Use only information up to each bar - the engine trades on the NEXT bar.
        sma = ta.sma(data["close"], self.p.window)
        return (data["close"] > sma).astype(float)      # 1 = long, 0 = flat (-1 = short)
'''},
    "ema_rsi": {"title": "EMA trend with an RSI filter", "code": '''from trader.core import indicators as ta
from trader.strategies.base import Strategy, flat_until_ready


class TrendWithRSIFilter(Strategy):
    """Long while EMA(fast) > EMA(slow), but skip entries when RSI says the move is stretched."""
    name = "EMA trend + RSI filter"
    params = {
        "fast": {"default": 20, "min": 2, "max": 200, "help": "Fast EMA"},
        "slow": {"default": 50, "min": 3, "max": 400, "help": "Slow EMA"},
        "rsi_max": {"default": 75, "min": 50, "max": 95, "help": "No longs above this RSI(14)"},
    }

    def generate_signals(self, data):
        f, s = ta.ema(data["close"], self.p.fast), ta.ema(data["close"], self.p.slow)
        r = ta.rsi(data["close"], 14)
        return flat_until_ready((f > s) & (r < self.p.rsi_max), f, s, r)
'''},
    "mean_reversion": {"title": "Bollinger mean reversion with a stop", "code": '''from trader.core import indicators as ta
from trader.strategies.base import Strategy, enter_exit


class BandReversion(Strategy):
    """Buy a close below the lower band, exit at the middle band. Add a stop-loss in the backtest form."""
    name = "Band reversion"
    params = {"window": 20, "k": {"default": 2.0, "min": 0.5, "max": 4.0, "step": 0.1}}

    def generate_signals(self, data):
        b = ta.bollinger(data["close"], self.p.window, self.p.k)
        return enter_exit(data["close"] < b["lower"], data["close"] > b["middle"])
'''},
    "long_short": {"title": "Long/short momentum", "code": '''from trader.strategies.base import Strategy


class LongShortMomentum(Strategy):
    """Long when the 3-month return is positive, short when negative (tick 'Allow short' in the backtest)."""
    name = "Long/short momentum"
    allow_short = True
    params = {"lookback": {"default": 63, "min": 5, "max": 252}}

    def generate_signals(self, data):
        r = data["close"].pct_change(self.p.lookback)
        return ((r > 0).astype(float) - (r < 0).astype(float)).fillna(0.0)
'''},
    "multi_asset": {"title": "Multi-asset rotation (weights)", "code": '''import pandas as pd

from trader.strategies.base import Strategy


class TopNRotation(Strategy):
    """Each month hold the N symbols with the best 6-month return, equally weighted."""
    name = "Top-N rotation"
    multi_asset = True
    params = {"lookback": 126, "top_n": {"default": 2, "min": 1, "max": 10}, "rebalance": 21}

    def generate_signals(self, data):
        closes = pd.DataFrame({s: df["close"] for s, df in data.items()}).dropna()
        mom = closes.pct_change(self.p.lookback)
        w = pd.DataFrame(float("nan"), index=closes.index, columns=closes.columns)
        for i in range(0, len(closes), self.p.rebalance):
            row = mom.iloc[i]
            if row.notna().sum() >= self.p.top_n:
                w.iloc[i] = ((row.rank(ascending=False) <= self.p.top_n) / self.p.top_n).values
        return w.ffill().fillna(0.0)
'''},
    "ml": {"title": "Machine-learning classifier (walk-forward)", "code": '''from trader.core import ml as ML
from trader.strategies.base import Strategy


class MyClassifier(Strategy):
    """Walk-forward logistic regression on the course feature set; long when P(up) > threshold."""
    name = "My ML classifier"
    params = {
        "model": {"default": "logistic", "choices": ["logistic", "random_forest", "xgboost"]},
        "threshold": {"default": 0.55, "min": 0.4, "max": 0.8, "step": 0.01},
    }

    def generate_signals(self, data):
        proba, _folds = ML.walk_forward_proba(data, self.p.model, min_train=504, retrain_every=126)
        return (proba > self.p.threshold).astype(float).where(proba.notna(), 0.0)
'''},
}

# The deliberately biased exhibit for Lab 18 (look-ahead through a centred rolling window)
BIASED_CODE = '''"""Lab 18 exhibit - 'smoothed momentum' as submitted by a junior quant. It contains a LOOK-AHEAD BUG:
rolling(..., center=True) averages bars t-2 .. t+2, so each signal uses two FUTURE closes.
Run Research > Diagnostics on it, then fix it (center=False) and compare."""
from trader.strategies.base import Strategy


class BiasedSmoothedMomentum(Strategy):
    name = "Lab 18 exhibit: biased smoothed momentum"
    params = {"window": {"default": 5, "min": 3, "max": 21, "help": "Smoothing window (centred - the bug)"}}

    def generate_signals(self, data):
        smooth = data["close"].rolling(self.p.window, center=True).mean()     # BUG: uses future bars
        return (smooth > smooth.shift(1)).astype(float)
'''
