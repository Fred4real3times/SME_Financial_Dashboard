"""Environment-backed application settings without implicit secret generation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = "sqlite:///./.data/sme_financial_dashboard.db"
    app_env: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv(override=False)
        database_url = os.getenv("DATABASE_URL", "sqlite:///./.data/sme_financial_dashboard.db")
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        log_level = os.getenv("APP_LOG_LEVEL", "INFO").strip().upper()
        if not database_url.strip():
            raise ValueError("DATABASE_URL must not be empty")
        if app_env not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test or production")
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("APP_LOG_LEVEL is not a valid logging level")
        return cls(database_url=database_url, app_env=app_env, log_level=log_level)


def ensure_sqlite_parent(database_url: str) -> None:
    """Create the parent directory for a local SQLite file, when applicable."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url in {
        "sqlite:///:memory:",
        "sqlite://",
    }:
        return
    raw_path = database_url.removeprefix(prefix).split("?", maxsplit=1)[0]
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
