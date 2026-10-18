"""Pine Script v6 export of built-in strategies for TradingView's Strategy Tester (course Lab 05 / 06 / 17).

Every script fills orders on the NEXT bar's open (process_orders_on_close = false), charges a
commission per order and slippage, and carries a webhook alert message in the app's JSON format.
"""
from __future__ import annotations

HEADER = """//@version=6
// {title} - exported from the Quant Trading Simulator (Tertiary Infotech Academy course software)
// Orders fill on the NEXT bar's open (process_orders_on_close = false), net of commission and slippage,
// to match the app's next-bar backtest engine. Educational use only - PAPER trading, not investment advice.
strategy("{short}", shorttitle = "{short}", overlay = {overlay},
     initial_capital = 100000, currency = currency.USD,
     default_qty_type = strategy.percent_of_equity, default_qty_value = 100,
     commission_type = strategy.commission.cash_per_order, commission_value = {commission},
     slippage = {slippage}, pyramiding = 0, process_orders_on_close = false)

startTime = input.time(timestamp("2018-01-01T00:00:00"), "Backtest start date")
endTime   = input.time(timestamp("2025-12-31T23:59:59"), "Backtest end date")
inWindow  = time >= startTime and time <= endTime
// TradingView webhook message (Alerts -> Message). Replace YOUR_SECRET with the app's webhook secret.
alertMsg(string action) => '{{"secret": "YOUR_SECRET", "id": "' + str.tostring(timenow) + '", "ticker": "' + syminfo.ticker + '", "action": "' + action + '", "qty": "{{{{strategy.order.contracts}}}}", "price": "' + str.tostring(close) + '"}}'
"""

FOOTER = """
if goLong and inWindow and strategy.position_size == 0
    strategy.entry("Long", strategy.long, comment = "{entry_c}", alert_message = alertMsg("buy"))
if goFlat and strategy.position_size > 0
    strategy.close("Long", comment = "{exit_c}", alert_message = alertMsg("sell"))
if time > endTime
    strategy.close_all(comment = "End of test window")
bgcolor(strategy.position_size > 0 ? color.new(color.green, 92) : na, title = "In position")
"""

BODIES = {
    "sma_cross": ("""fastLen = input.int({fast}, "Fast SMA", minval = 1)
slowLen = input.int({slow}, "Slow SMA", minval = 2)
fastMA = ta.sma(close, fastLen)
slowMA = ta.sma(close, slowLen)
goLong = fastMA > slowMA
goFlat = fastMA < slowMA
plot(fastMA, "Fast SMA", color = color.blue, linewidth = 2)
plot(slowMA, "Slow SMA", color = color.orange, linewidth = 2)""", "Golden cross", "Death cross", "true"),
    "ema_cross": ("""fastLen = input.int({fast}, "Fast EMA", minval = 1)
slowLen = input.int({slow}, "Slow EMA", minval = 2)
fastMA = ta.ema(close, fastLen)
slowMA = ta.ema(close, slowLen)
goLong = fastMA > slowMA
goFlat = fastMA < slowMA
plot(fastMA, "Fast EMA", color = color.blue, linewidth = 2)
plot(slowMA, "Slow EMA", color = color.orange, linewidth = 2)""", "EMA cross up", "EMA cross down", "true"),
    "trend_filter": ("""len = input.int({window}, "SMA length", minval = 2)
ma = ta.sma(close, len)
goLong = close > ma
goFlat = close < ma
plot(ma, "SMA", color = color.orange, linewidth = 2)""", "Above SMA", "Below SMA", "true"),
    "macd_cross": ("""[macdLine, signalLine, hist] = ta.macd(close, {fast}, {slow}, {signal})
goLong = macdLine > signalLine
goFlat = macdLine < signalLine""", "MACD above signal", "MACD below signal", "true"),
    "rsi_threshold": ("""len = input.int({window}, "RSI length", minval = 2)
r = ta.rsi(close, len)
goLong = r < {oversold}
goFlat = r > {overbought}""", "RSI oversold", "RSI overbought", "true"),
    "rsi2_reversion": ("""len = input.int({n}, "RSI length", minval = 2)
r = ta.rsi(close, len)
goLong = r < {entry}
goFlat = r > {exit}""", "RSI dip", "RSI bounce", "true"),
    "bollinger_reversion": ("""[mid, upper, lower] = ta.bb(close, {window}, {k})
goLong = close < lower
goFlat = close > mid
plot(mid, "Middle", color = color.gray)
plot(upper, "Upper", color = color.teal)
plot(lower, "Lower", color = color.teal)""", "Below lower band", "Back to the mean", "true"),
    "bollinger_breakout": ("""[mid, upper, lower] = ta.bb(close, {window}, {k})
goLong = close > upper
goFlat = close < mid
plot(mid, "Middle", color = color.gray)
plot(upper, "Upper", color = color.teal)
plot(lower, "Lower", color = color.teal)""", "Upper-band breakout", "Below the middle band", "true"),
    "donchian_breakout": ("""hi = ta.highest(high, {entry})[1]
lo = ta.lowest(low, {exit})[1]
goLong = close > hi
goFlat = close < lo
plot(hi, "Breakout level", color = color.green)
plot(lo, "Exit level", color = color.red)""", "Donchian breakout", "Donchian exit", "true"),
    "ts_momentum": ("""lookback = input.int({lookback}, "Momentum lookback", minval = 2)
mom = close / close[lookback] - 1
goLong = mom > {threshold}
goFlat = mom <= {threshold}""", "Positive momentum", "Momentum gone", "true"),
    "buy_hold": ("""goLong = true
goFlat = false""", "Buy and hold", "-", "true"),
}


def export(key: str, params: dict, title: str, commission: float = 0.0, slippage_ticks: int = 1) -> str:
    if key not in BODIES:
        raise KeyError(f"no Pine Script template for {key} (multi-asset, ML, execution and agentic strategies need Python)")
    body, entry_c, exit_c, overlay = BODIES[key]
    short = title[:30].replace('"', "'")
    return (HEADER.format(title=title, short=short, overlay=overlay, commission=commission, slippage=slippage_ticks)
            + "\n" + body.format(**params) + "\n" + FOOTER.format(entry_c=entry_c, exit_c=exit_c))
