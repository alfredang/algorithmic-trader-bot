"""Research tools: hypothesis test, grid search with in/out-of-sample decay, walk-forward optimisation,
A/B test, regime analysis, pairs screen, ML report, execution comparison and bias diagnostics."""
from __future__ import annotations

import itertools
import time

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from trader.core import execution_algos as EXA
from trader.core import metrics as M
from trader.core import ml as ML
from trader.core import pairs as PR
from trader.core import regime as RG
from trader.core import stats as ST
from trader.core.backtest import BacktestConfig, break_even_bps, buy_and_hold, run_backtest, series_payload
from trader.core.costs import COST_PRESETS, CostModel
from trader.core.signal_checks import lookahead_check
from trader.data import service as data
from trader.models import ResearchRun
from trader.services.backtests import prepare_data
from trader.services.events import emit, jsonable, stage
from trader.strategies import registry

DEFAULT_GRIDS = {
    "sma_cross": {"fast": [5, 10, 20, 30, 50], "slow": [50, 100, 150, 200, 250]},
    "ema_cross": {"fast": [5, 10, 15, 20, 30], "slow": [30, 50, 75, 100, 150]},
    "rsi2_reversion": {"n": [2, 3, 5, 14], "entry": [10, 20, 30], "exit": [50, 60, 70]},
    "bollinger_reversion": {"window": [10, 20, 30, 50], "k": [1.0, 1.5, 2.0, 2.5]},
    "bollinger_breakout": {"window": [10, 20, 30, 50], "k": [1.0, 1.5, 2.0, 2.5]},
    "donchian_breakout": {"entry": [10, 20, 55, 100], "exit": [5, 10, 20, 50]},
    "ts_momentum": {"lookback": [21, 63, 126, 189, 252], "threshold": [0.0, 0.02, 0.05]},
    "macd_cross": {"fast": [8, 12, 16], "slow": [21, 26, 34], "signal": [5, 9, 13]},
    "trend_filter": {"window": [50, 100, 150, 200, 250]},
    "dip_buy": {"n_down": [2, 3, 4, 5], "hold": [1, 3, 5, 10]},
}


def _record(db: Session, kind: str, name: str, config: dict, fn) -> ResearchRun:
    t0 = time.time()
    rr = ResearchRun(kind=kind, name=name, config=jsonable(config), status="running")
    db.add(rr)
    db.flush()
    stage_name = {"grid": "search", "walk_forward": "search", "abtest": "abtest", "diagnostics": "abtest",
                  "hypothesis": "strategy", "regime": "search", "pairs": "search", "ml": "search",
                  "execution": "execution"}.get(kind, "search")
    stage(stage_name, "running", f"{kind}: {name}", ref_type="research", ref_id=rr.id, db=db)
    try:
        rr.result = jsonable(fn())
        rr.status = "done"
        stage(stage_name, _status_of(kind, rr.result), f"{kind} #{rr.id}: {_headline(kind, rr.result)}",
              {"id": rr.id, "kind": kind, **_metrics_of(kind, rr.result)}, ref_type="research", ref_id=rr.id, db=db)
    except Exception as exc:
        rr.status, rr.error = "error", str(exc)[:2000]
        stage(stage_name, "error", f"{kind}: {exc}", ref_type="research", ref_id=rr.id, db=db)
    rr.duration_ms = int((time.time() - t0) * 1000)
    db.flush()
    emit("research.done", {"id": rr.id, "kind": kind, "status": rr.status}, db=db)
    return rr


def _status_of(kind, r) -> str:
    if kind == "diagnostics":
        return "error" if r.get("verdict", "").startswith("BLOCK") else ("warning" if r.get("warns") else "ok")
    if kind == "abtest":
        return "ok" if r.get("reject_h0") else "warning"
    return "ok"


