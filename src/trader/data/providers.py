"""Market-data providers: bundled offline demo CSVs, Alpaca Market Data, Twelve Data and yfinance.

Every provider returns a DataFrame indexed by timestamp with columns
open, high, low, close, volume. Daily bars are tz-naive session dates;
intraday bars are tz-aware America/New_York timestamps.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import httpx
import pandas as pd

from trader.config import DEMO_DIR, get_settings

COLUMNS = ["open", "high", "low", "close", "volume"]
RESAMPLE = {"1Week": "W-FRI", "1Month": "ME"}
TIMEFRAMES = ["1Day", "1Week", "1Month", "1Hour"]
DEMO_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "JPM", "XLF", "KO", "PEP", "BAC", "GLD", "TLT"]
ET = "America/New_York"


class DataError(RuntimeError):
    pass


def _clip(df: pd.DataFrame, start, end) -> pd.DataFrame:
    tz = getattr(df.index, "tz", None)
    if start:
        df = df[df.index >= pd.Timestamp(start, tz=tz) if tz else df.index >= pd.Timestamp(start)]
    if end:
        e = pd.Timestamp(end, tz=tz) if tz else pd.Timestamp(end)
        df = df[df.index <= e + pd.Timedelta(hours=23, minutes=59)]
    return df


def resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe not in RESAMPLE:
        return df
    return df.resample(RESAMPLE[timeframe]).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


# --------------------------------------------------------------------------- offline demo
class DemoProvider:
    name = "demo"
    label = "Bundled demo data (Yahoo Finance via yfinance, 2018-2025; offline)"

    def available(self) -> bool:
        return True

    def symbols(self) -> list[str]:
        return sorted(p.stem for p in DEMO_DIR.glob("*.csv") if "_" not in p.stem)

    def bars(self, symbol: str, timeframe: str = "1Day", start=None, end=None) -> pd.DataFrame:
        if timeframe.endswith(("Min", "Hour")):
            path = DEMO_DIR / f"{symbol}_{timeframe}.csv"
            if not path.exists():
                raise DataError(f"No offline {timeframe} demo file for {symbol} (bundled: SPY 1Hour only).")
            df = pd.read_csv(path)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(ET)
            df = df.set_index("timestamp")
        else:
            path = DEMO_DIR / f"{symbol}.csv"
            if not path.exists():
                raise DataError(f"No offline demo data for {symbol}. Demo symbols: {', '.join(self.symbols())}")
            df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
        df = resample(_clip(df, start, end), timeframe)
        return df[COLUMNS].astype(float)

    def raw_reference(self, symbol: str) -> pd.DataFrame | None:
        """Split-adjusted but dividend-UNadjusted reference bars (TradingView's default view) for Lab 02."""
        path = DEMO_DIR / f"{symbol}_1Day_raw.csv"
        if not path.exists():
            return None
        return pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")


# --------------------------------------------------------------------------- Alpaca
class AlpacaProvider:
    name = "alpaca"
    label = "Alpaca Market Data API (IEX feed, adjusted)"

    def available(self) -> bool:
        return get_settings().alpaca_configured

    def _client(self):
        from alpaca.data.historical import StockHistoricalDataClient
        s = get_settings()
        return StockHistoricalDataClient(api_key=s.alpaca_key_id, secret_key=s.alpaca_secret_key)

    @staticmethod
    def _tf(timeframe: str):
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        units = {"Min": TimeFrameUnit.Minute, "Hour": TimeFrameUnit.Hour, "Day": TimeFrameUnit.Day,
                 "Week": TimeFrameUnit.Week, "Month": TimeFrameUnit.Month}
        for suffix, unit in units.items():
            if timeframe.endswith(suffix):
                return TimeFrame(int(timeframe[: -len(suffix)] or 1), unit)
        raise DataError(f"Unsupported timeframe {timeframe}")

    def bars(self, symbol: str, timeframe: str = "1Day", start=None, end=None) -> pd.DataFrame:
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest
        feed = DataFeed.SIP if get_settings().alpaca_data_feed.lower() == "sip" else DataFeed.IEX
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=self._tf(timeframe),
                               start=pd.Timestamp(start or "2018-01-01").to_pydatetime(),
                               end=pd.Timestamp(end).to_pydatetime() if end else None,
                               adjustment=Adjustment.ALL, feed=feed)
        df = self._client().get_stock_bars(req).df
        if df.empty:
            raise DataError(f"Alpaca returned no bars for {symbol}")
        df = df.xs(symbol, level="symbol")[COLUMNS]
        if timeframe.endswith(("Day", "Week", "Month")):
            df.index = df.index.tz_convert(ET).tz_localize(None).normalize()
        else:
            df.index = df.index.tz_convert(ET)
        df.index.name = "timestamp"
        return df.astype(float)

    def latest_quote(self, symbol: str) -> dict:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest
        c = self._client()
        try:
            q = c.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX))[symbol]
            if q.bid_price and q.ask_price and q.ask_price >= q.bid_price > 0:
                return {"bid": float(q.bid_price), "ask": float(q.ask_price),
                        "last": (float(q.bid_price) + float(q.ask_price)) / 2, "source": "alpaca quote (IEX)"}
        except Exception:
            pass
        t = c.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX))[symbol]
        px = float(t.price)
        return {"bid": px, "ask": px, "last": px, "source": "alpaca latest trade"}

    def news(self, symbol: str, days: int = 7, limit: int = 20) -> list[dict]:
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest
        s = get_settings()
        client = NewsClient(api_key=s.alpaca_key_id, secret_key=s.alpaca_secret_key)
        res = client.get_news(NewsRequest(symbols=symbol, start=datetime.now() - timedelta(days=days), limit=limit))
        items = res.data.get("news", []) if hasattr(res, "data") else []
        return [{"symbol": symbol, "published_at": pd.Timestamp(n.created_at).tz_localize(None) if pd.Timestamp(n.created_at).tzinfo is None
                 else pd.Timestamp(n.created_at).tz_convert("UTC").tz_localize(None),
                 "headline": n.headline, "summary": getattr(n, "summary", "") or "", "url": getattr(n, "url", "") or "",
                 "source": "alpaca"} for n in items]


