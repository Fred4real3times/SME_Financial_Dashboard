from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from conftest import seed_workspace
from sme_financial_dashboard.db.models import (
    AuditEvent,
    Direction,
    ImportBatch,
    ImportRow,
    ImportRowStatus,
    MembershipRole,
    ReviewDecision,
    Transaction,
)
from sme_financial_dashboard.security.company_scope import (
    CompanyAccessDenied,
    CompanyContext,
    resolve_company_context,
)
from sme_financial_dashboard.services.import_service import ImportMapping, ImportService
from sme_financial_dashboard.services.review_service import (
    ReviewResolutionError,
    ReviewService,
)
from sme_financial_dashboard.services.categorization_service import (
    CategorizationRuleService,
    CategoryService,
)
from sme_financial_dashboard.db.models import CategoryKind, MatchField, MatchOperator


def _context(session, *, role=MembershipRole.ACCOUNTANT, suffix="review"):
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


def _review_preview(session, context):
    content = (
        b"Date;Amount;Currency;Direction;Reference;Counterparty\n"
        b"01/01/2026;100,00;XAF;CREDIT;;Client\n"
        b"01/01/2026;100,00;XAF;CREDIT;;Client\n"
    )
    preview = ImportService.preview(
        session,
        file_bytes=content,
        file_name="ambiguous.csv",
        mapping=_mapping(),
        context=context,
    )
    assert preview.review_count == 2
    assert preview.valid_count == 0
    return preview


def _corrected_values(reference: str = "MANUAL-REVIEW-001") -> dict:
    return {
        "transaction_date": "2026-01-01",
        "amount": "100.00",
        "currency": "XAF",
        "direction": "INFLOW",
        "description": "Customer payment",
        "counterparty": "Client",
        "reference": reference,
        "account_name": "Main account",
    }


def test_review_queue_is_company_scoped_and_viewer_cannot_access(session):
    _workspace, _user, _company, context = _context(session, suffix="queue-scope")
    preview = _review_preview(session, context)
    queue = ReviewService.list_pending(session, context)
    assert len(queue) == 2
    assert {item.batch_id for item in queue} == {preview.preview_id}
    assert {item.file_name for item in queue} == {"ambiguous.csv"}

    viewer_workspace, viewer, viewer_company = seed_workspace(
        session,
        "Viewer workspace",
        "review-viewer@example.test",
        "Viewer company",
        MembershipRole.VIEWER,
    )
    session.flush()
    viewer_context = resolve_company_context(
        session, user_id=viewer.id, company_id=viewer_company.id
    )
    with pytest.raises(PermissionError):
        ReviewService.list_pending(session, viewer_context)


def test_review_resolution_can_confirm_duplicate_or_reject_with_audit(session):
    _workspace, _user, company, context = _context(session, suffix="decisions")
    preview = _review_preview(session, context)
    rows = session.scalars(
        select(ImportRow)
        .where(ImportRow.import_batch_id == preview.preview_id)
        .order_by(ImportRow.source_row_number)
    ).all()

    duplicate_result = ReviewService.resolve(
        session,
        context,
        row_id=rows[0].id,
        decision=ReviewDecision.CONFIRMED_DUPLICATE,
        note="Confirmed against the bank statement reference and amount.",
    )
    rejected_result = ReviewService.resolve(
        session,
        context,
        row_id=rows[1].id,
        decision=ReviewDecision.REJECTED,
        note="The second row is a repeated statement line.",
    )
    session.flush()

    assert duplicate_result.row_status == ImportRowStatus.DUPLICATE.value
    assert rejected_result.row_status == ImportRowStatus.INVALID.value
    assert rejected_result.remaining_review_count == 0
    batch = session.get(ImportBatch, preview.preview_id)
    assert batch.duplicate_count == 1
    assert batch.invalid_count == 1
    assert batch.review_count == 0
    assert batch.status.value == "PARTIALLY_COMMITTED"
    assert session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.company_id == company.id)
    ) == 0
    actions = session.scalars(
        select(AuditEvent.action).where(AuditEvent.entity_id.in_([rows[0].id, rows[1].id]))
    ).all()
    assert actions.count("IMPORT_REVIEW_RESOLVED") == 2