def _headline(kind, r) -> str:
    return {"hypothesis": r.get("decision", ""), "abtest": r.get("decision", ""), "diagnostics": r.get("verdict", ""),
            "grid": f"{r.get('n_sets', 0)} sets, IS/OOS rank corr {r.get('rank_corr', 0) or 0:.2f}",
            "walk_forward": f"OOS Sharpe {r.get('oos_metrics', {}).get('sharpe') or 0:.2f}",
            }.get(kind, "done")


def _metrics_of(kind, r) -> dict:
    if kind == "abtest":
        return {"sharpe_diff": r.get("sharpe_diff"), "paired_p": r.get("paired_p"), "reject_h0": r.get("reject_h0")}
    if kind == "diagnostics":
        return {"verdict": r.get("verdict"), "fails": r.get("fails"), "warns": r.get("warns")}
    if kind == "grid":
        return {"n_sets": r.get("n_sets"), "rank_corr": r.get("rank_corr")}
    return {}


def _bars(db, symbol, start=None, end=None, timeframe="1Day"):
    b = data.load_bars(db, symbol, timeframe, start, end)
    if b.empty:
        raise ValueError(f"no bars for {symbol}")
    return b


def _cfg(d: dict | None) -> BacktestConfig:
    c = BacktestConfig.from_dict(d)
    c.compute_gross = False
    return c


# --------------------------------------------------------------------------- hypothesis
def hypothesis(db: Session, symbol="SPY", signal: dict | None = None, horizon=1, alpha=0.05, min_edge_bps=3.0,
               h0="", h1="", start=None, end=None, robustness_symbols=None) -> ResearchRun:
    signal = signal or {"type": "losing_streak", "n": 3}

    def go():
        bars = _bars(db, symbol, start, end)
        res = ST.hypothesis_test(bars, signal, horizon, alpha, min_edge_bps)
        rob = []
        param = next((k for k in signal if k != "type"), None)
        base = signal.get(param) if param else None
        variants = [base] if base is None else sorted({base, *([base - 1, base + 1] if isinstance(base, int) else [base * 0.8, base * 1.2])})
        for s in [symbol, *(robustness_symbols or ["QQQ"])]:
            try:
                b = bars if s == symbol else _bars(db, s, start, end)
            except Exception:
                continue
            for v in variants:
                sg = {**signal, param: v} if param else signal
                r = ST.hypothesis_test(b, sg, horizon, alpha, min_edge_bps)
                if "error" not in r:
                    rob.append({"symbol": s, "param": param, "value": v, "signal_days": r["signal_days"],
                                "edge_bps": r["edge_bps"], "t": r["welch_t"], "p": r["p_value"], "supported": r["supported"]})
        res["robustness"] = rob
        res["bonferroni_alpha"] = alpha / max(len(rob), 1)
        res["h0"] = h0 or "The mean forward return on signal days EQUALS the mean on all other days"
        res["h1"] = h1 or "The mean forward return on signal days is HIGHER than on all other days"
        res["symbol"], res["signal"] = symbol, signal
        return res
    return _record(db, "hypothesis", f"{symbol} {signal.get('type')}", locals_cfg(symbol=symbol, signal=signal,
                   horizon=horizon, alpha=alpha, min_edge_bps=min_edge_bps), go)


def locals_cfg(**kw):
    return kw


# --------------------------------------------------------------------------- grid search
def grid_points(grid: dict, key: str):
    keys = list(grid)
    for values in itertools.product(*grid.values()):
        p = dict(zip(keys, values, strict=False))
        if key in ("sma_cross", "ema_cross", "macd_cross") and p.get("fast", 0) >= p.get("slow", 1e9):
            continue
        yield p


