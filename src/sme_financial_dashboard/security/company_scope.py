"""Resolve company access using a workspace membership, never a UI company ID alone."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import Company, MembershipRole, User, WorkspaceMembership


class CompanyAccessDenied(PermissionError):
    """Raised when the actor is not a member of the company's workspace."""


@dataclass(frozen=True, slots=True)
class CompanyContext:
    user_id: UUID
    workspace_id: UUID
    company_id: UUID
    role: MembershipRole


def resolve_company_context(session: Session, *, user_id: UUID, company_id: UUID) -> CompanyContext:
    statement = (
        select(WorkspaceMembership.workspace_id, WorkspaceMembership.role)
        .join(Company, Company.workspace_id == WorkspaceMembership.workspace_id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.user_id == user_id,
            Company.id == company_id,
            User.is_active.is_(True),
            WorkspaceMembership.is_active.is_(True),
        )
    )
    membership = session.execute(statement).one_or_none()
    if membership is None:
        raise CompanyAccessDenied("User is not authorized for the requested company")
    return CompanyContext(
        user_id=user_id,
        workspace_id=membership.workspace_id,
        company_id=company_id,
        role=membership.role,
    )



@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    user_id: UUID
    workspace_id: UUID
    role: MembershipRole


def resolve_workspace_context(
    session: Session, *, user_id: UUID, workspace_id: UUID
) -> WorkspaceContext:
    statement = (
        select(WorkspaceMembership.role)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    role = session.scalar(statement)
    if role is None:
        raise CompanyAccessDenied("User is not an active member of the requested workspace")
    return WorkspaceContext(user_id=user_id, workspace_id=workspace_id, role=role)
