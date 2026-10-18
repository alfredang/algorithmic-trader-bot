import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from src.data import fetch_data
from src.strategy import calculate_signals
from src.backtest import run_backtest
from src.metrics import calculate_metrics
from src.utils import plot_interactive_results
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

st.set_page_config(page_title="Automated Quant Trader", layout="wide")

# Custom CSS for consistent, professional, and smaller fonts
st.markdown("""
    <style>
    html, body, [class*="st-"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 14px;
    }
    .stMarkdown p, .stMarkdown li {
        font-size: 14px !important;
        line-height: 1.5;
    }
    h1 { font-size: 24px !important; }
    h2 { font-size: 20px !important; }
    h3 { font-size: 16px !important; }
    .stMetric label { font-size: 12px !important; }
    .stMetric div[data-testid="stMetricValue"] { font-size: 24px !important; }
    </style>
    """, unsafe_allow_html=True)

if 'backtest_ready' not in st.session_state:
    st.session_state.backtest_ready = False
    st.session_state.backtest_results = None
    st.session_state.backtest_metrics = None
    st.session_state.current_ticker = ""

st.title("🤖 Automated Algorithmic Trading")
st.markdown("""
### Set your simulation parameters below and run the automated strategy.
""")

# Top Level Configuration
setup_col1, setup_col2, setup_col3 = st.columns(3)

with setup_col1:
    ticker_input = st.text_input("Stock Ticker", value="AAPL")

with setup_col2:
    start_date_input = st.date_input("Simulation Start Date", value=datetime(2024, 1, 1))

with setup_col3:
    end_date_input = st.date_input("Simulation End Date", value=datetime.today())

# Sidebar Configuration
st.sidebar.header("Strategy Settings")
strategy_type = st.sidebar.selectbox("Algorithm", 
                                    ["SMA Crossover", "EMA Crossover", "SMA Long Only", "RSI Strategy", "Bollinger Bands", "MACD Crossover", "Stochastic Oscillator"])

params = {}
if strategy_type in ["SMA Crossover", "EMA Crossover"]:
    params['short_window'] = st.sidebar.slider("Short Window", 10, 100, 50)
    params['long_window'] = st.sidebar.slider("Long Window", 50, 250, 200)
elif strategy_type == "SMA Long Only":
    params['window'] = st.sidebar.slider("Trend Window", 10, 300, 200)
elif strategy_type == "RSI Strategy":
    params['period'] = st.sidebar.slider("RSI Period", 5, 30, 14)
    params['overbought'] = st.sidebar.slider("Overbought Level", 60, 90, 70)
    params['oversold'] = st.sidebar.slider("Oversold Level", 10, 40, 30)
elif strategy_type == "Bollinger Bands":
    params['window'] = st.sidebar.slider("Window", 10, 100, 20)
    params['num_std'] = st.sidebar.slider("Std Dev", 1.0, 3.0, 2.0)
elif strategy_type == "MACD Crossover":
    params['fast'] = st.sidebar.slider("Fast Period", 5, 20, 12)
    params['slow'] = st.sidebar.slider("Slow Period", 21, 50, 26)
    params['signal'] = st.sidebar.slider("Signal Period", 5, 20, 9)
elif strategy_type == "Stochastic Oscillator":
    params['k_period'] = st.sidebar.slider("K Period", 5, 30, 14)
    params['d_period'] = st.sidebar.slider("D Period", 2, 10, 3)
    params['overbought'] = st.sidebar.slider("Overbought Level", 70, 90, 80)
    params['oversold'] = st.sidebar.slider("Oversold Level", 10, 30, 20)

trade_qty = st.sidebar.number_input("Standard Trade Quantity (units)", value=100)
initial_capital = st.sidebar.number_input("Initial Capital ($)", value=100000.0)

st.sidebar.divider()
st.sidebar.header("✨ AI Features")
gemini_api_key = os.getenv("GEMINI_API_KEY")

if gemini_api_key:
    st.sidebar.success("✅ Gemini AI Connected")
