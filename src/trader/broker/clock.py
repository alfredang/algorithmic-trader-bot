"""Which US trading session is it, and which orders are allowed? (course Lab 01 / Lab 08)

Alpaca 24/5 trading (US equities), New York time (ET), Monday-Friday:
    overnight  20:00 Sun -> 04:00 Fri  (each night 20:00 -> 04:00)
    pre        04:00 -> 09:30
    regular    09:30 -> 16:00
    after      16:00 -> 20:00
    closed     20:00 Fri -> 20:00 Sun (and exchange holidays)
Outside the regular session only LIMIT orders with time_in_force DAY or GTC and
extended_hours=True are accepted. Singapore (SGT) is 12 h ahead of New York in US
summer time and 13 h in winter, so a 09:00-18:30 SGT class sits in the US overnight
and pre-market sessions.
"""
from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
SGT = ZoneInfo("Asia/Singapore")

RULES = {
    "regular": {"order_types": ["market", "limit", "stop", "stop_limit", "bracket"], "time_in_force": ["day", "gtc"],
                "extended_hours": False, "note": "all order types accepted"},
    "pre": {"order_types": ["limit"], "time_in_force": ["day", "gtc"], "extended_hours": True,
            "note": "extended hours: LIMIT orders only, extended_hours=True"},
    "after": {"order_types": ["limit"], "time_in_force": ["day", "gtc"], "extended_hours": True,
              "note": "extended hours: LIMIT orders only, extended_hours=True"},
    "overnight": {"order_types": ["limit"], "time_in_force": ["day", "gtc"], "extended_hours": True,
                  "note": "24/5 overnight session: LIMIT orders only, extended_hours=True"},
    "closed": {"order_types": ["limit"], "time_in_force": ["gtc"], "extended_hours": False,
               "note": "market closed: a GTC limit order queues for the next session"},
}


def session_at(ts) -> str:
    ts = pd.Timestamp(ts)
    ts = ts.tz_localize(ET) if ts.tzinfo is None else ts.tz_convert(ET)
    wd, t = ts.weekday(), ts.time()
    if wd < 5 and time(9, 30) <= t < time(16, 0):
        return "regular"
    if wd < 5 and time(4, 0) <= t < time(9, 30):
        return "pre"
    if wd < 5 and time(16, 0) <= t < time(20, 0):
        return "after"
    if (t >= time(20, 0) and wd in (6, 0, 1, 2, 3)) or (t < time(4, 0) and wd in (0, 1, 2, 3, 4)):
        return "overnight"
    return "closed"


def now_et() -> datetime:
    return datetime.now(UTC).astimezone(ET)


def status(now: datetime | None = None, override: str | None = None, alpaca_clock=None) -> dict:
    """Clock snapshot. ``alpaca_clock``: result of TradingClient.get_clock() (detects holidays / early closes)."""
    now = pd.Timestamp(now).to_pydatetime() if now is not None else now_et()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    sess = override or session_at(now)
    holiday = False
    if alpaca_clock is not None and override is None and sess == "regular" and not getattr(alpaca_clock, "is_open", True):
        sess, holiday = "closed", True
    return {"now_et": now.astimezone(ET).isoformat(timespec="seconds"),
            "now_sgt": now.astimezone(SGT).isoformat(timespec="seconds"), "session": sess, "holiday": holiday,
            "is_open_regular": sess == "regular", **RULES[sess],
            "next_open": getattr(alpaca_clock, "next_open", None) and str(alpaca_clock.next_open),
            "next_close": getattr(alpaca_clock, "next_close", None) and str(alpaca_clock.next_close)}


def describe(st: dict) -> str:
    et, sg = pd.Timestamp(st["now_et"]), pd.Timestamp(st["now_sgt"])
    return (f"{et:%a %Y-%m-%d %H:%M} New York = {sg:%a %H:%M} Singapore | session {st['session'].upper()} "
            f"({st['note']})")