def test_corrected_review_row_creates_transaction_with_manual_reference(session):
    _workspace, _user, company, context = _context(session, suffix="corrected")
    category = CategoryService.create_category(
        session, context, name="Reviewed inflows", kind=CategoryKind.INFLOW
    )
    CategorizationRuleService.create_rule(
        session,
        context,
        category_id=category.id,
        match_field=MatchField.KEYWORD,
        operator=MatchOperator.CONTAINS,
        match_value="customer payment",
        priority=100,
    )
    preview = _review_preview(session, context)
    row = session.scalar(
        select(ImportRow)
        .where(
            ImportRow.import_batch_id == preview.preview_id,
            ImportRow.row_status == ImportRowStatus.REVIEW,
        )
        .order_by(ImportRow.source_row_number)
    )
    result = ReviewService.resolve(
        session,
        context,
        row_id=row.id,
        decision=ReviewDecision.CORRECTED_AND_ACCEPTED,
        note="Verified with the source statement and assigned a unique internal reference.",
        corrected_values=_corrected_values(),
    )
    session.flush()
    session.refresh(row)
    batch = session.get(ImportBatch, preview.preview_id)
    transaction = session.get(Transaction, result.transaction_id)

    assert result.row_status == ImportRowStatus.VALID_WITH_WARNING.value
    assert result.transaction_id == row.transaction_id
    assert transaction.reference == "MANUAL-REVIEW-001"
    assert transaction.amount == Decimal("100.00")
    assert transaction.direction is Direction.INFLOW
    assert transaction.category_id == category.id
    assert transaction.categorization_source.value == "RULE"
    assert row.review_decision is ReviewDecision.CORRECTED_AND_ACCEPTED
    assert row.reviewed_by_user_id == context.user_id
    assert row.reviewed_at is not None
    assert batch.valid_count == 1
    assert batch.review_count == 1
    assert batch.status.value == "PARTIALLY_COMMITTED"
    assert session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.company_id == company.id)
    ) == 1


def test_review_acceptance_requires_unique_reference_and_rejects_existing_match(session):
    _workspace, _user, company, context = _context(session, suffix="unique-ref")
    preview = _review_preview(session, context)
    row = session.scalar(
        select(ImportRow).where(
            ImportRow.import_batch_id == preview.preview_id,
            ImportRow.row_status == ImportRowStatus.REVIEW,
        )
    )
    values_without_reference = _corrected_values()
    values_without_reference["reference"] = ""
    with pytest.raises(ReviewResolutionError, match="manual unique reference"):
        ReviewService.resolve(
            session,
            context,
            row_id=row.id,
            decision=ReviewDecision.CORRECTED_AND_ACCEPTED,
            note="Attempt without a distinguishing reference.",
            corrected_values=values_without_reference,
        )
    existing_fingerprint_values = _corrected_values()
    from sme_financial_dashboard.domain.fingerprints import transaction_fingerprint

    fingerprint = transaction_fingerprint(
        company_id=company.id,
        transaction_date=date(2026, 1, 1),
        amount=Decimal("100.00"),
        currency="XAF",
        direction=Direction.INFLOW,
        reference="MANUAL-REVIEW-001",
        counterparty="Client",
    )
    session.add(
        Transaction(
            company_id=company.id,
            transaction_date=date(2026, 1, 1),
            amount=Decimal("100.00"),
            currency="XAF",
            direction=Direction.INFLOW,
            reference="MANUAL-REVIEW-001",
            counterparty="Client",
            fingerprint_version=1,
            source_fingerprint=fingerprint,
            is_validated=True,
        )
    )
    session.flush()
    with pytest.raises(ReviewResolutionError, match="matches an existing transaction"):
        ReviewService.resolve(
            session,
            context,
            row_id=row.id,
            decision=ReviewDecision.CORRECTED_AND_ACCEPTED,
            note="Corrected reference collides with an existing transaction.",
            corrected_values=existing_fingerprint_values,
        )
    session.refresh(row)
    assert row.row_status is ImportRowStatus.REVIEW
    assert row.transaction_id is None


