# app.py — Streamlit UI for SMA Crossover Trading System

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

from config import (
    DEFAULT_TICKER,
    DEFAULT_SHORT_WINDOW,
    DEFAULT_LONG_WINDOW,
    DEFAULT_CAPITAL,
    DEFAULT_POSITION_SIZE_PCT,
    DEFAULT_COMMISSION,
    DEFAULT_SLIPPAGE_PCT,
    DEFAULT_START_DATE,
    DEFAULT_END_DATE,
    TIMEFRAME_MAP,
    ALPACA_API_KEY,
    ALPACA_PAPER_URL,
)
from data_handler import validate_ticker, fetch_historical_data, get_max_lookback_warning
from indicators import compute_sma, compute_ema
from strategy import generate_signals, evaluate_latest_signal
from backtester import run_backtest
from executor import PaperTradeExecutor
from alpaca_executor import AlpacaExecutor
from utils import (
    setup_logging,
    format_currency,
    format_percentage,
    format_number,
    validate_date_range,
    validate_sma_windows,
    df_to_trade_log_display,
)

# ─── Page Config ─────────────────────────────────────────────
st.set_page_config(
    page_title="SMA Trading System",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

setup_logging()


# ─── Session State ───────────────────────────────────────────
def init_session_state():
    defaults = {
        "executor": None,
        "backtest_result": None,
        "paper_trading_active": False,
        "paper_trade_log": [],
        "historical_df": None,
        "paper_df": None,
        "paper_bar_index": 0,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session_state()


# ─── Sidebar ─────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.header("Configuration")

        # Ticker & Timeframe
        st.subheader("Ticker & Timeframe")
        ticker = st.text_input("Stock Ticker", value=DEFAULT_TICKER)
        timeframe = st.selectbox("Timeframe", options=list(TIMEFRAME_MAP.keys()), index=4)
        interval = TIMEFRAME_MAP[timeframe]

        # Show intraday lookback warning
        warning = get_max_lookback_warning(interval)
        if warning:
            st.caption(warning)

        start_date = st.date_input(
            "Start Date",
            value=datetime.strptime(DEFAULT_START_DATE, "%Y-%m-%d").date(),
        )
        end_date = st.date_input(
            "End Date",
            value=datetime.strptime(DEFAULT_END_DATE, "%Y-%m-%d").date(),
        )

        st.divider()

        # Strategy Parameters
        st.subheader("Strategy Parameters")
        short_window = st.slider("Short Window", min_value=2, max_value=100, value=DEFAULT_SHORT_WINDOW)
        long_window = st.slider("Long Window", min_value=5, max_value=300, value=DEFAULT_LONG_WINDOW)

        if short_window >= long_window:
            st.error("Short window must be less than Long window")

        st.divider()

        # Capital & Position Sizing
        st.subheader("Capital & Sizing")
        initial_capital = st.number_input(
            "Initial Capital ($)",
            min_value=1000.0,
            max_value=10_000_000.0,
            value=DEFAULT_CAPITAL,
            step=1000.0,
        )
        position_size_pct = st.slider(
            "Position Size (%)",
            min_value=10,
            max_value=100,
            value=int(DEFAULT_POSITION_SIZE_PCT * 100),
        ) / 100.0

        st.divider()

        # Trading Mode
        st.subheader("Mode & Strategy")
        mode = st.selectbox(
            "Trading Mode",
            ["Backtest", "Local Paper Simulation", "Alpaca Paper Trading"]
        )
        
        strategy = st.selectbox(
            "Strategy",
            ["SMA Crossover"]
        )

        st.divider()

        # Costs (Only for Backtest/Local Sim)
        if mode != "Alpaca Paper Trading":
            st.subheader("Costs (Simulation Only)")
            commission = st.number_input(
                "Commission per Trade ($)",
                min_value=0.0,
                max_value=50.0,
                value=DEFAULT_COMMISSION,
                step=0.01,
            )
            slippage_pct = st.number_input(
                "Slippage (%)",
                min_value=0.0,
                max_value=5.0,
                value=DEFAULT_SLIPPAGE_PCT * 100,
                step=0.01,
                format="%.4f",
            ) / 100.0
        else:
            commission = 0.0
            slippage_pct = 0.0

        st.divider()

        # Action buttons
        if mode == "Backtest":
            run_backtest_btn = st.button("Run Backtest", type="primary", use_container_width=True)
            toggle_paper_btn = False
        else:
            run_backtest_btn = False
            # Determine button text based on state
            if st.session_state.get("paper_trading_active"):
                btn_text = "Stop Trading"
                btn_type = "secondary"
            else:
                btn_text = f"Start {mode}"
                btn_type = "primary"
                
            toggle_paper_btn = st.button(
                btn_text,
                type=btn_type,
                use_container_width=True,
            )

    return {
        "mode": mode,
        "strategy": strategy,
        "ticker": ticker,
        "timeframe": timeframe,
        "interval": interval,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "short_window": short_window,
        "long_window": long_window,
        "initial_capital": initial_capital,
        "position_size_pct": position_size_pct,
        "commission": commission,
        "slippage_pct": slippage_pct,
        "run_backtest": run_backtest_btn,
        "toggle_paper": toggle_paper_btn,
    }


# ─── Charts ──────────────────────────────────────────────────
def create_candlestick_chart(df):
    """Create Plotly candlestick chart with SMA overlays, trade markers, and volume."""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.8, 0.2],
        vertical_spacing=0.03,
    )

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df["datetime"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1,
        col=1,
    )

    # Short Moving Average
    short_col = "ema_short" if "ema_short" in df.columns else "sma_short"
    if short_col in df.columns:
        label = "EMA" if "ema" in short_col else "SMA"
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=df[short_col],
                name=f"{label} {df.attrs.get('short_window', 'Short')}",
                line=dict(color="#2196f3", width=1.5),
                mode="lines",
            ),
            row=1,
            col=1,
        )

    # Long Moving Average
    long_col = "ema_long" if "ema_long" in df.columns else "sma_long"
    if long_col in df.columns:
        label = "EMA" if "ema" in long_col else "SMA"
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=df[long_col],
                name=f"{label} {df.attrs.get('long_window', 'Long')}",
                line=dict(color="#ff9800", width=1.5),
                mode="lines",
            ),
            row=1,
            col=1,
        )

    # Buy signals
    if "position" in df.columns:
        buys = df[df["position"] == 1]
        if not buys.empty:
            fig.add_trace(
                go.Scatter(
                    x=buys["datetime"],
                    y=buys["low"] * 0.995,
                    mode="markers",
                    name="Buy",
                    marker=dict(
                        size=10,
                        color="#26a69a",
                        symbol="triangle-up",
                        line=dict(width=1, color="#004d40"),
                    ),
                    hovertemplate="<b>BUY</b><br>%{x}<br>$%{y:.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

        # Sell signals
        sells = df[df["position"] == -1]
        if not sells.empty:
            fig.add_trace(
                go.Scatter(
                    x=sells["datetime"],
                    y=sells["high"] * 1.005,
                    mode="markers",
                    name="Sell",
                    marker=dict(
                        size=10,
                        color="#ef5350",
                        symbol="triangle-down",
                        line=dict(width=1, color="#b71c1c"),
                    ),
                    hovertemplate="<b>SELL</b><br>%{x}<br>$%{y:.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

    # Volume bars
    colors = [
        "#26a69a" if c >= o else "#ef5350"
        for c, o in zip(df["close"], df["open"])
    ]
    fig.add_trace(
        go.Bar(
            x=df["datetime"],
            y=df["volume"],
            name="Volume",
            marker_color=colors,
            opacity=0.5,
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        height=600,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=40, b=20),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    return fig


def create_equity_curve_chart(equity_df):
    """Line chart of equity over time with drawdown shading."""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.05,
    )

    # Equity line
    fig.add_trace(
        go.Scatter(
            x=equity_df["datetime"],
            y=equity_df["equity"],
            name="Equity",
            line=dict(color="#2196f3", width=2),
            fill="tozeroy",
            fillcolor="rgba(33, 150, 243, 0.1)",
        ),
        row=1,
        col=1,
    )

    # Drawdown area
    fig.add_trace(
        go.Scatter(
            x=equity_df["datetime"],
            y=equity_df["drawdown"] * 100,
            name="Drawdown %",
            line=dict(color="#ef5350", width=1),
            fill="tozeroy",
            fillcolor="rgba(239, 83, 80, 0.2)",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        height=400,
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=40, b=20),
    )
    fig.update_yaxes(title_text="Equity ($)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)

    return fig


# ─── Backtest Flow ───────────────────────────────────────────
def run_backtest_flow(params):
    """Orchestrate the backtest pipeline."""
    # Validate inputs
    if not validate_date_range(params["start_date"], params["end_date"]):
        st.error("Invalid date range: start must be before end.")
        return

    if not validate_sma_windows(params["short_window"], params["long_window"]):
        st.error("Invalid SMA windows: short must be less than long.")
        return

    # Validate ticker
    with st.spinner(f"Validating ticker {params['ticker']}..."):
        if not validate_ticker(params["ticker"]):
            st.error(f"Invalid ticker: {params['ticker']}. Check the symbol and try again.")
            return

    # Fetch data
    with st.spinner("Fetching historical data from Yahoo Finance..."):
        try:
            df = fetch_historical_data(
                ticker=params["ticker"],
                start=params["start_date"],
                end=params["end_date"],
                interval=params["interval"],
            )
        except RuntimeError as e:
            st.error(str(e))
            return

    if df.empty:
        st.warning("No data returned for the given parameters.")
        return

    # Compute indicators
    try:
        if params["strategy"] == "EMA Crossover":
            df = compute_ema(df, params["short_window"], params["long_window"])
        else:
            df = compute_sma(df, params["short_window"], params["long_window"])
    except ValueError as e:
        st.error(f"Indicator error: {e}")
        return

    # Store window info in DataFrame attrs for chart labels
    df.attrs["short_window"] = params["short_window"]
    df.attrs["long_window"] = params["long_window"]
    df.attrs["strategy"] = params["strategy"]

    # Generate signals
    df = generate_signals(df, strategy=params["strategy"])

    # Run backtest
    with st.spinner("Running backtest..."):
        result = run_backtest(
            df,
            initial_capital=params["initial_capital"],
            position_size_pct=params["position_size_pct"],
            commission=params["commission"],
            slippage_pct=params["slippage_pct"],
        )

    # Store results
    st.session_state["backtest_result"] = result
    st.session_state["historical_df"] = df
    st.success(f"Backtest complete: {result.total_trades} trades executed")


# ─── Paper Trading Flow ──────────────────────────────────────
def start_paper_trading(params):
    """Initialize paper trading: fetch data, create executor, set up state."""
    # Validate SMA windows (needed for strategy regardless of mode)
    if not validate_sma_windows(params["short_window"], params["long_window"]):
        st.error("Invalid SMA/EMA windows.")
        return False

    # Fetch full historical data for simulation/charting
    with st.spinner("Fetching data..."):
        try:
            df = fetch_historical_data(
                ticker=params["ticker"],
                start=params["start_date"],
                end=params["end_date"],
                interval=params["interval"],
            )
        except RuntimeError as e:
            st.error(str(e))
            return False

    if len(df) < params["long_window"] + 2:
        st.error(
            f"Insufficient data ({len(df)} bars) for long window "
            f"({params['long_window']}). Adjust date range or parameters."
        )
        return False

    # Compute Indicators on full data
    if params["strategy"] == "EMA Crossover":
        df = compute_ema(df, params["short_window"], params["long_window"])
    else:
        df = compute_sma(df, params["short_window"], params["long_window"])
        
    df.attrs["short_window"] = params["short_window"]
    df.attrs["long_window"] = params["long_window"]
    df.attrs["strategy"] = params["strategy"]

    # Create executor based on mode
    if params["mode"] == "Alpaca Paper Trading":
        executor = AlpacaExecutor(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        if not executor.connect():
            st.error("Failed to connect to Alpaca. Check .env keys.")
            return False
        st.success("Connected to Alpaca Paper Trading!")
        
        # for Alpaca, we don't 'step' through history, we watch live.
        # But we still want to show the chart of historical data.
        st.session_state["paper_bar_index"] = len(df) - 1 # Point to end
        
    else:
        # Local Simulation
        executor = PaperTradeExecutor(initial_capital=params["initial_capital"])
        executor.connect()
        st.session_state["paper_bar_index"] = params["long_window"]  # first valid bar

    # Store state
    st.session_state["executor"] = executor
    st.session_state["paper_df"] = df
    st.session_state["paper_trading_active"] = True
    st.session_state["paper_trade_log"] = []
    
    return True


def step_paper_trading(params):
    """Advance paper trading by one bar and evaluate signal."""
    executor = st.session_state["executor"]
    df = st.session_state["paper_df"]
    idx = st.session_state["paper_bar_index"]

    if idx >= len(df):
        st.warning("Reached end of data. No more bars to simulate.")
        return

    # Get data up to current bar
    current_slice = df.iloc[: idx + 1]
    current_bar = df.iloc[idx]
    current_price = float(current_bar["close"])

    # Evaluate signal
    current_qty = executor.get_position_qty(params["ticker"])
    signal = evaluate_latest_signal(current_slice, current_qty)

    # Execute if signal
    if signal:
        result = executor.execute_signal(
            signal=signal,
            ticker=params["ticker"],
            current_price=current_price,
            position_size_pct=params["position_size_pct"],
        )
        if result:
            result["time"] = str(current_bar["datetime"])
            st.session_state["paper_trade_log"].append(result)
            st.toast(
                f"{result['action']}: {params['ticker']} x{result['qty']} "
                f"@ ${result['price']:.2f}"
            )

    # Advance bar
    st.session_state["paper_bar_index"] = idx + 1


# ─── Main Layout ─────────────────────────────────────────────
# ─── Main Layout ─────────────────────────────────────────────
def render_main_area(params):
    st.title("SMA Crossover Trading System")

    tab_backtest, tab_paper = st.tabs(["Backtest", "Paper Trading"])

    # ── TAB 1: Backtest ──────────────────────────────────────
    with tab_backtest:
        result = st.session_state["backtest_result"]
        df = st.session_state["historical_df"]

        if result is None:
            st.info("Configure parameters in the sidebar and click **Run Backtest**.")
            return

        # Metrics row 1
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Return", format_percentage(result.total_return))
        c2.metric("Sharpe Ratio", format_number(result.sharpe_ratio))
        c3.metric("Max Drawdown", format_percentage(result.max_drawdown))
        c4.metric("Win Rate", format_percentage(result.win_rate))

        # Metrics row 2
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Total Trades", str(result.total_trades))
        c6.metric("Profit Factor", format_number(result.profit_factor))
        c7.metric("Avg Trade Return", format_percentage(result.avg_trade_return))
        c8.metric("Annual Return", format_percentage(result.annual_return))

        # Candlestick chart
        if df is not None:
            st.plotly_chart(create_candlestick_chart(df), use_container_width=True)

        # Equity curve and trade log
        col_eq, col_log = st.columns([1, 1])

        with col_eq:
            st.subheader("Equity Curve")
            st.plotly_chart(
                create_equity_curve_chart(result.equity_curve),
                use_container_width=True,
            )

        with col_log:
            st.subheader("Trade Log")
            trade_df = df_to_trade_log_display(result.trade_log)
            st.dataframe(trade_df, use_container_width=True, height=400)

    # ── TAB 2: Paper Trading (Simulation & Alpaca) ───────────
    with tab_paper:
        if not st.session_state["paper_trading_active"]:
            st.info(
                f"Click **Start {params['mode']}** in the sidebar to begin."
            )
            return

        executor = st.session_state["executor"]
        df = st.session_state["paper_df"]
        idx = st.session_state["paper_bar_index"]
        total_bars = len(df)
        is_alpaca = params["mode"] == "Alpaca Paper Trading"

        st.markdown(f"**{params['mode']}: {params['ticker']}**")

        # Controls
        if is_alpaca:
            if st.button("Refresh Monitor", type="primary"):
                st.rerun()
            st.caption("Monitoring Alpaca Paper Trading account. Updates require manual refresh.")
        else:
            # Progress (Sim only)
            progress = idx / total_bars
            st.progress(progress, text=f"Bar {idx} / {total_bars}")

            # Step controls
            col_step, col_step5, col_all, col_stop = st.columns(4)
            step_one = col_step.button("Next Bar", use_container_width=True)
            step_five = col_step5.button("Next 5 Bars", use_container_width=True)
            step_all = col_all.button("Run All", use_container_width=True)
            stop_btn = col_stop.button("Stop", use_container_width=True)

            if stop_btn:
                st.session_state["paper_trading_active"] = False
                st.rerun()

            if step_one and idx < total_bars:
                step_paper_trading(params)
                st.rerun()

            if step_five:
                for _ in range(5):
                    if st.session_state["paper_bar_index"] < total_bars:
                        step_paper_trading(params)
                st.rerun()

            if step_all:
                while st.session_state["paper_bar_index"] < total_bars:
                    step_paper_trading(params)
                st.rerun()

        # Account Info
        if is_alpaca:
            account = executor.get_account_info()
            if account:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Cash", format_currency(account["cash"]))
                c2.metric("Equity", format_currency(account["equity"]))
                c3.metric("Buying Power", format_currency(account["buying_power"]))
                
                # Calculate Day P&L roughly
                total_pl = account["equity"] - float(DEFAULT_CAPITAL) # Approximation if we don't know start
                # Better: Use account data if available, or just show Equity
                # Alpaca account has 'equity' - 'last_equity' for day change usually, but here we just show totals
                c4.metric("Portfolio Value", format_currency(account["portfolio_value"]))
        
        elif idx > 0 and idx <= total_bars:
            current_price = float(df.iloc[min(idx - 1, total_bars - 1)]["close"])
            account = executor.get_account_info_with_price(
                {params["ticker"]: current_price}
            )
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Cash", format_currency(account["cash"]))
            c2.metric("Market Value", format_currency(account["market_val"]))
            c3.metric("Total Assets", format_currency(account["total_assets"]))
            pnl = account["total_assets"] - executor.initial_capital
            c4.metric(
                "P&L",
                format_currency(pnl),
                delta=format_percentage(pnl / executor.initial_capital),
            )

        # Positions
        positions = executor.get_positions()
        if not positions.empty:
            st.subheader("Current Positions")
            st.dataframe(positions, use_container_width=True)
        else:
            st.info("No open positions.")

        # Chart
        # For Alpaca, we show the historical data we fetched (latest available)
        # For Sim, we show data up to current index
        if is_alpaca:
             visible_df = df # Show all fetched data
             # Re-compute signals/indicators on full df to be sure
             visible_df = generate_signals(visible_df)
             visible_df.attrs["short_window"] = params["short_window"]
             visible_df.attrs["long_window"] = params["long_window"]
             st.subheader("Market Data (Yahoo Finance Delayed)")
             st.plotly_chart(create_candlestick_chart(visible_df), use_container_width=True)
        elif idx > 0:
            visible_df = df.iloc[: idx].copy()
            visible_df = generate_signals(visible_df)
            visible_df.attrs["short_window"] = params["short_window"]
            visible_df.attrs["long_window"] = params["long_window"]
            st.subheader("Price Chart (Bars Seen)")
            st.plotly_chart(create_candlestick_chart(visible_df), use_container_width=True)

        # Execution log (Sim only, or custom Alpaca log if we tracked it)
        if not is_alpaca:
            log = st.session_state["paper_trade_log"]
            if log:
                st.subheader("Execution Log")
                st.dataframe(pd.DataFrame(log), use_container_width=True)


# ─── Entry Point ─────────────────────────────────────────────
def main():
    params = render_sidebar()

    # Handle backtest
    if params["run_backtest"]:
        run_backtest_flow(params)

    # Handle paper trading toggle
    if params["toggle_paper"]:
        if st.session_state["paper_trading_active"]:
            st.session_state["paper_trading_active"] = False
            st.session_state["executor"] = None
            st.session_state["paper_df"] = None
            st.session_state["paper_bar_index"] = 0
            st.session_state["paper_trade_log"] = []
            st.toast("Paper trading stopped")
            st.rerun()
        else:
            if start_paper_trading(params):
                st.toast("Paper trading started — step through bars to simulate")
                st.rerun()

    render_main_area(params)


if __name__ == "__main__":
    main()
