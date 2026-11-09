from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.base import Base
from sme_financial_dashboard.db.models import Workspace
from sme_financial_dashboard.ops.sqlite_backup import (
    SQLiteBackupError,
    create_sqlite_backup,
    restore_sqlite_backup,
)


def _create_database(path: Path, workspace_name: str) -> None:
    engine = create_engine(f"sqlite:///{path}")
    event.listen(
        engine,
        "connect",
        lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('qa-revision')")
    with Session(engine) as session, session.begin():
        session.add(Workspace(name=workspace_name))
    engine.dispose()


def _workspace_names(path: Path) -> list[str]:
    # sqlite3.Connection's context manager commits/rolls back but does not close.
    # Close explicitly so Windows releases the file handle before os.replace().
    with closing(sqlite3.connect(path)) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT name FROM workspaces ORDER BY name")
        ]


def test_backup_creates_verified_consistent_copy_and_sha256(tmp_path: Path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    _create_database(source, "Synthetic source workspace")

    report = create_sqlite_backup(source, backup)

    assert report.source == source.resolve()
    assert report.destination == backup.resolve()
    assert report.integrity_status == "ok"
    assert report.foreign_key_violations == 0
    assert report.size_bytes == backup.stat().st_size
    assert len(report.sha256) == 64
    assert _workspace_names(backup) == ["Synthetic source workspace"]


def test_backup_never_overwrites_without_explicit_flag(tmp_path: Path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    _create_database(source, "Workspace one")
    _create_database(backup, "Preserve me")

    with pytest.raises(SQLiteBackupError, match="already exists"):
        create_sqlite_backup(source, backup)
    assert _workspace_names(backup) == ["Preserve me"]

    report = create_sqlite_backup(source, backup, overwrite=True)
    assert report.integrity_status == "ok"
    assert _workspace_names(backup) == ["Workspace one"]


def test_restore_requires_explicit_replace_and_preserves_backup(tmp_path: Path):
    source = tmp_path / "source.db"
    backup = tmp_path / "source-backup.db"
    destination = tmp_path / "application.db"
    _create_database(source, "Restored workspace")
    _create_database(destination, "Old target workspace")
    create_sqlite_backup(source, backup)

    with pytest.raises(SQLiteBackupError, match="already exists"):
        restore_sqlite_backup(backup, destination)
    assert _workspace_names(destination) == ["Old target workspace"]

    report = restore_sqlite_backup(backup, destination, replace_existing=True)
    assert report.integrity_status == "ok"
    assert report.foreign_key_violations == 0
    assert _workspace_names(destination) == ["Restored workspace"]
    assert _workspace_names(backup) == ["Restored workspace"]


def test_backup_rejects_invalid_sqlite_and_same_file_paths(tmp_path: Path):
    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"not a sqlite database")
    destination = tmp_path / "copy.db"
    with pytest.raises(SQLiteBackupError, match="not readable"):
        create_sqlite_backup(invalid, destination)
    assert not destination.exists()

    valid = tmp_path / "valid.db"
    _create_database(valid, "Valid workspace")
    with pytest.raises(SQLiteBackupError, match="different files"):
        create_sqlite_backup(valid, valid)


def test_backup_rejects_database_missing_application_tables(tmp_path: Path):
    incomplete = tmp_path / "incomplete.db"
    backup = tmp_path / "should-not-be-created.db"
    with sqlite3.connect(incomplete) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('qa-revision')")
        # These were the previous minimum checks, but they do not form a usable app DB.
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE companies (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY)")

    with pytest.raises(SQLiteBackupError, match="missing tables"):
        create_sqlite_backup(incomplete, backup)

    assert not backup.exists()

def test_replace_permission_error_explains_database_lock_and_cleans_temp_file(
    tmp_path: Path, monkeypatch
):
    import sme_financial_dashboard.ops.sqlite_backup as backup_module

    source = tmp_path / "source.db"
    destination = tmp_path / "locked.db"
    _create_database(source, "Source workspace")
    _create_database(destination, "Destination workspace")

    def deny_replace(_source, _destination):
        raise PermissionError("file is in use")

    monkeypatch.setattr(backup_module.os, "replace", deny_replace)

    with pytest.raises(SQLiteBackupError, match="Close Streamlit"):
        create_sqlite_backup(source, destination, overwrite=True)

    assert not list(tmp_path.glob(".locked.db.*.partial"))
    assert _workspace_names(destination) == ["Destination workspace"]