def grid_search(db: Session, strategy_key="sma_cross", symbol="SPY", grid: dict | None = None,
                split_date="2021-12-31", config: dict | None = None, start=None, end=None) -> ResearchRun:
    grid = grid or DEFAULT_GRIDS.get(strategy_key)
    if not grid:
        raise ValueError(f"no default grid for {strategy_key}; pass a grid")

    def go():
        desc = registry.get(db, strategy_key)
        d, _ = prepare_data(db, desc, [symbol], "1Day", start, end)
        bars = {symbol: d}
        cfg = _cfg(config)
        rows = []
        pts = list(grid_points(grid, strategy_key))
        if len(pts) > 400:
            raise ValueError(f"grid has {len(pts)} points - keep it under 400")
        oos_start = pd.Timestamp(split_date) + pd.Timedelta(days=1)
        for p in pts:
            sig, _ = registry.compute_signals(db, strategy_key, d, p)
            res = run_backtest(bars, sig, cfg)
            r_is, r_oos = res.returns.loc[:split_date], res.returns.loc[oos_start:]
            rows.append({"params": p, "IS_sharpe": M._f(M.sharpe_ratio(r_is)), "OOS_sharpe": M._f(M.sharpe_ratio(r_oos)),
                         "IS_cagr": M._f(M.cagr(r_is)), "OOS_cagr": M._f(M.cagr(r_oos)), "trades": int(len(res.trades)),
                         "max_drawdown": M._f(M.max_drawdown(res.returns))})
        df = pd.DataFrame(rows)
        df["IS_rank"] = df["IS_sharpe"].rank(ascending=False, method="min", na_option="bottom").astype(int)
        df["OOS_rank"] = df["OOS_sharpe"].rank(ascending=False, method="min", na_option="bottom").astype(int)
        df["decay"] = df["OOS_sharpe"] - df["IS_sharpe"]
        bh = d["close"].pct_change().fillna(0)
        bh_is, bh_oos = M._f(M.sharpe_ratio(bh.loc[:split_date])), M._f(M.sharpe_ratio(bh.loc[oos_start:]))
        rank_corr = df["IS_sharpe"].corr(df["OOS_sharpe"], method="spearman")
        top = df.nsmallest(5, "IS_rank")
        best = df.loc[df["IS_sharpe"].idxmax()] if df["IS_sharpe"].notna().any() else df.iloc[0]
        keys = list(grid)
        heat = None
        if len(keys) == 2:
            a, b = keys
            heat = {"x_name": b, "y_name": a, "x": grid[b], "y": grid[a], "IS": [], "OOS": []}
            look = {(r["params"][a], r["params"][b]): r for r in rows}
            for ya in grid[a]:
                heat["IS"].append([look.get((ya, xb), {}).get("IS_sharpe") for xb in grid[b]])
                heat["OOS"].append([look.get((ya, xb), {}).get("OOS_sharpe") for xb in grid[b]])
            heat["robust"] = _robust_cell(heat["IS"], grid[a], grid[b], a, b)
        return {"strategy": strategy_key, "symbol": symbol, "split_date": split_date, "n_sets": len(df),
                "rows": df.sort_values("IS_rank").to_dict("records"), "best": best.to_dict(),
                "top5": top.to_dict("records"), "rank_corr": M._f(rank_corr), "top5_decay": M._f(top["decay"].mean()),
                "beat_bh_oos": M._f((df["OOS_sharpe"] > (bh_oos or 0)).mean()), "bh_is_sharpe": bh_is,
                "bh_oos_sharpe": bh_oos, "heatmap": heat,
                "note": "Rank on in-sample only; judge on out-of-sample. Prefer a robust region over a single peak. "
                        f"{len(df)} parameter sets tried - expect about {0.05 * len(df):.0f} lucky winners at 5%."}
    return _record(db, "grid", f"{strategy_key} on {symbol}", locals_cfg(strategy_key=strategy_key, symbol=symbol,
                   grid=grid, split_date=split_date), go)


def _robust_cell(g, ys, xs, a, b):
    v = np.array([[np.nan if x is None else x for x in row] for row in g], float)
    if np.all(np.isnan(v)):
        return None
    score = np.full(v.shape, np.nan)
    for i, j in itertools.product(range(v.shape[0]), range(v.shape[1])):
        if not np.isnan(v[i, j]):
            score[i, j] = np.nanmean(v[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2])
    i, j = np.unravel_index(np.nanargmax(score), score.shape)
    return {a: ys[i], b: xs[j], "neighbour_IS_sharpe": float(score[i, j]), "own_IS_sharpe": float(v[i, j])}


