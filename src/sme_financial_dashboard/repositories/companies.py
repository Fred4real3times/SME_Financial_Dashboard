"""Workspace-scoped company listing."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import Company, User, WorkspaceMembership


class CompanyRepository:
    @staticmethod
    def list_for_user(session: Session, *, user_id: UUID) -> list[Company]:
        statement = (
            select(Company)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Company.workspace_id)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(WorkspaceMembership.user_id == user_id, User.is_active.is_(True))
            .order_by(Company.name, Company.id)
        )
        return list(session.scalars(statement).all())
