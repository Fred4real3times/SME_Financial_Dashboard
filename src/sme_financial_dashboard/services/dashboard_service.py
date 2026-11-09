"""Company-scoped reporting and verified opening-balance snapshots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import (
    AccountSnapshot,
    AuditEvent,
    Category,
    Direction,
    Transaction,
)
from sme_financial_dashboard.domain.money import MAX_AMOUNT, SIX_PLACES
from sme_financial_dashboard.security.company_scope import (
    CompanyContext,
    resolve_company_context,
)
from sme_financial_dashboard.security.rbac import Permission, require_permission


ZERO = Decimal("0")


class DashboardError(ValueError):
    """Raised when reporting filters or snapshot data violate the finance contract."""


class BalanceStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
    CURRENCY_REQUIRED = "CURRENCY_REQUIRED"
    INCOMPATIBLE_FILTERS = "INCOMPATIBLE_FILTERS"
    NO_VERIFIED_SNAPSHOT = "NO_VERIFIED_SNAPSHOT"
    CONFLICTING_SNAPSHOTS = "CONFLICTING_SNAPSHOTS"


@dataclass(frozen=True, slots=True)
class DashboardFilters:
    start_date: date
    end_date: date
    currency: str | None = None
    account_name: str | None = None
    category_id: UUID | None = None
    direction: Direction | str | None = None


@dataclass(frozen=True, slots=True)
class CurrencyTotals:
    currency: str
    inflows: Decimal
    outflows: Decimal
    net: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class MonthlyCashflow:
    month: str
    currency: str
    inflows: Decimal
    outflows: Decimal
    net: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class SpendBreakdown:
    currency: str
    label: str
    amount: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class BalanceState:
    status: BalanceStatus
    account_name: str | None = None
    currency: str | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    snapshot_date: date | None = None
    source_description: str | None = None


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    start_date: date
    end_date: date
    totals: tuple[CurrencyTotals, ...]
    monthly: tuple[MonthlyCashflow, ...]
    top_categories: tuple[SpendBreakdown, ...]
    top_counterparties: tuple[SpendBreakdown, ...]
    transaction_count: int
    balance: BalanceState


@dataclass(frozen=True, slots=True)
class DashboardReport:
    current: DashboardSummary
    previous: DashboardSummary
    previous_start_date: date
    previous_end_date: date


@dataclass(frozen=True, slots=True)
class DashboardFilterOptions:
    currencies: tuple[str, ...]
    account_names: tuple[str, ...]
    categories: tuple[tuple[UUID, str], ...]


def _verified_context(
    session: Session,
    context: CompanyContext,
    permission: Permission = Permission.VIEW,
) -> CompanyContext:
    verified = resolve_company_context(
        session, user_id=context.user_id, company_id=context.company_id
    )
    require_permission(verified.role, permission)
    return verified


def _normalize_currency(value: str) -> str:
    if not isinstance(value, str):
        raise DashboardError("Currency must be a three-letter ISO 4217 code.")
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise DashboardError("Currency must be a three-letter ISO 4217 code.")
    return normalized


def _validated_filters(
    session: Session,
    context: CompanyContext,
    filters: DashboardFilters,
) -> DashboardFilters:
    if not isinstance(filters.start_date, date) or isinstance(filters.start_date, datetime):
        raise DashboardError("Start date must be a calendar date.")
    if not isinstance(filters.end_date, date) or isinstance(filters.end_date, datetime):
        raise DashboardError("End date must be a calendar date.")
    if filters.start_date > filters.end_date:
        raise DashboardError("Start date must be on or before end date.")

    currency = _normalize_currency(filters.currency) if filters.currency is not None else None
    account_name = filters.account_name
    if account_name is not None:
        if not isinstance(account_name, str):
            raise DashboardError("Account name must be text.")
        account_name = account_name.strip()
        if not account_name or len(account_name) > 120:
            raise DashboardError("Account name must contain 1 to 120 characters.")

    category_id = filters.category_id
    if category_id is not None:
        if not isinstance(category_id, UUID):
            raise DashboardError("Category filter must be a UUID.")
        category_exists = session.scalar(
            select(Category.id).where(
                Category.id == category_id,
                Category.company_id == context.company_id,
            )
        )
        if category_exists is None:
            raise DashboardError("Category filter does not belong to the active company.")

    direction = filters.direction
    if direction is not None:
        try:
            direction = direction if isinstance(direction, Direction) else Direction(direction)
        except ValueError as exc:
            raise DashboardError("Direction must be INFLOW or OUTFLOW.") from exc

    return DashboardFilters(
        start_date=filters.start_date,
        end_date=filters.end_date,
        currency=currency,
        account_name=account_name,
        category_id=category_id,
        direction=direction,
    )


def _month_keys(start_date: date, end_date: date) -> list[str]:
    cursor = date(start_date.year, start_date.month, 1)
    final_month = date(end_date.year, end_date.month, 1)
    months: list[str] = []
    while cursor <= final_month:
        months.append(cursor.strftime("%Y-%m"))
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return months


def _load_rows(
    session: Session,
    company_id: UUID,
    filters: DashboardFilters,
    *,
    limit: int | None = None,
) -> list[tuple[Transaction, str | None]]:
    statement = (
        select(Transaction, Category.name)
        .outerjoin(
            Category,
            and_(
                Category.id == Transaction.category_id,
                Category.company_id == Transaction.company_id,
            ),
        )
        .where(
            Transaction.company_id == company_id,
            Transaction.deleted_at.is_(None),
            Transaction.is_validated.is_(True),
            Transaction.transaction_date >= filters.start_date,
            Transaction.transaction_date <= filters.end_date,
        )
    )
    if filters.currency is not None:
        statement = statement.where(Transaction.currency == filters.currency)
    if filters.account_name is not None:
        statement = statement.where(Transaction.account_name == filters.account_name)
    if filters.category_id is not None:
        statement = statement.where(Transaction.category_id == filters.category_id)
    if filters.direction is not None:
        statement = statement.where(Transaction.direction == filters.direction)
    statement = statement.order_by(Transaction.transaction_date, Transaction.id)
    if limit is not None:
        statement = statement.limit(limit)
    return [(transaction, category_name) for transaction, category_name in session.execute(statement)]


def _aggregate(
    rows: list[tuple[Transaction, str | None]],
    filters: DashboardFilters,
    *,
    balance: BalanceState | None = None,
) -> DashboardSummary:
    totals: dict[str, list[Decimal | int]] = defaultdict(lambda: [ZERO, ZERO, 0])
    monthly: dict[tuple[str, str], list[Decimal | int]] = defaultdict(
        lambda: [ZERO, ZERO, 0]
    )
    category_spend: dict[tuple[str, str], list[Decimal | int]] = defaultdict(
        lambda: [ZERO, 0]
    )
    counterparty_spend: dict[tuple[str, str], list[Decimal | int]] = defaultdict(
        lambda: [ZERO, 0]
    )

    for transaction, category_name in rows:
        amount = transaction.amount
        if not isinstance(amount, Decimal):
            raise DashboardError("Stored transaction amount is not a Decimal.")
        currency = transaction.currency.upper()
        month = transaction.transaction_date.strftime("%Y-%m")
        totals[currency][2] += 1
        monthly[(month, currency)][2] += 1

        if transaction.direction is Direction.INFLOW:
            totals[currency][0] += amount
            monthly[(month, currency)][0] += amount
        else:
            totals[currency][1] += amount
            monthly[(month, currency)][1] += amount
            category_label = category_name or "Uncategorized"
            counterparty_label = (transaction.counterparty or "").strip() or "Unspecified"
            category_spend[(currency, category_label)][0] += amount
            category_spend[(currency, category_label)][1] += 1
            counterparty_spend[(currency, counterparty_label)][0] += amount
            counterparty_spend[(currency, counterparty_label)][1] += 1

    currencies = {filters.currency} if filters.currency is not None else set(totals)
    currency_totals = tuple(
        CurrencyTotals(
            currency=currency,
            inflows=totals[currency][0],
            outflows=totals[currency][1],
            net=totals[currency][0] - totals[currency][1],
            transaction_count=int(totals[currency][2]),
        )
        for currency in sorted(currencies)
    )

    monthly_rows = tuple(
        MonthlyCashflow(
            month=month,
            currency=currency,
            inflows=monthly[(month, currency)][0],
            outflows=monthly[(month, currency)][1],
            net=monthly[(month, currency)][0] - monthly[(month, currency)][1],
            transaction_count=int(monthly[(month, currency)][2]),
        )
        for currency in sorted(currencies)
        for month in _month_keys(filters.start_date, filters.end_date)
    )

    def _rank(
        source: dict[tuple[str, str], list[Decimal | int]],
    ) -> tuple[SpendBreakdown, ...]:
        result: list[SpendBreakdown] = []
        for currency in sorted({key[0] for key in source}):
            ranked = sorted(
                (
                    SpendBreakdown(
                        currency=key[0],
                        label=key[1],
                        amount=value[0],
                        transaction_count=int(value[1]),
                    )
                    for key, value in source.items()
                    if key[0] == currency
                ),
                key=lambda item: (-item.amount, item.label.casefold()),
            )
            result.extend(ranked[:10])
        return tuple(result)

    return DashboardSummary(
        start_date=filters.start_date,
        end_date=filters.end_date,
        totals=currency_totals,
        monthly=monthly_rows,
        top_categories=_rank(category_spend),
        top_counterparties=_rank(counterparty_spend),
        transaction_count=len(rows),
        balance=balance or BalanceState(status=BalanceStatus.ACCOUNT_REQUIRED),
    )


def _balance_state(
    session: Session,
    company_id: UUID,
    filters: DashboardFilters,
) -> BalanceState:
    if filters.account_name is None:
        return BalanceState(status=BalanceStatus.ACCOUNT_REQUIRED)
    if filters.currency is None:
        return BalanceState(
            status=BalanceStatus.CURRENCY_REQUIRED,
            account_name=filters.account_name,
        )
    if filters.category_id is not None or filters.direction is not None:
        return BalanceState(
            status=BalanceStatus.INCOMPATIBLE_FILTERS,
            account_name=filters.account_name,
            currency=filters.currency,
        )

    snapshots = list(
        session.scalars(
            select(AccountSnapshot)
            .where(
                AccountSnapshot.company_id == company_id,
                AccountSnapshot.account_name == filters.account_name,
                AccountSnapshot.currency == filters.currency,
                AccountSnapshot.is_verified.is_(True),
                AccountSnapshot.as_of_date <= filters.end_date,
            )
            .order_by(AccountSnapshot.as_of_date.desc(), AccountSnapshot.created_at.desc())
        ).all()
    )
    if not snapshots:
        return BalanceState(
            status=BalanceStatus.NO_VERIFIED_SNAPSHOT,
            account_name=filters.account_name,
            currency=filters.currency,
        )

    snapshot_date = snapshots[0].as_of_date
    latest_snapshots = [item for item in snapshots if item.as_of_date == snapshot_date]
    if len(latest_snapshots) != 1:
        return BalanceState(
            status=BalanceStatus.CONFLICTING_SNAPSHOTS,
            account_name=filters.account_name,
            currency=filters.currency,
            snapshot_date=snapshot_date,
        )

    snapshot = latest_snapshots[0]
    movements = session.execute(
        select(Transaction.amount, Transaction.direction).where(
            Transaction.company_id == company_id,
            Transaction.deleted_at.is_(None),
            Transaction.is_validated.is_(True),
            Transaction.account_name == filters.account_name,
            Transaction.currency == filters.currency,
            Transaction.transaction_date >= snapshot.as_of_date,
            Transaction.transaction_date <= filters.end_date,
        )
    ).all()
    inflows = sum(
        (amount for amount, direction in movements if direction is Direction.INFLOW),
        ZERO,
    )
    outflows = sum(
        (amount for amount, direction in movements if direction is Direction.OUTFLOW),
        ZERO,
    )
    opening_balance = snapshot.opening_balance
    return BalanceState(
        status=BalanceStatus.AVAILABLE,
        account_name=filters.account_name,
        currency=filters.currency,
        opening_balance=opening_balance,
        closing_balance=opening_balance + inflows - outflows,
        snapshot_date=snapshot.as_of_date,
        source_description=snapshot.source_description,
    )


class DashboardService:
    """Read-only, company-scoped dashboard reports; currencies are never combined."""

    @staticmethod
    def filter_options(
        session: Session,
        context: CompanyContext,
    ) -> DashboardFilterOptions:
        verified = _verified_context(session, context)
        currencies = tuple(
            session.scalars(
                select(Transaction.currency)
                .where(
                    Transaction.company_id == verified.company_id,
                    Transaction.deleted_at.is_(None),
                    Transaction.is_validated.is_(True),
                )
                .distinct()
                .order_by(Transaction.currency)
            ).all()
        )
        account_names = tuple(
            session.scalars(
                select(Transaction.account_name)
                .where(
                    Transaction.company_id == verified.company_id,
                    Transaction.deleted_at.is_(None),
                    Transaction.is_validated.is_(True),
                    Transaction.account_name.is_not(None),
                    Transaction.account_name != "",
                )
                .distinct()
                .order_by(Transaction.account_name)
            ).all()
        )
        categories = tuple(
            (category.id, category.name)
            for category in session.scalars(
                select(Category)
                .where(Category.company_id == verified.company_id)
                .order_by(Category.normalized_name, Category.id)
            ).all()
        )
        return DashboardFilterOptions(
            currencies=currencies,
            account_names=account_names,
            categories=categories,
        )

    @staticmethod
    def transactions(
        session: Session,
        context: CompanyContext,
        filters: DashboardFilters,
        *,
        limit: int | None = None,
    ) -> list[tuple[Transaction, str | None]]:
        """Return exactly the validated transaction rows covered by report filters."""
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise DashboardError("Transaction list limit must be a positive integer.")
        verified = _verified_context(session, context)
        validated = _validated_filters(session, verified, filters)
        return _load_rows(session, verified.company_id, validated, limit=limit)

    @staticmethod
    def report(
        session: Session,
        context: CompanyContext,
        filters: DashboardFilters,
    ) -> DashboardReport:
        verified = _verified_context(session, context)
        validated = _validated_filters(session, verified, filters)
        current_rows = _load_rows(session, verified.company_id, validated)
        balance = _balance_state(session, verified.company_id, validated)
        current = _aggregate(current_rows, validated, balance=balance)

        period_days = (validated.end_date - validated.start_date).days + 1
        previous_end = validated.start_date - timedelta(days=1)
        previous_start = previous_end - timedelta(days=period_days - 1)
        previous_filters = DashboardFilters(
            start_date=previous_start,
            end_date=previous_end,
            currency=validated.currency,
            account_name=validated.account_name,
            category_id=validated.category_id,
            direction=validated.direction,
        )
        previous_rows = _load_rows(session, verified.company_id, previous_filters)
        previous = _aggregate(previous_rows, previous_filters)
        return DashboardReport(
            current=current,
            previous=previous,
            previous_start_date=previous_start,
            previous_end_date=previous_end,
        )


def _parse_opening_balance(value: str | int | Decimal) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise DashboardError("Opening balance must be text, integer or Decimal; floats are forbidden.")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise DashboardError("Opening balance is not a valid decimal number.") from exc
    if not amount.is_finite():
        raise DashboardError("Opening balance must be finite.")
    if abs(amount) > MAX_AMOUNT:
        raise DashboardError("Opening balance exceeds NUMERIC(20,6) capacity.")
    try:
        if amount != amount.quantize(SIX_PLACES):
            raise DashboardError("Opening balance supports at most six decimal places.")
    except InvalidOperation as exc:
        raise DashboardError("Opening balance exceeds supported decimal precision.") from exc
    return amount


class AccountSnapshotService:
    """Manage opening-balance evidence; only explicitly verified snapshots affect balances."""

    @staticmethod
    def list_recent(
        session: Session,
        context: CompanyContext,
        *,
        limit: int = 100,
    ) -> list[AccountSnapshot]:
        verified = _verified_context(session, context)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise DashboardError("Snapshot limit must be an integer from 1 to 500.")
        statement = (
            select(AccountSnapshot)
            .where(AccountSnapshot.company_id == verified.company_id)
            .order_by(AccountSnapshot.as_of_date.desc(), AccountSnapshot.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(statement).all())

    @staticmethod
    def create(
        session: Session,
        context: CompanyContext,
        *,
        account_name: str,
        as_of_date: date,
        currency: str,
        opening_balance: str | int | Decimal,
        is_verified: bool,
        source_description: str,
    ) -> AccountSnapshot:
        verified = _verified_context(
            session, context, Permission.MANAGE_SNAPSHOTS
        )
        if not isinstance(account_name, str):
            raise DashboardError("Account name must be text.")
        normalized_account = account_name.strip()
        if not normalized_account or len(normalized_account) > 120:
            raise DashboardError("Account name must contain 1 to 120 characters.")
        if not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
            raise DashboardError("Snapshot date must be a calendar date.")
        normalized_currency = _normalize_currency(currency)
        normalized_balance = _parse_opening_balance(opening_balance)
        if not isinstance(is_verified, bool):
            raise DashboardError("Snapshot verification flag must be boolean.")
        if not isinstance(source_description, str):
            raise DashboardError("Snapshot source description must be text.")
        source = source_description.strip()
        if not source or len(source) > 250:
            raise DashboardError("Snapshot source description must contain 1 to 250 characters.")

        existing = session.scalar(
            select(AccountSnapshot.id).where(
                AccountSnapshot.company_id == verified.company_id,
                AccountSnapshot.account_name == normalized_account,
                AccountSnapshot.as_of_date == as_of_date,
                AccountSnapshot.currency == normalized_currency,
            )
        )
        if existing is not None:
            raise DashboardError(
                "A snapshot already exists for this account, date and currency; do not overwrite it."
            )

        snapshot = AccountSnapshot(
            company_id=verified.company_id,
            account_name=normalized_account,
            as_of_date=as_of_date,
            currency=normalized_currency,
            opening_balance=normalized_balance,
            is_verified=is_verified,
            source_description=source,
            created_by_user_id=verified.user_id,
        )
        try:
            with session.begin_nested():
                session.add(snapshot)
                session.flush()
                session.add(
                    AuditEvent(
                        company_id=verified.company_id,
                        actor_user_id=verified.user_id,
                        action="ACCOUNT_SNAPSHOT_CREATED",
                        entity_type="ACCOUNT_SNAPSHOT",
                        entity_id=snapshot.id,
                        after_json={
                            "account_name": normalized_account,
                            "as_of_date": as_of_date.isoformat(),
                            "currency": normalized_currency,
                            "opening_balance": str(normalized_balance),
                            "is_verified": is_verified,
                            "source_description": source,
                        },
                    )
                )
                session.flush()
        except IntegrityError as exc:
            raise DashboardError("Opening-balance snapshot could not be saved.") from exc
        return snapshot
