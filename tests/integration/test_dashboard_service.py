from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from conftest import seed_workspace
from sme_financial_dashboard.db.models import (
    AccountSnapshot,
    AuditEvent,
    CategoryKind,
    Direction,
    MembershipRole,
    Transaction,
)
from sme_financial_dashboard.security.company_scope import (
    CompanyAccessDenied,
    CompanyContext,
    resolve_company_context,
)
from sme_financial_dashboard.services.categorization_service import CategoryService
from sme_financial_dashboard.services.dashboard_service import (
    AccountSnapshotService,
    BalanceStatus,
    DashboardError,
    DashboardFilters,
    DashboardService,
)


def _context(session, *, role=MembershipRole.ACCOUNTANT, suffix="dashboard"):
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
    counterparty: str | None = None,
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
        counterparty=counterparty,
        category_id=category_id,
        fingerprint_version=1,
        source_fingerprint=hashlib.sha256(label.encode("utf-8")).hexdigest(),
        is_validated=validated,
    )
    if deleted:
        row.deleted_at = datetime.now(UTC)
        row.deleted_by_user_id = deleted_by
        row.deletion_reason = "Removed from active cash-flow reporting test"
    session.add(row)
    session.flush()
    return row


def _filters(
    start=date(2026, 1, 1),
    end=date(2026, 1, 31),
    **kwargs,
):
    return DashboardFilters(start_date=start, end_date=end, **kwargs)


def test_report_uses_decimal_and_keeps_currency_partitions_and_rankings_separate(session):
    _workspace, _user, company, context = _context(session, suffix="partition")
    rent = CategoryService.create_category(
        session, context, name="Rent", kind=CategoryKind.OUTFLOW
    )
    _transaction(
        session, company, label="in-xaf", transaction_date=date(2026, 1, 3),
        amount="100.10", direction=Direction.INFLOW, counterparty="Customer A"
    )
    _transaction(
        session, company, label="rent-a", transaction_date=date(2026, 1, 5),
        amount="15.25", category_id=rent.id, counterparty="Landlord"
    )
    _transaction(
        session, company, label="rent-b", transaction_date=date(2026, 1, 7),
        amount="12.75", category_id=rent.id, counterparty="Landlord"
    )
    _transaction(
        session, company, label="usd-fee", transaction_date=date(2026, 1, 8),
        amount="5.00", currency="USD", counterparty="Bank"
    )
    _transaction(
        session, company, label="deleted", transaction_date=date(2026, 1, 9),
        amount="999.00", deleted=True, deleted_by=context.user_id
    )
    _transaction(
        session, company, label="unvalidated", transaction_date=date(2026, 1, 10),
        amount="777.00", validated=False
    )

    report = DashboardService.report(session, context, _filters())
    current = {item.currency: item for item in report.current.totals}

    assert report.current.transaction_count == 4
    assert current["XAF"].inflows == Decimal("100.100000")
    assert current["XAF"].outflows == Decimal("28.000000")
    assert current["XAF"].net == Decimal("72.100000")
    assert current["USD"].inflows == Decimal("0.000000")
    assert current["USD"].outflows == Decimal("5.000000")
    assert current["USD"].net == Decimal("-5.000000")
    assert [(item.currency, item.label, item.amount) for item in report.current.top_categories] == [
        ("USD", "Uncategorized", Decimal("5.000000")),
        ("XAF", "Rent", Decimal("28.000000")),
    ] or {(item.currency, item.label, item.amount) for item in report.current.top_categories} == {
        ("XAF", "Rent", Decimal("28.000000")),
        ("USD", "Uncategorized", Decimal("5.000000")),
    }
    xaf_counterparty = next(
        item for item in report.current.top_counterparties
        if item.currency == "XAF" and item.label == "Landlord"
    )
    assert xaf_counterparty.amount == Decimal("28.000000")
    assert all(item.month == "2026-01" for item in report.current.monthly)


