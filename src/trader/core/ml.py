"""Walk-forward machine-learning direction classifiers (course Topic 3.2 / Lab 11).

features  : lagged returns, momentum, RSI(14), RSI(2), MACD histogram, Bollinger %B,
            21-day volatility, distance to SMA 50/200, volume z-score (all known at close t)
label     : 1 if close t+1 > close t (training only - never a feature)
validation: position-based walk-forward. The model is refitted every ``retrain_every`` bars
            on rows whose label was already known (gap of one bar), then predicts the next
            block. Refit points depend only on bar positions from the start, so truncating
            or shocking the future never changes past predictions (no look-ahead).
tuning    : optional, inside each training window only (in-sample): the first 75% trains each
            candidate in ``GRIDS``, the last 25% (after a one-bar gap) is the validation set, the
            best validation AUC wins and the model is refitted on the whole window before it
            predicts the unseen block. Each fold reports in-sample, validation and out-of-sample
            AUC so the decay from training to unseen data is visible.
signal    : P(up) > threshold -> long, else flat
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, roc_auc_score
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from trader.core import indicators as ta

warnings.filterwarnings("ignore", category=UserWarning)


def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Every feature uses data up to today's close only. ``target`` is the next-bar label."""
    c = bars["close"]
    r = c.pct_change()
    f = pd.DataFrame(index=bars.index)
    for lag in (1, 2, 3, 5):
        f[f"ret_lag{lag}"] = r.shift(lag - 1)
    f["mom_5"], f["mom_21"] = c.pct_change(5), c.pct_change(21)
    f["rsi_14"], f["rsi_2"] = ta.rsi(c, 14), ta.rsi(c, 2)
    f["macd_hist"] = ta.macd(c)["hist"] / c
    f["bb_pct_b"] = ta.bollinger(c)["pct_b"]
    f["vol_21"] = r.rolling(21).std() * np.sqrt(252)
    f["dist_sma50"], f["dist_sma200"] = c / ta.sma(c, 50) - 1, c / ta.sma(c, 200) - 1
    vol = bars["volume"].replace(0, np.nan)
    f["volume_z"] = (vol - vol.rolling(21).mean()) / vol.rolling(21).std()
    f["target"] = (c.shift(-1) > c).astype(float).where(c.shift(-1).notna())
    return f


def _xgb(max_depth: int = 3):
    try:
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=150, max_depth=max_depth, learning_rate=0.05, subsample=0.8,
                             colsample_bytree=0.8, random_state=42, eval_metric="logloss", n_jobs=1)
    except Exception:          # pragma: no cover - xgboost missing or libomp unavailable
        return HistGradientBoostingClassifier(max_depth=max_depth, learning_rate=0.05, max_iter=150, random_state=42)


MODELS = {
    "logistic": ("Logistic regression",
                 lambda C=0.1: make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=1000))),
    "random_forest": ("Random forest", lambda max_depth=4: RandomForestClassifier(
        n_estimators=150, max_depth=max_depth, min_samples_leaf=20, random_state=42, n_jobs=1)),
    "xgboost": ("XGBoost", _xgb),
}

# hyperparameter candidates tried in-sample, simplest (most regularised) first so ties pick the simpler model
GRIDS = {"logistic": ("C", [0.01, 0.1, 1.0]),
         "random_forest": ("max_depth", [2, 4, 6]),
         "xgboost": ("max_depth", [2, 3, 5])}
VALIDATION_SHARE = 0.25


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    return float(roc_auc_score(y, p)) if len(y) > 1 and len(np.unique(y)) == 2 else None


def tune_in_sample(model: str, X: np.ndarray, y: np.ndarray) -> tuple[dict, float | None]:
    """Pick the GRIDS setting with the best validation AUC on the last part of a training window."""
    name, values = GRIDS[model]
    k = int(len(y) * (1 - VALIDATION_SHARE))
    fit_rows, val_rows = slice(0, k), slice(k + 1, len(y))          # one-bar gap: the last fit label uses close k
    if k < 100 or len(np.unique(y[fit_rows])) < 2:
        return {}, None
    best, best_auc = {}, None
    for v in values:
        m = MODELS[model][1](**{name: v}).fit(X[fit_rows], y[fit_rows])
        auc = _auc(y[val_rows], m.predict_proba(X[val_rows])[:, 1])
        if auc is not None and (best_auc is None or auc > best_auc):
            best, best_auc = {name: v}, auc
    return best, best_auc


