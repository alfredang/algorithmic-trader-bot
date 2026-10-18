"""Seed the database with the offline demo data and sample results so every page is populated on first launch."""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.data import providers as P
from trader.data import service as data
from trader.models import Backtest, Bot, Instrument, ResearchRun, Setting, StrategyRecord
from trader.sentiment import news as NEWS
from trader.services import backtests as BT
from trader.services import research as R
from trader.strategies import registry

log = logging.getLogger("trader.seed")

SAMPLE_BACKTESTS = [
    {"name": "EMA 10/30 crossover on SPY (Alpaca-style costs)", "strategy_key": "ema_cross", "symbols": ["SPY"],
     "params": {"fast": 10, "slow": 30}},
    {"name": "SMA 50/200 golden cross on SPY", "strategy_key": "sma_cross", "symbols": ["SPY"]},
    {"name": "RSI(2) mean reversion on SPY", "strategy_key": "rsi2_reversion", "symbols": ["SPY"]},
    {"name": "Bollinger mean reversion on KO", "strategy_key": "bollinger_reversion", "symbols": ["KO"]},
    {"name": "Donchian 20/10 breakout on QQQ", "strategy_key": "donchian_breakout", "symbols": ["QQQ"]},
    {"name": "Cross-sectional momentum (9 assets)", "strategy_key": "xs_momentum",
     "symbols": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "JPM", "XLF", "GLD", "TLT"]},
    {"name": "KO / PEP pairs trade (hedged)", "strategy_key": "pairs_cointegration", "symbols": ["KO", "PEP"]},
    {"name": "Buy and hold SPY (benchmark)", "strategy_key": "buy_hold", "symbols": ["SPY"]},
]


def seed(db: Session, quick: bool = False, log_fn=print) -> dict:
    out = {"ingested": [], "backtests": [], "research": []}
    for sym in P.DEMO_SYMBOLS:
        r = data.ingest(db, sym, "1Day", source="demo")
        out["ingested"].append(f"{sym} {r['bars']} bars ({r['quality']['status']})")
    r = data.ingest(db, "SPY", "1Hour", source="demo")
    out["ingested"].append(f"SPY 1Hour {r['bars']} bars")
    _seed_reference(db)
    db.commit()
    log_fn(f"[seed] bars cached: {', '.join(out['ingested'])}")
    items = NEWS.demo_headlines()
    n = data.store_news(db, items)
    for sym in sorted({i["symbol"] for i in items}):
        data.rebuild_daily_sentiment(db, sym)
    db.commit()
    log_fn(f"[seed] {n} sample headlines (SYNTHETIC, training only) scored with VADER")
    from trader.services.events import stage
    stage("news", "warning", f"{n} SYNTHETIC sample headlines scored with VADER (offline demo)", {"new": n}, db=db)
    db.commit()
    if not db.scalar(select(StrategyRecord).where(StrategyRecord.key == "custom_lab18_biased_smoothed_momentum")):
        spy = data.load_bars(db, "SPY")
        v = registry.validate_code(registry.BIASED_CODE, spy)
        rec = registry.save_custom(db, registry.BIASED_CODE, v.get("meta", {"name": "Lab 18 exhibit"}),
                                   info={"summary": "Deliberately biased exhibit for Lab 18: a centred rolling window "
                                                    "leaks two future closes into every signal.",
                                         "family": "Exhibit (biased)", "course_ref": "TOPIC 4 · K8"}, validation=v)
        rec.key = "custom_lab18_biased_smoothed_momentum"
        tmpl = registry.TEMPLATES["ema_rsi"]["code"]
        v2 = registry.validate_code(tmpl, spy)
        registry.save_custom(db, tmpl, v2.get("meta", {"name": "EMA trend + RSI filter"}),
                             info={"summary": "Example custom strategy written with the plugin API."}, validation=v2)
        db.commit()
        log_fn("[seed] custom strategies: Lab 18 biased exhibit + an example EMA/RSI strategy")
    existing = {b.name for b in db.scalars(select(Backtest))}
    samples = SAMPLE_BACKTESTS[:3] if quick else SAMPLE_BACKTESTS
    for req in samples:
        if req["name"] in existing:
            continue
        bt = BT.run(db, {**req, "config": {"costs": "alpaca_retail"}})
        db.commit()
        out["backtests"].append(f"#{bt.id} {bt.name}: {bt.status}")
        log_fn(f"[seed] backtest #{bt.id} {bt.name}: {bt.status}")
    if not quick and not db.scalar(select(ResearchRun.id).limit(1)):
        runs = [R.hypothesis(db, "SPY", {"type": "losing_streak", "n": 3}),
                R.grid_search(db, "sma_cross", "SPY"),
                R.abtest(db, {"strategy_key": "trend_filter"}, {"strategy_key": "dip_buy"}, "SPY"),
                R.diagnostics(db, "ema_cross", "SPY", {"fast": 10, "slow": 30}),
                R.pairs_screen(db)]
        db.commit()
        for rr in runs:
            out["research"].append(f"#{rr.id} {rr.kind}: {rr.status}")
            log_fn(f"[seed] research #{rr.id} {rr.kind}: {rr.status}")
    if not db.scalar(select(Bot.id).limit(1)):
        db.add(Bot(name="SPY EMA bot (offline replay)", strategy_key="ema_cross", params={"fast": 10, "slow": 30},
                   symbols=["SPY"], schedule="every 10s", broker="sim", data_mode="replay", replay_start="2025-01-02",
                   sizing={"mode": "percent_equity", "pct": 0.95}, risk={"max_position_pct": 0.95}, status="stopped"))
        db.flush()
        from trader.bots.runner import ensure_account
        for b in db.scalars(select(Bot)):
            ensure_account(db, b)
        db.commit()
        log_fn("[seed] bot 'SPY EMA bot (offline replay)' created (stopped) - start it on the Paper Trading page")
    s = db.get(Setting, "onboarding") or Setting(key="onboarding", value={"done": False})
    db.add(s)
    db.commit()
    return out


def _seed_reference(db: Session) -> None:
    """D05.SI (DBS, SGX) research bars from the raw reference file x the adjustment factor (Lab 02)."""
    raw = P.PROVIDERS["demo"].raw_reference("D05.SI")
    if raw is None:
        return
    f = raw["adj_close"] / raw["close"]
    adj = raw[["open", "high", "low", "close"]].mul(f, axis=0)
    adj["volume"] = raw["volume"]
    data.store_bars(db, "D05.SI", "1Day", adj, "demo")
    inst = db.scalar(select(Instrument).where(Instrument.symbol == "D05.SI"))
    if inst is None:
        db.add(Instrument(symbol="D05.SI", name="DBS Group Holdings (SGX)", exchange="SGX", currency="SGD",
                          tradingview_symbol="SGX:D05", source="demo", first_bar=pd.Timestamp(adj.index[0]).to_pydatetime(),
                          last_bar=pd.Timestamp(adj.index[-1]).to_pydatetime()))
