from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from conftest import seed_workspace
from sme_financial_dashboard.db.models import (
    Category,
    CategoryKind,
    Company,
    Direction,
    FileType,
    ImportBatch,
    ImportBatchStatus,
    ImportMethod,
    ImportRow,
    ImportRowStatus,
    MembershipRole,
    Transaction,
    WorkspaceMembership,
)
from sme_financial_dashboard.security.company_scope import (
    CompanyAccessDenied,
    resolve_company_context,
)


def test_workspace_member_can_resolve_company_in_workspace(session):
    _workspace, user, company = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    context = resolve_company_context(session, user_id=user.id, company_id=company.id)
    assert context.company_id == company.id
    assert context.workspace_id == company.workspace_id
    assert context.role is MembershipRole.ACCOUNTANT


def test_user_cannot_resolve_company_outside_workspace(session):
    _workspace_a, user_a, _company_a = seed_workspace(
        session, "Workspace A", "a@example.test", "Company A"
    )
    _workspace_b, _user_b, company_b = seed_workspace(
        session, "Workspace B", "b@example.test", "Company B"
    )
    with pytest.raises(CompanyAccessDenied):
        resolve_company_context(session, user_id=user_a.id, company_id=company_b.id)


def test_inactive_user_cannot_resolve_company(session):
    _workspace, user, company = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    user.is_active = False
    session.flush()
    with pytest.raises(CompanyAccessDenied):
        resolve_company_context(session, user_id=user.id, company_id=company.id)


def test_workspace_membership_is_unique_per_user(session):
    workspace, user, _company = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=MembershipRole.ADMIN))
    with pytest.raises(IntegrityError):
        session.flush()


def test_database_rejects_cross_company_category_reference(session):
    _workspace_a, _user_a, company_a = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    _workspace_b, _user_b, company_b = seed_workspace(session, "Workspace B", "b@example.test", "Company B")
    foreign_category = Category(
        company_id=company_b.id, name="Sales", normalized_name="sales", kind=CategoryKind.INFLOW
    )
    session.add(foreign_category)
    session.flush()
    transaction = Transaction(
        company_id=company_a.id,
        transaction_date=date(2026, 1, 1),
        amount=Decimal("100.00"),
        currency="XAF",
        direction=Direction.INFLOW,
        category_id=foreign_category.id,
        source_fingerprint="a" * 64,
        fingerprint_version=1,
    )
    session.add(transaction)
    with pytest.raises(IntegrityError):
        session.flush()


def test_database_rejects_non_positive_transaction_amount(session):
    _workspace, _user, company = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    transaction = Transaction(
        company_id=company.id,
        transaction_date=date(2026, 1, 1),
        amount=Decimal("0"),
        currency="XAF",
        direction=Direction.OUTFLOW,
        source_fingerprint="b" * 64,
        fingerprint_version=1,
    )
    session.add(transaction)
    with pytest.raises(IntegrityError):
        session.flush()


def test_review_import_row_cannot_be_linked_to_transaction(session):
    _workspace, user, company = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    batch = ImportBatch(
        company_id=company.id,
        uploaded_by_user_id=user.id,
        file_name="statement.csv",
        file_sha256="c" * 64,
        file_type=FileType.CSV,
        extraction_method=ImportMethod.CSV_ROWS,
        status=ImportBatchStatus.PREVIEWED,
    )
    session.add(batch)
    session.flush()
    transaction = Transaction(
        company_id=company.id,
        transaction_date=date(2026, 1, 1),
        amount=Decimal("10"),
        currency="XAF",
        direction=Direction.INFLOW,
        source_fingerprint="d" * 64,
        fingerprint_version=1,
    )
    session.add(transaction)
    session.flush()
    row = ImportRow(
        company_id=company.id,
        import_batch_id=batch.id,
        source_row_number=1,
        raw_values_json={"date": "01/01/2026"},
        row_status=ImportRowStatus.REVIEW,
        transaction_id=transaction.id,
    )
    session.add(row)
    with pytest.raises(IntegrityError):
        session.flush()


def test_soft_delete_requires_actor_timestamp_and_reason(session):
    _workspace, user, company = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    transaction = Transaction(
        company_id=company.id,
        transaction_date=date(2026, 1, 1),
        amount=Decimal("10"),
        currency="XAF",
        direction=Direction.OUTFLOW,
        source_fingerprint="e" * 64,
        fingerprint_version=1,
        deleted_by_user_id=user.id,
    )
    session.add(transaction)
    with pytest.raises(IntegrityError):
        session.flush()


def test_import_row_cannot_link_transaction_from_another_company(session):
    _workspace_a, user_a, company_a = seed_workspace(
        session, "Workspace A", "a@example.test", "Company A"
    )
    _workspace_b, _user_b, company_b = seed_workspace(
        session, "Workspace B", "b@example.test", "Company B"
    )
    batch = ImportBatch(
        company_id=company_a.id,
        uploaded_by_user_id=user_a.id,
        file_name="statement.csv",
        file_sha256="j" * 64,
        file_type=FileType.CSV,
        extraction_method=ImportMethod.CSV_ROWS,
        status=ImportBatchStatus.PREVIEWED,
    )
    foreign_transaction = Transaction(
        company_id=company_b.id,
        transaction_date=date(2026, 1, 1),
        amount=Decimal("15"),
        currency="XAF",
        direction=Direction.INFLOW,
        source_fingerprint="k" * 64,
        fingerprint_version=1,
    )
    session.add_all([batch, foreign_transaction])
    session.flush()
    row = ImportRow(
        company_id=company_a.id,
        import_batch_id=batch.id,
        source_row_number=1,
        raw_values_json={"amount": "15"},
        row_status=ImportRowStatus.VALID,
        transaction_id=foreign_transaction.id,
    )
    session.add(row)
    with pytest.raises(IntegrityError):
        session.flush()


def test_same_workspace_membership_role_applies_to_multiple_companies(session):
    workspace, user, first_company = seed_workspace(
        session, "Workspace A", "a@example.test", "Company A", role=MembershipRole.ACCOUNTANT
    )
    second_company = Company(
        workspace_id=workspace.id,
        name="Company A2",
        base_currency="XAF",
        timezone="Africa/Douala",
        is_demo=True,
    )
    session.add(second_company)
    session.flush()
    context_one = resolve_company_context(session, user_id=user.id, company_id=first_company.id)
    context_two = resolve_company_context(session, user_id=user.id, company_id=second_company.id)
    assert context_one.role is MembershipRole.ACCOUNTANT
    assert context_two.role is MembershipRole.ACCOUNTANT
    assert context_one.workspace_id == context_two.workspace_id == workspace.id
