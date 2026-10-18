"""Backtest service: load data -> strategy signals -> engine -> metrics -> persisted Backtest record."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from trader.core import execution_algos as EXA
from trader.core import market_making as MMK
from trader.core import metrics as M
from trader.core.backtest import (
    BacktestConfig,
    BacktestResult,
    break_even_bps,
    buy_and_hold,
    run_backtest,
    series_payload,
)
from trader.data import service as data
from trader.models import Backtest
from trader.services.events import emit, jsonable, stage
from trader.strategies import registry


def prepare_data(db: Session, desc: dict, symbols: list[str], timeframe: str, start=None, end=None):
    """Bars for a strategy: a DataFrame (single asset) or {symbol: DataFrame}; adds sentiment if needed."""
    panel = data.load_panel(db, symbols, timeframe, start, end)
    for s, df in panel.items():
        if df.empty:
            raise ValueError(f"no {timeframe} bars for {s} in the selected window")
    notes = {}
    if "sentiment" in desc.get("needs", []):
        for s, df in panel.items():
            sent, src = data.sentiment_series(db, s, df["close"])
            df["sentiment"] = sent.values
            notes[f"sentiment_{s}"] = src
    if desc["multi_asset"]:
        return panel, notes
    return panel[symbols[0].upper()], notes


def _benchmark_returns(db: Session, benchmark: str, index: pd.DatetimeIndex, timeframe: str) -> pd.Series | None:
    try:
        b = data.load_bars(db, benchmark, timeframe, str(index[0])[:10], str(index[-1])[:10])
    except Exception:
        return None
    if b.empty:
        return None
    return b["close"].pct_change().reindex(index).fillna(0.0)


def summarize(res: BacktestResult, bench: pd.Series | None, benchmark_res: BacktestResult | None) -> dict:
    eq = res.equity
    out = {
        "metrics": res.metrics(bench), "gross_metrics": res.metrics(bench, gross=True),
        "cost_summary": res.cost_summary(),
        "benchmark_metrics": benchmark_res.metrics() if benchmark_res is not None else None,
    }
    dd = M.drawdown_series(res.returns)
    roll = M.rolling_sharpe(res.returns, 126 if len(eq) > 300 else max(20, len(eq) // 4))
    monthly = M.monthly_returns(res.returns)
    series = {"equity": series_payload(eq, 2), "equity_gross": series_payload(res.equity_gross, 2),
              "drawdown": series_payload(dd, 5), "rolling_sharpe": series_payload(roll, 3),
              "exposure": series_payload(res.exposure, 4),
              "monthly": {"years": [int(y) for y in monthly.index],
                          "values": [[None if pd.isna(v) else round(float(v), 5) for v in row] for row in monthly.values]}}
    if benchmark_res is not None:
        b = benchmark_res.equity * (res.initial_capital / benchmark_res.equity.iloc[0]) if len(benchmark_res.equity) else None
        series["benchmark"] = series_payload(b.reindex(eq.index).ffill(), 2) if b is not None else []
        series["benchmark_drawdown"] = series_payload(M.drawdown_series(benchmark_res.returns.reindex(eq.index).fillna(0)), 5)
    trades = res.trades.copy()
    if len(trades):
        for c in ("entry_date", "exit_date"):
            trades[c] = trades[c].astype(str).str[:19]
    fills = res.fills.copy()
    if len(fills):
        fills["date"] = fills["date"].astype(str).str[:19]
    out["series"] = series
    out["trades"] = jsonable(trades.to_dict("records"))
    out["fills"] = jsonable(fills.tail(2000).to_dict("records"))
    return out


def run(db: Session, req: dict, record: bool = True) -> Backtest:
    t0 = time.time()
    key = req["strategy_key"]
    desc = registry.get(db, key)
    symbols = [s.upper() for s in (req.get("symbols") or desc["default_symbols"])]
    tf = req.get("timeframe") or ("1Hour" if desc["kind"] in ("execution", "market_making") else "1Day")
    params = registry.coerce_params(desc, req.get("params"))
    cfg = BacktestConfig.from_dict(req.get("config"))
    if desc.get("allow_short") and desc["kind"] == "portfolio":
        cfg.allow_short = True
    benchmark = (req.get("benchmark") or "SPY").upper()
    bt = Backtest(name=req.get("name") or f"{desc['name']} on {', '.join(symbols)}", strategy_key=key, params=params,
                  symbols=symbols, timeframe=tf, start=req.get("start"), end=req.get("end"), benchmark=benchmark,
                  config=cfg.to_dict(), status="running")
    if record:
        db.add(bt)
        db.flush()
    stage("strategy", "ok", f"{desc['name']} selected {params}", {"strategy": key, "custom": desc["custom"]},
          ref_type="backtest", ref_id=bt.id, db=db)
    stage("backtest", "running", f"Backtesting {desc['name']} on {', '.join(symbols)}", ref_type="backtest", ref_id=bt.id, db=db)
    try:
        if desc["kind"] == "execution":
            out = _run_execution(db, desc, params, symbols, req)
        elif desc["kind"] == "market_making":
            out = _run_market_making(db, params, symbols, tf, req, cfg)
        else:
            out = _run_signal(db, desc, key, params, symbols, tf, req, cfg, benchmark)
        fills = out.pop("fills", None)
        if fills is not None:
            out.setdefault("extra", {})["fills"] = fills
        for k, v in out.items():
            setattr(bt, k, jsonable(v))
        bt.status = "done"
        m = bt.metrics or {}
        stage("features", "ok", f"Indicators/features computed for {', '.join(symbols)}", {"symbols": symbols}, db=db)
        stage("signals", "ok", f"Signals for {desc['name']}", {"strategy": key}, ref_type="backtest", ref_id=bt.id, db=db)
        stage("backtest", "ok", f"#{bt.id} {desc['name']}: CAGR {_pct(m.get('cagr'))}, Sharpe {_num(m.get('sharpe'))}, "
              f"MaxDD {_pct(m.get('max_drawdown'))}, {m.get('trades', 0)} trades",
              {k: m.get(k) for k in ("cagr", "sharpe", "max_drawdown", "trades")} | {"id": bt.id, "strategy": key},
              ref_type="backtest", ref_id=bt.id, db=db)
        stage("analytics", "ok", f"Metrics for backtest #{bt.id}", {"id": bt.id, **{k: m.get(k) for k in ("sharpe", "sortino", "calmar")}},
              ref_type="backtest", ref_id=bt.id, db=db)
    except Exception as exc:
        bt.status, bt.error = "error", str(exc)[:2000]
        stage("backtest", "error", f"{desc['name']}: {exc}", ref_type="backtest", ref_id=bt.id, db=db)
        if not record:
            raise
    bt.duration_ms = int((time.time() - t0) * 1000)
    if record:
        db.flush()
        emit("backtest.done", {"id": bt.id, "status": bt.status, "name": bt.name}, db=db)
    return bt


def _run_signal(db, desc, key, params, symbols, tf, req, cfg, benchmark) -> dict:
    d, notes = prepare_data(db, desc, symbols, tf, req.get("start"), req.get("end"))
    sig, extra = registry.compute_signals(db, key, d, params)
    bars = d if isinstance(d, dict) else {symbols[0]: d}
    if isinstance(sig, pd.Series):
        sig = sig.to_frame(symbols[0])
    if not desc["multi_asset"] and (desc.get("allow_short") and params.get("allow_short")):
        cfg.allow_short = True
    if desc.get("custom") and desc.get("allow_short"):
        cfg.allow_short = True
    res = run_backtest(bars, sig, cfg)
    bench = _benchmark_returns(db, benchmark, res.equity.index, tf)
    bres = None
    try:
        bb = data.load_bars(db, benchmark, tf, str(res.equity.index[0])[:10], str(res.equity.index[-1])[:10])
        if len(bb):
            bres = buy_and_hold({benchmark: bb}, BacktestConfig(costs=cfg.costs, initial_capital=cfg.initial_capital))
    except Exception:
        bres = None
    out = summarize(res, bench, bres)
    if len(bars) == 1:
        try:
            be = break_even_bps(bars, sig, cfg, iterations=14)
        except Exception:
            be = None
        out["cost_summary"]["break_even_bps"] = be
        out["metrics"]["break_even_bps"] = be
    out["extra"] = {**extra, **notes, "signal_latest": {c: float(sig[c].iloc[-1]) for c in sig.columns},
                    "kind": desc["kind"]}
    out["metrics"]["total_costs"] = out["cost_summary"]["total"]
    return out


def _run_market_making(db, params, symbols, tf, req, cfg) -> dict:
    sym = symbols[0]
    bars = data.load_bars(db, sym, tf, req.get("start"), req.get("end"))
    if bars.empty:
        raise ValueError(f"no {tf} bars for {sym}")
    r = MMK.simulate(bars, params["half_spread_bps"], params["clip"], params["max_inventory"], params["skew_bps"],
                     initial_capital=cfg.initial_capital)
    eq = r["equity"]
    rets = eq.pct_change().fillna(0.0)
    periods = 252 * 7 if tf == "1Hour" else 252
    pos = MMK.signals_from_inventory(r["inventory"], params["max_inventory"])
    m = M.summary(rets, pos, None, None, periods)
    series = {"equity": series_payload(eq, 2), "drawdown": series_payload(M.drawdown_series(rets), 5),
              "inventory": series_payload(r["inventory"], 1), "exposure": series_payload(pos, 4)}
    return {"metrics": m, "series": series, "trades": r["fills"][-500:], "cost_summary": {},
            "extra": {"kind": "market_making", "n_buys": r["n_buys"], "n_sells": r["n_sells"],
                      "spread_captured": r["spread_captured"], "inventory_pnl": r["inventory_pnl"],
                      "final_inventory": r["final_inventory"], "max_abs_inventory": r["max_abs_inventory"]}}


def _run_execution(db, desc, params, symbols, req) -> dict:
    sym = symbols[0]
    bars = data.load_bars(db, sym, "1Hour")
    if bars.empty:
        raise ValueError(f"execution algorithms need intraday (1Hour) bars for {sym}; bundled: SPY")
    algo = desc["key"].split("_", 1)[1]
    r = EXA.simulate(bars, req.get("day"), algo, params["side"], params["qty"], params["participation"], params["impact_coef"])
    cmp = EXA.compare(bars, r["day"], params["side"], params["qty"], params["participation"], params["impact_coef"])
    m = {"avg_price": r["avg_price"], "session_vwap": r["session_vwap"], "arrival_price": r["arrival_price"],
         "slippage_vs_vwap_bps": r["slippage_vs_vwap_bps"], "implementation_shortfall_bps": r["implementation_shortfall_bps"],
         "fill_rate": r["fill_rate"], "n_children": r["n_children"], "max_participation": r["max_participation"]}
    return {"metrics": m, "series": {"children": r["children"]}, "trades": r["children"], "cost_summary": {},
            "extra": {"kind": "execution", "algo": algo, "day": r["day"], "compare": cmp, "days_available": r["days_available"]}}


def _pct(x):
    return "-" if x is None else f"{x:.1%}"


def _num(x):
    return "-" if x is None else f"{x:.2f}"


def to_dict(bt: Backtest, full: bool = True) -> dict:
    d = {"id": bt.id, "name": bt.name, "strategy_key": bt.strategy_key, "params": bt.params, "symbols": bt.symbols,
         "timeframe": bt.timeframe, "start": bt.start, "end": bt.end, "benchmark": bt.benchmark, "status": bt.status,
         "error": bt.error, "metrics": bt.metrics, "duration_ms": bt.duration_ms,
         "created_at": bt.created_at.isoformat() if bt.created_at else None,
         "kind": (bt.extra or {}).get("kind", "signal")}
    if full:
        d.update(config=bt.config, gross_metrics=bt.gross_metrics, benchmark_metrics=bt.benchmark_metrics,
                 cost_summary=bt.cost_summary, series=bt.series, trades=bt.trades, extra=bt.extra)
    return d


def equity_frame(bt: Backtest) -> pd.DataFrame:
    s = bt.series or {}
    df = pd.DataFrame(s.get("equity", []), columns=["date", "equity"]).set_index("date")
    for k in ("equity_gross", "benchmark", "drawdown"):
        if s.get(k):
            df[k] = pd.DataFrame(s[k], columns=["date", k]).set_index("date")[k]
    return df


def returns_of(bt: Backtest) -> pd.Series:
    df = equity_frame(bt)
    r = df["equity"].astype(float).pct_change().fillna(0.0)
    r.index = pd.to_datetime(r.index)
    return r


__all__ = ["run", "to_dict", "equity_frame", "returns_of", "prepare_data", "np"]
