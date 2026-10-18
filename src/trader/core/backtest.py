"""Portfolio backtest engine with next-bar execution and realistic costs.

Extends the course lab backtester (``labs/common/backtest.py``) from one asset
to many, adds position sizing, stop-loss / take-profit and a borrow cost for
shorts, while keeping its core rule:

    A target position decided with information available at the CLOSE of bar t
    is executed on the NEXT bar - at the open of t+1 (``next_open``, default,
    matches TradingView's Strategy Tester and the paper bot) or at the close of
    t+1 (``next_close``). There is no same-bar execution path, so the engine
    cannot introduce look-ahead bias.

Signals
    single asset : a Series of target positions in [-1, 1] (1 long, 0 flat, -1 short)
    multi asset  : a DataFrame of target weights (columns = symbols)

Sizing (turns a signal into a target weight of equity)
    percent_equity  weight = signal x size_pct
    fixed_notional  weight = signal x fixed_notional / equity
    vol_target      weight = signal x min(max_leverage, vol_target / realised vol)
    atr_risk        weight = signal x min(max_leverage, risk_pct / (atr_mult x ATR / close))

Gross results are produced by re-running the same path with a zero-cost model,
so ``net = gross - costs`` exactly, including compounding.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from trader.core import indicators as ta
from trader.core import metrics as M
from trader.core.costs import COST_KEYS, COST_PRESETS, CostModel

SIZING_MODES = ["percent_equity", "fixed_notional", "vol_target", "atr_risk"]


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    costs: CostModel = field(default_factory=lambda: COST_PRESETS["alpaca_retail"])
    execution: str = "next_open"            # next_open | next_close
    allow_short: bool = False
    sizing: str = "percent_equity"
    size_pct: float = 1.0
    fixed_notional: float = 10_000.0
    vol_target: float = 0.15
    vol_window: int = 21
    max_leverage: float = 1.0
    atr_risk_pct: float = 0.01
    atr_mult: float = 2.0
    atr_window: int = 14
    stop_loss_pct: float | None = None      # e.g. 0.05 = exit 5 % below entry (long)
    take_profit_pct: float | None = None    # e.g. 0.10 = exit 10 % above entry (long)
    rebalance_band: float = 0.05            # trade a drifted weight only if it is off by more than this
    whole_shares: bool = False
    periods: int = 252
    compute_gross: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["costs"] = self.costs.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict | None) -> BacktestConfig:
        d = dict(d or {})
        costs = CostModel.from_dict(d.pop("costs", None) or d.pop("cost_preset", None) or "alpaca_retail")
        known = set(cls.__dataclass_fields__) - {"costs"}
        kw = {k: v for k, v in d.items() if k in known and v is not None and v != ""}
        for k in ("stop_loss_pct", "take_profit_pct"):
            if k in kw and not float(kw[k]):
                kw[k] = None
        return cls(costs=costs, **kw)


@dataclass
class BacktestResult:
    equity: pd.Series
    returns: pd.Series
    equity_gross: pd.Series
    returns_gross: pd.Series
    weights: pd.DataFrame                   # weight of equity held at each close, per symbol
    exposure: pd.Series                     # net exposure (sum of weights) at each close
    trades: pd.DataFrame
    fills: pd.DataFrame
    costs: pd.DataFrame                     # per-bar dollar costs by type
    turnover_series: pd.Series              # traded notional / equity per bar
    config: BacktestConfig
    symbols: list[str]

    @property
    def initial_capital(self) -> float:
        return self.config.initial_capital

    def metrics(self, benchmark: pd.Series | None = None, gross: bool = False) -> dict:
        r = self.returns_gross if gross else self.returns
        col = "gross_return" if gross else "net_return"
        tr = self.trades[col] if len(self.trades) else pd.Series(dtype=float)
        pos = self.exposure
        m = M.summary(r, pos, tr, benchmark, self.config.periods)
        n = max(len(self.turnover_series), 1)
        m["turnover"] = float(self.turnover_series.sum() * self.config.periods / n)
        return m

    def cost_summary(self) -> dict:
        totals = self.costs.sum() if len(self.costs) else pd.Series(dtype=float)
        out = {k: float(totals.get(k, 0.0)) for k in COST_KEYS}
        out["total"] = float(sum(out.values()))
        out["total_pct_of_capital"] = out["total"] / self.initial_capital
        out["gross_cagr"] = M._f(M.cagr(self.returns_gross, self.config.periods))
        out["net_cagr"] = M._f(M.cagr(self.returns, self.config.periods))
        g, n = out["gross_cagr"], out["net_cagr"]
        out["cost_drag_cagr"] = (g - n) if g is not None and n is not None else None
        out["n_fills"] = len(self.fills)
        return out


# --------------------------------------------------------------------------- helpers
def _as_panel(bars) -> dict[str, pd.DataFrame]:
    if isinstance(bars, pd.DataFrame):
        return {getattr(bars, "attrs", {}).get("symbol", "ASSET"): bars}
    return dict(bars)


def align(bars: dict[str, pd.DataFrame]) -> tuple[pd.DatetimeIndex, dict[str, pd.DataFrame]]:
    """Inner-join the bar indices of several symbols (forward-fill isolated gaps)."""
    idx = None
    for df in bars.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    idx = pd.DatetimeIndex(idx).sort_values()
    return idx, {s: df.reindex(idx)[["open", "high", "low", "close", "volume"]].astype(float).ffill()
                 for s, df in bars.items()}


def _sizing_scale(cfg: BacktestConfig, df: pd.DataFrame) -> pd.Series:
    """Multiplicative scale applied to the raw signal (excluding fixed_notional, which is dynamic)."""
    if cfg.sizing == "vol_target":
        vol = ta.realized_vol(df["close"], cfg.vol_window, cfg.periods)
        return (cfg.vol_target / vol).clip(upper=cfg.max_leverage).fillna(0.0)
    if cfg.sizing == "atr_risk":
        a = ta.atr(df, cfg.atr_window)
        risk_per_unit = cfg.atr_mult * a / df["close"]
        return (cfg.atr_risk_pct / risk_per_unit).clip(upper=cfg.max_leverage).fillna(0.0)
    if cfg.sizing == "fixed_notional":
        return pd.Series(1.0, index=df.index)
    return pd.Series(float(cfg.size_pct), index=df.index)


def _round_shares(x: float, whole: bool) -> float:
    if not whole:
        return x
    return float(math.floor(x)) if x >= 0 else float(math.ceil(x))


# --------------------------------------------------------------------------- engine
def run_backtest(bars, signals, config: BacktestConfig | None = None) -> BacktestResult:
    cfg = config or BacktestConfig()
    if cfg.execution not in ("next_open", "next_close"):
        raise ValueError("execution must be 'next_open' or 'next_close'")
    panel = _as_panel(bars)
    if isinstance(signals, pd.Series):
        if len(panel) != 1:
            raise ValueError("a Series signal needs exactly one symbol of bars")
        signals = signals.to_frame(next(iter(panel)))
    idx, panel = align(panel)
    symbols = list(panel)
    sig = signals.reindex(index=idx, columns=symbols).astype(float).fillna(0.0)
    sig = sig.clip(-cfg.max_leverage * 10, cfg.max_leverage * 10)
    if not cfg.allow_short:
        sig = sig.clip(lower=0.0)
    scale = pd.DataFrame({s: _sizing_scale(cfg, panel[s]) for s in symbols}, index=idx)
    target = (sig * scale).values                  # decided at the close of each bar
    raw_sig = sig.values

    net = _simulate(idx, symbols, panel, target, raw_sig, cfg, cfg.costs)
    if cfg.compute_gross:
        gross = _simulate(idx, symbols, panel, target, raw_sig, cfg, CostModel())
        equity_gross = gross["equity"]
    else:
        equity_gross = net["equity"] + net["costs"]["total"].cumsum()
    equity = net["equity"]
    returns = equity.pct_change().fillna(equity.iloc[0] / cfg.initial_capital - 1.0)
    returns_gross = equity_gross.pct_change().fillna(equity_gross.iloc[0] / cfg.initial_capital - 1.0)
    return BacktestResult(equity, returns, equity_gross, returns_gross, net["weights"], net["exposure"],
                          net["trades"], net["fills"], net["costs"], net["turnover"], cfg, symbols)


def _simulate(idx, symbols, panel, target, raw_sig, cfg: BacktestConfig, costs: CostModel) -> dict:
    n, k = len(idx), len(symbols)
    O = np.column_stack([panel[s]["open"].values for s in symbols])
    H = np.column_stack([panel[s]["high"].values for s in symbols])
    L = np.column_stack([panel[s]["low"].values for s in symbols])
    C = np.column_stack([panel[s]["close"].values for s in symbols])
    cash = cfg.initial_capital
    shares = np.zeros(k)
    entry_px = np.full(k, np.nan)                 # average entry price of the open position
    stopped_sig = np.full(k, np.nan)              # signal value at the time of a stop / target exit
    prev_tgt = np.zeros(k)
    eq = np.empty(n)
    wts = np.zeros((n, k))
    cost_rows = np.zeros((n, len(COST_KEYS)))
    traded = np.zeros(n)
    fills: list[dict] = []
    open_tr: list[dict | None] = [None] * k
    trades: list[dict] = []
    ci = {c: j for j, c in enumerate(COST_KEYS)}

    def fill(i, j, new_shares, px, reason):
        nonlocal cash
        delta = new_shares - shares[j]
        if abs(delta) < 1e-12 or not np.isfinite(px) or px <= 0:
            return
        # a flip is two fills: close the old side, then open the new side
        if shares[j] != 0 and np.sign(new_shares) != np.sign(shares[j]) and new_shares != 0:
            fill(i, j, 0.0, px, reason)
            fill(i, j, new_shares, px, reason)
            return
        notional = abs(delta) * px
        cb = costs.trade_cost(notional, px, is_sell=delta < 0)
        tc = sum(cb.values())
        cash -= delta * px + tc
        for key, v in cb.items():
            cost_rows[i, ci[key]] += v
        traded[i] += notional
        fills.append({"date": idx[i], "symbol": symbols[j], "side": "buy" if delta > 0 else "sell",
                      "qty": float(abs(delta)), "price": float(px), "cost": float(tc), "reason": reason})
        old = shares[j]
        shares[j] = new_shares
        tr = open_tr[j]
        if old == 0:                               # open a new trade
            entry_px[j] = px
            open_tr[j] = {"symbol": symbols[j], "entry_date": idx[i], "entry_i": i, "side": "long" if delta > 0 else "short",
                          "entry_price": float(px), "cash_flow": -delta * px - tc, "costs": tc,
                          "max_notional": notional, "qty": float(abs(new_shares))}
        else:
            tr["cash_flow"] += -delta * px - tc
            tr["costs"] += tc
            if abs(new_shares) > abs(old):         # adding: update average entry
                entry_px[j] = (abs(old) * entry_px[j] + abs(delta) * px) / abs(new_shares)
                tr["max_notional"] = max(tr["max_notional"], abs(new_shares) * entry_px[j])
                tr["qty"] = max(tr["qty"], float(abs(new_shares)))
            if new_shares == 0:                    # close the trade
                sgn = 1.0 if tr["side"] == "long" else -1.0
                trades.append({"symbol": tr["symbol"], "entry_date": tr["entry_date"], "exit_date": idx[i],
                               "side": tr["side"], "qty": tr["qty"], "entry_price": tr["entry_price"],
                               "exit_price": float(px), "bars_held": i - tr["entry_i"],
                               "pnl": float(tr["cash_flow"]), "costs": float(tr["costs"]),
                               "gross_return": float(sgn * (px / tr["entry_price"] - 1.0)),
                               "net_return": float(tr["cash_flow"] / tr["max_notional"]) if tr["max_notional"] else 0.0,
                               "exit_reason": reason})
                open_tr[j] = None
                entry_px[j] = np.nan

    def rebalance(i, px_row, tgt_row, reason="signal"):
        e = cash + float(np.nansum(shares * px_row))
        if e <= 0:
            return
        for j in range(k):
            px = px_row[j]
            if not np.isfinite(px) or px <= 0:
                continue
            t = tgt_row[j]
            sraw = raw_sig_prev[j]
            if not np.isnan(stopped_sig[j]):
                if sraw == stopped_sig[j]:
                    t = 0.0                        # stay out after a stop until the signal changes
                else:
                    stopped_sig[j] = np.nan
            if cfg.sizing == "fixed_notional":
                t = t * cfg.fixed_notional / e
            cur_w = shares[j] * px / e
            changed_state = (np.sign(t) != np.sign(cur_w)) or (t == 0 and shares[j] != 0)
            drifted = abs(t - cur_w) > cfg.rebalance_band
            if changed_state or drifted:
                new = _round_shares(t * e / px, cfg.whole_shares)
                fill(i, j, new, px, reason)
            prev_tgt[j] = t

    def check_stops(i, open_row=None):
        if cfg.stop_loss_pct is None and cfg.take_profit_pct is None:
            return
        for j in range(k):
            if shares[j] == 0 or np.isnan(entry_px[j]):
                continue
            long = shares[j] > 0
            ep = entry_px[j]
            sl = cfg.stop_loss_pct
            tp = cfg.take_profit_pct
            stop_px = (ep * (1 - sl) if long else ep * (1 + sl)) if sl else None
            tp_px = (ep * (1 + tp) if long else ep * (1 - tp)) if tp else None
            if open_row is not None:               # gap through the level at the open
                o = open_row[j]
                if stop_px is not None and ((long and o <= stop_px) or (not long and o >= stop_px)):
                    fill(i, j, 0.0, o, "stop_loss (gap)")
                    stopped_sig[j] = raw_sig_prev[j]
                    continue
                if tp_px is not None and ((long and o >= tp_px) or (not long and o <= tp_px)):
                    fill(i, j, 0.0, o, "take_profit (gap)")
                    stopped_sig[j] = raw_sig_prev[j]
                    continue
                continue
            hit_sl = stop_px is not None and ((long and L[i, j] <= stop_px) or (not long and H[i, j] >= stop_px))
            hit_tp = tp_px is not None and ((long and H[i, j] >= tp_px) or (not long and L[i, j] <= tp_px))
            if hit_sl:                             # conservative: assume the stop is hit first
                fill(i, j, 0.0, stop_px, "stop_loss")
                stopped_sig[j] = raw_sig_prev[j]
            elif hit_tp:
                fill(i, j, 0.0, tp_px, "take_profit")
                stopped_sig[j] = raw_sig_prev[j]

    raw_sig_prev = np.zeros(k)
    for i in range(n):
        if i > 0:
            tgt = target[i - 1]
            raw_sig_prev = raw_sig[i - 1]
            if cfg.execution == "next_open":
                check_stops(i, open_row=O[i])
                rebalance(i, O[i], tgt)
                check_stops(i)
            else:                                  # next_close: hold through the bar, trade at its close
                check_stops(i)
                rebalance(i, C[i], tgt)
        short_notional = float(np.nansum(np.where(shares < 0, -shares * C[i], 0.0)))
        if short_notional > 0 and costs.borrow_bps_annual:
            b = costs.borrow_cost(short_notional, cfg.periods)
            cash -= b
            cost_rows[i, ci["borrow"]] += b
        e = cash + float(np.nansum(shares * C[i]))
        eq[i] = e
        wts[i] = shares * C[i] / e if e > 0 else 0.0

    last = n - 1
    for j in range(k):                             # open trades: mark to market at the last close
        tr = open_tr[j]
        if tr is None:
            continue
        sgn = 1.0 if tr["side"] == "long" else -1.0
        mtm = tr["cash_flow"] + shares[j] * C[last, j]
        trades.append({"symbol": tr["symbol"], "entry_date": tr["entry_date"], "exit_date": idx[last],
                       "side": tr["side"] + " (open)", "qty": tr["qty"], "entry_price": tr["entry_price"],
                       "exit_price": float(C[last, j]), "bars_held": last - tr["entry_i"], "pnl": float(mtm),
                       "costs": float(tr["costs"]), "gross_return": float(sgn * (C[last, j] / tr["entry_price"] - 1.0)),
                       "net_return": float(mtm / tr["max_notional"]) if tr["max_notional"] else 0.0,
                       "exit_reason": "open"})
    equity = pd.Series(eq, idx, name="equity")
    cost_df = pd.DataFrame(cost_rows, index=idx, columns=COST_KEYS)
    cost_df["total"] = cost_df[COST_KEYS].sum(axis=1)
    weights = pd.DataFrame(wts, index=idx, columns=symbols)
    turnover = pd.Series(traded, idx) / equity.shift(1).fillna(cfg.initial_capital)
    trades_df = pd.DataFrame(trades)
    if len(trades_df):
        trades_df = trades_df.sort_values("entry_date").reset_index(drop=True)
    return {"equity": equity, "costs": cost_df, "weights": weights, "exposure": weights.sum(axis=1),
            "trades": trades_df, "fills": pd.DataFrame(fills), "turnover": turnover}


# --------------------------------------------------------------------------- conveniences
def buy_and_hold(bars, config: BacktestConfig | None = None) -> BacktestResult:
    """Benchmark: buy at the first next-bar open and hold to the end."""
    panel = _as_panel(bars)
    idx, panel = align(panel)
    w = pd.DataFrame(1.0 / len(panel), index=idx, columns=list(panel))
    return run_backtest(panel, w, config)


def break_even_bps(bars, signals, config: BacktestConfig | None = None, iterations: int = 20) -> float:
    """One-way cost (charged as slippage bps) at which the net CAGR reaches zero (bisection)."""
    base = config or BacktestConfig()
    cfg0 = BacktestConfig(**{**base.__dict__, "costs": CostModel(), "compute_gross": False})
    if (M.cagr(run_backtest(bars, signals, cfg0).returns) or 0) <= 0:
        return 0.0
    lo, hi = 0.0, 500.0
    for _ in range(iterations):
        mid = (lo + hi) / 2
        cfg = BacktestConfig(**{**cfg0.__dict__, "costs": CostModel("probe", slippage_bps=mid)})
        if M.cagr(run_backtest(bars, signals, cfg).returns) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def series_payload(s: pd.Series, decimals: int = 6) -> list[list]:
    """[[iso date, value], ...] for JSON (NaN -> None)."""
    out = []
    for t, v in s.items():
        fv = None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), decimals)
        out.append([pd.Timestamp(t).isoformat()[:19 if pd.Timestamp(t).hour or pd.Timestamp(t).minute else 10], fv])
    return out
