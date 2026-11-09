from datetime import UTC, date, datetime
from decimal import Decimal

from conftest import seed_workspace
from sme_financial_dashboard.db.models import Company, Direction, Transaction
from sme_financial_dashboard.repositories.companies import CompanyRepository
from sme_financial_dashboard.repositories.transactions import TransactionRepository
from sme_financial_dashboard.security.company_scope import resolve_company_context


def test_transaction_repository_never_returns_other_company_rows(session):
    _workspace_a, user_a, company_a = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    _workspace_b, _user_b, company_b = seed_workspace(session, "Workspace B", "b@example.test", "Company B")
    transaction_a = Transaction(
        company_id=company_a.id,
        transaction_date=date(2026, 1, 1),
        amount=Decimal("100"),
        currency="XAF",
        direction=Direction.INFLOW,
        source_fingerprint="f" * 64,
        fingerprint_version=1,
    )
    transaction_b = Transaction(
        company_id=company_b.id,
        transaction_date=date(2026, 1, 2),
        amount=Decimal("200"),
        currency="XAF",
        direction=Direction.INFLOW,
        source_fingerprint="g" * 64,
        fingerprint_version=1,
    )
    session.add_all([transaction_a, transaction_b])
    session.flush()
    context = resolve_company_context(session, user_id=user_a.id, company_id=company_a.id)

    rows = TransactionRepository.list_active(session, context)
    assert [row.id for row in rows] == [transaction_a.id]
    assert TransactionRepository.get_active_by_id(session, context, transaction_b.id) is None


def test_transaction_repository_excludes_soft_deleted_rows(session):
    _workspace, user, company = seed_workspace(session, "Workspace A", "a@example.test", "Company A")
    active = Transaction(
        company_id=company.id,
        transaction_date=date(2026, 1, 1),
        amount=Decimal("100"),
        currency="XAF",
        direction=Direction.INFLOW,
        source_fingerprint="h" * 64,
        fingerprint_version=1,
    )
    deleted = Transaction(
        company_id=company.id,
        transaction_date=date(2026, 1, 2),
        amount=Decimal("200"),
        currency="XAF",
        direction=Direction.OUTFLOW,
        source_fingerprint="i" * 64,
        fingerprint_version=1,
        deleted_at=datetime.now(UTC),
        deleted_by_user_id=user.id,
        deletion_reason="Duplicate entered by mistake",
    )
    session.add_all([active, deleted])
    session.flush()
    context = resolve_company_context(session, user_id=user.id, company_id=company.id)
    assert [row.id for row in TransactionRepository.list_active(session, context)] == [active.id]


def test_company_repository_lists_only_companies_for_active_workspace_membership(session):
    workspace_a, user_a, company_a = seed_workspace(
        session, "Workspace A", "a@example.test", "Company A"
    )
    company_a2 = Company(
        workspace_id=workspace_a.id,
        name="Company A2",
        base_currency="XAF",
        timezone="Africa/Douala",
        is_demo=True,
    )
    _workspace_b, _user_b, _company_b = seed_workspace(
        session, "Workspace B", "b@example.test", "Company B"
    )
    session.add(company_a2)
    session.flush()

    companies = CompanyRepository.list_for_user(session, user_id=user_a.id)
    assert {company.id for company in companies} == {company_a.id, company_a2.id}

    user_a.is_active = False
    session.flush()
    assert CompanyRepository.list_for_user(session, user_id=user_a.id) == []
