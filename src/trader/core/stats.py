"""Statistical tests: hypothesis cards (Lab 04) and A/B tests of strategy variants (Lab 13)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from trader.core import indicators as ta
from trader.core import metrics as M


def describe_returns(r: pd.Series) -> dict:
    """Descriptive statistics of a return series (course Topic 3.1 'descriptive')."""
    r = r.dropna()
    return {"n": int(len(r)), "mean": float(r.mean()), "std": float(r.std(ddof=1)) if len(r) > 1 else None,
            "skew": float(r.skew()) if len(r) > 2 else None, "kurtosis": float(r.kurt()) if len(r) > 3 else None,
            "min": float(r.min()) if len(r) else None, "max": float(r.max()) if len(r) else None,
            "hit_rate": float((r > 0).mean()) if len(r) else None}


def condition(bars: pd.DataFrame, signal: dict) -> pd.Series:
    """Boolean signal for a hypothesis card - every type uses data up to the close of day t only."""
    c = bars["close"]
    kind = signal.get("type", "losing_streak")
    if kind == "losing_streak":
        return ta.losing_streak(c) >= int(signal.get("n", 3))
    if kind == "rsi_below":
        return ta.rsi(c, int(signal.get("window", 2))) < float(signal.get("level", 10))
    if kind == "close_below_sma":
        return c < ta.sma(c, int(signal.get("window", 200)))
    if kind == "close_below_lower_band":
        return c < ta.bollinger(c, int(signal.get("window", 20)), float(signal.get("k", 2.0)))["lower"]
    if kind == "gap_down":
        return bars["open"] / c.shift(1) - 1 < -abs(float(signal.get("pct", 0.01)))
    raise ValueError(f"unknown signal type {kind}")


HYPOTHESIS_SIGNALS = {
    "losing_streak": {"n": 3},
    "rsi_below": {"window": 2, "level": 10},
    "close_below_sma": {"window": 200},
    "close_below_lower_band": {"window": 20, "k": 2.0},
    "gap_down": {"pct": 0.01},
}


def hypothesis_test(bars: pd.DataFrame, signal: dict, horizon: int = 1, alpha: float = 0.05,
                    min_edge_bps: float = 3.0, n_boot: int = 2000, seed: int = 42) -> dict:
    """Signal days vs other days: means, hit rates, Welch t-test, bootstrap CI and a decision."""
    fwd = bars["close"].shift(-horizon) / bars["close"] - 1.0      # the OUTCOME (future), never a feature
    df = pd.DataFrame({"on": condition(bars, signal), "fwd": fwd}).dropna()
    sig, oth = df.loc[df["on"], "fwd"], df.loc[~df["on"], "fwd"]
    if len(sig) < 3 or len(oth) < 3:
        return {"error": "too few signal days to test", "signal_days": int(len(sig))}
    t, p = stats.ttest_ind(sig, oth, equal_var=False)
    rng = np.random.default_rng(seed)
    boot = rng.choice(sig.values, (n_boot, len(sig))).mean(axis=1)
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    edge_bps = (sig.mean() - oth.mean()) * 1e4
    supported = bool(p < alpha and t > 0 and edge_bps >= min_edge_bps)
    return {"n_days": int(len(df)), "signal_days": int(len(sig)), "share": float(len(sig) / len(df)),
            "mean_signal": float(sig.mean()), "mean_other": float(oth.mean()), "mean_all": float(df["fwd"].mean()),
            "hit_signal": float((sig > 0).mean()), "hit_all": float((df["fwd"] > 0).mean()),
            "ci": [float(lo), float(hi)], "welch_t": float(t), "p_value": float(p), "edge_bps": float(edge_bps),
            "supported": supported, "alpha": alpha, "min_edge_bps": min_edge_bps, "horizon": horizon,
            "signal_stats": describe_returns(sig), "other_stats": describe_returns(oth),
            "decision": ("SUPPORTED - reject H0; promote the idea to the signal and backtest stages" if supported else
                         "NOT SUPPORTED - do not reject H0; do not spend backtest time on it yet"),
            "first": str(df.index[0].date()), "last": str(df.index[-1].date())}


def block_bootstrap_sharpe_diff(a, b, n_boot: int = 2000, block: int = 21, seed: int = 7,
                                periods: int = 252) -> np.ndarray:
    """Resample blocks of consecutive days (keeps autocorrelation) and recompute Sharpe(A) - Sharpe(B)."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = len(a)
    block = max(1, min(block, n // 2))
    need = int(np.ceil(n / block))
    out = np.empty(n_boot)
    for i in range(n_boot):
        idx = np.concatenate([np.arange(s, s + block) for s in rng.integers(0, n - block + 1, need)])[:n]
        sa, sb = a[idx].std(), b[idx].std()
        da = a[idx].mean() / sa * np.sqrt(periods) if sa > 0 else 0.0
        db = b[idx].mean() / sb * np.sqrt(periods) if sb > 0 else 0.0
        out[i] = da - db
    return out


def ab_test(ra: pd.Series, rb: pd.Series, alpha: float = 0.05, tried: int = 20, n_boot: int = 2000,
            block: int = 21) -> dict:
    """A/B test of two return series on the SAME days.

    1 Welch t-test (independent samples) 2 paired t-test on A - B 3 block-bootstrap CI of the
    Sharpe difference 4 decision: reject H0 only if the paired test AND the CI agree 5 Bonferroni caution.
    """
    j = pd.concat([ra, rb], axis=1).dropna()
    a, b = j.iloc[:, 0], j.iloc[:, 1]
    t_w, p_w = stats.ttest_ind(a, b, equal_var=False)
    t_p, p_p = stats.ttest_rel(a, b)
    boot = block_bootstrap_sharpe_diff(a, b, n_boot, block)
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    diff = (M.sharpe_ratio(a) or 0) - (M.sharpe_ratio(b) or 0)
    reject = bool(p_p < alpha and not (lo <= 0 <= hi))
    winner = "A" if diff > 0 else "B"
    bonf = alpha / max(tried, 1)
    decision = (f"REJECT H0 - variant {winner} is better on the paired test and the Sharpe CI" if reject else
                f"DO NOT REJECT H0 - variant {winner} looks better on paper, but the evidence is not reliable; "
                "keep both on paper")
    hist, edges = np.histogram(boot, bins=40)
    return {"n_days": int(len(j)), "welch_t": float(t_w), "welch_p": float(p_w), "paired_t": float(t_p),
            "paired_p": float(p_p), "mean_diff_daily": float((a - b).mean()), "sharpe_a": M._f(M.sharpe_ratio(a)),
            "sharpe_b": M._f(M.sharpe_ratio(b)), "sharpe_diff": float(diff), "ci": [float(lo), float(hi)],
            "share_a_beats_b": float((boot > 0).mean()), "reject_h0": reject, "winner": winner,
            "alpha": alpha, "tried": tried, "bonferroni_alpha": bonf,
            "survives_bonferroni": bool(reject and p_p < bonf), "decision": decision,
            "multiple_testing_note": (f"With {tried} variants tried at alpha {alpha}, about {alpha * tried:.1f} "
                                      f"false 'winners' are expected by chance; Bonferroni requires p < {bonf:.4f}."),
            "bootstrap_hist": {"counts": hist.tolist(), "edges": [float(e) for e in edges]}}
