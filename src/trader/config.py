"""Application settings (pydantic-settings). Every value can be set in the environment or in ``.env``.

Secrets are read from the environment only; they are never written to the database
and the API only ever returns masked values.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]          # repo root when run from a checkout
PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- core
    app_name: str = "Quant Trading Simulator"
    database_url: str = Field("sqlite:///./data/trader.db", alias="DATABASE_URL")
    data_dir: Path = Field(Path("./data"), alias="DATA_DIR")
    host: str = Field("127.0.0.1", alias="APP_HOST")
    port: int = Field(8000, alias="APP_PORT")
    log_level: str = Field("info", alias="LOG_LEVEL")
    cors_origins: str = Field("", alias="CORS_ORIGINS")
    serve_frontend: bool = Field(True, alias="SERVE_FRONTEND")
    run_scheduler_in_process: bool = Field(False, alias="RUN_SCHEDULER_IN_PROCESS")
    auto_seed: bool = Field(False, alias="AUTO_SEED")
    timezone_desk: str = Field("Asia/Singapore", alias="DESK_TIMEZONE")

    # --- market data / broker (Alpaca PAPER only - there is no live-trading code path)
    alpaca_key_id: str = Field("", alias="APCA_API_KEY_ID")
    alpaca_secret_key: str = Field("", alias="APCA_API_SECRET_KEY")
    alpaca_data_feed: str = Field("iex", alias="APCA_DATA_FEED")
    twelvedata_api_key: str = Field("", alias="TWELVEDATA_API_KEY")
    newsapi_key: str = Field("", alias="NEWSAPI_KEY")
    default_data_source: str = Field("auto", alias="DEFAULT_DATA_SOURCE")   # auto|demo|alpaca|twelvedata|yfinance

    # --- AI agents
    ai_provider: str = Field("auto", alias="AI_PROVIDER")                 # auto|rules|claude|openai|codex
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    claude_model: str = Field("claude-sonnet-5-5", alias="CLAUDE_MODEL")
    claude_model_deep: str = Field("claude-opus-5-5", alias="CLAUDE_MODEL_DEEP")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openai_model: str = Field("", alias="OPENAI_MODEL")                   # blank = the Agents SDK default
    codex_model: str = Field("", alias="CODEX_MODEL")                     # blank = the Codex CLI default
    agent_timeout_s: int = Field(120, alias="AGENT_TIMEOUT_S")
    agent_auto_approve: bool = Field(False, alias="AGENT_AUTO_APPROVE")
    always_on_interval_min: int = Field(60, alias="ALWAYS_ON_INTERVAL_MIN")

    # --- TradingView webhook
    webhook_secret: str = Field("", alias="WEBHOOK_SECRET")

    # --- custom strategy sandbox
    sandbox_timeout_s: int = Field(30, alias="SANDBOX_TIMEOUT_S")
    sandbox_memory_mb: int = Field(1024, alias="SANDBOX_MEMORY_MB")

    @property
    def alpaca_configured(self) -> bool:
        return bool(self.alpaca_key_id and self.alpaca_secret_key)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()


def mask(value: str | None) -> str:
    """Show only enough of a secret to recognise it: 'PKAB...9XYZ'."""
    if not value:
        return ""
    v = str(value)
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}...{v[-4:]}"


DEMO_DIR = PACKAGE_DIR / "data" / "demo"
WEB_DIR = PACKAGE_DIR / "web"
LABS_MANIFEST = ROOT / "labs" / "course_labs.yaml"