else:
    st.sidebar.info("💡 To enable AI insights, add `GEMINI_API_KEY` to your `.env` file.")

# --- Automated Execution ---
if st.button("🚀 Run Automated Simulation", use_container_width=True):
    if start_date_input >= end_date_input:
        st.error("Start Date must be before End Date.")
    else:
        try:
            with st.spinner(f"Fetching data and simulating {strategy_type} for {ticker_input}..."):
                data = fetch_data(ticker_input, start_date_input.strftime('%Y-%m-%d'), end_date_input.strftime('%Y-%m-%d'))
                data_with_signals = calculate_signals(data, strategy_type, params)
                results = run_backtest(data_with_signals, initial_capital)
                
                st.session_state.backtest_results = results
                st.session_state.backtest_metrics = calculate_metrics(results)
                st.session_state.current_ticker = ticker_input
                st.session_state.current_strategy = strategy_type
                st.session_state.current_params = params
                st.session_state.backtest_ready = True
                st.session_state.ai_analysis = None # Reset AI analysis on new run
        except ValueError as ve:
            st.error(f"❌ Error: {str(ve)}. Please check if the ticker '{ticker_input}' is correct.")
            st.session_state.backtest_ready = False
        except Exception as e:
            st.error(f"❌ An unexpected error occurred: {str(e)}")
            st.session_state.backtest_ready = False

if st.session_state.backtest_ready:
    res = st.session_state.backtest_results
    met = st.session_state.backtest_metrics
    t_sym = st.session_state.current_ticker
    
    st.divider()
    st.subheader(f"Results: {t_sym} ({start_date_input.strftime('%Y-%m-%d')} to {end_date_input.strftime('%Y-%m-%d')})")
    
    # Financial Summary
    col1, col2, col3, col4 = st.columns(4)
    final_equity = res['Equity_Curve'].iloc[-1]
    net_profit = final_equity - initial_capital
    col1.metric("Strategy Final Value", f"${final_equity:,.2f}", f"${net_profit:,.2f} Net")
    col2.metric("Strategy Total Return", met["Total Return"])
    col3.metric("Annualized Return", met["Annualized Return"])
    col4.metric("Sharpe Ratio", met["Sharpe Ratio"])
    
    st.divider()
    
    # Comparison and Winners
    mkt_return_pct = float(met["Market Return"].strip('%')) / 100
    mkt_final_value = initial_capital * (1 + mkt_return_pct)
    mkt_net_profit = mkt_final_value - initial_capital

    if net_profit > mkt_net_profit:
        st.success(f"🏆 The **{strategy_type}** outperformed Buy & Hold by **${(net_profit - mkt_net_profit):,.2f}**!")
    else:
        st.warning(f"⚠️ **Buy & Hold** outperformed the strategy by **${(mkt_net_profit - net_profit):,.2f}**.")
    
    st.divider()
    st.subheader("🏁 Performance Comparison")
    comparison_data = {
        "Metric": ["Initial Investment", "Final Account Value", "Net Profit/Loss", "Percentage Return"],
        "Automated Strategy": [f"${initial_capital:,.2f}", f"${final_equity:,.2f}", f"${net_profit:,.2f}", met["Total Return"]],
        "Buy & Hold (Market)": [f"${initial_capital:,.2f}", f"${mkt_final_value:,.2f}", f"${mkt_net_profit:,.2f}", met["Market Return"]]
    }
    st.table(comparison_data)
    
    # Visualization
    st.divider()
    st.subheader("📈 Visualization")
    fig = plot_interactive_results(res, t_sym)
    st.plotly_chart(fig, use_container_width=True)
    
    with st.expander("📝 View Automated Trade Log"):
        trades = res[res['Position'] != 0].copy()
        if not trades.empty:
            trades['Action'] = trades['Position'].apply(lambda x: 'BUY' if x > 0 else 'SELL')
            trade_log = trades[['Close', 'Action']].copy()
            trade_log.columns = ['Execution Price', 'Action']
            st.dataframe(trade_log, use_container_width=True)

    # --- GEMINI AI ANALYSIS (MOVED TO BOTTOM) ---
    st.divider()
    st.subheader("🔮 AI Performance Deep-Dive")
    if gemini_api_key:
        if st.button("🪄 Generate AI Strategy Insight", use_container_width=True):
            try:
                genai.configure(api_key=gemini_api_key)
                model = genai.GenerativeModel('gemini-2.0-flash') # State of the art Flash model
                
                win_loss_text = "OUTPERFORMED" if net_profit > mkt_net_profit else "UNDERPERFORMED"
                diff_val = abs(net_profit - mkt_net_profit)

                prompt = f"""
                You are a professional quantitative trading assistant. 
                Analyze these results:
                - Stock: {t_sym}
                - Selected Algorithm: {st.session_state.current_strategy}
                - Observation: The strategy {win_loss_text} Buy & Hold by ${diff_val:,.2f}.
                
                Performance Metrics:
                - Strategy Return: {met["Total Return"]}
                - Market (Buy & Hold) Return: {met["Market Return"]}
                - Sharpe Ratio: {met["Sharpe Ratio"]}
                - Max Drawdown: {met["Max Drawdown"]}
                
                Please provide a report with these three sections:
                
                1. **Algorithm Mechanics**: Explain exactly how the {st.session_state.current_strategy} works in technical terms. Explain why its specific logic (crossovers, thresholds, or bands) triggered the results we see.
                
                2. **AI Performance Insight**: Provide a deep comparison of why this algorithm performed {win_loss_text} compared to a simple Buy & Hold strategy for {t_sym}. Was it the volatility, the trend strength, or the timing?
                
                3. **Quant Recommendation**: Based on the {met["Sharpe Ratio"]} Sharpe Ratio and {met["Max Drawdown"]} drawdown, is this algorithm viable for this stock? Suggest one specific parameter optimization.
                
                Format with clean markdown and use professional financial terminology.
                """
                
                with st.spinner("Gemini 2.0 is analyzing the market performance..."):
                    response = model.generate_content(prompt)
                    st.session_state.ai_analysis = response.text
            except Exception as e:
                st.error(f"AI Analysis Error: {str(e)}")

    if st.session_state.get('ai_analysis'):
        st.info("🧠 **AI Quant Insight**")
        st.markdown(st.session_state.ai_analysis)