def test_report_applies_filters_and_rejects_cross_company_category_or_context(session):
    _workspace_a, user_a, company_a, context_a = _context(session, suffix="filter-a")
    _workspace_b, _user_b, company_b, context_b = _context(session, suffix="filter-b")
    category_a = CategoryService.create_category(
        session, context_a, name="Office supplies", kind=CategoryKind.OUTFLOW
    )
    category_b = CategoryService.create_category(
        session, context_b, name="Other company", kind=CategoryKind.OUTFLOW
    )
    _transaction(
        session, company_a, label="a-hit", transaction_date=date(2026, 1, 3),
        amount="10.00", category_id=category_a.id, account_name="Cash"
    )
    _transaction(
        session, company_a, label="a-other", transaction_date=date(2026, 1, 4),
        amount="20.00", category_id=category_a.id, account_name="Bank"
    )
    _transaction(
        session, company_b, label="b-row", transaction_date=date(2026, 1, 3),
        amount="500.00", category_id=category_b.id, account_name="Cash"
    )

    report = DashboardService.report(
        session,
        context_a,
        _filters(currency="XAF", account_name="Cash", category_id=category_a.id),
    )
    assert report.current.transaction_count == 1
    assert report.current.totals[0].outflows == Decimal("10.000000")

    with pytest.raises(DashboardError, match="does not belong"):
        DashboardService.report(
            session, context_a, _filters(category_id=category_b.id)
        )

    forged = CompanyContext(
        user_id=user_a.id,
        workspace_id=context_a.workspace_id,
        company_id=company_b.id,
        role=MembershipRole.ADMIN,
    )
    with pytest.raises(CompanyAccessDenied):
        DashboardService.report(session, forged, _filters())


def test_comparison_uses_equal_length_previous_period_and_same_filters(session):
    _workspace, _user, company, context = _context(session, suffix="comparison")
    _transaction(
        session, company, label="previous-period", transaction_date=date(2026, 1, 10),
        amount="20.00", account_name="Main"
    )
    _transaction(
        session, company, label="current-period", transaction_date=date(2026, 1, 17),
        amount="35.00", account_name="Main"
    )
    _transaction(
        session, company, label="other-account", transaction_date=date(2026, 1, 17),
        amount="900.00", account_name="Reserve"
    )
    report = DashboardService.report(
        session,
        context,
        _filters(
            start=date(2026, 1, 15),
            end=date(2026, 1, 21),
            currency="XAF",
            account_name="Main",
        ),
    )
    assert (report.previous_start_date, report.previous_end_date) == (
        date(2026, 1, 8), date(2026, 1, 14)
    )
    assert report.current.totals[0].outflows == Decimal("35.000000")
    assert report.previous.totals[0].outflows == Decimal("20.000000")
    assert report.current.transaction_count == report.previous.transaction_count == 1


def test_balance_uses_latest_verified_snapshot_and_only_eligible_account_movements(session):
    _workspace, _user, company, context = _context(session, suffix="balance")
    _transaction(
        session, company, label="balance-day-one", transaction_date=date(2026, 1, 1),
        amount="80.00", direction=Direction.INFLOW
    )
    _transaction(
        session, company, label="balance-day-ten", transaction_date=date(2026, 1, 10),
        amount="120.00", direction=Direction.OUTFLOW
    )
    _transaction(
        session, company, label="other-account", transaction_date=date(2026, 1, 11),
        amount="500.00", direction=Direction.INFLOW, account_name="Reserve"
    )
    _transaction(
        session, company, label="other-currency", transaction_date=date(2026, 1, 12),
        amount="700.00", direction=Direction.INFLOW, currency="USD"
    )
    _transaction(
        session, company, label="deleted-balance", transaction_date=date(2026, 1, 13),
        amount="999.00", deleted=True, deleted_by=context.user_id
    )
    _transaction(
        session, company, label="unvalidated-balance", transaction_date=date(2026, 1, 14),
        amount="888.00", validated=False
    )
    AccountSnapshotService.create(
        session, context, account_name="Operating", as_of_date=date(2026, 1, 1),
        currency="XAF", opening_balance="1000.00", is_verified=True,
        source_description="Verified opening balance from bank statement"
    )
    report = DashboardService.report(
        session,
        context,
        _filters(currency="XAF", account_name="Operating"),
    )
    assert report.current.balance.status is BalanceStatus.AVAILABLE
    assert report.current.balance.opening_balance == Decimal("1000.000000")
    assert report.current.balance.closing_balance == Decimal("960.000000")

    AccountSnapshotService.create(
        session, context, account_name="Operating", as_of_date=date(2026, 1, 15),
        currency="XAF", opening_balance="2000.00", is_verified=True,
        source_description="Later verified statement opening balance"
    )
    _transaction(
        session, company, label="balance-after-latest-snapshot",
        transaction_date=date(2026, 1, 18), amount="30.00", direction=Direction.INFLOW
    )
    _transaction(
        session, company, label="balance-expense-after-latest-snapshot",
        transaction_date=date(2026, 1, 20), amount="10.00", direction=Direction.OUTFLOW
    )
    refreshed = DashboardService.report(
        session,
        context,
        _filters(currency="XAF", account_name="Operating"),
    )
    assert refreshed.current.balance.snapshot_date == date(2026, 1, 15)
    assert refreshed.current.balance.closing_balance == Decimal("2020.000000")


