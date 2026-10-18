"""Look-ahead detector for signal functions (course Lab 07 / Lab 18).

For random dates t it (1) recomputes the signal on data up to t only and (2) recomputes it
after SHOCKING every bar after t (prices x 1.5 and x 0.5). A signal that uses only the past
gives identical values up to t in every case; any difference means look-ahead.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def lookahead_check(fn: Callable[[pd.DataFrame], pd.Series], bars: pd.DataFrame, checks: int = 10,
                    seed: int = 0) -> dict:
    full = fn(bars)
    n = len(bars)
    if n < 60:
        return {"checks": 0, "failed": 0, "status": "SKIP", "dates": []}
    rng = np.random.default_rng(seed)
    idx = sorted(rng.choice(np.arange(n // 3, n - 5), size=min(checks, n // 3), replace=False))
    price_cols = [c for c in ("open", "high", "low", "close") if c in bars]
    failed = []
    for i in idx:
        t = bars.index[i]
        variants = [bars.loc[:t]]
        for k in (1.5, 0.5):
            shocked = bars.copy()
            shocked.iloc[i + 1:, [bars.columns.get_loc(c) for c in price_cols]] *= k
            variants.append(shocked)
        ref = full.loc[:t].values
        for v in variants:
            got = fn(v).loc[:t].values
            if len(got) != len(ref) or not np.allclose(got, ref, equal_nan=True):
                failed.append(str(t)[:10])
                break
    return {"checks": len(idx), "failed": len(failed), "status": "PASS" if not failed else "FAIL", "dates": failed[:10]}