# --------------------------------------------------------------------------- walk-forward optimisation
def walk_forward(db: Session, strategy_key="sma_cross", symbol="SPY", grid: dict | None = None, train_bars=756,
                 test_bars=252, config: dict | None = None, start=None, end=None) -> ResearchRun:
    grid = grid or DEFAULT_GRIDS.get(strategy_key)

    def go():
        desc = registry.get(db, strategy_key)
        d, _ = prepare_data(db, desc, [symbol], "1Day", start, end)
        cfg = _cfg(config)
        pts = list(grid_points(grid, strategy_key)) if grid else [{}]
        sigs = {i: registry.compute_signals(db, strategy_key, d, p)[0] for i, p in enumerate(pts)}
        rets = {i: run_backtest({symbol: d}, s, cfg).returns for i, s in sigs.items()}
        windows, stitched = [], []
        n = len(d)
        for s0 in range(train_bars, n, test_bars):
            tr = slice(s0 - train_bars, s0)
            te = slice(s0, min(s0 + test_bars, n))
            scores = {i: M.sharpe_ratio(r.iloc[tr]) for i, r in rets.items()}
            best = max(scores, key=lambda i: -1e9 if np.isnan(scores[i]) else scores[i])
            oos = rets[best].iloc[te]
            stitched.append(oos)
            windows.append({"train": [str(d.index[tr.start])[:10], str(d.index[tr.stop - 1])[:10]],
                            "test": [str(d.index[te.start])[:10], str(d.index[te.stop - 1])[:10]],
                            "params": pts[best], "IS_sharpe": M._f(scores[best]), "OOS_sharpe": M._f(M.sharpe_ratio(oos)),
                            "OOS_return": M._f(M.total_return(oos))})
        if not stitched:
            raise ValueError("not enough data for one train + test window")
        oos_r = pd.concat(stitched)
        bh = d["close"].pct_change().reindex(oos_r.index).fillna(0)
        return {"strategy": strategy_key, "symbol": symbol, "train_bars": train_bars, "test_bars": test_bars,
                "windows": windows, "oos_metrics": M.summary(oos_r, benchmark=bh), "bh_metrics": M.summary(bh),
                "equity": series_payload(M.equity_curve(oos_r, 100_000), 2),
                "benchmark": series_payload(M.equity_curve(bh, 100_000), 2),
                "param_stability": len({str(w["params"]) for w in windows}),
                "note": "Each test window uses parameters chosen on the PREVIOUS training window only; the stitched "
                        "test windows are a genuine out-of-sample record."}
    return _record(db, "walk_forward", f"{strategy_key} on {symbol}", locals_cfg(strategy_key=strategy_key, symbol=symbol,
                   grid=grid, train_bars=train_bars, test_bars=test_bars), go)


# --------------------------------------------------------------------------- A/B test
def abtest(db: Session, a: dict, b: dict, symbol="SPY", alpha=0.05, tried=20, config: dict | None = None,
           start=None, end=None) -> ResearchRun:
    def go():
        cfg = _cfg(config)
        out = {}
        for tag, v in (("A", a), ("B", b)):
            desc = registry.get(db, v["strategy_key"])
            d, _ = prepare_data(db, desc, [symbol] if not desc["multi_asset"] else (v.get("symbols") or desc["default_symbols"]),
                                "1Day", start, end)
            sig, _ = registry.compute_signals(db, v["strategy_key"], d, v.get("params"))
            bars = d if isinstance(d, dict) else {symbol: d}
            res = run_backtest(bars, sig, cfg)
            out[tag] = (desc, res)
        ra, rb = out["A"][1].returns, out["B"][1].returns
        j = pd.concat([ra, rb], axis=1).dropna()
        warm = 200 if len(j) > 600 else 0
        j = j.iloc[warm:]
        res = ST.ab_test(j.iloc[:, 0], j.iloc[:, 1], alpha, tried)
        res["a"] = {"strategy": out["A"][0]["name"], "key": a["strategy_key"], "params": a.get("params", {}),
                    "metrics": M.summary(j.iloc[:, 0], trade_returns=out["A"][1].trades.get("net_return"))}
        res["b"] = {"strategy": out["B"][0]["name"], "key": b["strategy_key"], "params": b.get("params", {}),
                    "metrics": M.summary(j.iloc[:, 1], trade_returns=out["B"][1].trades.get("net_return"))}
        res["equity_a"] = series_payload(M.equity_curve(j.iloc[:, 0], 100_000), 2)
        res["equity_b"] = series_payload(M.equity_curve(j.iloc[:, 1], 100_000), 2)
        res["window"] = [str(j.index[0])[:10], str(j.index[-1])[:10]]
        res["symbol"] = symbol
        return res
    return _record(db, "abtest", f"{a['strategy_key']} vs {b['strategy_key']} on {symbol}",
                   locals_cfg(a=a, b=b, symbol=symbol, alpha=alpha, tried=tried), go)


