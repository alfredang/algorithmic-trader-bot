"""Paper-trading bots: one decision cycle = clock -> completed bars -> signal -> risk -> orders -> P&L.

Data modes
  replay  OFFLINE forward test on the bundled data: every cycle advances ONE bar. The bot sees
          bars up to the previous close only and its market orders fill at that bar's open in the
          simulator - a true forward test of the decision loop, run as fast as the schedule says.
  live    latest data from the configured source; the session comes from the (Alpaca) clock and
          outside the regular session orders become extended-hours LIMIT orders (Alpaca 24/5),
          or queue as GTC limits when the market is closed.
"""
from __future__ import annotations

import math
import traceback
from datetime import timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trader.broker import service as BRK
from trader.core import metrics as M
from trader.core.backtest import BacktestConfig, run_backtest, series_payload
from trader.data import service as data
from trader.models import Account, Bot, Fill, Order, PnLSnapshot, utcnow
from trader.services.backtests import prepare_data
from trader.services.events import audit, emit, jsonable, stage
from trader.strategies import registry

DEFAULT_RISK = {"max_position_pct": 0.95, "max_order_value": 100_000.0, "max_order_qty": 10_000.0,
                "max_daily_loss_pct": 0.02, "allowed_symbols": [], "long_only": True}


def ensure_account(db: Session, bot: Bot) -> Account:
    if bot.account_id:
        a = db.get(Account, bot.account_id)
        if a is not None:
            return a
    if bot.broker == "alpaca_paper":
        a = BRK.get_account(db, "Alpaca paper account", broker="alpaca_paper")
    else:
        a = Account(name=f"Bot #{bot.id} {bot.name}"[:100], broker="sim", cash=100_000.0, starting_cash=100_000.0,
                    last_equity=100_000.0)
        db.add(a)
        db.flush()
    bot.account_id = a.id
    return a


def _history(db, bot, desc, end=None):
    """Completed bars for every bot symbol (single-asset strategies are evaluated symbol by symbol)."""
    syms = [s.upper() for s in bot.symbols]
    if desc["multi_asset"]:
        panel, _ = prepare_data(db, desc, syms, bot.timeframe, None, end)
        return {"__multi__": panel}
    out = {}
    for s in syms:
        d, _ = prepare_data(db, desc, [s], bot.timeframe, None, end)
        out[s] = d
    return out


def compute_targets(db: Session, bot: Bot, hist: dict) -> dict[str, float]:
    pct = float((bot.sizing or {}).get("pct", 0.95))
    if "__multi__" in hist:
        sig, _ = registry.compute_signals(db, bot.strategy_key, hist["__multi__"], bot.params)
        last = sig.iloc[-1]
        return {s: float(last.get(s, 0.0)) * pct for s in sig.columns}
    n = max(len(hist), 1)
    out = {}
    for s, d in hist.items():
        sig, _ = registry.compute_signals(db, bot.strategy_key, d, bot.params)
        out[s] = float(sig.iloc[-1]) * pct / n
    return out


def _rebalance(db, bot, acct, br, targets, prices, tag, run_id, session_override=None) -> list[dict]:
    """Target weights -> whole-share orders (sells first). Idempotent: one client_order_id per decision bar."""
    results = []
    equity = br.equity()
    limits = {**DEFAULT_RISK, **(bot.risk or {})}
    pending = {}
    for o in br.open_orders():
        pending[o.symbol] = pending.get(o.symbol, 0.0) + (o.qty - o.filled_qty) * (1 if o.side == "buy" else -1)
    plans = []
    for sym, w in targets.items():
        px = prices.get(sym)
        if not px or px <= 0:
            continue
        if limits.get("long_only", True):
            w = max(w, 0.0)
        tgt = math.floor(abs(w) * equity / px) * (1 if w >= 0 else -1)
        pos = br.position(sym)
        cur = pos.qty if pos else 0.0
        delta = tgt - cur - pending.get(sym, 0.0)
        if abs(delta) >= 1:
            plans.append((sym, "buy" if delta > 0 else "sell", abs(delta), tgt, cur))
    for sym, side, qty, tgt, cur in sorted(plans, key=lambda p: p[1] != "sell"):
        req = BRK.OrderRequest(symbol=sym, side=side, qty=float(qty), type="auto",
                               client_order_id=BRK.client_id(f"b{bot.id}-{tag}", sym, side, qty),
                               note=f"bot {bot.name}: target {tgt:g} shares (held {cur:g})", meta={"run_id": run_id})
        r = BRK.place_order(db, acct, req, source="bot", bot_id=bot.id, limits=limits, bot_kill=bot.kill_switch,
                            session_override=session_override, broker=br)
        results.append({"symbol": sym, "side": side, "qty": qty, "target": tgt, "ok": r["ok"],
                        "status": (r["order"] or {}).get("status"), "reason": r["risk"]["reason"],
                        "order_id": (r["order"] or {}).get("id")})
    return results


