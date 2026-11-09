from __future__ import annotations

import csv
import hashlib
import io
from datetime import date
from decimal import Decimal

import pdfplumber
import pytest
from sqlalchemy import select

from conftest import seed_workspace
from sme_financial_dashboard.db.models import (
    AuditEvent,
    CategoryKind,
    Direction,
    MembershipRole,
    Transaction,
)
from sme_financial_dashboard.services.categorization_service import CategoryService
from sme_financial_dashboard.services.dashboard_service import DashboardFilters
from sme_financial_dashboard.services.reporting_service import (
    ExportService,
    ReportingError,
)


def _context(session, *, role=MembershipRole.ACCOUNTANT, suffix="export"):
    workspace, user, company = seed_workspace(
        session,
        f"Workspace {suffix}",
        f"{suffix}@example.test",
        f"Company {suffix}",
        role,
    )
    session.flush()
    from sme_financial_dashboard.security.company_scope import resolve_company_context

    context = resolve_company_context(
        session, user_id=user.id, company_id=company.id
    )
    return workspace, user, company, context


def _transaction(
    session,
    company,
    *,
    label: str,
    transaction_date: date,
    amount: str,
    direction: Direction = Direction.OUTFLOW,
    currency: str = "XAF",
    account_name: str = "Operating",
    description: str | None = None,
    counterparty: str | None = None,
    reference: str | None = None,
    category_id=None,
    validated: bool = True,
    deleted: bool = False,
    deleted_by=None,
):
    row = Transaction(
        company_id=company.id,
        transaction_date=transaction_date,
        amount=Decimal(amount),
        currency=currency,
        direction=direction,
        account_name=account_name,
        description=description,
        counterparty=counterparty,
        reference=reference,
        category_id=category_id,
        fingerprint_version=1,
        source_fingerprint=hashlib.sha256(label.encode("utf-8")).hexdigest(),
        is_validated=validated,
    )
    if deleted:
        from datetime import UTC, datetime

        row.deleted_at = datetime.now(UTC)
        row.deleted_by_user_id = deleted_by
        row.deletion_reason = "Deleted test transaction"
    session.add(row)
    session.flush()
    return row


def _filters(**kwargs):
    return DashboardFilters(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        **kwargs,
    )


def test_csv_export_matches_company_filters_and_neutralizes_formula_cells(session):
    _workspace_a, _user_a, company_a, context_a = _context(session, suffix="csv-safe-a")
    _workspace_b, _user_b, company_b, _context_b = _context(session, suffix="csv-safe-b")
    supplies = CategoryService.create_category(
        session, context_a, name="Supplies", kind=CategoryKind.OUTFLOW
    )
    _transaction(
        session,
        company_a,
        label="csv-included",
        transaction_date=date(2026, 1, 10),
        amount="25.50",
        description="=HYPERLINK(\"https://example.invalid\",\"click\")",
        counterparty="@SUM(1,1)",
        reference="+CMD|' /C calc'!A0",
        category_id=supplies.id,
    )
    _transaction(
        session,
        company_a,
        label="csv-outside-period",
        transaction_date=date(2026, 2, 1),
        amount="900.00",
    )
    _transaction(
        session,
        company_a,
        label="csv-other-currency",
        transaction_date=date(2026, 1, 11),
        amount="700.00",
        currency="USD",
    )
    _transaction(
        session,
        company_a,
        label="csv-unvalidated",
        transaction_date=date(2026, 1, 12),
        amount="500.00",
        validated=False,
    )
    _transaction(
        session,
        company_a,
        label="csv-deleted",
        transaction_date=date(2026, 1, 13),
        amount="400.00",
        deleted=True,
        deleted_by=context_a.user_id,
    )
    _transaction(
        session,
        company_b,
        label="csv-other-company",
        transaction_date=date(2026, 1, 10),
        amount="9999.00",
    )

    artifact = ExportService.export_csv(
        session,
        context_a,
        _filters(currency="XAF", account_name="Operating"),
    )
    records = list(csv.reader(io.StringIO(artifact.data.decode("utf-8-sig"))))

    assert artifact.format == "CSV"
    assert artifact.row_count == 1
    assert artifact.content_type.startswith("text/csv")
    assert records[0][0:5] == [
        "Transaction date", "Value date", "Amount", "Currency", "Direction"
    ]
    assert records[1][2:5] == ["25.50", "XAF", "OUTFLOW"]
    assert records[1][6] == "Supplies"
    assert records[1][7].startswith("'=")
    assert records[1][8].startswith("'@")
    assert records[1][9].startswith("'+")
    assert company_b.id != company_a.id

    audit = session.scalar(
        select(AuditEvent).where(
            AuditEvent.company_id == company_a.id,
            AuditEvent.action == "EXPORT_CSV_PREPARED",
        )
    )
    assert audit is not None
    assert audit.actor_user_id == context_a.user_id
    assert audit.after_json["row_count"] == 1


def test_pdf_export_uses_same_filters_and_includes_currency_totals(session):
    _workspace, _user, company, context = _context(session, suffix="pdf")
    _transaction(
        session,
        company,
        label="pdf-inflow",
        transaction_date=date(2026, 1, 5),
        amount="100.25",
        direction=Direction.INFLOW,
        counterparty="Synthetic customer",
    )
    _transaction(
        session,
        company,
        label="pdf-outflow",
        transaction_date=date(2026, 1, 6),
        amount="20.00",
        direction=Direction.OUTFLOW,
        counterparty="Synthetic supplier",
    )
    _transaction(
        session,
        company,
        label="pdf-other-currency",
        transaction_date=date(2026, 1, 7),
        amount="500.00",
        currency="USD",
    )

    artifact = ExportService.export_pdf(
        session,
        context,
        _filters(currency="XAF", account_name="Operating"),
    )
    assert artifact.format == "PDF"
    assert artifact.content_type == "application/pdf"
    assert artifact.row_count == 2
    assert artifact.data.startswith(b"%PDF")

    with pdfplumber.open(io.BytesIO(artifact.data)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert company.name in text
    assert "100.250000" in text
    assert "20.000000" in text
    assert "XAF" in text
    assert "500.000000" not in text
    assert "USD" not in text

    audit = session.scalar(
        select(AuditEvent).where(
            AuditEvent.company_id == company.id,
            AuditEvent.action == "EXPORT_PDF_PREPARED",
        )
    )
    assert audit is not None
    assert audit.after_json["row_count"] == 2


def test_viewer_can_export_but_cannot_read_audit_history(session):
    _workspace, _user, company, context = _context(
        session, role=MembershipRole.VIEWER, suffix="viewer-export"
    )
    _transaction(
        session,
        company,
        label="viewer-export-row",
        transaction_date=date(2026, 1, 10),
        amount="10.00",
    )
    artifact = ExportService.export_csv(
        session, context, _filters(currency="XAF")
    )
    assert artifact.row_count == 1
    with pytest.raises(PermissionError):
        from sme_financial_dashboard.services.reporting_service import AuditService

        AuditService.list_events(session, context)


def test_export_rejects_more_than_configured_row_limit(session, monkeypatch):
    _workspace, _user, company, context = _context(session, suffix="export-limit")
    import sme_financial_dashboard.services.reporting_service as reporting

    monkeypatch.setattr(reporting, "MAX_EXPORT_ROWS", 0)
    with pytest.raises(ReportingError, match="safety limit"):
        ExportService.export_csv(session, context, _filters())