# --------------------------------------------------------------------------- Twelve Data
class TwelveDataProvider:
    name = "twelvedata"
    label = "Twelve Data time-series API"
    URL = "https://api.twelvedata.com"
    INTERVALS = {"1Day": "1day", "1Week": "1week", "1Month": "1month", "1Hour": "1h", "15Min": "15min", "5Min": "5min",
                 "1Min": "1min"}

    def available(self) -> bool:
        return bool(get_settings().twelvedata_api_key)

    def bars(self, symbol: str, timeframe: str = "1Day", start=None, end=None) -> pd.DataFrame:
        key = get_settings().twelvedata_api_key
        if not key:
            raise DataError("TWELVEDATA_API_KEY is not set")
        params = {"symbol": symbol, "interval": self.INTERVALS.get(timeframe, "1day"), "outputsize": 5000,
                  "order": "asc", "timezone": ET, "format": "JSON"}
        if start:
            params["start_date"] = str(pd.Timestamp(start).date())
        if end:
            params["end_date"] = str(pd.Timestamp(end).date())
        r = httpx.get(f"{self.URL}/time_series", params=params, headers={"Authorization": f"apikey {key}"}, timeout=30)
        return self.parse(r.json(), timeframe)

    @staticmethod
    def parse(js: dict, timeframe: str = "1Day") -> pd.DataFrame:
        if js.get("status") != "ok":
            raise DataError(f"Twelve Data error: {js.get('message', js)}")
        df = pd.DataFrame(js["values"])
        df["timestamp"] = pd.to_datetime(df["datetime"])
        if "volume" not in df:
            df["volume"] = 0
        df = df.set_index("timestamp")[COLUMNS].astype(float).sort_index()
        if timeframe.endswith(("Min", "Hour")):
            df.index = df.index.tz_localize(ET)
        return df

    def test(self) -> dict:
        key = get_settings().twelvedata_api_key
        r = httpx.get(f"{self.URL}/api_usage", headers={"Authorization": f"apikey {key}"}, timeout=15)
        js = r.json()
        if js.get("status") == "error":
            raise DataError(js.get("message", "error"))
        return js


# --------------------------------------------------------------------------- yfinance
class YFinanceProvider:
    name = "yfinance"
    label = "Yahoo Finance via yfinance (fallback, personal/educational use)"

    def available(self) -> bool:
        return True

    def bars(self, symbol: str, timeframe: str = "1Day", start=None, end=None) -> pd.DataFrame:
        import yfinance as yf
        interval = {"1Day": "1d", "1Week": "1wk", "1Month": "1mo", "1Hour": "1h"}.get(timeframe, "1d")
        kw = {"interval": interval, "auto_adjust": True}
        if interval == "1h":
            kw["period"] = "700d"
        else:
            kw["start"] = str(pd.Timestamp(start or "2018-01-01").date())
            if end:
                kw["end"] = str((pd.Timestamp(end) + pd.Timedelta(days=1)).date())
        df = yf.Ticker(symbol).history(**kw)
        if df is None or df.empty:
            raise DataError(f"yfinance returned no data for {symbol}")
        df = df.rename(columns=str.lower)[COLUMNS]
        if interval == "1h":
            df.index = df.index.tz_convert(ET)
        else:
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df.index.name = "timestamp"
        return df.astype(float)


PROVIDERS = {p.name: p for p in (DemoProvider(), AlpacaProvider(), TwelveDataProvider(), YFinanceProvider())}


def resolve_source(symbol: str, source: str = "auto") -> str:
    """auto: Alpaca if keys are set, else the bundled demo file if one exists, else yfinance."""
    if source and source != "auto":
        if source not in PROVIDERS:
            raise DataError(f"unknown data source {source}")
        return source
    pref = get_settings().default_data_source
    if pref and pref != "auto" and PROVIDERS.get(pref) and PROVIDERS[pref].available():
        return pref
    if PROVIDERS["alpaca"].available():
        return "alpaca"
    if (DEMO_DIR / f"{symbol}.csv").exists():
        return "demo"
    return "yfinance"


def fetch(symbol: str, timeframe: str = "1Day", start=None, end=None, source: str = "auto") -> tuple[pd.DataFrame, str]:
    """Fetch bars from a provider, falling back to the demo file (if any) when an online source fails."""
    src = resolve_source(symbol, source)
    try:
        return PROVIDERS[src].bars(symbol, timeframe, start, end), src
    except Exception as exc:
        if src != "demo" and ((DEMO_DIR / f"{symbol}.csv").exists() or timeframe == "1Hour" and symbol == "SPY"):
            return PROVIDERS["demo"].bars(symbol, timeframe, start, end), "demo"
        short = " ".join(re.sub(r"<[^>]+>", " ", str(exc)).split())[:200]
        raise DataError(f"{src} failed for {symbol}: {short}") from exc