def run_cycle(db: Session, bot: Bot) -> dict:
    """One decision cycle. Never raises: errors are recorded on the bot and the Pipeline Map."""
    run_id = f"bot{bot.id}-c{bot.cycles + 1}"
    stage("forward", "running", f"Bot '{bot.name}' cycle {bot.cycles + 1}", {"bot_id": bot.id}, ref_type="bot",
          ref_id=bot.id, run_id=run_id, db=db)
    try:
        if bot.kill_switch or BRK.kill_switch_on(db):
            res = {"status": "halted", "message": "kill switch ON - no orders sent"}
            stage("risk", "error", f"Bot '{bot.name}': kill switch ON", {"bot_id": bot.id}, run_id=run_id, db=db)
        elif bot.data_mode == "replay":
            res = _replay_cycle(db, bot, run_id)
        else:
            res = _live_cycle(db, bot, run_id)
        bot.cycles += 1
        bot.last_run_at = utcnow()
        bot.last_result = jsonable(res)
        bot.last_error = None
        if res.get("status") == "finished":
            bot.status = "stopped"
        snap = res.get("equity")
        stage("forward", "ok" if res.get("status") != "halted" else "warning",
              f"Bot '{bot.name}' {res.get('bar', '')}: {res.get('message', '')}",
              {"bot_id": bot.id, "equity": snap, "orders": len(res.get("orders", [])), "status": bot.status},
              ref_type="bot", ref_id=bot.id, run_id=run_id, db=db)
        stage("positions", "ok", f"Bot '{bot.name}' equity {snap if snap is None else round(snap, 2)}",
              {"bot_id": bot.id, "equity": snap, "positions": res.get("positions")}, ref_type="bot", ref_id=bot.id,
              run_id=run_id, db=db)
        emit("bot.cycle", {"bot_id": bot.id, "run_id": run_id, **jsonable(res)}, db=db)
        return res
    except Exception as exc:
        bot.last_error = f"{type(exc).__name__}: {exc}"
        bot.last_run_at = utcnow()
        stage("forward", "error", f"Bot '{bot.name}': {exc}", {"bot_id": bot.id}, ref_type="bot", ref_id=bot.id,
              run_id=run_id, db=db)
        emit("bot.error", {"bot_id": bot.id, "error": str(exc), "trace": traceback.format_exc(limit=3)}, db=db)
        return {"status": "error", "message": str(exc)}


