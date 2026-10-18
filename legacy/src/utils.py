import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

def plot_interactive_results(df: pd.DataFrame, symbol: str):
    """
    Creates an interactive Plotly chart with buy/sell signals and equity curve.
    """
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.1, 
                        subplot_titles=(f"{symbol} - Price and Signals", "Equity Curve"),
                        row_heights=[0.7, 0.3])

    # Price and Moving Averages
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name='Close', line=dict(color='rgba(100, 100, 100, 0.4)')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Short_MA'], name='Short MA', line=dict(color='blue')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Long_MA'], name='Long MA', line=dict(color='red')), row=1, col=1)

    # Buy Signals
    buy_signals = df[df['Position'] == 1]
    fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Short_MA'], 
                             mode='markers', name='Buy', 
                             marker=dict(symbol='triangle-up', size=12, color='green')), row=1, col=1)

    # Sell Signals
    sell_signals = df[df['Position'] == -1]
    fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Short_MA'], 
                             mode='markers', name='Sell', 
                             marker=dict(symbol='triangle-down', size=12, color='red')), row=1, col=1)

    # Equity Curves
    fig.add_trace(go.Scatter(x=df.index, y=df['Equity_Curve'], name='Strategy Equity', line=dict(color='orange')), row=2, col=1)
    
    # Calculate Buy & Hold Equity Curve for comparison
    bh_equity = (1.0 + df['Market_Returns'].fillna(0)).cumprod() * df['Equity_Curve'].iloc[0]
    fig.add_trace(go.Scatter(x=df.index, y=bh_equity, name='Buy & Hold', line=dict(color='gray', dash='dash')), row=2, col=1)

    fig.update_layout(height=800, template='plotly_dark', showlegend=True)
    return fig

def plot_results(df: pd.DataFrame, symbol: str):
    # Existing matplotlib code remains...
    """
    Plots the price, moving averages, signals, and equity curve.
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    
    # Plot Price and MAs
    ax1.plot(df.index, df['Close'], label='Close Price', alpha=0.5)
    ax1.plot(df.index, df['Short_MA'], label='Short MA', alpha=0.8)
    ax1.plot(df.index, df['Long_MA'], label='Long MA', alpha=0.8)
    
    # Plot Buy/Sell signals
    ax1.plot(df[df['Position'] == 1].index, 
             df['Short_MA'][df['Position'] == 1], 
             '^', markersize=10, color='g', label='Buy Signal')
    ax1.plot(df[df['Position'] == -1].index, 
             df['Short_MA'][df['Position'] == -1], 
             'v', markersize=10, color='r', label='Sell Signal')
    
    ax1.set_title(f"{symbol} - Moving Average Crossover")
    ax1.legend()
    ax1.grid()
    
    # Plot Equity Curve
    ax2.plot(df.index, df['Equity_Curve'], label='Strategy Equity Curve', color='orange')
    ax2.set_title("Equity Curve")
    ax2.legend()
    ax2.grid()
    
    plt.tight_layout()
    plt.savefig('backtest_results.png')
    plt.close()
    print("Results plotted and saved to 'backtest_results.png'")
