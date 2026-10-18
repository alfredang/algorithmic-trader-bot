import sqlite3
import tempfile
from pathlib import Path

from trader.db import migrate


def test_alembic_upgrade_creates_all_tables():
    path = Path(tempfile.mkdtemp()) / "m.db"
    migrate(f"sqlite:///{path}")
    tables = {r[0] for r in sqlite3.connect(path).execute("select name from sqlite_master where type='table'")}
    for t in ("instruments", "bars", "news", "sentiment_daily", "strategies", "backtests", "research_runs", "bots", "orders",
              "fills", "positions", "pnl_snapshots", "agent_runs", "agent_memory", "webhook_alerts", "settings", "audit_log",
              "events", "stage_events", "lab_progress", "accounts"):
        assert t in tables, t
