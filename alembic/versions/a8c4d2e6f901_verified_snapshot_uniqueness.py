"""Prevent duplicate verified opening snapshots for one account/date/currency.

Revision ID: a8c4d2e6f901
Revises: 2b7ce1a9c4d2
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "a8c4d2e6f901"
down_revision = "2b7ce1a9c4d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        duplicate = op.get_bind().execute(
            sa.text(
                """
                SELECT company_id, account_name, as_of_date, currency
                FROM account_snapshots
                WHERE is_verified = 1
                GROUP BY company_id, account_name, as_of_date, currency
                HAVING COUNT(*) > 1
                LIMIT 1
                """
            )
        ).first()
        if duplicate is not None:
            raise RuntimeError(
                "Cannot enforce verified snapshot uniqueness: duplicate verified "
                "account/date/currency rows already exist. Resolve them before upgrading."
            )

    op.create_index(
        "uq_verified_snapshot_company_account_date_currency",
        "account_snapshots",
        ["company_id", "account_name", "as_of_date", "currency"],
        unique=True,
        sqlite_where=sa.text("is_verified = 1"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_verified_snapshot_company_account_date_currency",
        table_name="account_snapshots",
    )
