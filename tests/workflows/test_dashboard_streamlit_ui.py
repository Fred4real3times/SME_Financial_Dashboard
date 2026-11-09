from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

from sme_financial_dashboard.config import Settings
from sme_financial_dashboard.db.base import Base
from sme_financial_dashboard.db.models import (
    CategoryKind,
    Direction,
    Transaction,
)
from sme_financial_dashboard.db.session import build_engine, build_session_factory
from sme_financial_dashboard.security.company_scope import (
    resolve_company_context,
    resolve_workspace_context,
)
from sme_financial_dashboard.services.auth_service import AuthService
from sme_financial_dashboard.services.categorization_service import CategoryService
from sme_financial_dashboard.services.dashboard_service import AccountSnapshotService
from sme_financial_dashboard.services.workspace_service import WorkspaceService


def test_streamlit_dashboard_renders_verified_closing_balance(
    tmp_path: Path, monkeypatch
):
    database_path = tmp_path / "streamlit-smoke.db"
    database_url = f"sqlite:///{database_path}"
    secret = "streamlit-ui-smoke-test-secret-1234567890"

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SESSION_SECRET", secret)
    monkeypatch.setenv("SESSION_TTL_HOURS", "12")

    settings = Settings(
        database_url=database_url,
        app_env="test",
        session_secret=secret,
        session_ttl_hours=12,
    )
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    factory = build_session_factory(settings, engine=engine)

    try:
        with factory() as session, session.begin():
            bootstrap = AuthService.bootstrap_first_admin(
                session,
                email="dashboard-ui-admin@example.test",
                display_name="Dashboard UI Admin",
                password="Dashboard-Smoke-Test-123!",
                workspace_name="Dashboard UI Workspace",
            )
            token = AuthService.login(
                session,
                email="dashboard-ui-admin@example.test",
                password="Dashboard-Smoke-Test-123!",
                secret=secret,
                ttl_hours=12,
            )
            workspace_context = resolve_workspace_context(
                session,
                user_id=bootstrap.user.id,
                workspace_id=bootstrap.workspace.id,
            )
            company = WorkspaceService.create_company(
                session,
                workspace_context,
                name="Dashboard UI Company",
                base_currency="XAF",
                timezone="Africa/Douala",
                is_demo=True,
            )
            company_context = resolve_company_context(
                session,
                user_id=bootstrap.user.id,
                company_id=company.id,
            )
            expense_category = CategoryService.create_category(
                session,
                company_context,
                name="Supplies",
                kind=CategoryKind.OUTFLOW,
            )

            snapshot_date = datetime.now(ZoneInfo("Africa/Douala")).date()
            AccountSnapshotService.create(
                session,
                company_context,
                account_name="Operating",
                as_of_date=snapshot_date,
                currency="XAF",
                opening_balance="1000.00",
                is_verified=True,
                source_description="Synthetic verified opening statement for UI smoke test",
            )
            session.add_all(
                [
                    Transaction(
                        company_id=company.id,
                        transaction_date=snapshot_date,
                        amount=Decimal("100.00"),
                        currency="XAF",
                        direction=Direction.INFLOW,
                        account_name="Operating",
                        counterparty="Synthetic customer",
                        reference="UI-SMOKE-IN-001",
                        fingerprint_version=1,
                        source_fingerprint=hashlib.sha256(
                            b"dashboard-ui-inflow"
                        ).hexdigest(),
                        is_validated=True,
                    ),
                    Transaction(
                        company_id=company.id,
                        transaction_date=snapshot_date,
                        amount=Decimal("25.00"),
                        currency="XAF",
                        direction=Direction.OUTFLOW,
                        account_name="Operating",
                        category_id=expense_category.id,
                        counterparty="Synthetic supplier",
                        reference="UI-SMOKE-OUT-001",
                        fingerprint_version=1,
                        source_fingerprint=hashlib.sha256(
                            b"dashboard-ui-outflow"
                        ).hexdigest(),
                        is_validated=True,
                    ),
                ]
            )

        # AppTest executes the real Streamlit entry point and renders its elements.
        import streamlit as st

        st.cache_resource.clear()
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "app.py", default_timeout=30)
        app.session_state["auth_token"] = token
        app.session_state["active_workspace_id"] = bootstrap.workspace.id
        app.session_state["active_company_id"] = company.id
        app.session_state[f"dashboard_currency_{company.id}"] = "XAF"
        app.session_state[f"dashboard_account_{company.id}"] = "Operating"
        app.run()

        assert not app.exception, [element.message for element in app.exception]
        assert any(element.value == "Financial dashboard" for element in app.subheader)
        assert any(element.value == "Exports and history" for element in app.subheader)
        assert any("Import history" in element.value for element in app.markdown)
        assert any("Audit history" in element.value for element in app.markdown)
        assert any(element.label == "Prepare filtered CSV" for element in app.button)
        assert any(element.label == "Prepare filtered PDF" for element in app.button)
        assert any(button.label == "Prepare filtered CSV" for button in app.button)
        assert any(button.label == "Prepare filtered PDF" for button in app.button)
        assert any(
            element.label == "Estimated closing balance — Operating"
            and "1,075.000000 XAF" in str(element.value)
            for element in app.metric
        )
        assert any(
            element.label == "Net cash flow" and "75.000000" in str(element.value)
            for element in app.metric
        )
        assert any("Monthly cash flow" in element.value for element in app.markdown)
        assert any(
            "Top spending categories and counterparties" in element.value
            for element in app.markdown
        )
    finally:
        try:
            import streamlit as st

            st.cache_resource.clear()
        finally:
            engine.dispose()