def walk_forward_proba(bars: pd.DataFrame, model: str = "logistic", min_train: int = 504,
                       retrain_every: int = 126, tune: bool = False) -> tuple[pd.Series, pd.DataFrame]:
    """Out-of-sample P(up) for every bar after ``min_train`` (NaN before), plus one row per fold with
    the chosen hyperparameters and in-sample / validation / out-of-sample metrics."""
    f = build_features(bars)
    feats = [c for c in f.columns if c != "target"]
    X = f[feats]
    y = f["target"]
    valid = X.notna().all(axis=1)
    proba = pd.Series(np.nan, index=f.index)
    make = MODELS[model][1]
    n = len(f)
    folds = []
    for start in range(min_train, n, retrain_every):
        # rows j with labels known at the close of bar start-1: j <= start-2 (label uses close j+1)
        tr = np.arange(0, max(start - 1, 0))
        tr = tr[valid.values[tr] & y.notna().values[tr]]
        te = np.arange(start, min(start + retrain_every, n))
        te = te[valid.values[te]]
        if len(tr) < 100 or not len(te) or len(np.unique(y.values[tr])) < 2:
            continue
        Xtr, ytr = X.values[tr], y.values[tr].astype(int)
        params, val_auc = tune_in_sample(model, Xtr, ytr) if tune else ({}, None)
        m = make(**params).fit(Xtr, ytr)
        p_is = m.predict_proba(Xtr)[:, 1]
        p_oos = m.predict_proba(X.values[te])[:, 1]
        proba.iloc[te] = p_oos
        yte = y.values[te]
        known = ~np.isnan(yte)                                            # the very last bar has no label yet
        folds.append({"train_start": str(f.index[tr[0]].date()), "train_end": str(f.index[tr[-1]].date()),
                      "test_start": str(f.index[te[0]].date()), "test_end": str(f.index[te[-1]].date()),
                      "n_train": int(len(tr)), "n_test": int(len(te)),
                      "params": ", ".join(f"{k}={v}" for k, v in params.items()) or "default",
                      "is_accuracy": float(accuracy_score(ytr, (p_is > 0.5).astype(int))), "is_auc": _auc(ytr, p_is),
                      "val_auc": val_auc,
                      "oos_accuracy": (float(accuracy_score(yte[known].astype(int), (p_oos[known] > 0.5).astype(int)))
                                       if known.any() else None),
                      "oos_auc": _auc(yte[known].astype(int), p_oos[known])})
    return proba, pd.DataFrame(folds)


def fold_summary(folds: pd.DataFrame) -> dict:
    """Average in-sample / validation / out-of-sample figures across folds and the most chosen setting."""
    if folds.empty:
        return {}
    def mean(col: str) -> float | None:
        return float(folds[col].dropna().mean()) if col in folds and folds[col].notna().any() else None
    counts = folds["params"].value_counts()
    out = {"is_accuracy": mean("is_accuracy"), "is_auc": mean("is_auc"), "val_auc": mean("val_auc"),
           "oos_auc_folds": mean("oos_auc"), "n_folds": int(len(folds)),
           "params": f"{counts.index[0]} ({counts.iloc[0]} of {len(folds)} folds)"}
    if out["is_auc"] is not None and out["oos_auc_folds"] is not None:
        out["auc_decay"] = out["is_auc"] - out["oos_auc_folds"]
    return out


def classification_report(bars: pd.DataFrame, proba: pd.Series) -> dict:
    y = build_features(bars)["target"]
    j = pd.concat([proba.rename("p"), y.rename("y")], axis=1).dropna()
    if len(j) < 10 or j["y"].nunique() < 2:
        return {"n": int(len(j))}
    pred = (j["p"] > 0.5).astype(int)
    auc = roc_auc_score(j["y"], j["p"])
    return {"n": int(len(j)), "accuracy": float(accuracy_score(j["y"], pred)),
            "precision": float(precision_score(j["y"], pred, zero_division=0)), "auc": float(auc),
            "base_rate": float(j["y"].mean()), "share_predicted_up": float(pred.mean()),
            "verdict": ("NO EDGE - AUC within noise of 0.5; keep the ML signal out of the live strategy" if auc < 0.53
                        else "possible edge - run diagnostics and an A/B test before promoting")}


def feature_importance(bars: pd.DataFrame, model: str = "random_forest") -> dict:
    f = build_features(bars).dropna()
    X, y = f.drop(columns="target"), f["target"].astype(int)
    m = MODELS[model][1]().fit(X.values, y.values)
    est = m[-1] if isinstance(m, Pipeline) else m      # a forest also supports m[-1] (its last tree)
    if hasattr(est, "feature_importances_"):
        imp = est.feature_importances_
    elif hasattr(est, "coef_"):
        imp = np.abs(est.coef_[0])
    else:
        return {}
    return {c: float(v) for c, v in sorted(zip(X.columns, imp, strict=False), key=lambda t: -t[1])}
