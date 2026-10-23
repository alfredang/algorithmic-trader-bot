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
