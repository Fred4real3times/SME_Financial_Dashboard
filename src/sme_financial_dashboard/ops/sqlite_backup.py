"""Verified, atomic backup and restore operations for the local SQLite database."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


class SQLiteBackupError(ValueError):
    """Raised when a database backup or restore cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class SQLiteBackupReport:
    source: Path
    destination: Path
    size_bytes: int
    sha256: str
    integrity_status: str
    foreign_key_violations: int


_REQUIRED_TABLES = {"alembic_version", "users", "companies", "transactions"}


def _database_path(value: str | Path, *, must_exist: bool) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise SQLiteBackupError("Symbolic links are not accepted for database paths.")
    if must_exist and not path.is_file():
        raise SQLiteBackupError(f"SQLite database file does not exist: {path}")
    if not must_exist and path.exists() and not path.is_file():
        raise SQLiteBackupError("Destination exists but is not a regular file.")
    return path.resolve(strict=must_exist)


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=30)


def _validate_connection(connection: sqlite3.Connection) -> tuple[str, int]:
    integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
    integrity = "; ".join(str(row[0]) for row in integrity_rows)
    if integrity != "ok":
        raise SQLiteBackupError(f"SQLite integrity_check failed: {integrity}")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SQLiteBackupError(
            f"SQLite foreign_key_check found {len(violations)} violation(s)."
        )
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing = sorted(_REQUIRED_TABLES - tables)
    if missing:
        raise SQLiteBackupError(
            "The file is not a complete SME Financial Dashboard database; "
            f"missing tables: {', '.join(missing)}."
        )
    return integrity, len(violations)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish(temp_path: Path, destination: Path, *, overwrite: bool) -> None:
    try:
        os.chmod(temp_path, 0o600)
    except OSError:
        pass
    if overwrite:
        os.replace(temp_path, destination)
        return
    try:
        os.link(temp_path, destination)
    except FileExistsError as exc:
        raise SQLiteBackupError(
            f"Destination already exists: {destination}. Use the explicit overwrite option."
        ) from exc
    except OSError as exc:
        raise SQLiteBackupError(
            f"Could not publish the backup without overwriting an existing file: {exc}"
        ) from exc
    else:
        temp_path.unlink(missing_ok=True)


def _copy_database(
    source_value: str | Path,
    destination_value: str | Path,
    *,
    overwrite: bool,
) -> SQLiteBackupReport:
    source = _database_path(source_value, must_exist=True)
    destination = _database_path(destination_value, must_exist=False)
    if source == destination:
        raise SQLiteBackupError("Source and destination must be different files.")
    if destination.exists() and not overwrite:
        raise SQLiteBackupError(
            f"Destination already exists: {destination}. Use explicit overwrite confirmation."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".partial",
        dir=destination.parent,
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        with closing(_connect_readonly(source)) as source_connection:
            with closing(sqlite3.connect(temp_path)) as target:
                source_connection.backup(target, pages=256, sleep=0.1)
                target.commit()
        with closing(sqlite3.connect(temp_path)) as verification:
            integrity, violations = _validate_connection(verification)
        _publish(temp_path, destination, overwrite=overwrite)
        return SQLiteBackupReport(
            source=source,
            destination=destination,
            size_bytes=destination.stat().st_size,
            sha256=_digest(destination),
            integrity_status=integrity,
            foreign_key_violations=violations,
        )
    except SQLiteBackupError:
        temp_path.unlink(missing_ok=True)
        raise
    except sqlite3.Error as exc:
        temp_path.unlink(missing_ok=True)
        raise SQLiteBackupError(f"SQLite copy or verification failed: {exc}") from exc
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def create_sqlite_backup(
    source: str | Path,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> SQLiteBackupReport:
    """Create and verify a consistent SQLite backup using SQLite's online backup API."""
    source_path = _database_path(source, must_exist=True)
    try:
        with closing(_connect_readonly(source_path)) as connection:
            _validate_connection(connection)
    except sqlite3.Error as exc:
        raise SQLiteBackupError(f"Source SQLite file is not readable: {exc}") from exc
    return _copy_database(source_path, destination, overwrite=overwrite)


def restore_sqlite_backup(
    backup_file: str | Path,
    destination: str | Path,
    *,
    replace_existing: bool = False,
) -> SQLiteBackupReport:
    """Restore a verified backup; replacing an existing database requires explicit consent."""
    backup_path = _database_path(backup_file, must_exist=True)
    try:
        with closing(_connect_readonly(backup_path)) as connection:
            _validate_connection(connection)
    except sqlite3.Error as exc:
        raise SQLiteBackupError(f"Backup SQLite file is not readable: {exc}") from exc
    return _copy_database(
        backup_path,
        destination,
        overwrite=replace_existing,
    )
