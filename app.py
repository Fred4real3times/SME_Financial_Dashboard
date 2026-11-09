"""Authenticated Streamlit entry point for the SME Financial Dashboard."""

from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from sme_financial_dashboard.config import Settings
from sme_financial_dashboard.db.models import BootstrapState, MembershipRole
from sme_financial_dashboard.db.session import build_engine, build_session_factory
from sme_financial_dashboard.security.company_scope import (
    resolve_workspace_context,
)
from sme_financial_dashboard.services.auth_service import AuthService, AuthenticationError
from sme_financial_dashboard.services.workspace_service import WorkspaceError, WorkspaceService

st.set_page_config(page_title="SME Financial Dashboard", page_icon="📊", layout="wide")


@st.cache_resource
def get_runtime():
    settings = Settings.from_environment()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(settings)
    return settings, engine, factory


try:
    settings, engine, session_factory = get_runtime()
except Exception as exc:  # configuration must fail visibly, without leaking secrets
    st.error(f"Application configuration error: {exc}")
    st.stop()

if len(settings.session_secret) < 32:
    st.error("SESSION_SECRET is missing or too short.")
    st.code("python scripts/generate_session_secret.py")
    st.caption("Copy the generated value into .env, then restart Streamlit.")
    st.stop()

with session_factory() as db:
    bootstrap_done = db.get(BootstrapState, 1) is not None

