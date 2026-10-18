import pandas as pd
import numpy as np

def calculate_metrics(df: pd.DataFrame, risk_free_rate: float = 0.0) -> dict:
    """
    Calculates key performance metrics.
    """
    returns = df['Strategy_Returns'].dropna()
    
    total_return = (df['Equity_Curve'].iloc[-1] / df['Equity_Curve'].iloc[0]) - 1
    annual_return = (1 + total_return) ** (252 / len(df)) - 1
    
    volatility = returns.std() * np.sqrt(252)
    sharpe_ratio = (annual_return - risk_free_rate) / volatility if volatility != 0 else 0
    
    max_drawdown = df['Drawdown'].min()
    market_return = (df['Close'].iloc[-1] / df['Close'].iloc[0]) - 1
    
    return {
        "Total Return": f"{total_return:.2%}",
        "Market Return": f"{market_return:.2%}",
        "Annualized Return": f"{annual_return:.2%}",
        "Annualized Volatility": f"{volatility:.2%}",
        "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Max Drawdown": f"{max_drawdown:.2%}"
    }