def test_balance_is_unavailable_without_required_scope_snapshot_or_unfiltered_flow(session):
    _workspace, _user, _company, context = _context(session, suffix="balance-state")
    AccountSnapshotService.create(
        session, context, account_name="Operating", as_of_date=date(2026, 1, 1),
        currency="XAF", opening_balance="10.00", is_verified=False,
        source_description="Unverified statement note"
    )
    assert DashboardService.report(session, context, _filters()).current.balance.status is (
        BalanceStatus.ACCOUNT_REQUIRED
    )
    assert DashboardService.report(
        session, context, _filters(account_name="Operating")
    ).current.balance.status is BalanceStatus.CURRENCY_REQUIRED
    assert DashboardService.report(
        session, context, _filters(currency="XAF", account_name="Operating")
    ).current.balance.status is BalanceStatus.NO_VERIFIED_SNAPSHOT
    assert DashboardService.report(
        session,
        context,
        _filters(currency="XAF", account_name="Operating", direction=Direction.OUTFLOW),
    ).current.balance.status is BalanceStatus.INCOMPATIBLE_FILTERS


def test_conflicting_latest_verified_snapshots_make_closing_balance_unavailable(session):
    _workspace, user, company, context = _context(session, suffix="snapshot-conflict")
    for amount, label in [("100.00", "first"), ("110.00", "second")]:
        session.add(
            AccountSnapshot(
                company_id=company.id,
                account_name="Operating",
                as_of_date=date(2026, 1, 1),
                currency="XAF",
                opening_balance=Decimal(amount),
                is_verified=True,
                source_description=label,
                created_by_user_id=user.id,
            )
        )
    session.flush()
    report = DashboardService.report(
        session,
        context,
        _filters(currency="XAF", account_name="Operating"),
    )
    assert report.current.balance.status is BalanceStatus.CONFLICTING_SNAPSHOTS
    assert report.current.balance.closing_balance is None


def test_snapshot_creation_is_audited_company_scoped_and_validated(session):
    _workspace, _user, company, context = _context(session, suffix="snapshot-create")
    snapshot = AccountSnapshotService.create(
        session, context, account_name="  Operating  ", as_of_date=date(2026, 1, 1),
        currency="xaf", opening_balance="-25.125000", is_verified=True,
        source_description="Statement balance independently reconciled"
    )
    assert snapshot.account_name == "Operating"
    assert snapshot.currency == "XAF"
    assert snapshot.opening_balance == Decimal("-25.125000")
    assert snapshot.is_verified is True
    audit = session.query(AuditEvent).filter_by(
        entity_type="ACCOUNT_SNAPSHOT", entity_id=snapshot.id
    ).one()
    assert audit.action == "ACCOUNT_SNAPSHOT_CREATED"
    assert audit.actor_user_id == context.user_id
    assert AccountSnapshotService.list_recent(session, context) == [snapshot]

    with pytest.raises(DashboardError, match="already exists"):
        AccountSnapshotService.create(
            session, context, account_name="Operating", as_of_date=date(2026, 1, 1),
            currency="XAF", opening_balance="1.00", is_verified=True,
            source_description="Duplicate snapshot"
        )
    with pytest.raises(DashboardError, match="floats are forbidden"):
        AccountSnapshotService.create(
            session, context, account_name="Other", as_of_date=date(2026, 1, 1),
            currency="XAF", opening_balance=1.25, is_verified=False,
            source_description="Float should be rejected"
        )
    with pytest.raises(DashboardError, match="six decimal places"):
        AccountSnapshotService.create(
            session, context, account_name="Other", as_of_date=date(2026, 1, 2),
            currency="XAF", opening_balance="1.1234567", is_verified=False,
            source_description="Too many decimal places"
        )
    assert session.query(AccountSnapshot).filter_by(company_id=company.id).count() == 1


def test_viewer_can_read_dashboard_but_cannot_create_opening_snapshot(session):
    _workspace, _user, company, context = _context(
        session, role=MembershipRole.VIEWER, suffix="snapshot-viewer"
    )
    report = DashboardService.report(session, context, _filters())
    assert report.current.transaction_count == 0
    with pytest.raises(PermissionError):
        AccountSnapshotService.create(
            session, context, account_name="Operating", as_of_date=date(2026, 1, 1),
            currency="XAF", opening_balance="10.00", is_verified=True,
            source_description="Viewer must not create a snapshot"
        )
