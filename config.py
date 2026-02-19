
import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca Paper Trading
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_PAPER_URL = os.getenv("ALPACA_PAPER_URL", "https://paper-api.alpaca.markets")

# Trading defaults
DEFAULT_TICKER = "AAPL"
DEFAULT_SHORT_WINDOW = 20
DEFAULT_LONG_WINDOW = 50
DEFAULT_CAPITAL = 100_000.0
DEFAULT_POSITION_SIZE_PCT = 0.95
DEFAULT_COMMISSION = 1.99
DEFAULT_SLIPPAGE_PCT = 0.001  # 0.1%

# Timeframe mapping: user-friendly name -> yfinance interval string
TIMEFRAME_MAP = {
    "1 Minute": "1m",
    "5 Minutes": "5m",
    "15 Minutes": "15m",
    "60 Minutes": "1h",
    "Daily": "1d",
    "Weekly": "1wk",
    "Monthly": "1mo",
}

# yfinance max period constraints per interval
# (intraday intervals have limited lookback in yfinance)
INTRADAY_MAX_DAYS = {
    "1m": 7,
    "5m": 60,
    "15m": 60,
    "1h": 730,
}

# Date defaults
DEFAULT_START_DATE = "2024-01-01"
DEFAULT_END_DATE = "2025-12-31"
