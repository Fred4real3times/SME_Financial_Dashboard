from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from sqlalchemy import func, select

from conftest import seed_workspace
from sme_financial_dashboard.db.models import (
    AuditEvent,
    Direction,
    ImportRow,
    ImportRowStatus,
    MembershipRole,
    Transaction,
)
from sme_financial_dashboard.security.company_scope import (
    CompanyAccessDenied,
    CompanyContext,
    resolve_company_context,
)
from sme_financial_dashboard.services.import_service import (
    ImportConfirmationRequired,
    ImportMapping,
    ImportService,
)


def _context(session, *, role=MembershipRole.ACCOUNTANT, suffix="one"):
    workspace, user, company = seed_workspace(
        session,
        f"Workspace {suffix}",
        f"{suffix}@example.test",
        f"Company {suffix}",
        role,
    )
    session.flush()
    return workspace, user, company, resolve_company_context(
        session, user_id=user.id, company_id=company.id
    )


def _mapping() -> ImportMapping:
    return ImportMapping(
        columns={
            "transaction_date": 0,
            "amount": 1,
            "currency": 2,
            "direction": 3,
            "reference": 4,
            "counterparty": 5,
        },
        date_format="%d/%m/%Y",
        decimal_separator=",",
        thousands_separator=".",
        delimiter=";",
    )


def test_preview_stages_rows_without_creating_transactions_then_partially_commits(session):
    _workspace, _user, company, context = _context(session)
    content = (
        b"Date;Amount;Currency;Direction;Reference;Counterparty\n"
        b"01/01/2026;1.250,50;XAF;CREDIT;R-1;Client A\n"
        b"02/01/2026;300,00;XAF;DEBIT;R-2;Vendor B\n"
        b"bad-date;50,00;XAF;CREDIT;R-3;Client C\n"
        b"03/01/2026;100,00;XAF;CREDIT;;Shop D\n"
        b"03/01/2026;100,00;XAF;CREDIT;;Shop D\n"
    )

    preview = ImportService.preview(
        session,
        file_bytes=content,
        file_name="../../bank-statement.csv",
        mapping=_mapping(),
        context=context,
    )
    session.flush()

    assert preview.file_name == "bank-statement.csv"
    assert preview.total_count == 5
    assert preview.valid_count == 2
    assert preview.invalid_count == 1
    assert preview.review_count == 2
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0
    assert session.scalar(select(func.count()).select_from(ImportRow)) == 5

    with pytest.raises(ImportConfirmationRequired, match="partial import explicitly"):
        ImportService.commit(
            session,
            preview_id=preview.preview_id,
            context=context,
            confirm=True,
        )

    summary = ImportService.commit(
        session,
        preview_id=preview.preview_id,
        context=context,
        confirm=True,
        confirm_partial=True,
    )
    session.flush()

    assert summary.imported_count == 2
    assert summary.status == "PARTIALLY_COMMITTED"
    transactions = session.scalars(
        select(Transaction).where(Transaction.company_id == company.id)
    ).all()
    assert len(transactions) == 2
    assert {transaction.direction for transaction in transactions} == {
        Direction.INFLOW,
        Direction.OUTFLOW,
    }
    inflow = next(transaction for transaction in transactions if transaction.direction is Direction.INFLOW)
    assert inflow.amount == Decimal("1250.50")
    rows = session.scalars(
        select(ImportRow).where(ImportRow.import_batch_id == preview.preview_id)
    ).all()
    assert sum(row.row_status is ImportRowStatus.REVIEW for row in rows) == 2
    assert all(row.transaction_id is None for row in rows if row.row_status is ImportRowStatus.REVIEW)
    actions = session.scalars(
        select(AuditEvent.action).where(AuditEvent.entity_id == preview.preview_id)
    ).all()
    assert "IMPORT_PREVIEW_CREATED" in actions
    assert "IMPORT_BATCH_COMMITTED" in actions


def test_preview_marks_referenced_reimport_as_duplicate(session):
    _workspace, _user, company, context = _context(session, suffix="duplicate")
    content = (
        b"Date;Amount;Currency;Direction;Reference;Counterparty\n"
        b"01/01/2026;100,00;XAF;CREDIT;REF-100;Client\n"
    )
    first = ImportService.preview(
        session, file_bytes=content, file_name="bank.csv", mapping=_mapping(), context=context
    )
    ImportService.commit(
        session, preview_id=first.preview_id, context=context, confirm=True
    )
    session.flush()

    second = ImportService.preview(
        session, file_bytes=content, file_name="bank.csv", mapping=_mapping(), context=context
    )
    assert second.valid_count == 0
    assert second.duplicate_count == 1
    summary = ImportService.commit(
        session,
        preview_id=second.preview_id,
        context=context,
        confirm=True,
        confirm_partial=True,
    )
    assert summary.imported_count == 0
    assert session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.company_id == company.id)
    ) == 1


def test_existing_reference_less_match_is_review_not_silent_duplicate(session):
    _workspace, _user, _company, context = _context(session, suffix="review")
    content = (
        b"Date;Amount;Currency;Direction;Reference;Counterparty\n"
        b"01/01/2026;100,00;XAF;CREDIT;;Client\n"
    )
    first = ImportService.preview(
        session, file_bytes=content, file_name="bank.csv", mapping=_mapping(), context=context
    )
    assert first.valid_count == 1
    ImportService.commit(
        session, preview_id=first.preview_id, context=context, confirm=True
    )
    session.flush()

    second = ImportService.preview(
        session, file_bytes=content, file_name="bank.csv", mapping=_mapping(), context=context
    )
    assert second.review_count == 1
    assert second.duplicate_count == 0