def _replay_cycle(db: Session, bot: Bot, run_id: str) -> dict:
    acct = ensure_account(db, bot)
    br = BRK.SimBroker(db, acct)
    desc = registry.get(db, bot.strategy_key)
    hist_all = _history(db, bot, desc)
    frames = hist_all["__multi__"] if "__multi__" in hist_all else hist_all
    index = None
    for df in frames.values():
        index = df.index if index is None else index.intersection(df.index)
    start = pd.Timestamp(bot.cursor) + pd.Timedelta(days=1) if bot.cursor else pd.Timestamp(bot.replay_start or "2025-01-02")
    future = index[index >= start]
    if not len(future):
        return {"status": "finished", "message": "replay complete - no more bars", "equity": br.equity(), "orders": []}
    day = future[0]
    acct.sim_clock = (day + timedelta(hours=9, minutes=35)).to_pydatetime()
    stage("ingestion", "ok", f"Replay bar {str(day)[:10]} for {', '.join(frames)}", {"bot_id": bot.id}, run_id=run_id, db=db)
    hist = ({"__multi__": {s: df.loc[df.index < day] for s, df in frames.items()}} if "__multi__" in hist_all
            else {s: df.loc[df.index < day] for s, df in frames.items()})
    stage("features", "ok", "Indicators on completed bars", {"bot_id": bot.id}, run_id=run_id, db=db)
    targets = compute_targets(db, bot, hist)
    stage("signals", "ok", f"Targets {', '.join(f'{k} {v:.0%}' for k, v in targets.items())}",
          {"bot_id": bot.id, "targets": targets}, run_id=run_id, db=db)
    opens = {s: float(df.loc[day, "open"]) for s, df in frames.items()}
    for s, px in opens.items():
        br.mark(s, px)
    orders = _rebalance(db, bot, acct, br, targets, opens, str(day)[:10].replace("-", ""), run_id, session_override="regular")
    for s, df in frames.items():
        b = df.loc[day]
        br.match(s, float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]), session="regular")
    eq = br.equity()
    br.end_of_day()
    snap = br.snapshot(bot.id, str(day)[:10])
    bot.cursor = str(day)[:10]
    filled = [o for o in orders if o["status"] == "filled"]
    return {"status": "ok", "bar": str(day)[:10], "equity": eq, "orders": orders, "targets": targets,
            "positions": {p.symbol: p.qty for p in br.positions()}, "realized": snap.realized,
            "message": f"{len(orders)} orders ({len(filled)} filled), equity {eq:,.2f}"}


def _live_cycle(db: Session, bot: Bot, run_id: str) -> dict:
    acct = ensure_account(db, bot)
    br = BRK.broker_for(db, acct)
    if isinstance(br, BRK.AlpacaPaperBroker):
        br.sync()
    desc = registry.get(db, bot.strategy_key)
    for s in bot.symbols:
        try:
            data.ingest(db, s.upper(), bot.timeframe if bot.timeframe != "1Week" else "1Day", "2018-01-01")
        except Exception as exc:
            stage("ingestion", "warning", f"{s}: refresh failed ({exc}); using cached bars", run_id=run_id, db=db)
    hist = _history(db, bot, desc)
    st = br.session()
    today = pd.Timestamp(st["now_et"]).tz_localize(None).normalize()
    frames = hist["__multi__"] if "__multi__" in hist else hist
    for s, df in list(frames.items()):
        if bot.timeframe == "1Day" and len(df) and df.index[-1] >= today and st["session"] in ("regular", "after"):
            frames[s] = df.loc[df.index < today]          # drop today's unfinished bar
    targets = compute_targets(db, bot, hist)
    stage("signals", "ok", f"Targets {targets}", {"bot_id": bot.id, "targets": targets}, run_id=run_id, db=db)
    prices = {s: BRK.quote(db, s, acct.broker)["last"] for s in frames}
    if not bot.extended_hours and st["session"] not in ("regular",):
        return {"status": "ok", "message": f"{st['session']} session and extended hours disabled - waiting",
                "equity": br.equity(), "orders": [], "session": st["session"]}
    orders = _rebalance(db, bot, acct, br, targets, prices, utcnow().strftime("%Y%m%d%H"), run_id)
    if not isinstance(br, BRK.AlpacaPaperBroker):
        for s, px in prices.items():
            br.match(s, px, px, px, px)
    eq = br.equity()
    br.snapshot(bot.id, st["now_et"][:16])
    return {"status": "ok", "bar": st["now_et"][:16], "session": st["session"], "equity": eq, "orders": orders,
            "targets": targets, "positions": {p.symbol: p.qty for p in br.positions()},
            "message": f"{st['session']} session, {len(orders)} orders, equity {eq:,.2f}"}


def reset(db: Session, bot: Bot) -> None:
    """Fresh simulator account and replay cursor (old orders and snapshots are kept for the audit trail)."""
    if bot.broker == "sim":
        a = Account(name=f"Bot #{bot.id} {bot.name} ({utcnow():%Y%m%d%H%M%S})"[:100], broker="sim", cash=100_000.0,
                    starting_cash=100_000.0, last_equity=100_000.0)
        db.add(a)
        db.flush()
        bot.account_id = a.id
    bot.cursor, bot.cycles, bot.last_result, bot.last_error = None, 0, None, None
    audit("bot.reset", "bot", bot.id, {"account_id": bot.account_id}, db=db)


