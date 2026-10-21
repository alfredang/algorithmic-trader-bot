# Bundled market data (offline mode)

| Item | Detail |
|---|---|
| Source | Yahoo Finance, downloaded with the `yfinance` Python package (`auto_adjust=True`) |
| Download date | 2026-10-18 (TSLA added 2026-10-22, same method) |
| Daily files | `SPY, QQQ, AAPL, MSFT, NVDA, TSLA, JPM, GLD, TLT, XLF, KO, PEP, BAC` - one CSV each, 2018-01-02 to 2025-12-31 (2,011 sessions) |
| Hourly file | `SPY_1Hour.csv` - last ~700 trading days available from Yahoo (2024-01-03 to 2026-10-16), US/Eastern timestamps with UTC offset |
| Columns | `timestamp, open, high, low, close, volume` |
| Adjustment | Prices are split- and dividend-adjusted, so they differ from unadjusted prices shown by default on TradingView or in broker statements |

**For training use only.** Yahoo Finance data is provided for personal, educational use; it is
not suitable for live trading decisions and must not be redistributed commercially. When Alpaca
keys are configured the labs use the Alpaca Market Data API (IEX feed) instead of these files.
Market data contains no personal data.
