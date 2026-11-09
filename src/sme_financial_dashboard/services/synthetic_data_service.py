"""Generate deterministic fictional SME data through the real import workflow."""

from __future__ import annotations

import csv
import io
import random
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import CategoryKind, MatchField, MatchOperator
from sme_financial_dashboard.security.company_scope import (
    resolve_company_context,
    resolve_workspace_context,
)
from sme_financial_dashboard.services.auth_service import AuthService
from sme_financial_dashboard.services.categorization_service import (
    CategorizationRuleService,
    CategoryService,
)
from sme_financial_dashboard.services.dashboard_service import AccountSnapshotService
from sme_financial_dashboard.services.import_service import ImportMapping, ImportService
from sme_financial_dashboard.services.workspace_service import WorkspaceService


@dataclass(frozen=True, slots=True)
class SyntheticCompanyResult:
    company_id: UUID
    name: str
    batch_id: UUID
    imported: int
    source_rows: int
    invalid: int
    duplicate: int
    review: int


@dataclass(frozen=True, slots=True)
class SyntheticDatasetResult:
    workspace_id: UUID
    admin_user_id: UUID
    start_date: date
    end_date: date
    seed: int
    companies: tuple[SyntheticCompanyResult, ...]

    @property
    def imported_count(self) -> int:
        return sum(company.imported for company in self.companies)


# Profile order is stable; the seed controls amount variation only.
_PROFILES = (
    ("Coastal Retail SARL", "RETAIL", "Monthly retail sales receipt", "sales", (1_200_000, 850_000), "8500000.00", (300_000, 420_000, 95_000, 620_000, 80_000, 25_000)),
    ("Littoral Advisory Services SARL", "SERVICES", "Professional service income", "service income", (2_100_000, 1_350_000), "6200000.00", (260_000, 980_000, 115_000, 145_000, 55_000, 30_000)),
    ("Mungo Light Manufacturing SARL", "MANUFACTURING", "Finished goods sale receipt", "goods sale", (4_500_000, 2_800_000), "18500000.00", (600_000, 1_250_000, 255_000, 2_050_000, 340_000, 60_000)),
)
_EXPENSES = (
    ("Rent", "rent", "Office rent payment", "Property manager", 0),
    ("Payroll", "payroll", "Monthly payroll", "Staff payroll", 1),
    ("Utilities", "utility", "Electricity utility bill", "Electricity provider", 2),
    ("Suppliers", "supplier", "Supplier materials payment", "Local suppliers", 3),
    ("Logistics", "logistics", "Logistics delivery cost", "Transport partner", 4),
    ("Bank fees", "bank fee", "Monthly bank fee", "Commercial bank", 5),
)
_HEADERS = (
    "Transaction Date", "Value Date", "Amount", "Currency", "Direction",
    "Description", "Counterparty", "Reference", "Account",
)


def _months(end_date: date) -> tuple[date, ...]:
    if end_date.day != monthrange(end_date.year, end_date.month)[1]:
        raise ValueError("end_date must be the last day of a month.")
    year, month = end_date.year, end_date.month
    months = []
    for _ in range(11):
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    for _ in range(12):
        months.append(date(year, month, 1))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return tuple(months)


def _amount(base: int, rng: random.Random) -> str:
    scaled = Decimal(base) * Decimal(rng.randint(90, 110)) / Decimal(100)
    return format(scaled.quantize(Decimal("0.01")), ".2f")


def _make_row(day: date, amount: str, currency: str, direction: str,
              description: str, counterparty: str, reference: str, account: str) -> dict[str, str]:
    return {
        "Transaction Date": day.isoformat(),
        "Value Date": day.isoformat(),
        "Amount": amount,
        "Currency": currency,
        "Direction": direction,
        "Description": description,
        "Counterparty": counterparty,
        "Reference": reference,
        "Account": account,
    }


