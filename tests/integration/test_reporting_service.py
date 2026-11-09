from __future__ import annotations

import csv
import hashlib
import io
from datetime import date
from decimal import Decimal
from uuid import UUID

import pdfplumber
import pytest

from conftest import seed_workspace
from sme_financial_dashboard.db.models import (
    AuditEvent,
    CategoryKind,
    Direction,
    FileType,
    ImportBatch,
    ImportBatchStatus,
    ImportMethod,
    ImportRow,
    ImportRowStatus,
    MembershipRole,
    Transaction,
)
from sme_financial_dashboard.security.company_scope import (
    CompanyContext,
    CompanyAccessDenied,
    resolve_company_context,
)
from sme_financial_dashboard.services.categorization_service import CategoryService
from sme_financial_dashboard.services.dashboard_service import DashboardFilters
from sme_financial_dashboard.services.reporting_service import (
    AuditService,
    ExportService,
    ImportHistoryService,
    ReportingError,
)


def _context(session, *, role=MembershipRole.ACCOUNTANT, suffix="reporting"):
    workspace, user, company = seed_workspace(
        session,
        f"Workspace {suffix}",
        f"{suffix}@example.test",
        f"Company {suffix}",
        role,
    )
    session.flush()
    context = resolve_company_context(
        session, user_id=user.id, company_id=company.id
    )
    return workspace, user, company, context


def _filters(**kwargs):
    return DashboardFilters(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        **kwargs,
    )


def _add_transaction(
    session,
    company,
    *,
    reference: str,
    description: str = "Office supplies",
    counterparty: str = "Stationery Ltd",
    account_name: str = "Operating",
    category_id=None,
    amount: str = "25.50",
    currency: str = "XAF",
    direction: Direction = Direction.OUTFLOW,
    transaction_date: date = date(2026, 1, 15),
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
        description=description,
        counterparty=counterparty,
        reference=reference,
        account_name=account_name,
        category_id=category_id,
        fingerprint_version=1,
        source_fingerprint=hashlib.sha256(reference.encode("utf-8")).hexdigest(),
        is_validated=validated,
    )
    if deleted:
        from datetime import UTC, datetime

        row.deleted_at = datetime.now(UTC)
        row.deleted_by_user_id = deleted_by
        row.deletion_reason = "Removed in reporting test"
    session.add(row)
    session.flush()
    return row


def _add_batch(session, company, user, *, filename="statement.csv"):
    batch = ImportBatch(
        company_id=company.id,
        uploaded_by_user_id=user.id,
        file_name=filename,
        file_sha256=hashlib.sha256(filename.encode("utf-8")).hexdigest(),
        file_type=FileType.CSV,
        extraction_method=ImportMethod.CSV_ROWS,
        mapping_json={"columns": {"date": 0, "amount": 1}},
        status=ImportBatchStatus.PREVIEWED,
        total_count=2,
        valid_count=1,
        review_count=1,
    )
    session.add(batch)
    session.flush()
    valid_row = ImportRow(
        company_id=company.id,
        import_batch_id=batch.id,
        source_row_number=2,
        raw_values_json={"date": "15/01/2026", "amount": "25.50"},
        normalized_values_json={"transaction_date": "2026-01-15"},
        row_status=ImportRowStatus.VALID,
        issues_json=[],
    )
    review_row = ImportRow(
        company_id=company.id,
        import_batch_id=batch.id,
        source_row_number=3,
        raw_values_json={"date": "15/01/2026", "amount": "ambiguous"},
        row_status=ImportRowStatus.REVIEW,
        issues_json=[{"code": "REFERENCE_REQUIRED"}],
    )
    session.add_all([valid_row, review_row])
    session.flush()
    return batch, valid_row, review_row