def equity_series(db: Session, bot: Bot) -> list[dict]:
    rows = db.scalars(select(PnLSnapshot).where(PnLSnapshot.bot_id == bot.id, PnLSnapshot.account_id == bot.account_id)
                      .order_by(PnLSnapshot.id)).all()
    return [{"t": r.bar_time or r.ts.isoformat()[:16], "equity": r.equity, "cash": r.cash, "realized": r.realized,
             "unrealized": r.unrealized} for r in rows]


def compare(db: Session, bot: Bot) -> dict:
    """Backtest vs forward test over the same bars (course Topic 4.5)."""
    eq = equity_series(db, bot)
    if len(eq) < 3:
        return {"ready": False, "message": "Run the bot for a few cycles first."}
    fwd = pd.Series([e["equity"] for e in eq], index=pd.to_datetime([e["t"] for e in eq]))
    desc = registry.get(db, bot.strategy_key)
    syms = [s.upper() for s in bot.symbols]
    start = fwd.index[0]
    d, _ = prepare_data(db, desc, syms if desc["multi_asset"] else syms[:1], bot.timeframe, None, str(fwd.index[-1])[:10])
    sig, _ = registry.compute_signals(db, bot.strategy_key, d, bot.params)
    bars = d if isinstance(d, dict) else {syms[0]: d}
    pct = float((bot.sizing or {}).get("pct", 0.95))
    sig = sig * pct
    res = run_backtest({s: b.loc[b.index >= start - pd.Timedelta(days=5)] for s, b in bars.items()},
                       sig.loc[sig.index >= start - pd.Timedelta(days=5)], BacktestConfig())
    bt_eq = res.equity.loc[res.equity.index >= start]
    bt_eq = bt_eq / bt_eq.iloc[0] * fwd.iloc[0]
    fr, br_ = fwd.pct_change().fillna(0), bt_eq.pct_change().fillna(0)
    n_fills = db.scalar(select(func.count(Fill.id)).where(Fill.bot_id == bot.id, Fill.account_id == bot.account_id))
    return {"ready": True, "forward": series_payload(fwd, 2), "backtest": series_payload(bt_eq, 2),
            "forward_metrics": M.summary(fr), "backtest_metrics": M.summary(br_),
            "tracking_error": M._f((fr - br_.reindex(fr.index).fillna(0)).std() * (252 ** 0.5)),
            "forward_fills": int(n_fills or 0), "backtest_fills": int(len(res.fills[res.fills["date"] >= start])) if len(res.fills) else 0,
            "note": "Differences come from whole-share sizing, fill prices (simulator slippage vs model costs), risk "
                    "resizing and the bot's own order timing. Explain every material gap."}


def bot_dict(db: Session, bot: Bot) -> dict:
    acct = db.get(Account, bot.account_id) if bot.account_id else None
    orders_today = 0
    if bot.account_id:
        orders_today = db.scalar(select(func.count(Order.id)).where(Order.bot_id == bot.id,
                                                                     Order.account_id == bot.account_id)) or 0
    eq = None
    if acct:
        br = BRK.SimBroker(db, acct)
        try:
            eq = br.equity()
        except Exception:
            eq = None
    return {"id": bot.id, "name": bot.name, "strategy_key": bot.strategy_key, "params": bot.params, "symbols": bot.symbols,
            "timeframe": bot.timeframe, "schedule": bot.schedule, "broker": bot.broker, "data_mode": bot.data_mode,
            "sizing": bot.sizing, "risk": {**DEFAULT_RISK, **(bot.risk or {})}, "status": bot.status,
            "kill_switch": bot.kill_switch, "account_id": bot.account_id, "replay_start": bot.replay_start,
            "cursor": bot.cursor, "cycles": bot.cycles, "extended_hours": bot.extended_hours,
            "last_run_at": bot.last_run_at.isoformat() if bot.last_run_at else None, "last_result": bot.last_result,
            "last_error": bot.last_error, "equity": eq, "starting_cash": acct.starting_cash if acct else None,
            "orders": orders_today, "backtest_id": bot.backtest_id,
            "created_at": bot.created_at.isoformat() if bot.created_at else None}
