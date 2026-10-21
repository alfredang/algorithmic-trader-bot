"""Shared fixtures: a temporary SQLite database migrated with Alembic and seeded with demo data (offline)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

_TMP = Path(tempfile.mkdtemp(prefix="qts-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["AI_PROVIDER"] = "rules"
os.environ["DATA_DIR"] = str(_TMP / "data")          # never touch a real data/keys.env
for k in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "NEWSAPI_KEY", "TWELVEDATA_API_KEY", "EQUIBLES_API_KEY",
          "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "WEBHOOK_SECRET"):
    os.environ[k] = ""

from trader import db as DB  # noqa: E402
from trader.config import DEMO_DIR, reset_settings  # noqa: E402

reset_settings()


def demo(symbol: str) -> pd.DataFrame:
    return pd.read_csv(DEMO_DIR / f"{symbol}.csv", parse_dates=["timestamp"], index_col="timestamp")


@pytest.fixture(scope="session")
def seeded():
    DB.configure(os.environ["DATABASE_URL"])
    DB.migrate()
    from trader.data import service as data
    from trader.services.seed import seed
    with DB.session_scope() as s:
        seed(s, quick=True, log_fn=lambda *a: None)
        for sym in ("QQQ", "TLT"):
            data.load_bars(s, sym)
    return True


@pytest.fixture()
def db(seeded):
    s = DB.SessionLocal()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient

    from trader.api.app import create_app
    with TestClient(create_app(start_worker=False, migrate=False)) as c:
        yield c


@pytest.fixture()
def spy():
    return demo("SPY")
