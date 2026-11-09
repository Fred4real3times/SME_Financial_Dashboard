"""Authentication and one-time first ADMIN bootstrap."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import (
    AuditEvent,
    BootstrapState,
    MembershipRole,
    User,
    Workspace,
    WorkspaceMembership,
)
from sme_financial_dashboard.security.passwords import hash_password, verify_password
from sme_financial_dashboard.security.sessions import (
    authenticate_session,
    issue_session,
    revoke_all_user_sessions,
    revoke_session,
)


class AuthenticationError(ValueError):
    """Raised with a deliberately generic message for failed authentication."""


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    user: User
    workspace: Workspace


def normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("Email address is required")
    value = email.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("Enter a valid email address")
    return value


def _clean_name(value: str, *, field: str, maximum: int) -> str:
    cleaned = " ".join(value.strip().split()) if isinstance(value, str) else ""
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{field} must contain between 1 and {maximum} characters")
    return cleaned


class AuthService:
    @staticmethod
    def bootstrap_first_admin(
        session: Session,
        *,
        email: str,
        display_name: str,
        password: str,
        workspace_name: str,
    ) -> BootstrapResult:
        if session.get(BootstrapState, 1) is not None:
            raise AuthenticationError("First-run setup has already been completed")
        if session.scalar(select(func.count()).select_from(User)) != 0:
            raise AuthenticationError("Bootstrap is closed because user records already exist")

        normalized_email = normalize_email(email)
        name = _clean_name(display_name, field="Display name", maximum=120)
        workspace_label = _clean_name(workspace_name, field="Workspace name", maximum=120)
        user = User(
            email=normalized_email,
            display_name=name,
            password_hash=hash_password(password),
            is_active=True,
            must_change_password=False,
        )
        workspace = Workspace(name=workspace_label)
        session.add_all([user, workspace])
        session.flush()
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=user.id,
            role=MembershipRole.ADMIN,
            is_active=True,
        )
        session.add(membership)
        session.add(
            BootstrapState(id=1, initial_admin_user_id=user.id, initialized_at=datetime.now(UTC))
        )
        session.add(
            AuditEvent(
                company_id=None,
                actor_user_id=user.id,
                action="FIRST_ADMIN_BOOTSTRAPPED",
                entity_type="WORKSPACE",
                entity_id=workspace.id,
                after_json={"workspace_name": workspace.name, "role": "ADMIN"},
            )
        )
        session.flush()
        return BootstrapResult(user=user, workspace=workspace)

    @staticmethod
    def login(
        session: Session,
        *,
        email: str,
        password: str,
        secret: str,
        ttl_hours: int = 12,
    ) -> str:
        try:
            normalized_email = normalize_email(email)
        except ValueError:
            raise AuthenticationError("Email or password is incorrect") from None
        user = session.scalar(select(User).where(User.email == normalized_email))
        if user is None or not user.is_active or not verify_password(user.password_hash, password):
            raise AuthenticationError("Email or password is incorrect")
        return issue_session(session, user=user, secret=secret, ttl_hours=ttl_hours)

    @staticmethod
    def authenticate(session: Session, token: str, *, secret: str) -> User | None:
        return authenticate_session(session, token, secret=secret)

    @staticmethod
    def logout(session: Session, token: str, *, secret: str) -> bool:
        return revoke_session(session, token, secret=secret)

    @staticmethod
    def change_password(
        session: Session,
        *,
        user_id: UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        user = session.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
        if user is None or not verify_password(user.password_hash, current_password):
            raise AuthenticationError("Current password is incorrect")
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        revoke_all_user_sessions(session, user_id=user.id)
        session.flush()
