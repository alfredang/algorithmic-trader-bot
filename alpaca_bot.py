
import time
import logging
import pandas as pd
from datetime import datetime, timedelta
from config import (
    DEFAULT_TICKER,
    DEFAULT_SHORT_WINDOW,
    DEFAULT_LONG_WINDOW,
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    ALPACA_PAPER_URL
)
from data_handler import fetch_historical_data
from indicators import compute_sma
from strategy import evaluate_latest_signal
from alpaca_executor import AlpacaExecutor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("alpaca_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def run_bot():
    """Run the auto-trading bot loop."""
    logger.info("Starting Alpaca Auto-Trading Bot...")
    
    # Initialize Executor
    executor = AlpacaExecutor(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
    if not executor.connect():
        logger.error("Failed to connect to Alpaca. Check your API keys in .env")
        return

    ticker = DEFAULT_TICKER
    logger.info(f"Target Ticker: {ticker}")
    logger.info(f"Strategy: SMA Crossover ({DEFAULT_SHORT_WINDOW}/{DEFAULT_LONG_WINDOW})")

    while True:
        try:
            # 1. Fetch Data
            # Note: For real-time trading, yfinance data might be delayed.
            # Using 1m interval to allow for frequent updates and testing.
            end_date = datetime.now()
            start_date = end_date - timedelta(days=5) # yfinance 1m limit is 7 days
            
            df = fetch_historical_data(
                ticker,
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval="1m" 
            )
            
            if df.empty:
                logger.warning("No data fetched. Waiting...")
                time.sleep(60)
                continue

            # 2. Compute Indicators
            df = compute_sma(df, short_window=DEFAULT_SHORT_WINDOW, long_window=DEFAULT_LONG_WINDOW)
            
            # 3. Check Signal
            # Get current position
            qty = executor.get_position_qty(ticker)
            logger.info(f"Current Position: {qty} shares of {ticker}")
            
            # Evaluate signal
            signal = evaluate_latest_signal(df, current_position_qty=qty)
            
            if signal:
                logger.info(f"Signal Detected: {signal}")
                
                # Get current price (approximate from last close)
                current_price = df.iloc[-1]["close"]
                
                # Execute
                result = executor.execute_signal(
                    signal=signal,
                    ticker=ticker,
                    current_price=current_price,
                    position_size_pct=0.95 
                )
                
                if result:
                    logger.info(f"Trade Executed: {result}")
                else:
                    logger.warning("Trade failed or constraints not met.")
            else:
                logger.info("No signal. Waiting for next check.")

            # Sleep
            # For daily bars, we don't need to check often. 
            # But for demo purposes, let's check every minute.
            logger.info("Sleeping for 60 seconds...")
            time.sleep(60)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"An error occurred: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
