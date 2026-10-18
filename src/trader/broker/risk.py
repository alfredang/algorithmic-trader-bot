"""Pre-trade risk checks and the kill switch (course Topic 4.1 / Lab 16).

Every automated order path (bots, webhook, agents, manual ticket) calls :func:`check`
before anything is sent. The risk layer is deterministic code - no model or AI agent can
loosen it:

  kill switch      global or per-bot -> nothing trades
  session          market closed -> only a queued GTC limit order (if allowed)
  order type       outside the regular session -> LIMIT + extended_hours only
  allow-list       only listed symbols may be bought (empty list = any)
  long only        no short sales unless explicitly allowed
  max order value  qty x price capped
  max order qty    shares per order capped (webhook alerts)
  max position     position value / equity capped
  max daily loss   equity down >= limit since the last close -> no new buys
  duplicates       client_order_id must be unique (idempotent re-runs)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

DEFAULT_LIMITS = {
    "max_position_pct": 0.95, "max_order_value": 100_000.0, "max_order_qty": 10_000.0, "max_daily_loss_pct": 0.02,
    "allowed_symbols": [], "long_only": True, "allow_extended_hours": True, "allow_queue_when_closed": True,
}


@dataclass
class RiskResult:
    ok: bool
    qty: float
    checks: list[dict] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def merge_limits(*layers: dict | None) -> dict:
    out = dict(DEFAULT_LIMITS)
    for lay in layers:
        if lay:
            out.update({k: v for k, v in lay.items() if v is not None})
    return out


def check(*, symbol: str, side: str, qty: float, price: float, order_type: str, extended_hours: bool,
          session: str, equity: float, last_equity: float, position_qty: float, limits: dict,
          kill_switch: bool = False, duplicate: bool = False, resize: bool = True) -> RiskResult:
    lim = merge_limits(limits)
    checks: list[dict] = []

    def add(name, ok, msg):
        checks.append({"check": name, "ok": bool(ok), "message": msg})
        return ok

    if not add("kill_switch", not kill_switch, "kill switch is ON - trading halted" if kill_switch else "off"):
        return RiskResult(False, 0.0, checks, "kill switch is ON")
    if not add("duplicate", not duplicate, "client_order_id already used - not sent again" if duplicate else "unique"):
        return RiskResult(False, 0.0, checks, "duplicate order (idempotent re-run)")
    if qty <= 0:
        add("qty", False, "quantity must be positive")
        return RiskResult(False, 0.0, checks, "quantity must be positive")
    buying = side == "buy"
    reducing = (side == "sell" and position_qty > 0) or (side == "buy" and position_qty < 0)
    # session / order type rules
    if session == "closed":
        ok = lim["allow_queue_when_closed"] and order_type == "limit"
        if not add("session", ok, "market closed - GTC limit order will queue for the next session" if ok
                   else "market closed - only a queued GTC LIMIT order is allowed"):
            return RiskResult(False, 0.0, checks, "market closed")
    elif session != "regular":
        ok = lim["allow_extended_hours"] and order_type == "limit" and extended_hours
        if not add("session", ok, f"{session} session - limit + extended_hours" if ok
                   else f"{session} session accepts only LIMIT orders with extended_hours=True"):
            return RiskResult(False, 0.0, checks, f"{session} session: limit + extended hours only")
    else:
        add("session", True, "regular session")
    allowed = [s.upper() for s in lim.get("allowed_symbols") or []]
    if buying and allowed and symbol.upper() not in allowed and not reducing:
        add("allow_list", False, f"{symbol} is not on the allow-list")
        return RiskResult(False, 0.0, checks, f"{symbol} not on the allow-list")
    add("allow_list", True, "any symbol" if not allowed else "on the allow-list")
    if lim["long_only"] and side == "sell" and qty > max(position_qty, 0) + 1e-9:
        add("long_only", False, f"sell {qty:g} exceeds the {max(position_qty, 0):g} shares held (long-only account)")
        return RiskResult(False, 0.0, checks, "long-only: cannot sell more than held")
    add("long_only", True, "ok")
    day = equity / last_equity - 1 if last_equity else 0.0
    if buying and not reducing and day <= -abs(lim["max_daily_loss_pct"]):
        add("daily_loss", False, f"equity {day:.2%} since last close breaches the {lim['max_daily_loss_pct']:.0%} limit - no new buys")
        return RiskResult(False, 0.0, checks, "max daily loss breached")
    add("daily_loss", True, f"{day:+.2%} today vs limit -{lim['max_daily_loss_pct']:.0%}")
    new_qty = qty
    if not reducing:
        caps = []
        if lim["max_order_qty"]:
            caps.append(("max_order_qty", float(lim["max_order_qty"])))
        if lim["max_order_value"] and price > 0:
            caps.append(("max_order_value", float(lim["max_order_value"]) / price))
        if lim["max_position_pct"] and price > 0 and equity > 0:
            room = lim["max_position_pct"] * equity / price - abs(position_qty)
            caps.append(("max_position_pct", max(room, 0.0)))
        for name, cap in caps:
            if new_qty > cap + 1e-9:
                if not resize:
                    add(name, False, f"{new_qty:g} shares exceeds the {name} cap of {cap:g}")
                    return RiskResult(False, 0.0, checks, f"{name} exceeded")
                add(name, True, f"resized {new_qty:g} -> {int(cap) if cap >= 1 else round(cap, 4):g} shares ({name})")
                new_qty = float(int(cap)) if cap >= 1 else round(cap, 4)
            else:
                add(name, True, "within limit")
        if new_qty <= 0:
            return RiskResult(False, 0.0, checks, "position / order limits leave no room for this order")
    return RiskResult(True, new_qty, checks, "all checks passed")
