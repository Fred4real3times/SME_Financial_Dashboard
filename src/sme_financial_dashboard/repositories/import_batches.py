"""Company-scoped import history queries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import ImportBatch
from sme_financial_dashboard.security.company_scope import CompanyContext


class ImportBatchRepository:
    @staticmethod
    def list_for_company(session: Session, context: CompanyContext) -> list[ImportBatch]:
        statement = (
            select(ImportBatch)
            .where(ImportBatch.company_id == context.company_id)
            .order_by(ImportBatch.created_at.desc(), ImportBatch.id)
        )
        return list(session.scalars(statement).all())

    @staticmethod
    def get_by_id(
        session: Session, context: CompanyContext, batch_id: UUID
    ) -> ImportBatch | None:
        statement = select(ImportBatch).where(
            ImportBatch.company_id == context.company_id,
            ImportBatch.id == batch_id,
        )
        return session.scalar(statement)
