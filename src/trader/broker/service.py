"""Paper brokers and the order manager. PAPER TRADING ONLY - there is no live-money order path.

* SimBroker     - a database-backed simulator (cash account, optional shorting) that mimics
                  Alpaca order semantics: market / limit / stop / bracket (OCO exit legs),
                  extended-hours limit orders, GTC orders queued while the market is closed.
* AlpacaPaperBroker - alpaca-py ``TradingClient(paper=True)``. ``paper=True`` is hard-coded and
                  the class refuses any other base URL. Orders are mirrored in the local DB.

:func:`place_order` is the single entry point used by the manual ticket, bots, the TradingView
webhook and the AI agents: session-aware order styling -> idempotency -> pre-trade risk -> submit.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from trader.broker import clock as CLK
from trader.broker import risk as RISK
from trader.config import get_settings
from trader.core.costs import FINRA_TAF, SEC_FEE
from trader.models import Account, Bar, Fill, Order, PnLSnapshot, Position, Setting, utcnow
from trader.services.events import audit, emit, stage

OPEN_STATES = {"new", "accepted", "pending_new", "partially_filled", "held"}
TERMINAL = {"filled", "canceled", "expired", "rejected"}


class BrokerError(Exception):
    pass


@dataclass
class OrderRequest:
    symbol: str
    side: str                                   # buy | sell
    qty: float
    type: str = "auto"                          # auto | market | limit | stop | stop_limit
    time_in_force: str = "day"
    limit_price: float | None = None
    stop_price: float | None = None
    take_profit: float | None = None            # bracket: take-profit limit price
    stop_loss: float | None = None              # bracket: stop price
    extended_hours: bool = False
    client_order_id: str | None = None
    order_class: str = "simple"                 # simple | bracket
    note: str = ""
    meta: dict = field(default_factory=dict)


def client_id(tag: str, symbol: str, side: str, qty: float) -> str:
    """Deterministic client_order_id: re-running the same decision finds the order instead of duplicating it."""
    return re.sub(r"[^A-Za-z0-9-]", "", f"qts-{tag}-{symbol}-{side}-{qty:g}")[:48]


def kill_switch_on(db: Session) -> bool:
    s = db.get(Setting, "kill_switch")
    return bool(s and s.value)


def set_kill_switch(db: Session, on: bool, actor: str = "user") -> None:
    s = db.get(Setting, "kill_switch") or Setting(key="kill_switch")
    s.value = bool(on)
    db.add(s)
    audit("kill_switch", "system", "global", {"on": on}, actor=actor, db=db)
    emit("kill_switch", {"on": on}, db=db)
    stage("risk", "error" if on else "ok", "GLOBAL KILL SWITCH ON - all trading halted" if on else "Kill switch off", db=db)


def latest_price(db: Session, symbol: str) -> float:
    px = db.scalar(select(Bar.close).where(Bar.symbol == symbol).order_by(Bar.ts.desc()).limit(1))
    if px:
        return float(px)
    from trader.data import service as data
    df = data.load_bars(db, symbol, "1Day")
    if df.empty:
        raise BrokerError(f"no price for {symbol}")
    return float(df["close"].iloc[-1])


def quote(db: Session, symbol: str, broker: str = "sim") -> dict:
    if broker == "alpaca_paper" and get_settings().alpaca_configured:
        try:
            from trader.data.providers import PROVIDERS
            return PROVIDERS["alpaca"].latest_quote(symbol)
        except Exception:
            pass
    last = latest_price(db, symbol)
    return {"bid": last * (1 - 0.5e-4), "ask": last * (1 + 0.5e-4), "last": last, "source": "simulator last price"}


def style(req: OrderRequest, session: str, q: dict, buffer_bps: float = 25.0) -> OrderRequest:
    """Pick the order style for the session (regular: market; extended: limit DAY extended_hours; closed: GTC limit)."""
    r = OrderRequest(**{**asdict(req), "meta": dict(req.meta)})
    buf = buffer_bps / 1e4
    if r.type == "auto":
        if session == "regular":
            r.type = "market"
        else:
            r.type = "limit"
            r.limit_price = round(q["ask"] * (1 + buf) if r.side == "buy" else q["bid"] * (1 - buf), 2)
            if session == "closed":
                r.time_in_force, r.extended_hours = "gtc", False
            else:
                r.time_in_force, r.extended_hours = "day", True
    if session not in ("regular", "closed") and r.type == "limit" and r.meta.get("auto_extended", True):
        r.extended_hours = True
    if session != "regular" and r.order_class == "bracket":
        r.order_class = "simple"                 # brackets are regular-session only
        r.note = (r.note + " | bracket dropped outside the regular session").strip(" |")
    if r.type == "limit" and r.limit_price is None:
        r.limit_price = round(q["ask"] * (1 + buf) if r.side == "buy" else q["bid"] * (1 - buf), 2)
    return r


# =========================================================================== simulator
class SimBroker:
    mode = "sim"

    def __init__(self, db: Session, account: Account, slippage_bps: float = 1.0):
        self.db, self.acct, self.slip = db, account, slippage_bps / 1e4
        self.marks: dict[str, float] = {}

    def now(self) -> datetime:
        return self.acct.sim_clock or utcnow()

    def session(self, override: str | None = None) -> dict:
        if self.acct.sim_clock is not None:
            return CLK.status(self.acct.sim_clock, override)
        return CLK.status(None, override)

    # ---- positions and prices
    def position(self, symbol: str) -> Position | None:
        return self.db.scalar(select(Position).where(Position.account_id == self.acct.id, Position.symbol == symbol))

    def positions(self) -> list[Position]:
        return list(self.db.scalars(select(Position).where(Position.account_id == self.acct.id, Position.qty != 0)))

    def price(self, symbol: str) -> float:
        if symbol in self.marks:
            return self.marks[symbol]
        p = self.position(symbol)
        return float(p.last_price) if p and p.last_price else latest_price(self.db, symbol)

    def equity(self) -> float:
        return float(self.acct.cash + sum(p.qty * (p.last_price or p.avg_entry_price) for p in self.positions()))

    def mark(self, symbol: str, price: float) -> None:
        self.marks[symbol] = float(price)
        p = self.position(symbol)
        if p is not None:
            p.last_price = float(price)

    # ---- orders
    def submit(self, req: OrderRequest, session: str, source: str, bot_id: int | None) -> Order:
        o = Order(client_order_id=req.client_order_id, account_id=self.acct.id, bot_id=bot_id, symbol=req.symbol,
                  side=req.side, qty=float(req.qty), type=req.type, time_in_force=req.time_in_force,
                  order_class=req.order_class, limit_price=req.limit_price, stop_price=req.stop_price,
                  take_profit=req.take_profit, stop_loss=req.stop_loss, extended_hours=req.extended_hours,
                  status="new" if session != "closed" else "accepted", broker="sim", source=source, session=session,
                  note=req.note, history=[{"status": "new", "ts": str(self.now())}])
        if session == "closed":
            o.history.append({"status": "accepted", "ts": str(self.now()), "note": "queued until the next session"})
        self.db.add(o)
        self.db.flush()
        if o.order_class == "bracket":
            ex = "sell" if o.side == "buy" else "buy"
            for typ, lp, sp in (("limit", o.take_profit, None), ("stop", None, o.stop_loss)):
                if lp is None and sp is None:
                    continue
                self.db.add(Order(client_order_id=f"{o.client_order_id}-{typ[:2]}", account_id=o.account_id, bot_id=bot_id,
                                  parent_id=o.id, symbol=o.symbol, side=ex, qty=o.qty, type=typ, time_in_force="gtc",
                                  order_class="bracket", limit_price=lp, stop_price=sp, status="held", broker="sim",
                                  source=source, session=session, history=[{"status": "held", "ts": str(self.now())}]))
            self.db.flush()
        if session != "closed":
            px = self.price(o.symbol)
            self.match(o.symbol, px, px, px, px, only=[o], session=session)
        return o

    def open_orders(self, symbol: str | None = None) -> list[Order]:
        q = select(Order).where(Order.account_id == self.acct.id, Order.status.in_(OPEN_STATES - {"held"}))
        if symbol:
            q = q.where(Order.symbol == symbol)
        return list(self.db.scalars(q.order_by(Order.submitted_at)))

    def match(self, symbol: str, open_: float, high: float, low: float, close: float, only: list[Order] | None = None,
              session: str | None = None) -> list[Fill]:
        """Fill open orders for ``symbol`` that this bar / price would trigger."""
        fills = []
        sess = session or self.session()["session"]
        for o in (only if only is not None else self.open_orders(symbol)):
            if o.status not in OPEN_STATES or o.status == "held":
                continue
            if sess == "closed":
                continue
            if sess != "regular" and not (o.type == "limit" and o.extended_hours):
                continue                          # regular-session-only orders wait for the open
            buy, px = o.side == "buy", None
            if o.type == "market":
                px = open_ * (1 + self.slip if buy else 1 - self.slip)
            elif o.type == "limit":
                if buy and low <= o.limit_price:
                    px = min(open_, o.limit_price)
                elif not buy and high >= o.limit_price:
                    px = max(open_, o.limit_price)
            elif o.type in ("stop", "stop_limit"):
                if buy and high >= o.stop_price:
                    px = max(open_, o.stop_price) * (1 + self.slip)
                elif not buy and low <= o.stop_price:
                    px = min(open_, o.stop_price) * (1 - self.slip)
            if px is not None:
                f = self._fill(o, px)
                if f:
                    fills.append(f)
        self.mark(symbol, close)
        return fills

    def _fill(self, o: Order, px: float) -> Fill | None:
        qty = o.qty
        pos = self.position(o.symbol)
        if pos is None:
            pos = Position(account_id=self.acct.id, symbol=o.symbol, qty=0.0, avg_entry_price=0.0, last_price=px)
            self.db.add(pos)
            self.db.flush()
        notional = qty * px
        costs = 0.0
        if o.side == "sell":
            costs = notional * SEC_FEE + min(qty * FINRA_TAF, 8.30)
        if o.side == "buy" and notional + costs > self.acct.cash + 1e-6 and pos.qty >= 0:
            self._status(o, "rejected", "insufficient buying power")
            return None
        realized = 0.0
        signed = qty if o.side == "buy" else -qty
        old = pos.qty
        if old == 0 or (old > 0) == (signed > 0):          # open / add
            new = old + signed
            pos.avg_entry_price = (abs(old) * pos.avg_entry_price + qty * px) / abs(new)
            pos.qty = new
        else:                                               # reduce / close / flip
            closing = min(abs(signed), abs(old))
            realized = closing * (px - pos.avg_entry_price) * (1 if old > 0 else -1)
            new = old + signed
            if abs(new) > 1e-9 and (new > 0) != (old > 0):
                pos.avg_entry_price = px
            elif abs(new) <= 1e-9:
                pos.avg_entry_price = 0.0
            pos.qty = 0.0 if abs(new) <= 1e-9 else new
        realized -= costs
        pos.realized_pnl = (pos.realized_pnl or 0.0) + realized
        pos.last_price = px
        self.acct.cash += -signed * px - costs
        o.filled_qty, o.filled_avg_price, o.filled_at = qty, round(px, 4), self.now()
        self._status(o, "filled")
        f = Fill(order_id=o.id, account_id=self.acct.id, bot_id=o.bot_id, symbol=o.symbol, side=o.side, qty=qty,
                 price=round(px, 4), costs=costs, realized_pnl=realized, ts=self.now())
        self.db.add(f)
        # bracket legs: parent filled -> exits live; a leg filled -> cancel its sibling (OCO)
        legs = self.db.scalars(select(Order).where(Order.parent_id == (o.parent_id or o.id), Order.id != o.id))
        for leg in legs:
            if o.parent_id is None and leg.status == "held":
                self._status(leg, "new")
            elif o.parent_id is not None and leg.status in OPEN_STATES:
                self._status(leg, "canceled", "one-cancels-other")
        self.db.flush()
        emit("order.filled", {"id": o.id, "symbol": o.symbol, "side": o.side, "qty": qty, "price": round(px, 4),
                              "bot_id": o.bot_id, "source": o.source}, db=self.db)
        return f

    def _status(self, o: Order, status: str, note: str = "") -> None:
        o.status = status
        o.history = [*(o.history or []), {"status": status, "ts": str(self.now()), **({"note": note} if note else {})}]
        if note:
            o.note = (o.note + " | " + note).strip(" |")
        emit("order.status", {"id": o.id, "symbol": o.symbol, "status": status, "bot_id": o.bot_id}, db=self.db)

    def cancel(self, o: Order) -> Order:
        if o.status not in OPEN_STATES:
            raise BrokerError(f"order is not cancelable (status {o.status})")
        self._status(o, "canceled", "cancelled by user")
        for leg in self.db.scalars(select(Order).where(Order.parent_id == o.id)):
            if leg.status in OPEN_STATES:
                self._status(leg, "canceled")
        return o

    def cancel_all(self) -> int:
        n = 0
        for o in self.db.scalars(select(Order).where(Order.account_id == self.acct.id, Order.status.in_(OPEN_STATES))):
            self._status(o, "canceled", "cancel all")
            n += 1
        return n

    def snapshot(self, bot_id: int | None = None, bar_time: str | None = None) -> PnLSnapshot:
        pos = self.positions()
        pv = sum(p.qty * (p.last_price or p.avg_entry_price) for p in pos)
        unreal = sum(p.qty * ((p.last_price or p.avg_entry_price) - p.avg_entry_price) for p in pos)
        realized = float(sum(p.realized_pnl or 0 for p in self.db.scalars(
            select(Position).where(Position.account_id == self.acct.id))))
        snap = PnLSnapshot(account_id=self.acct.id, bot_id=bot_id, ts=utcnow(), bar_time=bar_time, equity=self.acct.cash + pv,
                           cash=self.acct.cash, positions_value=pv, realized=realized, unrealized=unreal)
        self.db.add(snap)
        self.db.flush()
        return snap

    def end_of_day(self) -> None:
        self.acct.last_equity = self.equity()


# =========================================================================== Alpaca paper
class AlpacaPaperBroker(SimBroker):
    """Alpaca PAPER account. ``paper=True`` is hard-coded: this class can never reach a live account."""
    mode = "alpaca_paper"

    def __init__(self, db: Session, account: Account):
        super().__init__(db, account)
        s = get_settings()
        if not s.alpaca_configured:
            raise BrokerError("Alpaca paper keys are not configured (APCA_API_KEY_ID / APCA_API_SECRET_KEY)")
        from alpaca.trading.client import TradingClient
        self.client = TradingClient(api_key=s.alpaca_key_id, secret_key=s.alpaca_secret_key, paper=True)   # PAPER ONLY
        base = str(getattr(self.client, "_base_url", "paper"))
        if "paper" not in base:
            raise BrokerError("refusing a non-paper Alpaca endpoint")

    def session(self, override: str | None = None) -> dict:
        try:
            clk = self.client.get_clock()
            return CLK.status(clk.timestamp, override, alpaca_clock=clk)
        except Exception:
            return CLK.status(None, override)

    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def account_info(self) -> dict:
        a = self.client.get_account()
        return {"equity": float(a.equity), "cash": float(a.cash), "buying_power": float(a.buying_power),
                "last_equity": float(a.last_equity), "status": str(getattr(a.status, "value", a.status)),
                "pattern_day_trader": bool(a.pattern_day_trader), "trading_blocked": bool(a.trading_blocked)}

    def submit(self, req: OrderRequest, session: str, source: str, bot_id: int | None) -> Order:
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            LimitOrderRequest,
            MarketOrderRequest,
            StopLossRequest,
            StopOrderRequest,
            TakeProfitRequest,
        )
        side = OrderSide.BUY if req.side == "buy" else OrderSide.SELL
        tif = TimeInForce.GTC if req.time_in_force == "gtc" else TimeInForce.DAY
        common = {"symbol": req.symbol, "qty": req.qty, "side": side, "time_in_force": tif,
                  "client_order_id": req.client_order_id}
        if req.order_class == "bracket":
            common.update(order_class=OrderClass.BRACKET, take_profit=TakeProfitRequest(limit_price=round(req.take_profit, 2)),
                          stop_loss=StopLossRequest(stop_price=round(req.stop_loss, 2)))
        if req.type == "market":
            ar = MarketOrderRequest(**common)
        elif req.type == "limit":
            ar = LimitOrderRequest(**common, limit_price=round(req.limit_price, 2), extended_hours=req.extended_hours)
        elif req.type == "stop":
            ar = StopOrderRequest(**common, stop_price=round(req.stop_price, 2))
        else:
            raise BrokerError(f"unsupported order type {req.type}")
        o = Order(client_order_id=req.client_order_id, account_id=self.acct.id, bot_id=bot_id, symbol=req.symbol,
                  side=req.side, qty=float(req.qty), type=req.type, time_in_force=req.time_in_force,
                  order_class=req.order_class, limit_price=req.limit_price, stop_price=req.stop_price,
                  take_profit=req.take_profit, stop_loss=req.stop_loss, extended_hours=req.extended_hours,
                  broker="alpaca_paper", source=source, session=session, note=req.note, history=[])
        try:
            ao = self.client.submit_order(ar)
        except Exception as exc:
            o.status = "rejected"
            o.note = f"Alpaca rejected: {str(exc)[:300]}"
            o.history = [{"status": "rejected", "ts": str(utcnow()), "note": o.note}]
            self.db.add(o)
            self.db.flush()
            return o
        self._apply(o, ao)
        self.db.add(o)
        self.db.flush()
        return o

    def _apply(self, o: Order, ao) -> None:
        st = str(getattr(ao.status, "value", ao.status))
        o.broker_order_id = str(ao.id)
        if st != o.status:
            o.history = [*(o.history or []), {"status": st, "ts": str(utcnow())}]
        o.status = st
        o.filled_qty = float(ao.filled_qty or 0)
        o.filled_avg_price = float(ao.filled_avg_price) if ao.filled_avg_price else None
        o.filled_at = ao.filled_at.replace(tzinfo=None) if getattr(ao, "filled_at", None) else None

    def sync(self) -> dict:
        """Refresh open orders and positions from the Alpaca paper account into the local mirror."""
        n = 0
        for o in self.db.scalars(select(Order).where(Order.account_id == self.acct.id, Order.broker == "alpaca_paper",
                                                     Order.status.in_(OPEN_STATES))):
            try:
                ao = self.client.get_order_by_id(o.broker_order_id)
                before = o.status
                self._apply(o, ao)
                if o.status == "filled" and before != "filled":
                    self.db.add(Fill(order_id=o.id, account_id=o.account_id, bot_id=o.bot_id, symbol=o.symbol, side=o.side,
                                     qty=o.filled_qty, price=o.filled_avg_price or 0.0, ts=utcnow()))
                    emit("order.filled", {"id": o.id, "symbol": o.symbol, "side": o.side, "qty": o.filled_qty,
                                          "price": o.filled_avg_price, "bot_id": o.bot_id}, db=self.db)
                n += 1
            except Exception:
                continue
        held = {p.symbol: p for p in self.client.get_all_positions()}
        for p in self.db.scalars(select(Position).where(Position.account_id == self.acct.id)):
            if p.symbol not in held:
                p.qty = 0.0
        for sym, ap in held.items():
            p = self.position(sym) or Position(account_id=self.acct.id, symbol=sym)
            p.qty, p.avg_entry_price, p.last_price = float(ap.qty), float(ap.avg_entry_price), float(ap.current_price or 0)
            self.db.add(p)
        a = self.client.get_account()
        self.acct.cash, self.acct.last_equity = float(a.cash), float(a.last_equity)
        self.db.flush()
        return {"orders_synced": n, "positions": len(held)}

    def cancel(self, o: Order) -> Order:
        self.client.cancel_order_by_id(o.broker_order_id)
        self._status(o, "canceled", "cancel requested")
        return o

    def match(self, *a, **k):                     # fills come from Alpaca, not from local matching
        return []


# =========================================================================== accounts and the entry point
def get_account(db: Session, name: str = "Default paper account", broker: str = "sim", create: bool = True) -> Account:
    acct = db.scalar(select(Account).where(Account.name == name))
    if acct is None and create:
        acct = Account(name=name, broker=broker, cash=100_000.0, starting_cash=100_000.0, last_equity=100_000.0)
        db.add(acct)
        db.flush()
    return acct


def broker_for(db: Session, account: Account) -> SimBroker:
    if account.broker == "alpaca_paper":
        return AlpacaPaperBroker(db, account)
    return SimBroker(db, account)


def place_order(db: Session, account: Account, req: OrderRequest, source: str = "manual", bot_id: int | None = None,
                limits: dict | None = None, bot_kill: bool = False, session_override: str | None = None,
                buffer_bps: float = 25.0, broker: SimBroker | None = None) -> dict:
    """Style -> idempotency -> risk -> submit. Returns {ok, order, risk, session}."""
    br = broker or broker_for(db, account)
    st = br.session(session_override)
    req.symbol = req.symbol.upper().strip()
    if account.broker == "alpaca_paper":
        q = quote(db, req.symbol, account.broker)
    else:
        last = br.price(req.symbol)
        q = {"bid": last * (1 - 0.5e-4), "ask": last * (1 + 0.5e-4), "last": last, "source": "simulator last price"}
    styled = style(req, st["session"], q, buffer_bps)
    styled.client_order_id = styled.client_order_id or client_id(utcnow().strftime("%Y%m%d%H%M%S%f")[:17], req.symbol,
                                                                  req.side, req.qty)
    dup = db.scalar(select(Order).where(Order.client_order_id == styled.client_order_id))
    pos = br.position(req.symbol)
    pos_qty = float(pos.qty) if pos else 0.0
    px = styled.limit_price or q["last"]
    equity = br.equity()
    rr = RISK.check(symbol=req.symbol, side=req.side, qty=float(req.qty), price=px, order_type=styled.type,
                    extended_hours=styled.extended_hours, session=st["session"], equity=equity,
                    last_equity=account.last_equity or equity, position_qty=pos_qty, limits=limits or {},
                    kill_switch=kill_switch_on(db) or bot_kill, duplicate=dup is not None)
    run_id = req.meta.get("run_id")
    if not rr.ok:
        stage("risk", "warning", f"{source}: {req.side.upper()} {req.qty:g} {req.symbol} blocked - {rr.reason}",
              {"symbol": req.symbol, "reason": rr.reason}, run_id=run_id, db=db)
        audit("order.blocked", "order", styled.client_order_id, {"reason": rr.reason, "source": source, "req": asdict(styled)}, db=db)
        return {"ok": False, "order": _order_dict(dup) if dup else None, "risk": rr.to_dict(), "session": st,
                "duplicate": dup is not None}
    styled.qty = rr.qty
    stage("risk", "ok", f"{source}: {req.side.upper()} {rr.qty:g} {req.symbol} passed pre-trade checks",
          {"symbol": req.symbol}, run_id=run_id, db=db)
    o = br.submit(styled, st["session"], source, bot_id)
    audit("order.submitted", "order", o.id, {"source": source, "client_order_id": o.client_order_id, "status": o.status,
                                             "type": o.type, "session": st["session"]}, db=db)
    emit("order.new", _order_dict(o), db=db)
    stage("execution", "ok" if o.status != "rejected" else "error",
          f"{o.side.upper()} {o.qty:g} {o.symbol} {o.type.upper()} {o.time_in_force.upper()}"
          f"{' ext-hours' if o.extended_hours else ''} -> {o.status}", {"order_id": o.id, "status": o.status},
          ref_type="order", ref_id=o.id, run_id=run_id, db=db)
    return {"ok": o.status != "rejected", "order": _order_dict(o), "risk": rr.to_dict(), "session": st}


def _order_dict(o: Order | None) -> dict | None:
    if o is None:
        return None
    return {"id": o.id, "client_order_id": o.client_order_id, "account_id": o.account_id, "bot_id": o.bot_id,
            "parent_id": o.parent_id, "symbol": o.symbol, "side": o.side, "qty": o.qty, "type": o.type,
            "time_in_force": o.time_in_force, "order_class": o.order_class, "limit_price": o.limit_price,
            "stop_price": o.stop_price, "take_profit": o.take_profit, "stop_loss": o.stop_loss,
            "extended_hours": o.extended_hours, "status": o.status, "filled_qty": o.filled_qty,
            "filled_avg_price": o.filled_avg_price, "broker": o.broker, "source": o.source, "session": o.session,
            "note": o.note, "history": o.history,
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
            "filled_at": o.filled_at.isoformat() if o.filled_at else None}


order_dict = _order_dict


def position_dict(p: Position) -> dict:
    px = p.last_price or p.avg_entry_price
    mv = p.qty * px
    cost = p.qty * p.avg_entry_price
    return {"symbol": p.symbol, "account_id": p.account_id, "qty": p.qty, "avg_entry_price": p.avg_entry_price,
            "last_price": px, "market_value": mv, "cost_basis": cost, "unrealized_pl": mv - cost,
            "unrealized_plpc": (mv / cost - 1) if cost else 0.0, "realized_pnl": p.realized_pnl,
            "side": "long" if p.qty > 0 else "short" if p.qty < 0 else "flat"}
