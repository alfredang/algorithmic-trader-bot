"""Performance and risk metrics (course Topic 2.5 / Lab 09).

Inputs are simple periodic returns (0.01 = +1 %) indexed by date. Annualised
figures assume ``periods`` bars per year (252 trading days by default). Every
docstring gives the formula so learners can reproduce it in Excel.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _clean(x) -> pd.Series:
    return pd.Series(x, dtype=float).replace([np.inf, -np.inf], np.nan)


def equity_curve(returns: pd.Series, start_value: float = 1.0) -> pd.Series:
    """Equity_t = start_value * prod(1 + r_1 .. r_t)."""
    return start_value * (1.0 + returns.fillna(0.0)).cumprod()


def total_return(returns: pd.Series) -> float:
    """Total return = prod(1 + r_t) - 1."""
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def cagr(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    """CAGR = (1 + total return) ** (periods / N) - 1, N = number of bars."""
    n = returns.dropna().shape[0]
    if n == 0:
        return float("nan")
    tr = total_return(returns)
    if tr <= -1:
        return -1.0
    return float((1.0 + tr) ** (periods / n) - 1.0)


def annual_volatility(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    """Annualised volatility = stdev(r) * sqrt(periods)."""
    r = returns.dropna()
    return float(r.std(ddof=1) * np.sqrt(periods)) if len(r) > 1 else float("nan")


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0, periods: int = TRADING_DAYS) -> float:
    """Sharpe = mean(r - rf/periods) / stdev(r - rf/periods) * sqrt(periods)."""
    excess = returns.dropna() - risk_free / periods
    if len(excess) < 2:
        return float("nan")
    sd = excess.std(ddof=1)
    return float(excess.mean() / sd * np.sqrt(periods)) if sd > 0 else float("nan")


def sortino_ratio(returns: pd.Series, risk_free: float = 0.0, periods: int = TRADING_DAYS) -> float:
    """Sortino = mean(r - rf) / downside deviation * sqrt(periods);
    downside deviation = sqrt(mean(min(r - rf, 0) ** 2))."""
    excess = returns.dropna() - risk_free / periods
    if not len(excess):
        return float("nan")
    downside = np.sqrt((np.minimum(excess, 0.0) ** 2).mean())
    return float(excess.mean() / downside * np.sqrt(periods)) if downside > 0 else float("nan")


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Drawdown_t = Equity_t / running max(Equity) - 1 (0 at a new high, negative below)."""
    eq = equity_curve(returns)
    return eq / eq.cummax() - 1.0


def max_drawdown(returns: pd.Series) -> float:
    """Maximum drawdown = min over t of Drawdown_t (worst peak-to-trough loss, negative)."""
    if not len(returns):
        return float("nan")
    return float(drawdown_series(returns).min())


def max_drawdown_duration(returns: pd.Series) -> int:
    """Longest number of bars spent below a previous equity peak."""
    dd = drawdown_series(returns)
    longest = cur = 0
    for v in dd.values:
        cur = cur + 1 if v < 0 else 0
        longest = max(longest, cur)
    return int(longest)


