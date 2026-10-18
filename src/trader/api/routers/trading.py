"""Paper trading: bots, orders, positions, accounts, P&L, kill switch and the market clock."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.api.schemas import BotRequest, OrderTicket
from trader.bots import runner
from trader.broker import clock as CLK
from trader.broker import service as BRK
from trader.config import get_settings
from trader.db import get_db
from trader.models import Account, Bot, Fill, Order, PnLSnapshot, Position
from trader.scheduler import validate_schedule
from trader.services.events import audit, emit, stage
from trader.strategies import registry

router = APIRouter(prefix="/api", tags=["paper trading"])


def _bot(db, bid) -> Bot:
    b = db.get(Bot, bid)
    if not b:
        raise HTTPException(404, "bot not found")
    return b


@router.get("/clock")
def clock(account: str | None = None, db: Session = Depends(get_db)):
    if get_settings().alpaca_configured:
        try:
            br = BRK.AlpacaPaperBroker(db, BRK.get_account(db, "Alpaca paper account", broker="alpaca_paper"))
            st = br.session()
            return {**st, "source": "Alpaca clock", "describe": CLK.describe(st)}
        except Exception:
            pass
    st = CLK.status()
    return {**st, "source": "local clock (US/Eastern session rules)", "describe": CLK.describe(st)}


# --------------------------------------------------------------------------- bots
@router.get("/bots")
def bots(db: Session = Depends(get_db)):
    return [runner.bot_dict(db, b) for b in db.scalars(select(Bot).order_by(Bot.id))]


@router.post("/bots")
def create_bot(req: BotRequest, db: Session = Depends(get_db)):
    try:
        desc = registry.get(db, req.strategy_key)
        params = registry.coerce_params(desc, req.params)
        validate_schedule(req.schedule)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    if desc["kind"] in ("execution", "market_making"):
        raise HTTPException(400, "execution and market-making strategies are simulations, not bot strategies")
    if req.broker == "alpaca_paper" and not get_settings().alpaca_configured:
        raise HTTPException(400, "Alpaca paper keys are not configured - use the simulator broker or add keys to .env")
    b = Bot(name=req.name, strategy_key=req.strategy_key, params=params, symbols=[s.upper() for s in req.symbols],
            timeframe=req.timeframe, schedule=req.schedule, broker=req.broker,
            data_mode="live" if req.broker == "alpaca_paper" else req.data_mode, replay_start=req.replay_start,
            sizing=req.sizing, risk=req.risk, extended_hours=req.extended_hours, status="stopped")
    db.add(b)
    db.flush()
    runner.ensure_account(db, b)
    audit("bot.created", "bot", b.id, req.model_dump(), actor="user", db=db)
    db.commit()
    return runner.bot_dict(db, b)


@router.get("/bots/{bid}")
def get_bot(bid: int, db: Session = Depends(get_db)):
    return runner.bot_dict(db, _bot(db, bid))


@router.put("/bots/{bid}")
def update_bot(bid: int, body: dict = Body(...), db: Session = Depends(get_db)):
    b = _bot(db, bid)
    for k in ("name", "schedule", "risk", "sizing", "params", "extended_hours", "replay_start"):
        if k in body:
            if k == "schedule":
                validate_schedule(body[k])
            setattr(b, k, body[k])
    audit("bot.updated", "bot", b.id, body, actor="user", db=db)
    db.commit()
    return runner.bot_dict(db, b)


@router.post("/bots/{bid}/{action}")
def bot_action(bid: int, action: str, db: Session = Depends(get_db)):
    b = _bot(db, bid)
    if action == "start":
        if b.kill_switch:
            raise HTTPException(409, "bot kill switch is ON - release it first")
        b.status = "running"
        stage("forward", "ok", f"Bot '{b.name}' started ({b.schedule})", {"bot_id": b.id}, ref_type="bot", ref_id=b.id, db=db)
    elif action == "stop":
        b.status = "stopped"
    elif action == "run-now":
        res = runner.run_cycle(db, b)
        db.commit()
        return {"bot": runner.bot_dict(db, b), "result": res}
    elif action == "kill":
        b.kill_switch, b.status = True, "halted"
        acct = runner.ensure_account(db, b)
        n = BRK.broker_for(db, acct).cancel_all() if acct.broker == "sim" else 0
        stage("risk", "error", f"Bot '{b.name}' KILL SWITCH ON ({n} open orders cancelled)", {"bot_id": b.id}, db=db)
    elif action == "release":
        b.kill_switch, b.status = False, "stopped"
    elif action == "reset":
        runner.reset(db, b)
    elif action == "flatten":
        acct = runner.ensure_account(db, b)
        br = BRK.broker_for(db, acct)
        out = []
        for p in br.positions():
            r = BRK.place_order(db, acct, BRK.OrderRequest(symbol=p.symbol, side="sell" if p.qty > 0 else "buy",
                                                           qty=abs(p.qty), note="flatten"), source="bot", bot_id=b.id,
                                broker=br, limits={"long_only": False})
            out.append(r["ok"])
        db.commit()
        return {"bot": runner.bot_dict(db, b), "orders": out}
    else:
        raise HTTPException(400, f"unknown action {action}")
    audit(f"bot.{action}", "bot", b.id, {}, actor="user", db=db)
    emit("bot.status", {"bot_id": b.id, "status": b.status, "kill_switch": b.kill_switch}, db=db)
    db.commit()
    return runner.bot_dict(db, b)


@router.delete("/bots/{bid}")
def delete_bot(bid: int, db: Session = Depends(get_db)):
    b = _bot(db, bid)
    b.status = "stopped"
    db.delete(b)
    audit("bot.deleted", "bot", bid, {}, actor="user", db=db)
    db.commit()
    return {"deleted": bid}


@router.get("/bots/{bid}/equity")
def bot_equity(bid: int, db: Session = Depends(get_db)):
    return runner.equity_series(db, _bot(db, bid))


@router.get("/bots/{bid}/compare")
def bot_compare(bid: int, db: Session = Depends(get_db)):
    return runner.compare(db, _bot(db, bid))


# --------------------------------------------------------------------------- orders / positions
@router.get("/accounts")
def accounts(db: Session = Depends(get_db)):
    out = []
    for a in db.scalars(select(Account).order_by(Account.id)):
        try:
            eq = BRK.SimBroker(db, a).equity()
        except Exception:
            eq = None
        out.append({"id": a.id, "name": a.name, "broker": a.broker, "cash": a.cash, "equity": eq,
                    "starting_cash": a.starting_cash, "last_equity": a.last_equity,
                    "sim_clock": a.sim_clock.isoformat() if a.sim_clock else None})
    return out


@router.get("/orders")
def orders(status: str | None = None, bot_id: int | None = None, account_id: int | None = None, source: str | None = None,
           limit: int = 200, db: Session = Depends(get_db)):
    q = select(Order).order_by(Order.submitted_at.desc()).limit(limit)
    if status == "open":
        q = q.where(Order.status.in_(BRK.OPEN_STATES))
    elif status:
        q = q.where(Order.status == status)
    if bot_id is not None:
        q = q.where(Order.bot_id == bot_id)
    if account_id is not None:
        q = q.where(Order.account_id == account_id)
    if source:
        q = q.where(Order.source == source)
    return [BRK.order_dict(o) for o in db.scalars(q)]


@router.post("/orders")
def place(t: OrderTicket, db: Session = Depends(get_db)):
    broker = "alpaca_paper" if t.account == "Alpaca paper account" else "sim"
    if broker == "alpaca_paper" and not get_settings().alpaca_configured:
        raise HTTPException(400, "Alpaca paper keys are not configured")
    acct = BRK.get_account(db, t.account, broker=broker)
    req = BRK.OrderRequest(symbol=t.symbol, side=t.side.lower(), qty=t.qty, type=t.type, time_in_force=t.time_in_force,
                           limit_price=t.limit_price, stop_price=t.stop_price, take_profit=t.take_profit,
                           stop_loss=t.stop_loss, extended_hours=t.extended_hours, order_class=t.order_class,
                           client_order_id=t.client_order_id, note="manual ticket")
    try:
        r = BRK.place_order(db, acct, req, source="manual", limits={"long_only": True},
                            session_override=t.session_override if broker == "sim" else None)
    except BRK.BrokerError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return r


@router.post("/orders/{oid}/cancel")
def cancel(oid: str, db: Session = Depends(get_db)):
    o = db.get(Order, oid)
    if not o:
        raise HTTPException(404, "order not found")
    acct = db.get(Account, o.account_id)
    try:
        BRK.broker_for(db, acct).cancel(o)
    except BRK.BrokerError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return BRK.order_dict(o)


@router.post("/orders/process")
def process_open(session_override: str | None = None, db: Session = Depends(get_db)):
    """Simulator: try to fill working orders at the latest price (what the worker does every minute)."""
    from trader.scheduler import process_sim_orders
    n = process_sim_orders(db, session_override)
    db.commit()
    return {"filled": n}


@router.get("/positions")
def positions(account_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Position).where(Position.qty != 0)
    if account_id is not None:
        q = q.where(Position.account_id == account_id)
    return [BRK.position_dict(p) for p in db.scalars(q)]


@router.get("/fills")
def fills(account_id: int | None = None, bot_id: int | None = None, limit: int = 200, db: Session = Depends(get_db)):
    q = select(Fill).order_by(Fill.id.desc()).limit(limit)
    if account_id is not None:
        q = q.where(Fill.account_id == account_id)
    if bot_id is not None:
        q = q.where(Fill.bot_id == bot_id)
    return [{"id": f.id, "order_id": f.order_id, "account_id": f.account_id, "bot_id": f.bot_id, "symbol": f.symbol,
             "side": f.side, "qty": f.qty, "price": f.price, "costs": f.costs, "realized_pnl": f.realized_pnl,
             "ts": f.ts.isoformat()} for f in db.scalars(q)]


@router.get("/pnl")
def pnl(account_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(select(PnLSnapshot).where(PnLSnapshot.account_id == account_id).order_by(PnLSnapshot.id))
    return [{"t": r.bar_time or r.ts.isoformat(), "equity": r.equity, "cash": r.cash, "realized": r.realized,
             "unrealized": r.unrealized} for r in rows]


@router.get("/kill-switch")
def kill_status(db: Session = Depends(get_db)):
    return {"on": BRK.kill_switch_on(db)}


@router.post("/kill-switch")
def kill(body: dict = Body(..., examples=[{"on": True}]), db: Session = Depends(get_db)):
    on = bool(body.get("on"))
    BRK.set_kill_switch(db, on)
    if on:
        for a in db.scalars(select(Account).where(Account.broker == "sim")):
            BRK.SimBroker(db, a).cancel_all()
    db.commit()
    return {"on": on}
