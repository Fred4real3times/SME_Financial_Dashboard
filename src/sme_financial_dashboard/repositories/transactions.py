"""Transaction reads that always enforce the resolved company context."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import Transaction
from sme_financial_dashboard.security.company_scope import CompanyContext


class TransactionRepository:
    @staticmethod
    def _base_statement(context: CompanyContext) -> Select[tuple[Transaction]]:
        return select(Transaction).where(
            Transaction.company_id == context.company_id,
            Transaction.deleted_at.is_(None),
        )

    @classmethod
    def list_active(
        cls,
        session: Session,
        context: CompanyContext,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        currency: str | None = None,
    ) -> list[Transaction]:
        statement = cls._base_statement(context)
        if start_date is not None:
            statement = statement.where(Transaction.transaction_date >= start_date)
        if end_date is not None:
            statement = statement.where(Transaction.transaction_date <= end_date)
        if currency is not None:
            statement = statement.where(Transaction.currency == currency.upper())
        statement = statement.order_by(Transaction.transaction_date, Transaction.id)
        return list(session.scalars(statement).all())

    @classmethod
    def get_active_by_id(
        cls, session: Session, context: CompanyContext, transaction_id: UUID
    ) -> Transaction | None:
        statement = cls._base_statement(context).where(Transaction.id == transaction_id)
        return session.scalar(statement)
