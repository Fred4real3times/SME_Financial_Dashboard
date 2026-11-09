"""SQLite-aware SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sme_financial_dashboard.config import Settings, ensure_sqlite_parent


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    ensure_sqlite_parent(database_url)
    connect_args: dict[str, object] = {}
    engine_options: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
    if database_url.startswith("sqlite:"):
        connect_args["check_same_thread"] = False
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            engine_options["poolclass"] = StaticPool
        engine_options["connect_args"] = connect_args

    engine = create_engine(database_url, **engine_options)
    if database_url.startswith("sqlite:"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def build_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    active_settings = settings or Settings.from_environment()
    engine = build_engine(active_settings.database_url, echo=False)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transaction boundary that always closes its session."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