def test_csv_export_uses_exact_filters_company_scope_and_formula_neutralization(session):
    _workspace, user, company, context = _context(session, suffix="csv-export")
    _workspace_b, _user_b, company_b, _context_b = _context(session, suffix="csv-export-other")
    category = CategoryService.create_category(
        session, context, name="=HYPERLINK(\"https://evil.test\")", kind=CategoryKind.OUTFLOW
    )
    _add_transaction(
        session,
        company,
        reference=" \t@cmd",
        category_id=category.id,
        account_name="Operating",
        description=" \t=cmd|' /C calc'!A0",
        counterparty="+SUM(1,2)",
    )
    _add_transaction(
        session,
        company,
        reference="ROW-2",
        amount="10.00",
        currency="USD",
        account_name="Foreign currency account",
    )
    _add_transaction(
        session,
        company,
        reference="ROW-3",
        amount="999.00",
        validated=False,
    )
    _add_transaction(
        session,
        company,
        reference="ROW-4",
        amount="777.00",
        deleted=True,
        deleted_by=user.id,
    )
    _add_transaction(
        session,
        company_b,
        reference="OTHER-COMPANY",
        amount="5000.00",
    )

    artifact = ExportService.export_csv(
        session,
        context,
        _filters(currency="XAF", account_name="Operating"),
    )
    assert artifact.format == "CSV"
    assert artifact.filename == "sme_transactions_20260101_20260131.csv"
    assert artifact.content_type.startswith("text/csv")
    assert artifact.row_count == 1

    records = list(csv.reader(io.StringIO(artifact.data.decode("utf-8-sig"))))
    assert len(records) == 2
    row = records[1]
    assert row[2] == "25.500000"
    assert row[3] == "XAF"
    assert row[5] == "Operating"
    for index in (6, 7, 8, 9):
        assert row[index].startswith("'")

    audit = session.query(AuditEvent).filter_by(
        company_id=company.id,
        action="EXPORT_CSV_PREPARED",
    ).one()
    assert audit.actor_user_id == user.id
    assert audit.after_json["row_count"] == 1
    assert audit.after_json["currency"] == "XAF"
    assert session.query(AuditEvent).filter_by(
        company_id=company_b.id,
        action="EXPORT_CSV_PREPARED",
    ).count() == 0


def test_csv_formula_guard_neutralizes_all_supported_prefix_shapes():
    from sme_financial_dashboard.services.reporting_service import _safe_csv_text

    dangerous = [
        "=1+1",
        "+SUM(A1:A2)",
        "-2+3",
        "@SUM(A1)",
        "  =HYPERLINK(\"https://evil.test\")",
        "\t=cmd",
        " \t@cmd",
        "\r\n+cmd",
        "\ufeff=1+1",
        "\v=1+1",
        "\x00-1+1",
    ]
    for value in dangerous:
        assert _safe_csv_text(value).startswith("'")
    assert _safe_csv_text("ordinary text") == "ordinary text"
    assert _safe_csv_text(None) == ""


def test_pdf_export_is_valid_and_contains_only_filtered_company_rows(session):
    _workspace, _user, company, context = _context(session, suffix="pdf-export")
    _workspace_b, _user_b, other_company, _other_context = _context(
        session, suffix="pdf-export-other"
    )
    _add_transaction(
        session,
        company,
        reference="PDF-ROW-1",
        description="Monthly office rent",
        counterparty="City Properties",
    )
    _add_transaction(
        session,
        company,
        reference="PDF-ROW-2",
        amount="70.00",
        currency="USD",
        description="USD bank fee",
    )
    _add_transaction(
        session,
        other_company,
        reference="PDF-OTHER",
        description="Confidential other company",
        amount="9000.00",
    )

    artifact = ExportService.export_pdf(
        session,
        context,
        _filters(currency="XAF"),
    )
    assert artifact.format == "PDF"
    assert artifact.content_type == "application/pdf"
    assert artifact.data.startswith(b"%PDF-")
    assert artifact.row_count == 1

    with pdfplumber.open(io.BytesIO(artifact.data)) as document:
        text = "\n".join(page.extract_text() or "" for page in document.pages)
    assert company.name in text
    assert "Monthly office rent" in text
    assert "City Properties" in text
    assert "Confidential other company" not in text
    assert "USD bank fee" not in text

    audit = session.query(AuditEvent).filter_by(
        company_id=company.id,
        action="EXPORT_PDF_PREPARED",
    ).one()
    assert audit.after_json["row_count"] == 1


def test_export_row_limit_is_enforced_before_audit(session, monkeypatch):
    _workspace, _user, company, context = _context(session, suffix="export-limit")
    _add_transaction(session, company, reference="LIMIT-1")
    monkeypatch.setattr(
        "sme_financial_dashboard.services.reporting_service.MAX_EXPORT_ROWS", 0
    )
    with pytest.raises(ReportingError, match="safety limit"):
        ExportService.export_csv(session, context, _filters())
    assert session.query(AuditEvent).filter_by(
        company_id=company.id,
        action="EXPORT_CSV_PREPARED",
    ).count() == 0


def test_viewer_can_export_but_cannot_read_audit_history(session):
    _workspace, _user, company, context = _context(
        session, role=MembershipRole.VIEWER, suffix="viewer-export"
    )
    _add_transaction(session, company, reference="VIEWER-EXPORT")
    artifact = ExportService.export_csv(session, context, _filters())
    assert artifact.row_count == 1
    with pytest.raises(PermissionError):
        AuditService.list_events(session, context)


