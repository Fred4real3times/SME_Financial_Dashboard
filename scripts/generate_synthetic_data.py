from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sme_financial_dashboard.config import Settings
from sme_financial_dashboard.db.session import build_engine, build_session_factory
from sme_financial_dashboard.services.synthetic_data_service import SyntheticDatasetService


def _default_end_date() -> date:
    first_of_month = date.today().replace(day=1)
    return first_of_month - timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a separate, fictional 12-month SME QA database."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=ROOT / ".data" / "sme_financial_dashboard_synthetic.db",
    )
    parser.add_argument("--admin-email", default="demo-admin@example.test")
    parser.add_argument("--end-date", type=date.fromisoformat, default=_default_end_date())
    parser.add_argument("--seed", type=int, default=20261109)
    parser.add_argument(
        "--confirm-synthetic-only",
        action="store_true",
        required=True,
        help="Confirm that this creates fictional demo data, never production data.",
    )
    args = parser.parse_args()

    if os.getenv("APP_ENV", "development").strip().lower() == "production":
        parser.error("Synthetic data generation is disabled when APP_ENV=production.")
    target = args.database.expanduser()
    if target.is_symlink():
        parser.error("The synthetic database destination cannot be a symbolic link.")
    target = target.resolve()
    if "synthetic" not in target.stem.lower() and "demo" not in target.stem.lower():
        parser.error("Choose a new database filename containing 'synthetic' or 'demo'.")
    if target.exists():
        parser.error(
            f"{target} already exists. Choose a new filename; this script never overwrites databases."
        )

    configured_url = os.getenv("DATABASE_URL")
    if configured_url:
        try:
            configured = make_url(configured_url)
            configured_path = Path(configured.database).expanduser().resolve() if (
                configured.drivername.startswith("sqlite") and configured.database
            ) else None
        except Exception:
            configured_path = None
        if configured_path is not None and configured_path == target:
            parser.error("The destination matches DATABASE_URL; choose a separate synthetic path.")

    password = getpass.getpass("Create the synthetic ADMIN password (12–128 characters): ")
    confirmation = getpass.getpass("Confirm synthetic ADMIN password: ")
    if password != confirmation or not 12 <= len(password) <= 128:
        parser.error("Passwords must match and contain 12 to 128 characters.")

    target.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{target.as_posix()}"
    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("APP_ENV", "development")
    engine = None
    try:
        alembic_config = Config(str(ROOT / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(alembic_config, "head")
        settings = Settings.from_environment()
        engine = build_engine(settings.database_url)
        factory = build_session_factory(settings, engine=engine)
        with factory() as session, session.begin():
            result = SyntheticDatasetService.generate(
                session,
                admin_email=args.admin_email,
                admin_password=password,
                end_date=args.end_date,
                seed=args.seed,
            )
        print(f"Synthetic database created: {target}")
        print(f"Workspace ID: {result.workspace_id}")
        print(f"Admin email: {args.admin_email}")
        print(f"Period: {result.start_date.isoformat()} to {result.end_date.isoformat()}")
        print(f"Seed: {result.seed}")
        print(f"Imported transactions: {result.imported_count}")
        for company in result.companies:
            print(
                f"- {company.name}: {company.imported} imported; "
                f"{company.invalid} INVALID; {company.duplicate} DUPLICATE; "
                f"{company.review} REVIEW; batch={company.batch_id}"
            )
        print("The synthetic ADMIN password is stored only as a password hash.")
        print("Set DATABASE_URL to this file and configure a local SESSION_SECRET to sign in.")
        return 0
    except Exception:
        if engine is not None:
            engine.dispose()
        target.unlink(missing_ok=True)
        raise
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