# --------------------------------------------------------------------------- regimes
def regimes(db: Session, symbol="SPY", universe=None, clusters=3, base="ema_cross", base_params=None,
            config: dict | None = None) -> ResearchRun:
    universe = universe or ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "JPM", "XLF", "GLD", "TLT"]

    def go():
        closes = pd.DataFrame({s: data.load_bars(db, s)["close"] for s in universe}).dropna()
        pca = RG.pca_analysis(closes.pct_change().dropna())
        bars = _bars(db, symbol)
        feat = RG.regime_features(bars["close"]).dropna()
        scaler, km, names = RG.fit_regimes(feat, clusters)
        full = pd.Series(km.labels_, index=feat.index).map(names)
        nxt = bars["close"].pct_change().shift(-1)
        profile = RG.regime_profile(feat, full, nxt)
        wf = RG.walk_forward_regimes(feat, clusters)
        cfg = _cfg(config)
        sig = registry.compute_signals(db, base, bars, base_params)[0]
        test_start = wf.first_valid_index()
        tb = bars.loc[test_start:]
        ungated = run_backtest({symbol: tb}, sig.loc[test_start:], cfg)
        gated = run_backtest({symbol: tb}, RG.regime_gate(sig, wf).loc[test_start:], cfg)
        bh = buy_and_hold({symbol: tb}, cfg)
        lab = wf.dropna()
        segs = []
        cur, s0 = None, None
        for t, v in lab.items():
            if v != cur:
                if cur is not None:
                    segs.append({"start": str(s0)[:10], "end": str(t)[:10], "regime": cur})
                cur, s0 = v, t
        if cur is not None:
            segs.append({"start": str(s0)[:10], "end": str(lab.index[-1])[:10], "regime": cur})
        return {"symbol": symbol, "pca": pca, "profile": profile, "walk_forward_counts": lab.value_counts().to_dict(),
                "latest_regime": lab.iloc[-1] if len(lab) else None,
                "gate_open": bool(len(lab) and lab.iloc[-1] != RG.STRESS),
                "segments": segs, "price": series_payload(bars["close"].loc[test_start:], 2),
                "ungated_metrics": ungated.metrics(),
                "gated_metrics": gated.metrics(), "bh_metrics": bh.metrics(),
                "equity_gated": series_payload(gated.equity, 2), "equity_ungated": series_payload(ungated.equity, 2),
                "equity_bh": series_payload(bh.equity, 2), "base": base,
                "note": "Regimes are fitted walk-forward (refit every 63 bars on past data only). A gate is a model too - "
                        "A/B test it before it goes live."}
    return _record(db, "regime", f"{symbol} {clusters} regimes", locals_cfg(symbol=symbol, universe=universe,
                   clusters=clusters, base=base), go)


