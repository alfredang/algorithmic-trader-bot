"""Database engine and session (SQLAlchemy 2). SQLite by default, Postgres in Docker Compose."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from trader.config import ROOT, get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_Session: sessionmaker | None = None


def _make_engine(url: str) -> Engine:
    kw: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        path = url.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
    eng = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _):              # concurrent reader + writer (API + worker processes)
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return eng


def get_engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        _engine = _make_engine(get_settings().database_url)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def configure(url: str) -> Engine:
    """Point the app at another database (used by tests and the CLI)."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = _make_engine(url)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def SessionLocal() -> Session:
    get_engine()
    assert _Session is not None
    return _Session()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def migrate(url: str | None = None) -> None:
    """Apply Alembic migrations (``alembic upgrade head``) to the configured database."""
    from alembic import command
    from alembic.config import Config

    url = url or get_settings().database_url
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def create_all() -> None:
    """Create tables directly from the models (tests only - the app uses Alembic)."""
    from trader import models  # noqa: F401
    Base.metadata.create_all(get_engine())
