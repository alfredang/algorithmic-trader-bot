"""Walk-forward machine-learning direction classifiers (course Topic 3.2 / Lab 11).

features  : lagged returns, momentum, RSI(14), RSI(2), MACD histogram, Bollinger %B,
            21-day volatility, distance to SMA 50/200, volume z-score (all known at close t)
label     : 1 if close t+1 > close t (training only - never a feature)
validation: position-based walk-forward. The model is refitted every ``retrain_every`` bars
            on rows whose label was already known (gap of one bar), then predicts the next
            block. Refit points depend only on bar positions from the start, so truncating
            or shocking the future never changes past predictions (no look-ahead).
signal    : P(up) > threshold -> long, else flat
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
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


def _xgb():
    try:
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8,
                             colsample_bytree=0.8, random_state=42, eval_metric="logloss", n_jobs=1)
    except Exception:          # pragma: no cover - xgboost missing or libomp unavailable
        return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, random_state=42)


MODELS = {
    "logistic": ("Logistic regression", lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=1000))),
    "random_forest": ("Random forest", lambda: RandomForestClassifier(n_estimators=150, max_depth=4, min_samples_leaf=20,
                                                                      random_state=42, n_jobs=1)),
    "xgboost": ("XGBoost", _xgb),
}


def walk_forward_proba(bars: pd.DataFrame, model: str = "logistic", min_train: int = 504,
                       retrain_every: int = 126) -> tuple[pd.Series, pd.DataFrame]:
    """Out-of-sample P(up) for every bar after ``min_train`` (NaN before)."""
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
        m = make().fit(X.values[tr], y.values[tr].astype(int))
        proba.iloc[te] = m.predict_proba(X.values[te])[:, 1]
        folds.append({"train_start": str(f.index[tr[0]].date()), "train_end": str(f.index[tr[-1]].date()),
                      "test_start": str(f.index[te[0]].date()), "test_end": str(f.index[te[-1]].date()),
                      "n_train": int(len(tr)), "n_test": int(len(te))})
    return proba, pd.DataFrame(folds)


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
    est = m[-1] if hasattr(m, "__getitem__") else m
    if hasattr(est, "feature_importances_"):
        imp = est.feature_importances_
    elif hasattr(est, "coef_"):
        imp = np.abs(est.coef_[0])
    else:
        return {}
    return {c: float(v) for c, v in sorted(zip(X.columns, imp, strict=False), key=lambda t: -t[1])}