# --------------------------------------------------------------------------- pairs screen
def pairs_screen(db: Session, pairs=None, formation_end="2022-12-31") -> ResearchRun:
    pairs = pairs or [["KO", "PEP"], ["JPM", "BAC"], ["XLF", "JPM"], ["SPY", "QQQ"], ["GLD", "TLT"]]

    def go():
        syms = sorted({s for p in pairs for s in p})
        closes = pd.DataFrame({s: data.load_bars(db, s)["close"] for s in syms}).dropna()
        rows = PR.screen(closes.loc[:formation_end], [tuple(p) for p in pairs])
        return {"formation_end": formation_end, "pairs": rows, "critical_values": PR.EG_CRIT,
                "note": "High correlation does not imply cointegration; screening many pairs inflates false positives."}
    return _record(db, "pairs", "pairs screen", locals_cfg(pairs=pairs, formation_end=formation_end), go)


# --------------------------------------------------------------------------- ML report
def ml_report(db: Session, symbol="SPY", models=None, threshold=0.55) -> ResearchRun:
    models = models or ["logistic", "random_forest", "xgboost"]

    def go():
        bars = _bars(db, symbol)
        out = []
        cfg = _cfg({})
        for m in models:
            proba, folds = ML.walk_forward_proba(bars, m)
            rep = ML.classification_report(bars, proba)
            sig = (proba > threshold).astype(float).where(proba.notna(), 0.0)
            start = proba.first_valid_index()
            res = run_backtest({symbol: bars.loc[start:]}, sig.loc[start:], cfg)
            out.append({"model": ML.MODELS[m][0], "key": m, **rep, "folds": folds.to_dict("records"),
                        "backtest": res.metrics()})
        bh = buy_and_hold({symbol: bars.loc[proba.first_valid_index():]}, cfg).metrics()
        return {"symbol": symbol, "threshold": threshold, "models": out, "bh": bh,
                "importance": ML.feature_importance(bars.iloc[:-1], "random_forest")}
    return _record(db, "ml", f"ML classifiers on {symbol}", locals_cfg(symbol=symbol, models=models), go)


# --------------------------------------------------------------------------- execution algos
def execution_compare(db: Session, symbol="SPY", day=None, side="buy", qty=50000, participation=0.1,
                      impact_coef=0.1) -> ResearchRun:
    def go():
        bars = data.load_bars(db, symbol, "1Hour")
        return {"symbol": symbol, "results": EXA.compare(bars, day, side, qty, participation, impact_coef),
                "detail": {a: EXA.simulate(bars, day, a, side, qty, participation, impact_coef)["children"]
                           for a in ("twap", "vwap", "pov")}}
    return _record(db, "execution", f"TWAP/VWAP/POV {symbol}", locals_cfg(symbol=symbol, day=day, qty=qty), go)


