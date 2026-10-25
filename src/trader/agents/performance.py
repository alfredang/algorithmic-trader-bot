"""Performance of the agents' own paper trading (Performance Analysis agent) - computed in code, never by a model.

Inputs: the agent account's equity snapshots (one after every Stock Trader step and every performance step),
its fills and its orders. Metrics reuse :mod:`trader.core.metrics`:
  total return     = equity now / starting equity - 1
  daily returns    = last equity per day, percentage change (the starting equity is day 0)
  Sharpe           = mean(daily r) / stdev(daily r) x sqrt(252)          (needs 2+ daily returns)
  max drawdown     = min(equity / running peak - 1) over every snapshot
  win rate         = closed round trips with a profit / all closed round trips (FIFO-free average-price matching)
  trades           = filled orders;  exposure = share of snapshots holding a position
The latest result is persisted in Setting ``agent_performance`` for the dashboard.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.core import metrics as M
from trader.models import Account, Fill, Order, PnLSnapshot, Position, Setting, utcnow
from trader.services.events import jsonable

SETTING = "agent_performance"


def round_trips(fills: list[Fill]) -> list[dict]:
    """Average-price matching per symbol: every fill that reduces a position closes a (partial) round trip."""
    pos: dict[str, list[float]] = {}           # symbol -> [qty (signed), avg price]
    out = []
    for f in sorted(fills, key=lambda x: (x.ts, x.id)):
        q, avg = pos.get(f.symbol, [0.0, 0.0])
        signed = f.qty if f.side == "buy" else -f.qty
        if q == 0 or (q > 0) == (signed > 0):
            new = q + signed
            avg = (abs(q) * avg + f.qty * f.price) / abs(new) if new else 0.0
            pos[f.symbol] = [new, avg]
            continue
        closing = min(abs(signed), abs(q))
        direction = 1 if q > 0 else -1
        ret = direction * (f.price / avg - 1) if avg else 0.0
        out.append({"symbol": f.symbol, "side": "long" if q > 0 else "short", "qty": closing, "entry": round(avg, 4),
                    "exit": round(f.price, 4), "return": round(ret, 5), "pnl": round(direction * closing * (f.price - avg), 2),
                    "closed_at": f.ts.isoformat() if f.ts else None})
        new = q + signed
        pos[f.symbol] = [new, f.price if abs(new) > 1e-9 and (new > 0) != (q > 0) else (avg if abs(new) > 1e-9 else 0.0)]
    return out


def compute(db: Session, acct: Account, starting_equity: float | None = None) -> dict:
    snaps = list(db.scalars(select(PnLSnapshot).where(PnLSnapshot.account_id == acct.id, PnLSnapshot.bot_id.is_(None))
                            .order_by(PnLSnapshot.ts)))
    fills = list(db.scalars(select(Fill).where(Fill.account_id == acct.id)))
    orders = list(db.scalars(select(Order).where(Order.account_id == acct.id, Order.source == "agent",
                                                Order.parent_id.is_(None)).order_by(Order.submitted_at.desc())))
    positions = list(db.scalars(select(Position).where(Position.account_id == acct.id, Position.qty != 0)))
    base = float(starting_equity or acct.starting_cash or 100_000.0)
    t0 = pd.Timestamp(acct.created_at or (snaps[0].ts if snaps else utcnow()))
    eq = pd.Series([base] + [s.equity for s in snaps], index=pd.DatetimeIndex([t0] + [pd.Timestamp(s.ts) for s in snaps]))
    eq = eq[~eq.index.duplicated(keep="last")].sort_index()
    daily = eq.groupby(eq.index.normalize()).last()
    dret = daily.pct_change().dropna()
    trips = round_trips(fills)
    tr = pd.Series([t["return"] for t in trips], dtype=float)
    last = float(eq.iloc[-1])
    gross = sum(abs(p.qty * (p.last_price or p.avg_entry_price)) for p in positions)
    in_market = [s.positions_value != 0 for s in snaps]
    out = {
        "account": acct.name, "broker": acct.broker, "as_of": utcnow().isoformat(timespec="seconds"),
        "starting_equity": round(base, 2), "equity": round(last, 2), "cash": round(float(acct.cash), 2),
        "total_return": last / base - 1 if base else None,
        "daily_return_last": float(dret.iloc[-1]) if len(dret) else None,
        "days": int(len(daily)),
        "sharpe": M.sharpe_ratio(dret) if len(dret) >= 2 else None,
        "volatility": M.annual_volatility(dret) if len(dret) >= 2 else None,
        "max_drawdown": float((eq / eq.cummax() - 1).min()) if len(eq) else None,
        "win_rate": M.win_rate(tr) if len(tr) else None,
        "profit_factor": M.profit_factor(tr) if len(tr) else None,
        "round_trips": len(trips),
        "trades": sum(1 for f in fills),
        "orders": len(orders),
        "orders_rejected": sum(1 for o in orders if o.status == "rejected"),
        "open_positions": len(positions),
        "exposure": (sum(in_market) / len(in_market)) if in_market else 0.0,
        "gross_exposure": gross / last if last else None,
        "realized_pnl": round(sum(t["pnl"] for t in trips), 2),
        "unrealized_pnl": round(sum(p.qty * ((p.last_price or p.avg_entry_price) - p.avg_entry_price) for p in positions), 2),
        "positions": [{"symbol": p.symbol, "qty": p.qty, "avg_entry_price": round(p.avg_entry_price, 4),
                       "last_price": round(p.last_price or p.avg_entry_price, 4)} for p in positions],
        "daily_returns": [[str(d.date()), round(float(r), 6)] for d, r in dret.tail(60).items()],
        "equity_curve": [[t.isoformat(timespec="seconds"), round(float(v), 2)] for t, v in eq.tail(300).items()],
        "recent_round_trips": trips[-10:],
    }
    return jsonable(out)


def persist(db: Session, metrics: dict, run_id: int | None = None) -> None:
    s = db.get(Setting, SETTING) or Setting(key=SETTING)
    s.value = {**metrics, "run_id": run_id}
    db.add(s)
    db.flush()


def latest(db: Session) -> dict | None:
    s = db.get(Setting, SETTING)
    return s.value if s and s.value else None


def recent_orders(db: Session, acct: Account, limit: int = 10) -> list[dict]:
    rows = db.scalars(select(Order).where(Order.account_id == acct.id, Order.source == "agent", Order.parent_id.is_(None))
                      .order_by(Order.submitted_at.desc()).limit(limit))
    return [{"symbol": o.symbol, "side": o.side, "qty": o.qty, "type": o.type, "status": o.status,
             "filled_avg_price": o.filled_avg_price, "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
             "note": (o.note or "")[:160]} for o in rows]
