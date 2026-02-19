# strategy.py — SMA crossover signal generation

import pandas as pd
from typing import Optional


def generate_signals(df, strategy="SMA Crossover"):
    """
    Generate crossover signals.
    strategy: "SMA Crossover" or "EMA Crossover"
    """
    short_col = "sma_short" if strategy == "SMA Crossover" else "ema_short"
    long_col = "sma_long" if strategy == "SMA Crossover" else "ema_long"
    
    # Check if columns exist
    if short_col not in df.columns or long_col not in df.columns:
        return df

    df["signal"] = 0
    df.loc[df[short_col] > df[long_col], "signal"] = 1
    df["position"] = df["signal"].diff()
    return df


def evaluate_latest_signal(df, current_position_qty=0.0, strategy="SMA Crossover"):
    """
    Evaluate the most recent bar for a live trading decision.
    """
    short_col = "sma_short" if strategy == "SMA Crossover" else "ema_short"
    long_col = "sma_long" if strategy == "SMA Crossover" else "ema_long"

    if len(df) < 2:
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    # Skip if indicators not yet computed (NaN)
    if pd.isna(prev.get(short_col)) or pd.isna(prev.get(long_col)):
        return None
    if pd.isna(curr.get(short_col)) or pd.isna(curr.get(long_col)):
        return None

    was_below = prev[short_col] <= prev[long_col]
    now_above = curr[short_col] > curr[long_col]

    was_above = prev[short_col] > prev[long_col]
    now_below = curr[short_col] <= curr[long_col]

    if was_below and now_above and current_position_qty == 0:
        return "BUY"
    elif was_above and now_below and current_position_qty > 0:
        return "SELL"

    return None
