"""Pairs trading: Engle-Granger cointegration + z-score spread (course Topic 3.6 / Lab 14).

Engle-Granger two-step method, decided on the FORMATION period only:
  1. OLS  log(A) = a + beta * log(B) + e        -> beta = hedge ratio
  2. ADF unit-root test on the residual e        -> stationary = cointegrated pair
Trading period (beta held fixed):
  z = (spread - rolling mean) / rolling std
  short spread (short A, long beta x B) when z > +entry; long spread when z < -entry;
  exit when |z| < exit; positions act on the NEXT bar; both legs pay costs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EG_CRIT = {"1%": -3.90, "5%": -3.34, "10%": -3.04}      # Engle-Granger, 2 variables with constant (MacKinnon)


def ols(y: np.ndarray, X: np.ndarray):
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    sigma2 = resid @ resid / max(len(y) - X.shape[1], 1)
    return coef, np.sqrt(np.diag(sigma2 * np.linalg.pinv(X.T @ X))), resid


def adf_t(series, lags: int = 1) -> float:
    """ADF t-statistic: d e_t = g * e_(t-1) + sum phi_k * d e_(t-k) (no constant: residuals are mean zero)."""
    e = np.asarray(series, float)
    de = np.diff(e)
    X = np.column_stack([e[lags:-1]] + [de[lags - k:-k] for k in range(1, lags + 1)])
    coef, se, _ = ols(de[lags:], X)
    return float(coef[0] / se[0])


def engle_granger(log_a: pd.Series, log_b: pd.Series) -> tuple[float, float, float]:
    """(alpha, beta, ADF t) of the cointegrating regression log_a = alpha + beta log_b."""
    coef, _, resid = ols(log_a.values, np.column_stack([np.ones(len(log_b)), log_b.values]))
    return float(coef[0]), float(coef[1]), adf_t(resid)


def half_life(spread: pd.Series) -> float:
    lag, d = spread.shift(1).dropna(), spread.diff().dropna()
    k = np.polyfit(lag.loc[d.index], d, 1)[0]
    return float(-np.log(2) / k) if k < 0 else float("inf")


def spread_state(z: pd.Series, entry: float, exit_: float) -> pd.Series:
    """+1 long spread (long A / short B), -1 short spread, 0 flat - decided at each close."""
    vals = np.zeros(len(z))
    state = 0.0
    for i, zt in enumerate(z.values):
        if np.isnan(zt):
            vals[i] = state
            continue
        if state == 0 and zt > entry:
            state = -1.0
        elif state == 0 and zt < -entry:
            state = 1.0
        elif state != 0 and abs(zt) < exit_:
            state = 0.0
        vals[i] = state
    return pd.Series(vals, index=z.index)


def leg_weights(state: pd.Series, beta: float, a: str, b: str) -> pd.DataFrame:
    """Per-leg target weights for a spread position, gross exposure 1."""
    w = 1.0 / (1.0 + abs(beta))
    return pd.DataFrame({a: state * w, b: -state * beta * w})


def screen(closes: pd.DataFrame, pairs: list[tuple[str, str]]) -> list[dict]:
    """Correlation vs cointegration screen - high correlation does not imply cointegration."""
    rows = []
    for x, y in pairs:
        if x not in closes or y not in closes:
            continue
        sub = closes[[x, y]].dropna()
        corr = sub[x].pct_change().corr(sub[y].pct_change())
        a0, b0, t = engle_granger(np.log(sub[x]), np.log(sub[y]))
        hl = half_life(np.log(sub[x]) - b0 * np.log(sub[y]) - a0)
        rows.append({"pair": f"{x}/{y}", "a": x, "b": y, "corr": float(corr), "beta": b0, "adf_t": t,
                     "half_life": hl if np.isfinite(hl) else None,
                     "cointegrated_5pct": bool(t < EG_CRIT["5%"])})
    return rows