def calmar_ratio(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    """Calmar = CAGR / |max drawdown|."""
    mdd = max_drawdown(returns)
    return float(cagr(returns, periods) / abs(mdd)) if mdd and mdd < 0 else float("nan")


def win_rate(trade_returns) -> float:
    """Win rate = winning trades / all trades."""
    t = _clean(trade_returns).dropna()
    return float((t > 0).mean()) if len(t) else float("nan")


def profit_factor(trade_returns) -> float:
    """Profit factor = sum of winning trades / |sum of losing trades|."""
    t = _clean(trade_returns).dropna()
    losses = -t[t < 0].sum()
    if not len(t):
        return float("nan")
    return float(t[t > 0].sum() / losses) if losses > 0 else float("inf") if t.sum() > 0 else float("nan")


def avg_win(trade_returns) -> float:
    t = _clean(trade_returns).dropna()
    w = t[t > 0]
    return float(w.mean()) if len(w) else float("nan")


def avg_loss(trade_returns) -> float:
    t = _clean(trade_returns).dropna()
    lo = t[t <= 0]
    return float(lo.mean()) if len(lo) else float("nan")


def expectancy(trade_returns) -> float:
    """Expectancy = win rate * avg win - loss rate * |avg loss| (= mean trade return)."""
    t = _clean(trade_returns).dropna()
    if not len(t):
        return float("nan")
    wins, losses = t[t > 0], t[t <= 0]
    p = len(wins) / len(t)
    aw = wins.mean() if len(wins) else 0.0
    al = abs(losses.mean()) if len(losses) else 0.0
    return float(p * aw - (1 - p) * al)


def exposure(position) -> float:
    """Exposure = share of bars with a non-zero position (time in the market)."""
    p = _clean(position).fillna(0.0)
    return float((p != 0).mean()) if len(p) else float("nan")


def turnover(position, periods: int = TRADING_DAYS) -> float:
    """Annualised turnover = sum(|position_t - position_t-1|) * periods / N (1.0 = one full in or out)."""
    pos = _clean(position).fillna(0.0)
    if not len(pos):
        return float("nan")
    return float(pos.diff().abs().fillna(pos.abs()).sum() * periods / max(len(pos), 1))


def alpha_beta(returns: pd.Series, benchmark: pd.Series, periods: int = TRADING_DAYS) -> tuple[float, float]:
    """CAPM regression r_t = a + b * m_t: beta = cov(r, m) / var(m); alpha = a * periods (annualised)."""
    joined = pd.concat([returns, benchmark], axis=1).dropna()
    if len(joined) < 3:
        return float("nan"), float("nan")
    r, m = joined.iloc[:, 0], joined.iloc[:, 1]
    var = m.var()
    if not var or var <= 0:
        return float("nan"), float("nan")
    beta = r.cov(m) / var
    alpha = (r.mean() - beta * m.mean()) * periods
    return float(alpha), float(beta)


def information_ratio(returns: pd.Series, benchmark: pd.Series, periods: int = TRADING_DAYS) -> float:
    """Information ratio = mean(r - m) / stdev(r - m) * sqrt(periods)."""
    active = (returns - benchmark).dropna()
    sd = active.std(ddof=1)
    return float(active.mean() / sd * np.sqrt(periods)) if len(active) > 1 and sd > 0 else float("nan")


def rolling_sharpe(returns: pd.Series, window: int = 126, periods: int = TRADING_DAYS) -> pd.Series:
    m = returns.rolling(window).mean()
    s = returns.rolling(window).std()
    return (m / s * np.sqrt(periods)).replace([np.inf, -np.inf], np.nan)


def monthly_returns(returns: pd.Series) -> pd.DataFrame:
    """Year x month table of compounded monthly returns."""
    r = returns.copy()
    r.index = pd.to_datetime(r.index)
    if getattr(r.index, "tz", None) is not None:
        r.index = r.index.tz_localize(None)
    m = (1 + r.fillna(0)).groupby([r.index.year, r.index.month]).prod() - 1
    table = m.unstack(level=1)
    table.index.name, table.columns.name = "year", "month"
    return table


# --------------------------------------------------------------------------- definitions (tooltips)
METRIC_DEFINITIONS: dict[str, dict] = {
    "total_return": {"label": "Total return", "fmt": "pct", "formula": "prod(1 + r) - 1",
                     "help": "Overall percentage gain or loss over the whole test."},
    "cagr": {"label": "CAGR", "fmt": "pct", "formula": "(1 + total return)^(252/N) - 1",
             "help": "Compound annual growth rate - the constant yearly return that gives the same result."},
    "volatility": {"label": "Ann. volatility", "fmt": "pct", "formula": "stdev(daily r) x sqrt(252)",
                   "help": "How much returns swing around their average, annualised."},
    "sharpe": {"label": "Sharpe", "fmt": "num", "formula": "mean(r - rf) / stdev(r - rf) x sqrt(252)",
               "help": "Return per unit of total risk. Above 1 is good for a single strategy; above 2 is rare."},
    "sortino": {"label": "Sortino", "fmt": "num", "formula": "mean(r - rf) / downside deviation x sqrt(252)",
                "help": "Like Sharpe but only penalises downside volatility (losses)."},
    "calmar": {"label": "Calmar", "fmt": "num", "formula": "CAGR / |max drawdown|",
               "help": "Growth earned per unit of worst drawdown."},
    "max_drawdown": {"label": "Max drawdown", "fmt": "pct", "formula": "min(Equity / running peak - 1)",
                     "help": "Worst peak-to-trough fall of the equity curve."},
    "max_dd_duration": {"label": "Max DD duration", "fmt": "int", "formula": "longest run of bars below a peak",
                        "help": "How long (in bars) the strategy stayed under water."},
    "win_rate": {"label": "Win rate", "fmt": "pct", "formula": "winning trades / all trades",
                 "help": "Share of round-trip trades that made money."},
    "profit_factor": {"label": "Profit factor", "fmt": "num", "formula": "gross profit / gross loss",
                      "help": "Above 1 = winners outweigh losers. 1.5+ is healthy."},
    "expectancy": {"label": "Expectancy", "fmt": "pct", "formula": "p(win) x avg win - p(loss) x |avg loss|",
                   "help": "Average return you can expect per trade."},
    "avg_win": {"label": "Avg win", "fmt": "pct", "formula": "mean(winning trade returns)",
                "help": "Average return of winning trades."},
    "avg_loss": {"label": "Avg loss", "fmt": "pct", "formula": "mean(losing trade returns)",
                 "help": "Average return of losing trades."},
    "trades": {"label": "Trades", "fmt": "int", "formula": "count of round trips",
               "help": "Number of completed (or open, marked-to-market) round-trip trades."},
    "exposure": {"label": "Exposure", "fmt": "pct", "formula": "bars with a position / all bars",
                 "help": "Time in the market."},
    "turnover": {"label": "Turnover", "fmt": "num", "formula": "annual sum of |change in position|",
                 "help": "How often the book is traded: 1.0 = one full in-or-out per year."},
    "alpha": {"label": "Alpha", "fmt": "pct", "formula": "annualised CAPM intercept vs benchmark",
              "help": "Return not explained by exposure to the benchmark."},
    "beta": {"label": "Beta", "fmt": "num", "formula": "cov(r, benchmark) / var(benchmark)",
             "help": "Sensitivity to the benchmark: 1 = moves with the market, 0 = market neutral."},
    "information_ratio": {"label": "Information ratio", "fmt": "num", "formula": "mean(r - m) / stdev(r - m) x sqrt(252)",
                          "help": "Consistency of out-performance versus the benchmark."},
    "total_costs": {"label": "Total costs", "fmt": "usd", "formula": "commission + spread + slippage + fees + borrow",
                    "help": "Every dollar paid to trade."},
    "break_even_bps": {"label": "Break-even cost", "fmt": "bps", "formula": "one-way bps at which net CAGR = 0",
                       "help": "How much cost per trade the strategy can absorb before it stops making money."},
}


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else (None if math.isinf(v) else v)


def summary(returns: pd.Series, position=None, trade_returns=None, benchmark: pd.Series | None = None,
            periods: int = TRADING_DAYS) -> dict:
    """All metrics in one JSON-safe dict (None where an input is missing or undefined)."""
    returns = returns.astype(float)
    t = _clean(trade_returns if trade_returns is not None else [])
    pos = position if position is not None else pd.Series(1.0, index=returns.index)
    out = {
        "total_return": total_return(returns),
        "cagr": cagr(returns, periods),
        "volatility": annual_volatility(returns, periods),
        "sharpe": sharpe_ratio(returns, periods=periods),
        "sortino": sortino_ratio(returns, periods=periods),
        "max_drawdown": max_drawdown(returns),
        "max_dd_duration": max_drawdown_duration(returns),
        "calmar": calmar_ratio(returns, periods),
        "win_rate": win_rate(t),
        "profit_factor": profit_factor(t),
        "expectancy": expectancy(t),
        "avg_win": avg_win(t),
        "avg_loss": avg_loss(t),
        "trades": int(t.dropna().shape[0]),
        "exposure": exposure(pos),
        "turnover": turnover(pos, periods),
    }
    if benchmark is not None:
        b = benchmark.reindex(returns.index)
        out["alpha"], out["beta"] = alpha_beta(returns, b, periods)
        out["information_ratio"] = information_ratio(returns, b, periods)
    return {k: (_f(v) if k not in ("trades", "max_dd_duration") else v) for k, v in out.items()}