def test_review_row_cannot_be_resolved_twice_and_note_is_mandatory(session):
    _workspace, _user, _company, context = _context(session, suffix="repeat-review")
    preview = _review_preview(session, context)
    row = session.scalar(
        select(ImportRow).where(
            ImportRow.import_batch_id == preview.preview_id,
            ImportRow.row_status == ImportRowStatus.REVIEW,
        )
    )
    with pytest.raises(ReviewResolutionError, match="note is required"):
        ReviewService.resolve(
            session,
            context,
            row_id=row.id,
            decision=ReviewDecision.REJECTED,
            note="   ",
        )
    ReviewService.resolve(
        session,
        context,
        row_id=row.id,
        decision=ReviewDecision.CONFIRMED_DUPLICATE,
        note="Reviewed as a duplicate.",
    )
    with pytest.raises(ReviewResolutionError, match="Pending REVIEW row"):
        ReviewService.resolve(
            session,
            context,
            row_id=row.id,
            decision=ReviewDecision.REJECTED,
            note="A second decision must not be allowed.",
        )


def test_review_resolution_rejects_forged_company_context(session):
    _workspace_a, user_a, _company_a, context_a = _context(session, suffix="review-tenant-a")
    _workspace_b, _user_b, company_b, _context_b = _context(session, suffix="review-tenant-b")
    preview = _review_preview(session, context_a)
    row = session.scalar(
        select(ImportRow).where(
            ImportRow.import_batch_id == preview.preview_id,
            ImportRow.row_status == ImportRowStatus.REVIEW,
        )
    )
    forged = CompanyContext(
        user_id=user_a.id,
        workspace_id=context_a.workspace_id,
        company_id=company_b.id,
        role=MembershipRole.ADMIN,
    )
    with pytest.raises(CompanyAccessDenied):
        ReviewService.resolve(
            session,
            forged,
            row_id=row.id,
            decision=ReviewDecision.REJECTED,
            note="This forged context must be denied.",
        )



def test_reference_less_row_reimport_after_manual_acceptance_returns_to_review(session):
    _workspace, _user, _company, context = _context(session, suffix="reimport-manual-review")
    first_preview = _review_preview(session, context)
    first_row = session.scalar(
        select(ImportRow)
        .where(ImportRow.import_batch_id == first_preview.preview_id)
        .order_by(ImportRow.source_row_number)
    )
    original_fingerprint = first_row.source_fingerprint
    ReviewService.resolve(
        session,
        context,
        row_id=first_row.id,
        decision=ReviewDecision.CORRECTED_AND_ACCEPTED,
        note="Verified separately and assigned a unique manual reference.",
        corrected_values=_corrected_values("MANUAL-REIMPORT-001"),
    )
    session.flush()
    session.refresh(first_row)
    assert first_row.source_fingerprint == original_fingerprint
    assert first_row.review_decision is ReviewDecision.CORRECTED_AND_ACCEPTED

    content = (
        "Date;Amount;Currency;Direction;Reference;Counterparty\n"
        "01/01/2026;100,00;XAF;CREDIT;;Client\n"
        "01/01/2026;100,00;XAF;CREDIT;;Client\n"
    ).encode()
    second_preview = ImportService.preview(
        session,
        file_bytes=content,
        file_name="ambiguous-reimport.csv",
        mapping=_mapping(),
        context=context,
    )
    assert second_preview.valid_count == 0
    assert second_preview.review_count == 2
    assert any(
        issue["code"] == "REFERENCELESS_MATCH_MANUAL_OVERRIDE"
        for row in second_preview.sample_rows
        for issue in row.issues
    )
