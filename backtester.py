# backtester.py — Historical simulation engine

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List


@dataclass
class TradeRecord:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    qty: float
    pnl: float
    return_pct: float
    commission_paid: float
    slippage_cost: float


@dataclass
class BacktestResult:
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_duration: int  # bars in max drawdown
    win_rate: float
    total_trades: int
    avg_trade_return: float
    profit_factor: float
    trade_log: List[TradeRecord]
    equity_curve: pd.DataFrame  # columns: datetime, equity, drawdown


def run_backtest(
    df,
    initial_capital=100_000.0,
    position_size_pct=0.95,
    commission=1.99,
    slippage_pct=0.001,
):
    """
    Simulate the SMA long-only strategy on historical data.

    Args:
        df: DataFrame with columns: datetime, close, sma_short, sma_long, signal, position
        initial_capital: Starting cash
        position_size_pct: Fraction of current cash to allocate per trade
        commission: Fixed commission per trade (entry and exit each)
        slippage_pct: Slippage as fraction of price

    Returns:
        BacktestResult with metrics, trade log, and equity curve.
    """
    cash = initial_capital
    shares = 0
    entry_price = 0.0
    entry_date = None
    trades = []
    equity_values = []
    datetime_values = []

    for i in range(len(df)):
        row = df.iloc[i]
        current_price = row["close"]

        # Skip rows where SMAs are NaN (before long_window period)
        if pd.isna(row.get("sma_long", np.nan)):
            equity_values.append(cash + shares * current_price)
            datetime_values.append(row["datetime"])
            continue

        # BUY signal: position == 1 and flat
        if row.get("position", 0) == 1 and shares == 0:
            fill_price = current_price * (1 + slippage_pct)
            affordable_qty = int(
                (cash * position_size_pct - commission) / fill_price
            )
            if affordable_qty > 0:
                cost = affordable_qty * fill_price + commission
                cash -= cost
                shares = affordable_qty
                entry_price = fill_price
                entry_date = row["datetime"]

        # SELL signal: position == -1 and holding
        elif row.get("position", 0) == -1 and shares > 0:
            fill_price = current_price * (1 - slippage_pct)
            proceeds = shares * fill_price - commission
            entry_cost = shares * entry_price + commission
            pnl = proceeds - entry_cost
            return_pct = pnl / entry_cost if entry_cost > 0 else 0.0
            cash += proceeds

            trades.append(TradeRecord(
                entry_date=str(entry_date),
                entry_price=round(entry_price, 4),
                exit_date=str(row["datetime"]),
                exit_price=round(fill_price, 4),
                qty=shares,
                pnl=round(pnl, 2),
                return_pct=round(return_pct, 4),
                commission_paid=round(commission * 2, 2),
                slippage_cost=round(
                    shares * current_price * slippage_pct * 2, 2
                ),
            ))
            shares = 0

        # Mark-to-market equity
        equity = cash + shares * current_price
        equity_values.append(equity)
        datetime_values.append(row["datetime"])

    # Build equity curve
    equity_curve = pd.DataFrame({
        "datetime": datetime_values,
        "equity": equity_values,
    })

    # Compute drawdown
    equity_series = equity_curve["equity"]
    running_max = equity_series.cummax()
    equity_curve["drawdown"] = (equity_series - running_max) / running_max

    # Compute metrics
    final_equity = equity_values[-1] if equity_values else initial_capital
    total_return = (final_equity - initial_capital) / initial_capital

    # Annualized return (approximate using trading days)
    n_bars = len(equity_values)
    if n_bars > 1:
        annual_return = (1 + total_return) ** (252 / n_bars) - 1
    else:
        annual_return = 0.0

    # Sharpe ratio
    daily_returns = equity_series.pct_change().dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
    else:
        sharpe_ratio = 0.0

    # Max drawdown
    max_drawdown = equity_curve["drawdown"].min() if len(equity_curve) > 0 else 0.0

    # Max drawdown duration (bars)
    max_dd_duration = 0
    current_dd_duration = 0
    for dd in equity_curve["drawdown"]:
        if dd < 0:
            current_dd_duration += 1
            max_dd_duration = max(max_dd_duration, current_dd_duration)
        else:
            current_dd_duration = 0

    # Trade statistics
    total_trades = len(trades)
    if total_trades > 0:
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl <= 0]
        win_rate = len(winning) / total_trades
        avg_trade_return = sum(t.return_pct for t in trades) / total_trades

        gross_profit = sum(t.pnl for t in winning) if winning else 0.0
        gross_loss = abs(sum(t.pnl for t in losing)) if losing else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    else:
        win_rate = 0.0
        avg_trade_return = 0.0
        profit_factor = 0.0

    return BacktestResult(
        total_return=round(total_return, 4),
        annual_return=round(annual_return, 4),
        sharpe_ratio=round(sharpe_ratio, 2),
        max_drawdown=round(max_drawdown, 4),
        max_drawdown_duration=max_dd_duration,
        win_rate=round(win_rate, 4),
        total_trades=total_trades,
        avg_trade_return=round(avg_trade_return, 4),
        profit_factor=round(profit_factor, 2),
        trade_log=trades,
        equity_curve=equity_curve,
    )
