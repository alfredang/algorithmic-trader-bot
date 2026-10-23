import numpy as np

from trader.core import ml as ML


def test_forest_importance_covers_the_whole_forest(spy):
    imp = ML.feature_importance(spy, "random_forest")
    feats = [c for c in ML.build_features(spy).columns if c != "target"]
    assert sorted(imp) == sorted(feats)
    assert np.isclose(sum(imp.values()), 1.0)
    # one depth-4 tree splits on a handful of features; 150 trees with max_features='sqrt' use them all
    assert all(v > 0 for v in imp.values())


def test_logistic_importance_unwraps_the_pipeline(spy):
    imp = ML.feature_importance(spy, "logistic")
    assert len(imp) == 14 and all(v >= 0 for v in imp.values())


def test_tuning_picks_from_the_grid_and_reports_is_val_oos(spy):
    proba, folds = ML.walk_forward_proba(spy, "xgboost", tune=True)
    name, values = ML.GRIDS["xgboost"]
    assert len(folds) and set(folds["params"]) <= {f"{name}={v}" for v in values}
    assert folds[["is_auc", "val_auc", "oos_auc"]].notna().all().all()
    s = ML.fold_summary(folds)
    assert s["n_folds"] == len(folds) and s["is_auc"] > s["oos_auc_folds"]          # in-sample fit flatters the model
    # tuning only looks inside the training window: predictions before a cut are unchanged by data after it
    cut = 1500
    early, _ = ML.walk_forward_proba(spy.iloc[:cut], "xgboost", tune=True)
    assert np.allclose(early.dropna().values, proba.loc[early.dropna().index].values)


def test_untuned_walk_forward_keeps_the_default_model(spy):
    proba_default, folds = ML.walk_forward_proba(spy, "logistic")
    assert set(folds["params"]) == {"default"} and folds["val_auc"].isna().all()
    assert proba_default.notna().sum() > 1000


def test_ml_report_api_returns_in_sample_summary(client):
    r = client.post("/api/research/ml", json={"symbol": "SPY", "models": ["logistic"], "tune": True})
    assert r.status_code == 200, r.text[:300]
    m = r.json()["result"]["models"][0]
    assert m["in_sample"]["params"].startswith("C=") and m["grid"]["param"] == "C"
    assert {"is_auc", "val_auc", "oos_auc"} <= set(m["folds"][0])
