from __future__ import annotations

import pytest
from sqlalchemy import select

from sme_financial_dashboard.db.models import (
    BootstrapState,
    MembershipRole,
    WorkspaceMembership,
)
from sme_financial_dashboard.services.auth_service import (
    AuthService,
    AuthenticationError,
)


SECRET = "local-test-secret-that-is-at-least-32-characters-long"


def test_first_admin_bootstrap_creates_exactly_one_admin_workspace(session):
    result = AuthService.bootstrap_first_admin(
        session,
        email=" ADMIN@EXAMPLE.TEST ",
        display_name="First Admin",
        password="a-long-and-valid-password",
        workspace_name="Main Workspace",
    )
    session.commit()
    assert result.user.email == "admin@example.test"
    assert result.workspace.name == "Main Workspace"
    membership = session.scalar(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == result.user.id)
    )
    assert membership.role is MembershipRole.ADMIN
    assert membership.is_active is True
    assert session.get(BootstrapState, 1) is not None


def test_bootstrap_cannot_be_repeated(session):
    AuthService.bootstrap_first_admin(
        session,
        email="admin@example.test",
        display_name="First Admin",
        password="a-long-and-valid-password",
        workspace_name="Main Workspace",
    )
    session.commit()
    with pytest.raises(AuthenticationError):
        AuthService.bootstrap_first_admin(
            session,
            email="second@example.test",
            display_name="Second Admin",
            password="another-long-password",
            workspace_name="Other Workspace",
        )


def test_login_issues_signed_database_backed_session_and_logout_revokes_it(session):
    result = AuthService.bootstrap_first_admin(
        session,
        email="admin@example.test",
        display_name="First Admin",
        password="a-long-and-valid-password",
        workspace_name="Main Workspace",
    )
    session.commit()
    token = AuthService.login(
        session,
        email="ADMIN@example.test",
        password="a-long-and-valid-password",
        secret=SECRET,
    )
    session.commit()
    assert AuthService.authenticate(session, token, secret=SECRET).id == result.user.id
    assert AuthService.logout(session, token, secret=SECRET)
    session.commit()
    assert AuthService.authenticate(session, token, secret=SECRET) is None


def test_login_does_not_disclose_unknown_email_vs_bad_password(session):
    AuthService.bootstrap_first_admin(
        session,
        email="admin@example.test",
        display_name="First Admin",
        password="a-long-and-valid-password",
        workspace_name="Main Workspace",
    )
    session.commit()
    with pytest.raises(AuthenticationError, match="Email or password is incorrect"):
        AuthService.login(
            session,
            email="unknown@example.test",
            password="some-long-password",
            secret=SECRET,
        )
    with pytest.raises(AuthenticationError, match="Email or password is incorrect"):
        AuthService.login(
            session,
            email="admin@example.test",
            password="wrong-password-123",
            secret=SECRET,
        )


def test_tampered_session_token_is_rejected(session):
    AuthService.bootstrap_first_admin(
        session,
        email="admin@example.test",
        display_name="First Admin",
        password="a-long-and-valid-password",
        workspace_name="Main Workspace",
    )
    session.commit()
    token = AuthService.login(
        session,
        email="admin@example.test",
        password="a-long-and-valid-password",
        secret=SECRET,
    )
    session.commit()
    assert AuthService.authenticate(session, token + "x", secret=SECRET) is None
    assert AuthService.authenticate(session, token, secret="different-secret-" * 3) is None


def test_user_account_deactivation_invalidates_session(session):
    result = AuthService.bootstrap_first_admin(
        session,
        email="admin@example.test",
        display_name="First Admin",
        password="a-long-and-valid-password",
        workspace_name="Main Workspace",
    )
    session.commit()
    token = AuthService.login(
        session,
        email="admin@example.test",
        password="a-long-and-valid-password",
        secret=SECRET,
    )
    session.commit()
    result.user.is_active = False
    session.commit()
    assert AuthService.authenticate(session, token, secret=SECRET) is None


def test_password_change_revokes_existing_sessions(session):
    result = AuthService.bootstrap_first_admin(
        session,
        email="admin@example.test",
        display_name="First Admin",
        password="a-long-and-valid-password",
        workspace_name="Main Workspace",
    )
    session.commit()
    token = AuthService.login(
        session,
        email="admin@example.test",
        password="a-long-and-valid-password",
        secret=SECRET,
    )
    session.commit()
    AuthService.change_password(
        session,
        user_id=result.user.id,
        current_password="a-long-and-valid-password",
        new_password="another-valid-long-password",
    )
    session.commit()
    assert AuthService.authenticate(session, token, secret=SECRET) is None
    new_token = AuthService.login(
        session,
        email="admin@example.test",
        password="another-valid-long-password",
        secret=SECRET,
    )
    assert AuthService.authenticate(session, new_token, secret=SECRET).id == result.user.id