def test_import_history_is_company_scoped_and_preserves_row_provenance(session):
    _workspace, user, company, context = _context(session, suffix="history-a")
    _workspace_b, user_b, company_b, context_b = _context(session, suffix="history-b")
    batch, valid_row, review_row = _add_batch(session, company, user)
    batch_b, _valid_b, _review_b = _add_batch(
        session, company_b, user_b, filename="other-company.csv"
    )

    own_batches = ImportHistoryService.list_batches(session, context)
    assert [item.id for item in own_batches] == [batch.id]
    assert [item.id for item in ImportHistoryService.list_batches(session, context_b)] == [batch_b.id]

    rows = ImportHistoryService.list_rows(
        session, context, batch_id=batch.id
    )
    assert {item.id for item in rows} == {valid_row.id, review_row.id}
    assert rows[1].source_row_number == 3
    assert rows[1].row_status is ImportRowStatus.REVIEW
    assert rows[1].issues_json[0]["code"] == "REFERENCE_REQUIRED"

    with pytest.raises(ReportingError, match="not found"):
        ImportHistoryService.list_rows(
            session, context, batch_id=batch_b.id
        )
    with pytest.raises(ReportingError, match="UUID"):
        ImportHistoryService.list_rows(session, context, batch_id="not-a-uuid")


def test_import_history_pagination_validation_and_viewer_read_access(session):
    _workspace, user, company, context = _context(
        session, role=MembershipRole.VIEWER, suffix="history-viewer"
    )
    batch, _valid, _review = _add_batch(session, company, user)
    assert ImportHistoryService.list_batches(session, context) == [batch]
    assert ImportHistoryService.list_rows(session, context, batch_id=batch.id, limit=1) == [
        session.query(ImportRow)
        .filter_by(import_batch_id=batch.id, source_row_number=2)
        .one()
    ]
    with pytest.raises(ReportingError, match="limit"):
        ImportHistoryService.list_batches(session, context, limit=0)
    with pytest.raises(ReportingError, match="offset"):
        ImportHistoryService.list_rows(
            session, context, batch_id=batch.id, offset=-1
        )


def test_audit_history_is_company_scoped_permission_checked_and_paginated(session):
    _workspace, user, company, context = _context(session, suffix="audit-a")
    _workspace_b, user_b, company_b, _context_b = _context(session, suffix="audit-b")
    first = AuditEvent(
        company_id=company.id,
        actor_user_id=user.id,
        action="TEST_EVENT_ONE",
        entity_type="TEST",
        entity_id=UUID(int=100),
        after_json={"safe": "metadata"},
    )
    second = AuditEvent(
        company_id=company.id,
        actor_user_id=user.id,
        action="TEST_EVENT_TWO",
        entity_type="TEST",
        entity_id=UUID(int=101),
    )
    other = AuditEvent(
        company_id=company_b.id,
        actor_user_id=user_b.id,
        action="OTHER_COMPANY_EVENT",
        entity_type="TEST",
        entity_id=UUID(int=102),
    )
    session.add_all([first, second, other])
    session.flush()

    events = AuditService.list_events(session, context, limit=1)
    assert len(events) == 1
    assert events[0].company_id == company.id
    assert events[0].action in {"TEST_EVENT_ONE", "TEST_EVENT_TWO"}
    assert AuditService.list_events(session, context, offset=1)[0].company_id == company.id
    with pytest.raises(ReportingError, match="limit"):
        AuditService.list_events(session, context, limit=0)
    with pytest.raises(ReportingError, match="offset"):
        AuditService.list_events(session, context, offset=-1)

    _viewer_ws, _viewer, _viewer_company, viewer_context = _context(
        session, role=MembershipRole.VIEWER, suffix="audit-viewer"
    )
    with pytest.raises(PermissionError):
        AuditService.list_events(session, viewer_context)


def test_forged_company_context_is_rejected_for_exports_and_audit(session):
    _workspace_a, user_a, company_a, context_a = _context(session, suffix="forged-a")
    _workspace_b, _user_b, company_b, _context_b = _context(session, suffix="forged-b")
    _add_transaction(session, company_b, reference="FORGED-B")

    forged = CompanyContext(
        user_id=user_a.id,
        workspace_id=context_a.workspace_id,
        company_id=company_b.id,
        role=MembershipRole.ADMIN,
    )
    with pytest.raises(CompanyAccessDenied):
        ExportService.export_csv(session, forged, _filters())
    with pytest.raises(CompanyAccessDenied):
        AuditService.list_events(session, forged)
