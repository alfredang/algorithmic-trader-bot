# data_handler.py — Market data fetching via yfinance

import pandas as pd
import logging
import yfinance as yf
from config import INTRADAY_MAX_DAYS

logger = logging.getLogger(__name__)


def validate_ticker(ticker):
    """
    Validate that a ticker symbol exists on Yahoo Finance.

    Returns True if valid, False otherwise.
    """
    try:
        info = yf.Ticker(ticker).fast_info
        return info.get("regularMarketPrice", None) is not None
    except Exception as e:
        logger.warning(f"Ticker validation failed for {ticker}: {e}")
        return False


def fetch_historical_data(ticker, start, end, interval="1d"):
    """
    Fetch historical OHLCV data from Yahoo Finance.

    Args:
        ticker: Stock symbol (e.g. 'AAPL').
        start: Start date string 'yyyy-MM-dd'.
        end: End date string 'yyyy-MM-dd'.
        interval: yfinance interval ('1m','5m','15m','1h','1d','1wk','1mo').

    Returns:
        DataFrame with columns: datetime, open, high, low, close, volume.

    Raises:
        RuntimeError: if download fails or returns empty data.
    """
    logger.info(f"Fetching {ticker} from {start} to {end} ({interval})")

    try:
        df = yf.download(
            ticker,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to download data for {ticker}: {e}")

    if df.empty:
        raise RuntimeError(
            f"No data returned for {ticker} ({start} to {end}, interval={interval}). "
            f"Check the ticker symbol and date range."
        )

    # yfinance returns MultiIndex columns when single ticker — flatten
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Normalize to our standard format
    result = pd.DataFrame({
        "datetime": df.index,
        "open": df["Open"].values,
        "high": df["High"].values,
        "low": df["Low"].values,
        "close": df["Close"].values,
        "volume": df["Volume"].values,
    })

    result["datetime"] = pd.to_datetime(result["datetime"])
    result = result.sort_values("datetime").reset_index(drop=True)

    logger.info(f"Fetched {len(result)} bars for {ticker}")
    return result


def get_max_lookback_warning(interval):
    """
    Return a warning message if the interval has limited lookback, or None.
    """
    max_days = INTRADAY_MAX_DAYS.get(interval)
    if max_days:
        return (
            f"Intraday interval '{interval}' is limited to the last "
            f"{max_days} days of data on Yahoo Finance."
        )
    return None
