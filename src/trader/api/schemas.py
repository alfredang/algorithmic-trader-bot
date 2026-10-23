"""Request bodies for the REST API (responses are plain JSON dicts)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FetchRequest(BaseModel):
    symbol: str = Field(..., examples=["SPY"])
    timeframe: str = Field("1Day", examples=["1Day", "1Hour"])
    source: str = Field("auto", description="auto | demo | alpaca | twelvedata | yfinance")
    start: str | None = "2018-01-01"
    end: str | None = None


class NewsFetchRequest(BaseModel):
    symbol: str
    source: str = Field("auto", description="auto | newsapi | alpaca | demo")
    query: str | None = None
    days: int = 7


class BacktestRequest(BaseModel):
    strategy_key: str = Field(..., examples=["ema_cross"])
    symbols: list[str] | None = Field(None, examples=[["SPY"]])
    params: dict[str, Any] = Field(default_factory=dict, examples=[{"fast": 20, "slow": 50}])
    start: str | None = None
    end: str | None = None
    timeframe: str | None = None
    benchmark: str = "SPY"
    name: str | None = None
    day: str | None = Field(None, description="execution algorithms: session date")
    config: dict[str, Any] = Field(default_factory=dict, description="BacktestConfig: costs (preset name or dict), "
                                   "execution, allow_short, sizing, size_pct, vol_target, stop_loss_pct, take_profit_pct...")


class StrategyCode(BaseModel):
    code: str
    symbol: str = "SPY"
    symbols: list[str] | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class StrategySave(StrategyCode):
    key: str | None = None
    info: dict[str, Any] = Field(default_factory=dict)
    parent_key: str | None = None


class BotRequest(BaseModel):
    name: str
    strategy_key: str
    params: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=lambda: ["SPY"])
    timeframe: str = "1Day"
    schedule: str = Field("every 10s", description="cron (minute hour dom month dow, New York time) or 'every 30s'")
    broker: str = Field("sim", description="sim | alpaca_paper")
    data_mode: str = Field("replay", description="replay (offline, one bar per cycle) | live")
    replay_start: str | None = "2025-01-02"
    sizing: dict[str, Any] = Field(default_factory=lambda: {"mode": "percent_equity", "pct": 0.95})
    risk: dict[str, Any] = Field(default_factory=dict)
    extended_hours: bool = True


class OrderTicket(BaseModel):
    symbol: str
    side: str = Field(..., description="buy | sell")
    qty: float
    type: str = Field("auto", description="auto | market | limit | stop")
    time_in_force: str = "day"
    limit_price: float | None = None
    stop_price: float | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    extended_hours: bool = False
    order_class: str = "simple"
    account: str = "Default paper account"
    client_order_id: str | None = None
    session_override: str | None = Field(None, description="simulator only: regular | pre | after | overnight | closed")


class AgentRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["NVDA", "AAPL", "SPY"])
    provider: str | None = Field(None, description="auto | rules | codex | claude | openai")
    orchestration: str = Field("native", description="native (SDK multi-agent) | pipeline (one call per agent)")
    live_id: str | None = Field(None, max_length=64, description="client id to follow the run live at /api/agents/live/{live_id}")


class AlwaysOnConfig(BaseModel):
    enabled: bool = False
    interval_min: int = 60
    symbols: list[str] = Field(default_factory=lambda: ["NVDA", "AAPL", "SPY"])
    provider: str = "auto"
    refresh_news: bool = True
