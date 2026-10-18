"""Persistent tables."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trader.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid.uuid4())


class Instrument(Base):
    __tablename__ = "instruments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    asset_class: Mapped[str] = mapped_column(String(32), default="us_equity")
    exchange: Mapped[str] = mapped_column(String(32), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    tradingview_symbol: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(32), default="demo")
    first_bar: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_bar: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quality: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Bar(Base):
    __tablename__ = "bars"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "ts", "source", name="uq_bar"),
                      Index("ix_bars_symbol_tf_ts", "symbol", "timeframe", "ts"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(16), default="1Day")
    ts: Mapped[datetime] = mapped_column(DateTime)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(32), default="demo")


class NewsItem(Base):
    __tablename__ = "news"
    __table_args__ = (UniqueConstraint("symbol", "headline", "published_at", name="uq_news"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    headline: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    source: Mapped[str] = mapped_column(String(64), default="demo")
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_model: Mapped[str] = mapped_column(String(32), default="vader")
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SentimentDaily(Base):
    __tablename__ = "sentiment_daily"
    __table_args__ = (UniqueConstraint("symbol", "day", "model", name="uq_sentiment_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    day: Mapped[date] = mapped_column(Date)
    score: Mapped[float] = mapped_column(Float)
    n_items: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(32), default="vader")
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class StrategyRecord(Base):
    __tablename__ = "strategies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="signal")
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_schema: Mapped[list | None] = mapped_column(JSON, nullable=True)
    default_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parent_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    multi_asset: Mapped[bool] = mapped_column(Boolean, default=False)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Backtest(Base):
    __tablename__ = "backtests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    strategy_key: Mapped[str] = mapped_column(String(64), index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    timeframe: Mapped[str] = mapped_column(String(16), default="1Day")
    start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    end: Mapped[str | None] = mapped_column(String(32), nullable=True)
    benchmark: Mapped[str] = mapped_column(String(32), default="SPY")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="done")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    gross_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    benchmark_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cost_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    series: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # equity, gross, benchmark, drawdown...
    trades: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)        # strategy-specific diagnostics
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ResearchRun(Base):
    __tablename__ = "research_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)   # hypothesis|grid|walk_forward|abtest|regime|diagnostics|pairs|execution
    name: Mapped[str] = mapped_column(String(200), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="done")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Account(Base):
    """A paper account: a simulator book or the Alpaca PAPER account."""
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    broker: Mapped[str] = mapped_column(String(16), default="sim")       # sim | alpaca_paper
    cash: Mapped[float] = mapped_column(Float, default=100_000.0)
    starting_cash: Mapped[float] = mapped_column(Float, default=100_000.0)
    last_equity: Mapped[float] = mapped_column(Float, default=100_000.0)
    sim_clock: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Bot(Base):
    __tablename__ = "bots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    strategy_key: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    timeframe: Mapped[str] = mapped_column(String(16), default="1Day")
    schedule: Mapped[str] = mapped_column(String(64), default="*/1 * * * *")   # cron (minute hour dom month dow)
    broker: Mapped[str] = mapped_column(String(16), default="sim")
    data_mode: Mapped[str] = mapped_column(String(16), default="replay")       # replay (offline, one bar per cycle) | live
    sizing: Mapped[dict] = mapped_column(JSON, default=dict)
    risk: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="stopped")         # stopped|running|halted|error
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    backtest_id: Mapped[int | None] = mapped_column(Integer, nullable=True)    # backtest used for comparison
    replay_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cursor: Mapped[str | None] = mapped_column(String(32), nullable=True)       # last replayed bar date
    cycles: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extended_hours: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    bot_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[float] = mapped_column(Float)
    type: Mapped[str] = mapped_column(String(16), default="market")            # market|limit|stop|stop_limit
    time_in_force: Mapped[str] = mapped_column(String(8), default="day")
    order_class: Mapped[str] = mapped_column(String(16), default="simple")     # simple|bracket|oco
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    extended_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="new")
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    filled_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    broker: Mapped[str] = mapped_column(String(16), default="sim")
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")          # manual|bot|webhook|agent
    session: Mapped[str] = mapped_column(String(16), default="regular")
    note: Mapped[str] = mapped_column(Text, default="")
    history: Mapped[list] = mapped_column(JSON, default=list)                   # lifecycle [{status, ts}]
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    bot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    costs: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_position"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    last_price: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PnLSnapshot(Base):
    __tablename__ = "pnl_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    bot_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    bar_time: Mapped[str | None] = mapped_column(String(32), nullable=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    positions_value: Mapped[float] = mapped_column(Float, default=0.0)
    realized: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized: Mapped[float] = mapped_column(Float, default=0.0)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="desk")          # desk | always_on
    provider: Mapped[str] = mapped_column(String(32), default="rules")
    auth_mode: Mapped[str] = mapped_column(String(32), default="none")
    model: Mapped[str] = mapped_column(String(64), default="")
    orchestration: Mapped[str] = mapped_column(String(32), default="pipeline")
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    trace: Mapped[list] = mapped_column(JSON, default=list)                 # one entry per agent per symbol
    proposals: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="proposed")    # proposed|approved|rejected|executed|no_trade|error
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    orders: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AgentMemory(Base):
    __tablename__ = "agent_memory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), index=True)              # symbol or 'market'
    kind: Mapped[str] = mapped_column(String(32), default="observation")    # observation|decision|lesson
    content: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class WebhookAlert(Base):
    __tablename__ = "webhook_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    alert_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    client: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)        # secret redacted
    ticker: Mapped[str] = mapped_column(String(32), default="")
    action: Mapped[str] = mapped_column(String(16), default="")
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    http_status: Mapped[int] = mapped_column(Integer, default=200)
    result: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    pipeline_signal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Setting(Base):
    """Non-secret preferences and integration options (API keys stay in .env)."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Event(Base):
    """Append-only event stream; the SSE endpoint tails it (works across API and worker processes)."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class StageEvent(Base):
    """Pipeline Map: one row per stage activity (ok / warning / error / running)."""
    __tablename__ = "stage_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    stage: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    message: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)   # backtest|bot|agent_run|research|order
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)     # groups a bot cycle's stages


class LabProgress(Base):
    __tablename__ = "lab_progress"
    __table_args__ = (UniqueConstraint("user", "lab_id", "step_index", name="uq_lab_step"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user: Mapped[str] = mapped_column(String(64), default="local", index=True)
    lab_id: Mapped[int] = mapped_column(Integer)
    step_index: Mapped[int] = mapped_column(Integer)
    done: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
