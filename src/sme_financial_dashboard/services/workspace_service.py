"""Workspace, company and membership management with service-level authorization."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import (
    AuditEvent,
    Company,
    MembershipRole,
    User,
    Workspace,
    WorkspaceMembership,
)
from sme_financial_dashboard.security.company_scope import (
    WorkspaceContext,
    resolve_workspace_context,
)
from sme_financial_dashboard.security.passwords import hash_password
from sme_financial_dashboard.security.rbac import (
    AuthorizationError,
    Permission,
    require_permission,
)
from sme_financial_dashboard.services.auth_service import _clean_name, normalize_email


class WorkspaceError(ValueError):
    """Raised when a workspace operation violates an application invariant."""


@dataclass(frozen=True, slots=True)
class MemberResult:
    membership: WorkspaceMembership
    user: User
    temporary_password: str | None


def _admin_context(session: Session, context: WorkspaceContext) -> WorkspaceContext:
    verified = resolve_workspace_context(
        session, user_id=context.user_id, workspace_id=context.workspace_id
    )
    require_permission(verified.role, Permission.MANAGE_WORKSPACE)
    return verified


class WorkspaceService:
    @staticmethod
    def list_for_user(session: Session, *, user_id) -> list[tuple[Workspace, MembershipRole]]:
        statement = (
            select(Workspace, WorkspaceMembership.role)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
            .order_by(Workspace.name, Workspace.id)
        )
        return list(session.execute(statement).all())

    @staticmethod
    def create_workspace(session: Session, *, actor_user_id, name: str) -> Workspace:
        actor = session.scalar(select(User).where(User.id == actor_user_id, User.is_active.is_(True)))
        if actor is None:
            raise WorkspaceError("An active user is required")
        workspace = Workspace(name=_clean_name(name, field="Workspace name", maximum=120))
        session.add(workspace)
        session.flush()
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=actor.id,
            role=MembershipRole.ADMIN,
            is_active=True,
        )
        session.add(membership)
        session.add(
            AuditEvent(
                company_id=None,
                actor_user_id=actor.id,
                action="WORKSPACE_CREATED",
                entity_type="WORKSPACE",
                entity_id=workspace.id,
                after_json={"name": workspace.name, "creator_role": "ADMIN"},
            )
        )
        session.flush()
        return workspace

    @staticmethod
    def list_companies(
        session: Session, context: WorkspaceContext
    ) -> list[Company]:
        verified = resolve_workspace_context(
            session, user_id=context.user_id, workspace_id=context.workspace_id
        )
        statement = (
            select(Company)
            .where(Company.workspace_id == verified.workspace_id)
            .order_by(Company.name, Company.id)
        )
        return list(session.scalars(statement).all())

    @staticmethod
    def create_company(
        session: Session,
        context: WorkspaceContext,
        *,
        name: str,
        base_currency: str,
        timezone: str = "Africa/Douala",
        is_demo: bool = True,
    ) -> Company:
        verified = _admin_context(session, context)
        company_name = _clean_name(name, field="Company name", maximum=160)
        currency = base_currency.strip().upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise WorkspaceError("Currency must be a three-letter ISO 4217 code")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, TypeError) as exc:
            raise WorkspaceError("Timezone must be a valid IANA timezone") from exc
        existing = session.scalar(
            select(Company.id).where(
                Company.workspace_id == verified.workspace_id,
                func.lower(Company.name) == company_name.casefold(),
            )
        )
        if existing is not None:
            raise WorkspaceError("A company with this name already exists in the workspace")
        company = Company(
            workspace_id=verified.workspace_id,
            name=company_name,
            base_currency=currency,
            timezone=timezone,
            is_demo=is_demo,
        )
        session.add(company)
        session.flush()
        session.add(
            AuditEvent(
                company_id=company.id,
                actor_user_id=verified.user_id,
                action="COMPANY_CREATED",
                entity_type="COMPANY",
                entity_id=company.id,
                after_json={
                    "name": company.name,
                    "base_currency": company.base_currency,
                    "timezone": company.timezone,
                    "is_demo": company.is_demo,
                },
            )
        )
        session.flush()
        return company

    @staticmethod
    def list_members(
        session: Session, context: WorkspaceContext
    ) -> list[tuple[WorkspaceMembership, User]]:
        verified = resolve_workspace_context(
            session, user_id=context.user_id, workspace_id=context.workspace_id
        )
        statement = (
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(WorkspaceMembership.workspace_id == verified.workspace_id)
            .order_by(User.email)
        )
        return list(session.execute(statement).all())

    @staticmethod
    def add_member(
        session: Session,
        context: WorkspaceContext,
        *,
        email: str,
        display_name: str,
        role: MembershipRole,
    ) -> MemberResult:
        verified = _admin_context(session, context)
        normalized_email = normalize_email(email)
        cleaned_name = _clean_name(display_name, field="Display name", maximum=120)
        role = MembershipRole(role)
        user = session.scalar(select(User).where(User.email == normalized_email))
        temporary_password = None
        if user is None:
            temporary_password = secrets.token_urlsafe(18)
            user = User(
                email=normalized_email,
                display_name=cleaned_name,
                password_hash=hash_password(temporary_password),
                is_active=True,
                must_change_password=True,
            )
            session.add(user)
            session.flush()
        elif not user.is_active:
            raise WorkspaceError("This user account is inactive")
        existing = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == verified.workspace_id,
                WorkspaceMembership.user_id == user.id,
            )
        )
        if existing is not None and existing.is_active:
            raise WorkspaceError("This user is already an active workspace member")
        if existing is None:
            membership = WorkspaceMembership(
                workspace_id=verified.workspace_id,
                user_id=user.id,
                role=role,
                is_active=True,
            )
            session.add(membership)
        else:
            membership = existing
            membership.role = role
            membership.is_active = True
        session.flush()
        session.add(
            AuditEvent(
                company_id=None,
                actor_user_id=verified.user_id,
                action="WORKSPACE_MEMBER_ADDED",
                entity_type="WORKSPACE_MEMBERSHIP",
                entity_id=membership.id,
                after_json={"user_email": user.email, "role": role.value},
            )
        )
        session.flush()
        return MemberResult(membership, user, temporary_password)

    @staticmethod
    def update_member_role(
        session: Session,
        context: WorkspaceContext,
        *,
        membership_id,
        new_role: MembershipRole,
    ) -> WorkspaceMembership:
        verified = _admin_context(session, context)
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.id == membership_id,
                WorkspaceMembership.workspace_id == verified.workspace_id,
                WorkspaceMembership.is_active.is_(True),
            )
        )
        if membership is None:
            raise WorkspaceError("Active workspace member not found")
        old_role = membership.role
        if old_role is MembershipRole.ADMIN and new_role is not MembershipRole.ADMIN:
            remaining_admins = session.scalar(
                select(func.count()).select_from(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == verified.workspace_id,
                    WorkspaceMembership.is_active.is_(True),
                    WorkspaceMembership.role == MembershipRole.ADMIN,
                    WorkspaceMembership.id != membership.id,
                )
            )
            if remaining_admins == 0:
                raise WorkspaceError("The last active ADMIN cannot be demoted")
        membership.role = new_role
        session.add(
            AuditEvent(
                company_id=None,
                actor_user_id=verified.user_id,
                action="WORKSPACE_MEMBER_ROLE_CHANGED",
                entity_type="WORKSPACE_MEMBERSHIP",
                entity_id=membership.id,
                before_json={"role": old_role.value},
                after_json={"role": new_role.value},
            )
        )
        session.flush()
        return membership

    @staticmethod
    def deactivate_member(
        session: Session, context: WorkspaceContext, *, membership_id
    ) -> WorkspaceMembership:
        verified = _admin_context(session, context)
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.id == membership_id,
                WorkspaceMembership.workspace_id == verified.workspace_id,
                WorkspaceMembership.is_active.is_(True),
            )
        )
        if membership is None:
            raise WorkspaceError("Active workspace member not found")
        if membership.role is MembershipRole.ADMIN:
            remaining_admins = session.scalar(
                select(func.count()).select_from(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == verified.workspace_id,
                    WorkspaceMembership.is_active.is_(True),
                    WorkspaceMembership.role == MembershipRole.ADMIN,
                    WorkspaceMembership.id != membership.id,
                )
            )
            if remaining_admins == 0:
                raise WorkspaceError("The last active ADMIN cannot be deactivated")
        membership.is_active = False
        session.add(
            AuditEvent(
                company_id=None,
                actor_user_id=verified.user_id,
                action="WORKSPACE_MEMBER_DEACTIVATED",
                entity_type="WORKSPACE_MEMBERSHIP",
                entity_id=membership.id,
                before_json={"role": membership.role.value, "is_active": True},
                after_json={"role": membership.role.value, "is_active": False},
            )
        )
        session.flush()
        return membership
