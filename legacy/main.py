import yaml
import logging
from src.data import fetch_data
from src.strategy import calculate_signals
from src.backtest import run_backtest
from src.metrics import calculate_metrics
from src.utils import plot_results

def main():
    # Load config
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    symbol = config['symbol']
    start_date = config['start_date']
    end_date = config['end_date']
    short_window = config['strategy']['short_window']
    long_window = config['strategy']['long_window']
    initial_capital = config['strategy']['initial_capital']
    
    # 1. Fetch Data
    data = fetch_data(symbol, start_date, end_date)
    
    # 2. Calculate Signals
    data_with_signals = calculate_signals(data, short_window, long_window)
    
    # 3. Run Backtest
    results = run_backtest(data_with_signals, initial_capital)
    
    # 4. Calculate Metrics
    metrics = calculate_metrics(results)
    print("\n--- Performance Metrics ---")
    for k, v in metrics.items():
        print(f"{k}: {v}")
    
    # 5. Plot Results
    plot_results(results, symbol)

if __name__ == "__main__":
    main()
