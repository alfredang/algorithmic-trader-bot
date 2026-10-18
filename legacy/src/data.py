import yfinance as yf
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetches historical OHLCV data for a given ticker symbol.
    """
    logger.info(f"Fetching data for {symbol} from {start} to {end}")
    try:
        data = yf.download(symbol, start=start, end=end)
        if data.empty:
            raise ValueError(f"No data found for {symbol}")
        # Flatten multi-index columns if they exist (yfinance sometimes returns them)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return data
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        raise
