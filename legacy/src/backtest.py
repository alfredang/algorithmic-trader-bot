import pandas as pd
import numpy as np

def run_backtest(data: pd.DataFrame, initial_capital: float = 100000.0) -> pd.DataFrame:
    """
    Runs a vectorized backtest based on signals and positions.
    """
    df = data.copy()
    
    # Buy and hold returns
    df['Market_Returns'] = df['Close'].pct_change()
    
    # Strategy returns (Shift Signal by 1 to avoid lookahead bias)
    df['Strategy_Returns'] = df['Market_Returns'] * df['Signal'].shift(1)
    
    # Cumulative returns
    df['Equity_Curve'] = (1.0 + df['Strategy_Returns'].fillna(0)).cumprod() * initial_capital
    
    # Drawdown
    df['Peak'] = df['Equity_Curve'].cummax()
    df['Drawdown'] = (df['Equity_Curve'] - df['Peak']) / df['Peak']
    
    return df