# --------------------------------------------------------------------------- diagnostics
def _random_strategies(ret: pd.Series, n: int, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    state = (np.cumsum(rng.random((len(ret), n)) < 0.10, axis=0) % 2).astype(float)
    return pd.DataFrame(state, index=ret.index).shift(1).fillna(0).mul(ret, axis=0)


def diagnostics(db: Session, strategy_key="ema_cross", symbol="SPY", params=None, trials=76,
                split_date="2021-12-31", config: dict | None = None) -> ResearchRun:
    def go():
        desc = registry.get(db, strategy_key)
        if desc["multi_asset"] or desc["kind"] in ("execution", "market_making"):
            raise ValueError("diagnostics run on single-asset signal strategies")
        d, _ = prepare_data(db, desc, [symbol], "1Day")
        cfgd = BacktestConfig.from_dict(config)
        rows = []

        def add(check, status, evidence, detail=None):
            rows.append({"check": check, "status": status, "evidence": evidence, "detail": detail})

        def fn(b):
            return registry.compute_signals(db, strategy_key, b, params)[0]
        la = lookahead_check(fn, d, checks=8 if desc["custom"] else 15)
        add("1 Look-ahead in features", la["status"],
            f"{la['failed']} of {la['checks']} truncation / future-shock checks changed past signal values"
            + (f" (e.g. {', '.join(la['dates'][:3])})" if la["dates"] else ""), la)
        tgt = fn(d)
        daily = d["close"].pct_change().fillna(0)
        same_bar = (tgt * daily).fillna(0)
        nxt = run_backtest({symbol: d}, tgt, BacktestConfig(costs=CostModel(), compute_gross=False)).returns
        s_same, s_next = M._f(M.sharpe_ratio(same_bar)) or 0, M._f(M.sharpe_ratio(nxt)) or 0
        add("2 Look-ahead in execution", "PASS",
            f"The engine fills on the next bar. A same-bar backtest would show Sharpe {s_same:.2f} vs {s_next:.2f} "
            f"next-bar ({s_same - s_next:+.2f} inflation).")
        res = run_backtest({symbol: d}, tgt, cfgd)
        cs = res.cost_summary()
        be = break_even_bps({symbol: d}, tgt, cfgd, iterations=14)
        assumed = cfgd.costs.one_way_bps() or 1.0
        g, n_ = cs["gross_cagr"] or 0, cs["net_cagr"] or 0
        share = (g - n_) / g if g > 0 else 1.0
        st = "PASS" if (be >= 3 * assumed and share < 0.25) else ("WARN" if be >= assumed else "FAIL")
        add("3 Cost drag", st, f"Gross CAGR {g:.2%} -> net {n_:.2%} (drag {share:.0%} of gross); break-even {be:.1f} bps "
            f"vs assumed {assumed:.1f} bps one way", {"break_even_bps": be, "assumed_bps": assumed})
        rnd = _random_strategies(daily, 500)
        oos = pd.Timestamp(split_date) + pd.Timedelta(days=1)
        is_sh = rnd.loc[:split_date].apply(M.sharpe_ratio)
        oos_sh = rnd.loc[oos:].apply(M.sharpe_ratio)
        noise_max = float(is_sh.iloc[:max(1, trials)].max())
        s_is, s_oos = M._f(M.sharpe_ratio(res.returns.loc[:split_date])) or 0, M._f(M.sharpe_ratio(res.returns.loc[oos:])) or 0
        st = "PASS" if (s_is > noise_max and s_oos > 0) else ("WARN" if s_oos > 0 else "FAIL")
        add("4 Overfitting", st, f"IS Sharpe {s_is:.2f} vs best of {trials} skill-free random strategies {noise_max:.2f}; "
            f"OOS {s_oos:.2f} (decay {s_oos - s_is:+.2f})",
            {"random_is": [M._f(x) for x in is_sh.values[:300]], "random_oos": [M._f(x) for x in oos_sh.values[:300]],
             "strategy": [s_is, s_oos]})
        add("5 Survivorship / hindsight", "WARN",
            f"The demo universe was chosen today from listed survivors; results on {symbol} exclude delisted names. "
            "Use a point-in-time universe before drawing conclusions.")
        fails = sum(r["status"] == "FAIL" for r in rows)
        warns = sum(r["status"] == "WARN" for r in rows)
        verdict = ("BLOCK - fix the FAIL items before paper or live trading" if fails else
                   "CLEAR for paper trading - review every WARN with the risk committee")
        return {"strategy": strategy_key, "name": desc["name"], "symbol": symbol, "checks": rows, "fails": fails,
                "warns": warns, "verdict": verdict, "same_bar_sharpe": s_same, "next_bar_sharpe": s_next}
    return _record(db, "diagnostics", f"{strategy_key} on {symbol}", locals_cfg(strategy_key=strategy_key, symbol=symbol,
                   params=params, trials=trials), go)


def to_dict(rr: ResearchRun, full: bool = True) -> dict:
    d = {"id": rr.id, "kind": rr.kind, "name": rr.name, "status": rr.status, "error": rr.error,
         "duration_ms": rr.duration_ms, "created_at": rr.created_at.isoformat() if rr.created_at else None,
         "config": rr.config}
    if full:
        d["result"] = rr.result
    else:
        r = rr.result or {}
        d["headline"] = _headline(rr.kind, r) if r else ""
    return d


COSTS = COST_PRESETS