# --- Strategy Explanations Section ---
st.divider()
with st.expander("📚 Strategy Definitions & Help"):
    st.markdown("""
    ### 1. SMA / EMA Crossovers
    - **Logic**: Uses two moving averages (Short and Long).
    - **Signal**: Buy when the Short MA crosses ABOVE the Long MA (Golden Cross). Sell when it crosses BELOW (Death Cross).
    - **EMA** is more responsive to recent price changes than **SMA**.

    ### 2. SMA Long Only
    - **Logic**: A simple trend-following strategy.
    - **Signal**: Buy/Hold when the current price is above the Moving Average. Exit to cash when the price falls below it.

    ### 3. RSI Strategy (Relative Strength Index)
    - **Logic**: A momentum oscillator that measures the speed and change of price movements.
    - **Signal**: Buy when RSI falls below the 'Oversold' level (e.g., 30). Sell when it rises above 'Overbought' (e.g., 70).

    ### 4. Bollinger Bands
    - **Logic**: Measures volatility using standard deviations around a moving average.
    - **Signal**: Buy when price touches the **Lower Band** (mean reversion). Sell when it touches the **Upper Band**.

    ### 5. MACD Crossover (Moving Average Convergence Divergence)
    - **Logic**: Follows the relationship between two EMAs of a base price.
    - **Signal**: Buy when the MACD line crosses above the Signal line. Sell when it crosses below.

    ### 6. Stochastic Oscillator
    - **Logic**: Compares a particular closing price to a range of its prices over a certain period.
    - **Signal**: Similar to RSI, it uses overbought (80) and oversold (20) levels to identify potential reversals.
    """)

st.info(f"💡 This dashboard simulates a fully automated bot starting from {start_date_input.strftime('%Y-%b-%d')}.")
