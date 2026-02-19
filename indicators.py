# indicators.py — SMA computation

import pandas as pd


def compute_sma(df, short_window=20, long_window=50):
    """
    Add SMA columns to the DataFrame.

    Args:
        df: Must contain a 'close' column.
        short_window: Period for the fast SMA.
        long_window: Period for the slow SMA.

    Returns:
        Same DataFrame with 'sma_short' and 'sma_long' columns added.

    Raises:
        ValueError: if short_window >= long_window or insufficient data.
    """
    if short_window >= long_window:
        raise ValueError(
            f"short_window ({short_window}) must be less than long_window ({long_window})"
        )
    if len(df) < long_window:
        raise ValueError(
            f"DataFrame has {len(df)} rows but needs at least {long_window} "
            f"for long_window SMA"
        )

    df["sma_short"] = df["close"].rolling(window=short_window).mean()
    df["sma_long"] = df["close"].rolling(window=long_window).mean()
    return df


def compute_ema(df, short_window=12, long_window=26):
    """
    Add EMA columns to the DataFrame.
    """
    df["ema_short"] = df["close"].ewm(span=short_window, adjust=False).mean()
    df["ema_long"] = df["close"].ewm(span=long_window, adjust=False).mean()
    return df