def test_viewer_cannot_preview_or_commit(session):
    _workspace, _user, _company, context = _context(
        session, role=MembershipRole.VIEWER, suffix="viewer"
    )
    content = (
        b"Date;Amount;Currency;Direction;Reference;Counterparty\n"
        b"01/01/2026;100,00;XAF;CREDIT;REF-1;Client\n"
    )
    with pytest.raises(PermissionError):
        ImportService.preview(
            session, file_bytes=content, file_name="bank.csv", mapping=_mapping(), context=context
        )


def test_user_cannot_forge_company_context_for_another_workspace(session):
    _workspace_a, user_a, _company_a, context_a = _context(session, suffix="tenant-a")
    _workspace_b, _user_b, company_b, _context_b = _context(session, suffix="tenant-b")
    forged = CompanyContext(
        user_id=user_a.id,
        workspace_id=context_a.workspace_id,
        company_id=company_b.id,
        role=MembershipRole.ADMIN,
    )
    content = (
        b"Date;Amount;Currency;Direction;Reference;Counterparty\n"
        b"01/01/2026;100,00;XAF;CREDIT;REF-1;Client\n"
    )
    with pytest.raises(CompanyAccessDenied):
        ImportService.preview(
            session, file_bytes=content, file_name="bank.csv", mapping=_mapping(), context=forged
        )



def _pdf_statement() -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(output)
    table = Table(
        [
            ["Date", "Amount", "Currency", "Direction", "Reference", "Counterparty"],
            ["2026-01-01", "250.00", "XAF", "INFLOW", "PDF-1", "Client PDF"],
        ],
        colWidths=[90, 70, 60, 80, 80, 110],
    )
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black)]))
    document.build([table])
    return output.getvalue()


def test_pdf_import_keeps_page_table_row_provenance_through_commit(session):
    _workspace, _user, company, context = _context(session, suffix="pdf")
    mapping = ImportMapping(
        columns={
            "transaction_date": 0,
            "amount": 1,
            "currency": 2,
            "direction": 3,
            "reference": 4,
            "counterparty": 5,
        },
        date_format="%Y-%m-%d",
        decimal_separator=".",
        thousands_separator=",",
    )
    preview = ImportService.preview(
        session,
        file_bytes=_pdf_statement(),
        file_name="digital-statement.pdf",
        mapping=mapping,
        context=context,
    )
    assert preview.file_type == "PDF"
    assert preview.extraction_method == "PDF_TABLE"
    assert preview.valid_count == 1
    assert preview.sample_rows[0].source_page_number == 1
    assert preview.sample_rows[0].source_table_index == 1
    assert session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.company_id == company.id)
    ) == 0

    summary = ImportService.commit(
        session, preview_id=preview.preview_id, context=context, confirm=True
    )
    session.flush()
    assert summary.imported_count == 1
    stored_row = session.scalar(
        select(ImportRow).where(ImportRow.import_batch_id == preview.preview_id)
    )
    assert stored_row.source_page_number == 1
    assert stored_row.source_table_index == 1
    assert stored_row.transaction_id is not None


def test_xlsx_import_requires_and_uses_explicit_worksheet(session):
    _workspace, _user, company, context = _context(session, suffix="xlsx")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Transactions"
    sheet.append(["Date", "Amount", "Currency", "Direction", "Reference", "Counterparty"])
    sheet.append(["2026-01-02", 350.25, "XAF", "OUTFLOW", "X-1", "Supplier"])
    output = BytesIO()
    workbook.save(output)
    mapping = ImportMapping(
        columns={
            "transaction_date": 0,
            "amount": 1,
            "currency": 2,
            "direction": 3,
            "reference": 4,
            "counterparty": 5,
        },
        date_format="%Y-%m-%d",
        decimal_separator=".",
        thousands_separator=",",
        worksheet_name="Transactions",
    )
    preview = ImportService.preview(
        session,
        file_bytes=output.getvalue(),
        file_name="digital-statement.xlsx",
        mapping=mapping,
        context=context,
    )
    assert preview.file_type == "XLSX"
    assert preview.extraction_method == "XLSX_SHEET"
    assert preview.valid_count == 1
    summary = ImportService.commit(
        session, preview_id=preview.preview_id, context=context, confirm=True
    )
    session.flush()
    assert summary.imported_count == 1
    transaction = session.scalar(
        select(Transaction).where(Transaction.company_id == company.id)
    )
    assert transaction.amount == Decimal("350.25")
    assert transaction.direction is Direction.OUTFLOW


def test_optional_text_over_column_length_is_invalid_not_truncated(session):
    _workspace, _user, _company, context = _context(session, suffix="length")
    long_counterparty = "C" * 201
    content = (
        "Date;Amount;Currency;Direction;Reference;Counterparty\n"
        f"01/01/2026;100,00;XAF;CREDIT;REF-LONG;{long_counterparty}\n"
    ).encode()
    preview = ImportService.preview(
        session, file_bytes=content, file_name="bank.csv", mapping=_mapping(), context=context
    )
    assert preview.valid_count == 0
    assert preview.invalid_count == 1
    assert preview.sample_rows[0].issues[0]["code"] == "FIELD_TOO_LONG"
