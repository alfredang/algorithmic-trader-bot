# Algorithmic Trading Bot

A sophisticated algorithmic trading system built with Python that executes SMA/EMA crossover strategies using the Alpaca broker API. Features both live trading execution and comprehensive backtesting capabilities with a Streamlit dashboard.

## Features

- **Strategy Engine**: Implement and test SMA/EMA crossover strategies
- **Live Trading**: Execute trades via Alpaca API with paper trading support
- **Backtesting**: Comprehensive historical simulation with detailed metrics
- **Data Management**: Fetch and process market data via yfinance
- **Interactive Dashboard**: Real-time monitoring and analysis via Streamlit
- **Risk Management**: Position sizing, commission calculations, and slippage modeling

## Tech Stack

- **Python 3.13+**: Core language
- **alpaca-py**: Broker integration and order execution
- **pandas/numpy**: Data processing and analysis
- **yfinance**: Market data fetching
- **Streamlit**: Web-based dashboard interface
- **Plotly**: Interactive charting

## Project Structure

```
algorithmic-trading-bot/
├── main.py                 # Entry point
├── app.py                  # Streamlit dashboard
├── strategy.py             # Signal generation (SMA/EMA crossovers)
├── indicators.py           # Technical indicator calculations
├── backtester.py           # Historical simulation engine
├── data_handler.py         # Market data fetching and processing
├── executor.py             # Paper trading execution
├── alpaca_bot.py           # Alpaca API integration
├── alpaca_executor.py      # Live order execution
├── config.py               # Configuration and constants
├── utils.py                # Utility functions
├── pyproject.toml          # Project metadata and dependencies
└── requirements.txt        # Python dependencies
```

## Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd algorithmic-trading-bot
   ```

2. **Create a Python environment** (requires Python 3.13+):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   # or with uv
   uv sync
   ```

4. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your Alpaca API credentials
   ```

## Usage

### Interactive Dashboard
```bash
streamlit run app.py
```
Launches the web interface for backtesting, strategy configuration, and live trading monitoring.

### Command Line
```bash
python main.py
```
Runs the default trading configuration.

## Configuration

Edit `config.py` to customize:
- **Trading Defaults**: Capital, position size, ticker symbols
- **Strategy Parameters**: SMA/EMA periods
- **Timeframes**: 1m, 5m, 15m, 1h, 1d, 1wk, 1mo
- **Date Ranges**: Historical periods for backtesting
- **Alpaca API**: Endpoints and authentication

## Strategy

The bot implements **SMA/EMA Crossover** signals:
- **Entry Signal**: Short-term MA crosses above long-term MA
- **Exit Signal**: Short-term MA crosses below long-term MA
- **Default Parameters**: 20-period short, 50-period long

## Backtesting

Comprehensive metrics including:
- Total/annual returns
- Sharpe ratio and maximum drawdown
- Win rate and profit factor
- Detailed trade log with P&L
- Equity curve visualization

## Requirements

- Python 3.13 or higher
- Alpaca account (paper or live)
- Valid API credentials in `.env`

## Environment Variables

```
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_PAPER_URL=https://paper-api.alpaca.markets
```

## License

MIT License - See LICENSE file for details

## Disclaimer

This is an educational tool. Trading involves risk. Always test strategies thoroughly with paper trading before deploying real capital.
