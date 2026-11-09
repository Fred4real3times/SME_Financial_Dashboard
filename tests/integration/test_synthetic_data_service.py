from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select

from sme_financial_dashboard.db.models import (
    AccountSnapshot,
    AuditEvent,
    Company,
    ImportBatch,
    ImportBatchStatus,
    ImportRow,
    ImportRowStatus,
    Transaction,
)
from sme_financial_dashboard.services.synthetic_data_service import (
    SyntheticDatasetService,
)


def test_synthetic_dataset_creates_three_profiles_twelve_months_and_held_noise(session):
    summary = SyntheticDatasetService.generate(
        session,
        admin_email="synthetic-admin@example.test",
        admin_password="Synthetic-QA-Password-2026!",
        end_date=date(2026, 10, 31),
        seed=20261109,
    )

    assert isinstance(summary.workspace_id, UUID)
    assert summary.start_date == date(2025, 11, 1)
    assert summary.end_date == date(2026, 10, 31)
    assert summary.imported_count == 300
    assert len(summary.companies) == 3

    companies = session.scalars(
        select(Company).where(Company.workspace_id == summary.workspace_id)
    ).all()
    assert len(companies) == 3
    assert all(company.is_demo for company in companies)

    for result in summary.companies:
        batch = session.get(ImportBatch, result.batch_id)
        assert batch is not None
        assert batch.status is ImportBatchStatus.PARTIALLY_COMMITTED
        assert (
            batch.valid_count,
            batch.invalid_count,
            batch.duplicate_count,
            batch.review_count,
        ) == (100, 1, 1, 2)
        assert result.source_rows == 104
        assert result.imported == 100

        rows = session.scalars(
            select(ImportRow)
            .where(ImportRow.import_batch_id == batch.id)
            .order_by(ImportRow.source_row_number)
        ).all()
        assert len(rows) == 104
        assert sum(row.row_status is ImportRowStatus.INVALID for row in rows) == 1
        assert sum(row.row_status is ImportRowStatus.DUPLICATE for row in rows) == 1
        assert sum(row.row_status is ImportRowStatus.REVIEW for row in rows) == 2
        assert all(
            row.transaction_id is None
            for row in rows
            if row.row_status in {
                ImportRowStatus.INVALID,
                ImportRowStatus.DUPLICATE,
                ImportRowStatus.REVIEW,
            }
        )
        assert sum(row.transaction_id is not None for row in rows) == 100

        transactions = session.scalars(
            select(Transaction).where(
                Transaction.company_id == result.company_id,
                Transaction.is_validated.is_(True),
                Transaction.deleted_at.is_(None),
            )
        ).all()
        assert len(transactions) == 100
        assert all(transaction.category_id is not None for transaction in transactions)
        months = {
            (transaction.transaction_date.year, transaction.transaction_date.month)
            for transaction in transactions
        }
        assert len(months) == 12
        assert {transaction.currency for transaction in transactions} == {"XAF", "USD"}
        assert sum(transaction.currency == "USD" for transaction in transactions) == 4

        snapshots = session.scalars(
            select(AccountSnapshot).where(AccountSnapshot.company_id == result.company_id)
        ).all()
        assert len(snapshots) == 2
        assert all(item.is_verified for item in snapshots)
        assert {item.currency for item in snapshots} == {"XAF", "USD"}

        import_commit_events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.company_id == result.company_id,
                AuditEvent.action == "IMPORT_BATCH_COMMITTED",
            )
        ).all()
        assert len(import_commit_events) == 1


def test_synthetic_dataset_requires_full_month_end_before_bootstrap(session):
    import pytest

    with pytest.raises(ValueError, match="last day"):
        SyntheticDatasetService.generate(
            session,
            admin_email="synthetic-invalid-date@example.test",
            admin_password="Synthetic-QA-Password-2026!",
            end_date=date(2026, 10, 30),
        )
    assert session.scalar(select(func.count()).select_from(Company)) == 0
