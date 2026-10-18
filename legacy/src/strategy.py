import pandas as pd
import numpy as np

def calculate_rsi(series, period=14):
    """Calculates the Relative Strength Index."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_sma_crossover(df, short_window, long_window):
    df['Short_MA'] = df['Close'].rolling(window=short_window, min_periods=1).mean()
    df['Long_MA'] = df['Close'].rolling(window=long_window, min_periods=1).mean()
    df['Signal'] = np.where(df['Short_MA'] > df['Long_MA'], 1.0, 0.0)
    return df

def calculate_ema_crossover(df, short_window, long_window):
    df['Short_MA'] = df['Close'].ewm(span=short_window, adjust=False).mean()
    df['Long_MA'] = df['Close'].ewm(span=long_window, adjust=False).mean()
    df['Signal'] = np.where(df['Short_MA'] > df['Long_MA'], 1.0, 0.0)
    return df

def calculate_sma_long_only(df, window):
    df['Long_MA'] = df['Close'].rolling(window=window, min_periods=1).mean()
    df['Short_MA'] = df['Close'] # For plotting price as "short" line
    df['Signal'] = np.where(df['Close'] > df['Long_MA'], 1.0, 0.0)
    return df

def calculate_rsi_strategy(df, period, overbought, oversold):
    df['RSI'] = calculate_rsi(df['Close'], period)
    df['Short_MA'] = df['Close'] # Plotting
    df['Long_MA'] = df['Close'] # Plotting
    
    # 1 if RSI < oversold (Buy), 0 if RSI > overbought (Sell), else stay
    df['Signal'] = 0.0
    for i in range(1, len(df)):
        if df['RSI'].iloc[i] < oversold:
            df.loc[df.index[i], 'Signal'] = 1.0
        elif df['RSI'].iloc[i] > overbought:
            df.loc[df.index[i], 'Signal'] = 0.0
        else:
            df.loc[df.index[i], 'Signal'] = df['Signal'].iloc[i-1]
    return df

def calculate_bollinger_bands(df, window, num_std):
    df['MA'] = df['Close'].rolling(window=window).mean()
    df['STD'] = df['Close'].rolling(window=window).std()
    df['Upper_Band'] = df['MA'] + (num_std * df['STD'])
    df['Lower_Band'] = df['MA'] - (num_std * df['STD'])
    
    df['Short_MA'] = df['Upper_Band'] # For plotting context
    df['Long_MA'] = df['Lower_Band'] # For plotting context
    
    # Signal = 1 if close crosses above lower band, 0 if close crosses below upper band
    df['Signal'] = 0.0
    for i in range(1, len(df)):
        if df['Close'].iloc[i] < df['Lower_Band'].iloc[i]:
            df.loc[df.index[i], 'Signal'] = 1.0
        elif df['Close'].iloc[i] > df['Upper_Band'].iloc[i]:
            df.loc[df.index[i], 'Signal'] = 0.0
        else:
            df.loc[df.index[i], 'Signal'] = df['Signal'].iloc[i-1]
    return df

def calculate_macd(df, fast=12, slow=26, signal=9):
    fast_ema = df['Close'].ewm(span=fast, adjust=False).mean()
    slow_ema = df['Close'].ewm(span=slow, adjust=False).mean()
    df['MACD'] = fast_ema - slow_ema
    df['MACD_Signal'] = df['MACD'].ewm(span=signal, adjust=False).mean()
    
    # Plotting context
    df['Short_MA'] = df['MACD']
    df['Long_MA'] = df['MACD_Signal']
    
    df['Signal'] = np.where(df['MACD'] > df['MACD_Signal'], 1.0, 0.0)
    return df

def calculate_stochastic(df, k_period=14, d_period=3, overbought=80, oversold=20):
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    df['%K'] = 100 * ((df['Close'] - low_min) / (high_max - low_min))
    df['%D'] = df['%K'].rolling(window=d_period).mean()
    
    # Plotting context
    df['Short_MA'] = df['%K']
    df['Long_MA'] = df['%D']
    
    df['Signal'] = 0.0
    for i in range(1, len(df)):
        if df['%K'].iloc[i] < oversold:
            df.loc[df.index[i], 'Signal'] = 1.0
        elif df['%K'].iloc[i] > overbought:
            df.loc[df.index[i], 'Signal'] = 0.0
        else:
            df.loc[df.index[i], 'Signal'] = df['Signal'].iloc[i-1]
    return df

def calculate_signals(data, strategy_type, params):
    """
    Main entry point for calculating signals based on strategy type.
    """
    df = data.copy()
    
    if strategy_type == "SMA Crossover":
        df = calculate_sma_crossover(df, params['short_window'], params['long_window'])
    elif strategy_type == "EMA Crossover":
        df = calculate_ema_crossover(df, params['short_window'], params['long_window'])
    elif strategy_type == "SMA Long Only":
        df = calculate_sma_long_only(df, params['window'])
    elif strategy_type == "RSI Strategy":
        df = calculate_rsi_strategy(df, params['period'], params['overbought'], params['oversold'])
    elif strategy_type == "Bollinger Bands":
        df = calculate_bollinger_bands(df, params['window'], params['num_std'])
    elif strategy_type == "MACD Crossover":
        df = calculate_macd(df, params['fast'], params['slow'], params['signal'])
    elif strategy_type == "Stochastic Oscillator":
        df = calculate_stochastic(df, params['k_period'], params['d_period'], params['overbought'], params['oversold'])
    
    # Generate trading orders (1 = Buy, -1 = Sell) for the simulator
    df['Position'] = df['Signal'].diff()
    
    return df