def _company_rows(profile, *, end_date: date, rng: random.Random) -> list[dict[str, str]]:
    name, slug, revenue_description, revenue_match, revenue_amounts, opening, costs = profile
    rent, payroll, utilities, suppliers, logistics, bank_fees = costs
    rows = []
    for month_index, month_start in enumerate(_months(end_date)):
        year, month = month_start.year, month_start.month
        last_day = monthrange(year, month)[1]

        def txn_day(
            day_number: int,
            *,
            year: int = year,
            month: int = month,
            last_day: int = last_day,
        ) -> date:
            return date(year, month, min(day_number, last_day))

        prefix = f"SYN-{slug}-{year}{month:02d}"
        account = "Main XAF account"
        rows.extend([
            _make_row(txn_day(5), _amount(revenue_amounts[0], rng), "XAF", "INFLOW",
                      revenue_description, "Customers", f"{prefix}-IN-01", account),
            _make_row(txn_day(20), _amount(revenue_amounts[1], rng), "XAF", "INFLOW",
                      revenue_description, "Customers", f"{prefix}-IN-02", account),
        ])
        for _category, keyword, description, counterparty, index in _EXPENSES:
            cost = costs[index]
            rows.append(_make_row(
                txn_day((1, 25, 10, 12, 22, 27)[index]),
                _amount(cost, rng), "XAF", "OUTFLOW", description, counterparty,
                f"{prefix}-OUT-{keyword.upper().replace(' ', '-')}", account,
            ))
        if month_index % 3 == 0:
            rows.append(_make_row(
                txn_day(28), _amount(40, rng), "USD", "OUTFLOW",
                "International bank fee", "Foreign correspondent bank",
                f"{prefix}-OUT-USD", "USD settlement account",
            ))

    if len(rows) != 100:
        raise RuntimeError(f"Expected 100 valid rows for {slug}; generated {len(rows)}.")
    duplicate = dict(rows[0])
    invalid = _make_row(
        end_date - timedelta(days=3), "NOT-A-DECIMAL", "XAF", "OUTFLOW",
        "Malformed amount row for QA", "Synthetic noisy source",
        f"SYN-{slug}-NOISE-INVALID", "Main XAF account",
    )
    review = _make_row(
        end_date - timedelta(days=5), "12345.67", "XAF", "OUTFLOW",
        "Unreferenced supplier adjustment", "Ambiguous vendor", "",
        "Main XAF account",
    )
    return [*rows, duplicate, invalid, dict(review), dict(review)]


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=_HEADERS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def _configure_categories(session: Session, context, profile) -> None:
    _name, _slug, _description, revenue_match, *_ = profile
    revenue = CategoryService.create_category(
        session, context, name="Revenue", kind=CategoryKind.INFLOW
    )
    rules = [(revenue.id, revenue_match)]
    for category_name, keyword, _description, _counterparty, _index in _EXPENSES:
        category = CategoryService.create_category(
            session, context, name=category_name, kind=CategoryKind.OUTFLOW
        )
        rules.append((category.id, keyword))
    for category_id, keyword in rules:
        CategorizationRuleService.create_rule(
            session, context, category_id=category_id,
            match_field=MatchField.KEYWORD, operator=MatchOperator.CONTAINS,
            match_value=keyword, priority=100,
        )


class SyntheticDatasetService:
    """Create 3 fictional SME companies and 12 months of staged/imported transactions."""

    @staticmethod
    def generate(
        session: Session,
        *,
        admin_email: str,
        admin_password: str,
        end_date: date,
        seed: int = 20261109,
    ) -> SyntheticDatasetResult:
        months = _months(end_date)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer.")
        start_date = months[0]
        bootstrap = AuthService.bootstrap_first_admin(
            session, email=admin_email, display_name="Synthetic Demo Administrator",
            password=admin_password, workspace_name="Synthetic SME QA Workspace",
        )
        workspace_context = resolve_workspace_context(
            session, user_id=bootstrap.user.id, workspace_id=bootstrap.workspace.id
        )
        rng = random.Random(seed)
        mapping = ImportMapping(
            columns={
                "transaction_date": 0, "value_date": 1, "amount": 2,
                "currency": 3, "direction": 4, "description": 5,
                "counterparty": 6, "reference": 7, "account_name": 8,
            },
            date_format="%Y-%m-%d", decimal_separator=".", thousands_separator=None,
        )
        results = []
        for profile in _PROFILES:
            name, slug, _description, _revenue_match, _income, opening, _costs = profile
            company = WorkspaceService.create_company(
                session, workspace_context, name=name, base_currency="XAF",
                timezone="Africa/Douala", is_demo=True,
            )
            context = resolve_company_context(
                session, user_id=bootstrap.user.id, company_id=company.id
            )
            _configure_categories(session, context, profile)
            for account, currency, amount in (
                ("Main XAF account", "XAF", opening),
                ("USD settlement account", "USD", "3000.00"),
            ):
                AccountSnapshotService.create(
                    session, context, account_name=account, as_of_date=start_date,
                    currency=currency, opening_balance=amount, is_verified=True,
                    source_description="SYNTHETIC ONLY — generated opening balance",
                )
            rows = _company_rows(profile, end_date=end_date, rng=rng)
            preview = ImportService.preview(
                session, file_bytes=_csv_bytes(rows),
                file_name=f"synthetic_{slug.lower()}_12_months.csv",
                mapping=mapping, context=context,
            )
            expected = (100, 1, 1, 2)
            actual = (
                preview.valid_count, preview.invalid_count,
                preview.duplicate_count, preview.review_count,
            )
            if actual != expected:
                raise RuntimeError(f"{slug} preview counts expected {expected}, got {actual}.")
            committed = ImportService.commit(
                session, preview_id=preview.preview_id, context=context,
                confirm=True, confirm_partial=True,
            )
            if committed.imported_count != 100:
                raise RuntimeError(f"{slug} import expected 100 transactions.")
            results.append(SyntheticCompanyResult(
                company_id=company.id, name=company.name, batch_id=committed.batch_id,
                imported=committed.imported_count, source_rows=preview.total_count,
                invalid=committed.invalid_count, duplicate=committed.duplicate_count,
                review=committed.review_count,
            ))
        return SyntheticDatasetResult(
            workspace_id=bootstrap.workspace.id, admin_user_id=bootstrap.user.id,
            start_date=start_date, end_date=end_date, seed=seed,
            companies=tuple(results),
        )
