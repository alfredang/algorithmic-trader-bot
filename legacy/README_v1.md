# 🤖 Automated Quant Trader

An automated algorithmic trading dashboard built with **Streamlit**, **YFinance**, and **Gemini 2.0 AI**. This tool allows you to simulate various algorithmic trading strategies, compare them against a "Buy & Hold" benchmark, and receive AI-driven quant insights.

## ✨ Features

- **Automated Trading Simulation**: Choose a starting date and see how a fully automated bot would have performed using various technical strategies.
- **Multiple Algorithms**:
  - SMA/EMA Crossovers
  - RSI (Relative Strength Index)
  - Bollinger Bands
  - MACD (Moving Average Convergence Divergence)
  - Stochastic Oscillator
- **Benchmark Comparison**: Real-time comparison with the "Market Return" (Buy & Hold).
- **Interactive Visualizations**: Professional-grade Plotly charts with entry/exit signals.
- **AI-Powered Insights**: Integrated **Gemini 2.0 Flash** to provide technical analysis on strategy performance and optimization tips.
- **Performance Metrics**: Automated calculation of Sharpe Ratio, Max Drawdown, Annualized Return, and Volatility.

## 🚀 Getting Started

### 1. Installation

This project uses `uv` for lightning-fast Python package management.

```bash
# Clone the repository
git clone https://github.com/alfredang/algorithmic-trading.git
cd algorithmic-trading

# Setup environment and install dependencies
uv sync
```

### 2. Configuration

Create a `.env` file in the root directory to store your API keys:

```ini
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Running the Dashboard

```bash
uv run streamlit run app.py
```

## 🛠️ Tech Stack

- **Dashboard**: [Streamlit](https://streamlit.io/)
- **Data Engine**: [yfinance](https://github.com/ranaroussi/yfinance)
- **Quant Calculation**: [Pandas](https://pandas.pydata.org/), [NumPy](https://numpy.org/)
- **Visualization**: [Plotly](https://plotly.com/)
- **AI Insight**: [Google Generative AI (Gemini)](https://ai.google.dev/)

## 📝 License

Distributed under the MIT License.
