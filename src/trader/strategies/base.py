"""The strategy plugin API.

Write a strategy by subclassing :class:`Strategy`::

    from trader.strategies.base import Strategy
    from trader.core import indicators as ta

    class MyStrategy(Strategy):
        name = "My EMA cross"
        params = {
            "fast": {"default": 10, "min": 2, "max": 100, "help": "fast EMA length"},
            "slow": 30,                                    # short form: type inferred from the default
        }

        def generate_signals(self, data):                  # data: OHLCV DataFrame (index = bar time)
            fast = ta.ema(data["close"], self.p.fast)
            slow = ta.ema(data["close"], self.p.slow)
            return (fast > slow).astype(float)             # 1 = long, 0 = flat, -1 = short

Rules
* Use only information up to and including bar t to compute the value at bar t.
  The engine executes the signal on the NEXT bar (no same-bar fills).
* Single-asset strategies return a Series aligned to ``data.index``.
* Multi-asset strategies set ``multi_asset = True``; ``data`` is then a dict
  ``{symbol: DataFrame}`` and they return a DataFrame of target weights.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, ClassVar

import pandas as pd


@dataclass
class Param:
    name: str
    type: str = "float"                   # int | float | bool | str | choice
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list | None = None
    help: str = ""

    def coerce(self, v):
        if v is None or v == "":
            return self.default
        if self.type == "int":
            v = int(float(v))
        elif self.type == "float":
            v = float(v)
        elif self.type == "bool":
            v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
        elif self.type == "choice":
            if self.choices and v not in self.choices:
                raise ValueError(f"{self.name} must be one of {self.choices}")
            return v
        else:
            return str(v)
        if self.min is not None and v < self.min:
            raise ValueError(f"{self.name} must be >= {self.min}")
        if self.max is not None and v > self.max:
            raise ValueError(f"{self.name} must be <= {self.max}")
        return v

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None and v != ""}


def parse_params(spec: dict) -> dict[str, Param]:
    """Accept {"fast": 10} or {"fast": {"default": 10, "min": 2, ...}} or Param objects."""
    out: dict[str, Param] = {}
    for name, s in (spec or {}).items():
        if isinstance(s, Param):
            out[name] = s
            continue
        if isinstance(s, dict):
            d = dict(s)
            default = d.get("default")
            typ = d.get("type") or ("choice" if d.get("choices") else _infer(default))
            out[name] = Param(name=name, type=typ, default=default, min=d.get("min"), max=d.get("max"),
                              step=d.get("step"), choices=d.get("choices"), help=d.get("help", ""))
        else:
            out[name] = Param(name=name, type=_infer(s), default=s)
    return out


def _infer(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    return "str"


@dataclass
class StrategyInfo:
    """Metadata shown in the strategy library."""
    key: str
    name: str
    kind: str = "signal"                  # signal | portfolio | execution | market_making | agentic
    category: str = "Directional / alpha"
    family: str = "Trend following"
    holding_period: str = "Position"
    model_type: str = "Rule-based"
    summary: str = ""
    how: str = ""
    rule: str = ""
    works_best: str = ""
    watch_out: str = ""
    course_ref: str = ""
    default_symbols: list[str] = field(default_factory=lambda: ["SPY"])
    pine: bool = False
    needs: list[str] = field(default_factory=list)   # e.g. ["sentiment"], ["intraday"]


class Strategy:
    """Base class for every built-in and custom strategy."""

    name: ClassVar[str] = "Unnamed strategy"
    params: ClassVar[dict] = {}
    multi_asset: ClassVar[bool] = False
    allow_short: ClassVar[bool] = False
    info: ClassVar[StrategyInfo | None] = None

    def __init__(self, **overrides):
        self.schema = parse_params(type(self).params)
        unknown = set(overrides) - set(self.schema)
        if unknown:
            raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
        values = {n: p.coerce(overrides.get(n, p.default)) for n, p in self.schema.items()}
        self.p = SimpleNamespace(**values)
        self.values = values

    # ---- the one method a strategy must implement
    def generate_signals(self, data) -> pd.Series | pd.DataFrame:  # pragma: no cover - abstract
        raise NotImplementedError

    # ---- helpers
    def run(self, data):
        out = self.generate_signals(data)
        if self.multi_asset:
            if not isinstance(out, pd.DataFrame):
                raise TypeError("a multi-asset strategy must return a DataFrame of weights")
            return out.astype(float).fillna(0.0)
        if isinstance(out, pd.DataFrame):
            out = out.iloc[:, 0]
        if not isinstance(out, pd.Series):
            raise TypeError("generate_signals must return a pandas Series")
        out = out.reindex(data.index).astype(float).fillna(0.0)
        lo = -1.0 if (self.allow_short or getattr(self.p, "allow_short", False)) else 0.0
        return out.clip(lo, 1.0)

    @classmethod
    def schema_dict(cls) -> list[dict]:
        return [p.to_dict() for p in parse_params(cls.params).values()]


def enter_exit(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """Stateful long/flat: 1 from an entry bar until the next exit bar (entry wins a tie)."""
    state = pd.Series(float("nan"), index=entry.index)
    state[exit_.fillna(False).astype(bool)] = 0.0
    state[entry.fillna(False).astype(bool)] = 1.0
    return state.ffill().fillna(0.0)


def flat_until_ready(cond: pd.Series, *inputs: pd.Series) -> pd.Series:
    """1.0 where cond is true, 0.0 otherwise and during indicator warm-up (NaN inputs)."""
    ready = pd.concat(inputs, axis=1).notna().all(axis=1)
    return cond.astype(float).where(ready, 0.0)