if not bootstrap_done:
    st.title("SME Financial Dashboard — first-time setup")
    st.info("Create the one-time first ADMIN account and workspace. This setup closes permanently after success.")
    with st.form("bootstrap_form"):
        email = st.text_input("Administrator email")
        display_name = st.text_input("Administrator full name")
        workspace_name = st.text_input("Workspace name")
        password = st.text_input("Password (12–128 characters)", type="password")
        confirmation = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create first ADMIN", type="primary")
    if submitted:
        if password != confirmation:
            st.error("Passwords do not match.")
        else:
            try:
                with session_factory() as db, db.begin():
                    result = AuthService.bootstrap_first_admin(
                        db,
                        email=email,
                        display_name=display_name,
                        password=password,
                        workspace_name=workspace_name,
                    )
                st.success(f"Workspace '{result.workspace.name}' created. You can now sign in.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.stop()

token = st.session_state.get("auth_token")
user = None
if token:
    with session_factory() as db, db.begin():
        user = AuthService.authenticate(db, token, secret=settings.session_secret)
    if user is None:
        st.session_state.pop("auth_token", None)
        st.session_state.pop("active_workspace_id", None)
        st.session_state.pop("active_company_id", None)
        st.warning("Your session is invalid or expired. Please sign in again.")

if user is None:
    st.title("SME Financial Dashboard")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        try:
            with session_factory() as db, db.begin():
                new_token = AuthService.login(
                    db,
                    email=email,
                    password=password,
                    secret=settings.session_secret,
                    ttl_hours=settings.session_ttl_hours,
                )
            st.session_state["auth_token"] = new_token
            st.rerun()
        except AuthenticationError as exc:
            st.error(str(exc))
        except Exception:
            st.error("Unable to sign in. Check the application logs.")
    st.stop()

st.sidebar.write(f"Signed in as **{user.display_name}**")
if st.sidebar.button("Sign out"):
    with session_factory() as db, db.begin():
        AuthService.logout(db, token, secret=settings.session_secret)
    st.session_state.pop("auth_token", None)
    st.session_state.pop("active_workspace_id", None)
    st.session_state.pop("active_company_id", None)
    st.rerun()

if user.must_change_password:
    st.title("Change your temporary password")
    with st.form("change_password_form"):
        old_password = st.text_input("Current password", type="password")
        new_password = st.text_input("New password (12–128 characters)", type="password")
        new_confirmation = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update password", type="primary")
    if submitted:
        if new_password != new_confirmation:
            st.error("Passwords do not match.")
        else:
            try:
                with session_factory() as db, db.begin():
                    AuthService.change_password(
                        db,
                        user_id=user.id,
                        current_password=old_password,
                        new_password=new_password,
                    )
                    AuthService.logout(db, token, secret=settings.session_secret)
                st.session_state.pop("auth_token", None)
                st.success("Password changed. Sign in with your new password.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.stop()

with session_factory() as db:
    workspaces = WorkspaceService.list_for_user(db, user_id=user.id)

st.title("SME Financial Dashboard")
if not workspaces:
    st.warning("You do not currently belong to an active workspace.")
    st.stop()

workspace_labels = {workspace.id: f"{workspace.name} · {role.value}" for workspace, role in workspaces}
current_workspace = st.session_state.get("active_workspace_id")
workspace_ids = list(workspace_labels)
if current_workspace not in workspace_labels:
    current_workspace = workspace_ids[0]
    st.session_state["active_workspace_id"] = current_workspace
selected_workspace_id = st.selectbox(
    "Workspace",
    options=workspace_ids,
    format_func=lambda value: workspace_labels[value],
    index=workspace_ids.index(current_workspace),
)
st.session_state["active_workspace_id"] = selected_workspace_id

with session_factory() as db:
    workspace_context = resolve_workspace_context(
        db, user_id=user.id, workspace_id=selected_workspace_id
    )
    companies = WorkspaceService.list_companies(db, workspace_context)

col_a, col_b = st.columns([2, 1])
with col_a:
    st.subheader("Companies")
    if companies:
        labels = {company.id: f"{company.name} · {company.base_currency}" for company in companies}
        previous = st.session_state.get("active_company_id")
        if previous not in labels:
            previous = companies[0].id
        chosen = st.selectbox(
            "Active company",
            options=list(labels),
            format_func=lambda value: labels[value],
            index=list(labels).index(previous),
        )
        st.session_state["active_company_id"] = chosen
        st.info("Company context is resolved from your active workspace membership. The dashboard and import modules will appear here in subsequent phases.")
    else:
        st.info("No company has been created in this workspace yet.")
with col_b:
    st.subheader("Workspace actions")
    if workspace_context.role is MembershipRole.ADMIN:
        with st.form("create_company_form"):
            company_name = st.text_input("New company name")
            currency = st.text_input("Base currency (ISO 4217)", value="XAF", max_chars=3)
            timezone = st.text_input("IANA timezone", value="Africa/Douala")
            create_company = st.form_submit_button("Create company")
        if create_company:
            try:
                with session_factory() as db, db.begin():
                    WorkspaceService.create_company(
                        db,
                        workspace_context,
                        name=company_name,
                        base_currency=currency,
                        timezone=timezone,
                    )
                st.success("Company created.")
                st.rerun()
            except WorkspaceError as exc:
                st.error(str(exc))

        with st.form("create_workspace_form"):
            new_workspace_name = st.text_input("Create another workspace")
            create_workspace = st.form_submit_button("Create workspace")
        if create_workspace:
            try:
                with session_factory() as db, db.begin():
                    WorkspaceService.create_workspace(
                        db, actor_user_id=user.id, name=new_workspace_name
                    )
                st.success("Workspace created; you are its ADMIN.")
                st.rerun()
            except WorkspaceError as exc:
                st.error(str(exc))

    st.subheader("Members")
    if workspace_context.role is MembershipRole.ADMIN:
        with st.form("add_member_form"):
            member_email = st.text_input("New member email")
            member_name = st.text_input("New member full name")
            member_role = st.selectbox(
                "Role", options=[MembershipRole.ACCOUNTANT, MembershipRole.VIEWER, MembershipRole.ADMIN],
                format_func=lambda value: value.value,
            )
            add_member = st.form_submit_button("Add member")
        if add_member:
            try:
                with session_factory() as db, db.begin():
                    result = WorkspaceService.add_member(
                        db,
                        workspace_context,
                        email=member_email,
                        display_name=member_name,
                        role=member_role,
                    )
                st.success(f"{result.user.email} added.")
                if result.temporary_password:
                    st.warning("Copy this one-time temporary password now; it will not be shown again.")
                    st.code(result.temporary_password)
            except WorkspaceError as exc:
                st.error(str(exc))

        with session_factory() as db:
            members = WorkspaceService.list_members(db, workspace_context)
        for membership, member_user in members:
            status = "active" if membership.is_active else "inactive"
            st.caption(f"{member_user.email} · {membership.role.value} · {status}")
    else:
        st.caption("Only workspace ADMIN can manage members.")
