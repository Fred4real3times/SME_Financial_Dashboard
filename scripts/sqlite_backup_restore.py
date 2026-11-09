from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sme_financial_dashboard.ops.sqlite_backup import (
    SQLiteBackupError,
    create_sqlite_backup,
    restore_sqlite_backup,
)


def _print_report(report) -> None:
    print(f"Source:      {report.source}")
    print(f"Destination: {report.destination}")
    print(f"Size:        {report.size_bytes:,} bytes")
    print(f"SHA-256:     {report.sha256}")
    print(f"Integrity:   {report.integrity_status}")
    print(f"FK issues:   {report.foreign_key_violations}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or restore a verified SME Financial Dashboard SQLite database."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="Create a consistent SQLite backup.")
    backup.add_argument("--source", type=Path, required=True)
    backup.add_argument("--destination", type=Path, required=True)
    backup.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace an existing backup file.",
    )

    restore = commands.add_parser("restore", help="Restore a verified SQLite backup.")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument(
        "--replace-existing",
        action="store_true",
        help="Explicitly replace the destination database.",
    )

    arguments = parser.parse_args()
    try:
        if arguments.command == "backup":
            report = create_sqlite_backup(
                arguments.source,
                arguments.destination,
                overwrite=arguments.overwrite,
            )
        else:
            report = restore_sqlite_backup(
                arguments.backup,
                arguments.destination,
                replace_existing=arguments.replace_existing,
            )
        _print_report(report)
        if arguments.command == "restore":
            print("Stop Streamlit before restoring; restart it only after checking the workspace.")
        return 0
    except (SQLiteBackupError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
