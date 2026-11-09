from __future__ import annotations

import pytest
from sqlalchemy import select

from sme_financial_dashboard.db.models import (
    AuditEvent,
    MembershipRole,
)
from sme_financial_dashboard.security.company_scope import (
    CompanyAccessDenied,
    resolve_workspace_context,
)
from sme_financial_dashboard.services.auth_service import AuthService
from sme_financial_dashboard.services.workspace_service import WorkspaceError, WorkspaceService


def _admin(session):
    result = AuthService.bootstrap_first_admin(
        session,
        email="admin@example.test",
        display_name="Workspace Admin",
        password="a-long-and-valid-password",
        workspace_name="Primary",
    )
    session.commit()
    context = resolve_workspace_context(
        session, user_id=result.user.id, workspace_id=result.workspace.id
    )
    return result, context


def test_admin_can_create_company_with_audit(session):
    _result, context = _admin(session)
    company = WorkspaceService.create_company(
        session,
        context,
        name="Retail Cameroon",
        base_currency="xaf",
        timezone="Africa/Douala",
    )
    session.commit()
    assert company.base_currency == "XAF"
    assert company.is_demo is False
    assert session.scalar(
        select(AuditEvent).where(AuditEvent.entity_id == company.id)
    ).action == "COMPANY_CREATED"


def test_non_admin_cannot_create_company(session):
    result, admin_context = _admin(session)
    member = WorkspaceService.add_member(
        session,
        admin_context,
        email="accountant@example.test",
        display_name="Accountant",
        role=MembershipRole.ACCOUNTANT,
    )
    context = resolve_workspace_context(
        session, user_id=member.user.id, workspace_id=result.workspace.id
    )
    with pytest.raises(PermissionError):
        WorkspaceService.create_company(
            session,
            context,
            name="Unauthorized Company",
            base_currency="XAF",
        )


def test_admin_can_add_member_and_one_time_password_is_forced_to_change(session):
    result, context = _admin(session)
    member = WorkspaceService.add_member(
        session,
        context,
        email="member@example.test",
        display_name="Workspace Member",
        role=MembershipRole.VIEWER,
    )
    session.commit()
    assert member.temporary_password
    assert len(member.temporary_password) >= 20
    assert member.user.must_change_password is True
    assert member.membership.role is MembershipRole.VIEWER


def test_member_can_be_added_to_second_workspace_with_independent_role(session):
    result, context = _admin(session)
    member = WorkspaceService.add_member(
        session, context, email="member@example.test", display_name="Member", role=MembershipRole.VIEWER
    )
    session.commit()
    second_workspace = WorkspaceService.create_workspace(
        session, actor_user_id=member.user.id, name="Personal"
    )
    session.commit()
    second_context = resolve_workspace_context(
        session, user_id=member.user.id, workspace_id=second_workspace.id
    )
    assert second_context.role is MembershipRole.ADMIN
    assert second_workspace.id != result.workspace.id


def test_last_admin_cannot_be_demoted_or_deactivated(session):
    _result, context = _admin(session)
    members = WorkspaceService.list_members(session, context)
    admin_membership = next(m for m, u in members if u.email == "admin@example.test")
    with pytest.raises(WorkspaceError, match="last active ADMIN"):
        WorkspaceService.update_member_role(
            session, context, membership_id=admin_membership.id, new_role=MembershipRole.VIEWER
        )
    with pytest.raises(WorkspaceError, match="last active ADMIN"):
        WorkspaceService.deactivate_member(
            session, context, membership_id=admin_membership.id
        )


def test_non_admin_cannot_manage_members(session):
    result, admin_context = _admin(session)
    member = WorkspaceService.add_member(
        session, admin_context, email="viewer@example.test",
        display_name="Viewer", role=MembershipRole.VIEWER
    )
    viewer_context = resolve_workspace_context(
        session, user_id=member.user.id, workspace_id=result.workspace.id
    )
    with pytest.raises(PermissionError):
        WorkspaceService.list_members(session, viewer_context)
    with pytest.raises(PermissionError):
        WorkspaceService.add_member(
            session, viewer_context, email="attacker@example.test",
            display_name="Attacker", role=MembershipRole.ADMIN
        )


def test_inactive_membership_cannot_resolve_workspace(session):
    result, context = _admin(session)
    members = WorkspaceService.list_members(session, context)
    admin_membership = members[0][0]
    admin_membership.is_active = False
    session.commit()
    with pytest.raises(CompanyAccessDenied):
        resolve_workspace_context(
            session, user_id=result.user.id, workspace_id=result.workspace.id
        )
