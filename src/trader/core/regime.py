"""Market regimes with PCA and K-means (course Topic 3.3 / Lab 12).

Walk-forward labels: K-means is refitted every ``refit_every`` bars on data up to
the refit point only, so today's regime never uses future data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from trader.core import indicators as ta

STRESS = "High vol (stress)"


def regime_features(close: pd.Series) -> pd.DataFrame:
    """Backward-looking single-asset features: volatility, trend and distance to SMA200."""
    r = close.pct_change()
    return pd.DataFrame({
        "vol_21": r.rolling(21).std() * np.sqrt(252),
        "ret_21": close.pct_change(21),
        "ret_63": close.pct_change(63),
        "dist_sma200": close / ta.sma(close, 200) - 1,
    })


def _names(k: int) -> list[str]:
    return ["Low vol", "Moderate vol", STRESS] if k == 3 else [f"Regime {i + 1}" for i in range(k - 1)] + [STRESS]


def fit_regimes(train: pd.DataFrame, k: int = 3, seed: int = 42):
    scaler = StandardScaler().fit(train)
    km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(scaler.transform(train))
    order = train.groupby(km.labels_)["vol_21"].mean().sort_values().index
    return scaler, km, dict(zip(order, _names(k), strict=False))


def walk_forward_regimes(feat: pd.DataFrame, k: int = 3, min_train: int = 252, refit_every: int = 63) -> pd.Series:
    """Label each block with a model fitted only on rows before the block (position-based refits)."""
    feat = feat.dropna()
    labels = pd.Series(index=feat.index, dtype=object)
    for start in range(min_train, len(feat), refit_every):
        train = feat.iloc[:start]
        block = feat.iloc[start:start + refit_every]
        scaler, km, names = fit_regimes(train, k)
        labels.iloc[start:start + len(block)] = pd.Series(km.predict(scaler.transform(block))).map(names).values
    return labels.rename("regime")


def regime_gate(target: pd.Series, regimes: pd.Series, blocked=(STRESS,)) -> pd.Series:
    """Force the target flat on bars whose (known-at-close) regime is blocked."""
    allowed = ~regimes.reindex(target.index).isin(list(blocked))
    return target.where(allowed, 0.0)


def pca_analysis(returns: pd.DataFrame) -> dict:
    """Explained variance and loadings of standardised returns (PC1 ~ 'the market')."""
    r = returns.dropna()
    pca = PCA().fit(StandardScaler().fit_transform(r))
    ev = pca.explained_variance_ratio_
    n = min(3, len(ev))
    load = pd.DataFrame(pca.components_[:n].T, index=r.columns, columns=[f"PC{i + 1}" for i in range(n)])
    return {"explained_variance": [float(x) for x in ev], "cumulative": [float(x) for x in np.cumsum(ev)],
            "loadings": {c: {s: float(v) for s, v in load[c].items()} for c in load.columns},
            "n_assets": int(r.shape[1]), "n_days": int(r.shape[0])}


def regime_profile(feat: pd.DataFrame, labels: pd.Series, next_ret: pd.Series) -> list[dict]:
    from trader.core import metrics as M
    rows = []
    for name in labels.dropna().unique():
        m = labels == name
        f = feat.loc[m[m].index]
        nr = next_ret.reindex(m[m].index).dropna()
        rows.append({"regime": name, "days": int(m.sum()), "share": float(m.mean()),
                     "avg_vol": float(f["vol_21"].mean()), "avg_ret_21": float(f["ret_21"].mean()),
                     "next_day_sharpe": M._f(M.sharpe_ratio(nr)), "next_day_mean": float(nr.mean()) if len(nr) else None})
    order = {"Low vol": 0, "Moderate vol": 1, STRESS: 9}
    return sorted(rows, key=lambda r: order.get(r["regime"], 5))
