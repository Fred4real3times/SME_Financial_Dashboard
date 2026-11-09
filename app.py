"""Authenticated Streamlit entry point for the SME Financial Dashboard."""

from __future__ import annotations

import hashlib

import streamlit as st
from sqlalchemy import select
from sme_financial_dashboard.config import Settings
from sme_financial_dashboard.db.models import (
    BootstrapState,
    CategoryKind,
    MatchField,
    MatchOperator,
    MembershipRole,
    Transaction,
)
from sme_financial_dashboard.domain.import_parsing import (
    ImportFileError,
    list_xlsx_worksheets,
)
from sme_financial_dashboard.db.session import build_engine, build_session_factory
from sme_financial_dashboard.security.company_scope import (
    resolve_company_context,
    resolve_workspace_context,
)
from sme_financial_dashboard.services.auth_service import AuthService, AuthenticationError
from sme_financial_dashboard.services.workspace_service import WorkspaceError, WorkspaceService
from sme_financial_dashboard.services.import_service import (
    ImportMapping,
    ImportService,
    ImportServiceError,
)
from sme_financial_dashboard.services.categorization_service import (
    CategorizationError,
    CategorizationRuleService,
    CategorizationService,
    CategoryService,
)
from sme_financial_dashboard.services.review_service import (
    ReviewResolutionError,
    ReviewService,
)
from sme_financial_dashboard.db.models import ReviewDecision

st.set_page_config(page_title="SME Financial Dashboard", page_icon="📊", layout="wide")


@st.cache_resource
def get_runtime():
    settings = Settings.from_environment()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(settings, engine=engine)
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
        st.info("Company context is resolved from your active workspace membership. Imports, review, categories and transaction categorization are available below.")
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
            if membership.is_active:
                action_col, role_col = st.columns([1, 2])
                with role_col:
                    proposed_role = st.selectbox(
                        f"Role for {member_user.email}",
                        options=list(MembershipRole),
                        index=list(MembershipRole).index(membership.role),
                        key=f"role_{membership.id}",
                        format_func=lambda value: value.value,
                    )
                with action_col:
                    if st.button("Update role", key=f"update_role_{membership.id}"):
                        try:
                            with session_factory() as db, db.begin():
                                WorkspaceService.update_member_role(
                                    db, workspace_context,
                                    membership_id=membership.id,
                                    new_role=proposed_role,
                                )
                            st.success("Role updated.")
                            st.rerun()
                        except WorkspaceError as exc:
                            st.error(str(exc))
                    if st.button("Deactivate", key=f"deactivate_{membership.id}"):
                        try:
                            with session_factory() as db, db.begin():
                                WorkspaceService.deactivate_member(
                                    db, workspace_context, membership_id=membership.id
                                )
                            st.success("Member deactivated.")
                            st.rerun()
                        except WorkspaceError as exc:
                            st.error(str(exc))
    else:
        st.caption("Only workspace ADMIN can manage members.")


# Phase 3 — company-scoped statement import workflow.
if companies:
    st.divider()
    st.subheader("Import financial transactions")
    if workspace_context.role not in {MembershipRole.ADMIN, MembershipRole.ACCOUNTANT}:
        st.info("Your VIEWER role allows consultation and export, not financial imports.")
    else:
        uploaded_file = st.file_uploader(
            "Upload a bank or cash statement (.csv, .xlsx or digital .pdf)",
            type=["csv", "xlsx", "pdf"],
            key=f"statement_upload_{chosen}",
        )
        if uploaded_file is not None:
            file_bytes = uploaded_file.getvalue()
            file_digest = hashlib.sha256(file_bytes).hexdigest()
            suffix = uploaded_file.name.lower().rsplit(".", maxsplit=1)[-1]
            delimiter = ","
            encoding = "utf-8-sig"
            worksheet_name = None
            if suffix == "csv":
                delimiter_label = st.selectbox(
                    "CSV delimiter",
                    options=[",", ";", "Tab", "|"],
                    format_func=lambda value: "Tab" if value == "Tab" else value,
                    key=f"csv_delimiter_{chosen}",
                )
                delimiter = "\t" if delimiter_label == "Tab" else delimiter_label
                encoding = st.selectbox(
                    "CSV encoding",
                    options=["utf-8-sig", "utf-8", "cp1252", "latin-1"],
                    key=f"csv_encoding_{chosen}",
                )
            elif suffix == "xlsx":
                try:
                    worksheets = list_xlsx_worksheets(file_bytes)
                    worksheet_name = st.selectbox(
                        "Worksheet",
                        options=list(worksheets),
                        key=f"xlsx_sheet_{chosen}",
                    )
                except ImportFileError as exc:
                    st.error(f"{exc.code}: {exc.message}")
                    worksheets = ()
            date_format_label = st.selectbox(
                "Date format in source",
                options=["DD/MM/YYYY", "YYYY-MM-DD", "MM/DD/YYYY"],
                index=0,
                key=f"date_format_{chosen}",
            )
            date_format = {
                "DD/MM/YYYY": "%d/%m/%Y",
                "YYYY-MM-DD": "%Y-%m-%d",
                "MM/DD/YYYY": "%m/%d/%Y",
            }[date_format_label]
            decimal_separator = st.selectbox(
                "Decimal separator",
                options=[",", "."],
                index=0,
                key=f"decimal_separator_{chosen}",
            )
            default_thousands = "." if decimal_separator == "," else ","
            thousands_choice = st.selectbox(
                "Thousands separator",
                options=["None", default_thousands],
                index=1,
                key=f"thousands_separator_{chosen}",
            )
            thousands_separator = None if thousands_choice == "None" else thousands_choice

            parsed_document = None
            if suffix != "xlsx" or worksheet_name is not None:
                try:
                    parsed_document = ImportService.inspect_file(
                        file_bytes,
                        uploaded_file.name,
                        delimiter=delimiter,
                        encoding=encoding,
                        worksheet_name=worksheet_name,
                    )
                    st.caption(
                        f"Detected {parsed_document.file_type} · "
                        f"{len(parsed_document.rows):,} extracted rows · "
                        f"{len(parsed_document.headers)} columns"
                    )
                except (ImportFileError, ImportServiceError) as exc:
                    st.error(str(exc))

            if parsed_document is not None:
                header_options = list(range(len(parsed_document.headers)))
                no_column_label = "— Not mapped —"

                def _column_selector(label: str, field_key: str, required: bool = False):
                    options = header_options if required else [None, *header_options]
                    return st.selectbox(
                        label,
                        options=options,
                        format_func=lambda value: (
                            no_column_label
                            if value is None
                            else f"{value + 1}. {parsed_document.headers[value]}"
                        ),
                        key=f"mapping_{field_key}_{chosen}",
                    )

                with st.form(f"import_mapping_form_{chosen}"):
                    st.caption("Map each financial field to a source column. Required fields are marked *. ")
                    date_column = _column_selector("Transaction date *", "date", True)
                    amount_column = _column_selector("Amount *", "amount", True)
                    currency_column = _column_selector("Currency *", "currency", True)
                    direction_mode = st.radio(
                        "Direction interpretation",
                        options=["column", "signed_amount"],
                        format_func=lambda value: (
                            "Use a source direction column" if value == "column"
                            else "Infer direction from positive/negative amount"
                        ),
                        horizontal=True,
                    )
                    direction_column = (
                        _column_selector("Direction *", "direction", True)
                        if direction_mode == "column"
                        else None
                    )
                    value_date_column = _column_selector("Value date", "value_date")
                    description_column = _column_selector("Description", "description")
                    counterparty_column = _column_selector("Counterparty", "counterparty")
                    reference_column = _column_selector("Transaction reference", "reference")
                    account_column = _column_selector("Account name", "account_name")
                    build_preview = st.form_submit_button("Build import preview", type="primary")

                if build_preview:
                    columns = {
                        "transaction_date": date_column,
                        "amount": amount_column,
                        "currency": currency_column,
                    }
                    if direction_column is not None:
                        columns["direction"] = direction_column
                    optional_columns = {
                        "value_date": value_date_column,
                        "description": description_column,
                        "counterparty": counterparty_column,
                        "reference": reference_column,
                        "account_name": account_column,
                    }
                    columns.update({key: value for key, value in optional_columns.items() if value is not None})
                    mapping = ImportMapping(
                        columns=columns,
                        direction_mode=direction_mode,
                        date_format=date_format,
                        decimal_separator=decimal_separator,
                        thousands_separator=thousands_separator,
                        delimiter=delimiter,
                        encoding=encoding,
                        worksheet_name=worksheet_name,
                    )
                    try:
                        with session_factory() as db, db.begin():
                            company_context = resolve_company_context(
                                db, user_id=user.id, company_id=chosen
                            )
                            preview = ImportService.preview(
                                db,
                                file_bytes=file_bytes,
                                file_name=uploaded_file.name,
                                mapping=mapping,
                                context=company_context,
                            )
                        st.session_state["import_preview"] = preview
                        st.session_state["import_preview_company"] = str(chosen)
                        st.success("Preview created. No financial transactions have been committed yet.")
                    except ImportServiceError as exc:
                        st.error(str(exc))
                    except PermissionError:
                        st.error("You are not authorized to import into this company.")

                current_preview = st.session_state.get("import_preview")
                preview_company = st.session_state.get("import_preview_company")
                if current_preview is not None and (
                    preview_company != str(chosen)
                    or current_preview.file_sha256 != file_digest
                ):
                    st.session_state.pop("import_preview", None)
                    st.session_state.pop("import_preview_company", None)
                    current_preview = None

                if current_preview is not None:
                    st.markdown("**Import preview summary**")
                    metric_cols = st.columns(5)
                    for column, label, value in zip(
                        metric_cols,
                        ["Valid", "Invalid", "Duplicate", "Review", "Blank"],
                        [
                            current_preview.valid_count,
                            current_preview.invalid_count,
                            current_preview.duplicate_count,
                            current_preview.review_count,
                            current_preview.blank_count,
                        ],
                        strict=True,
                    ):
                        column.metric(label, value)
                    if current_preview.sample_rows:
                        st.dataframe(
                            [
                                {
                                    "Source row": row.source_row_number,
                                    "Status": row.status,
                                    "Values": row.values,
                                    "Issues": [issue["code"] for issue in row.issues],
                                    "PDF page": row.source_page_number,
                                    "PDF table": row.source_table_index,
                                }
                                for row in current_preview.sample_rows
                            ],
                            use_container_width=True,
                            hide_index=True,
                        )
                    has_held_rows = bool(
                        current_preview.invalid_count
                        or current_preview.duplicate_count
                        or current_preview.review_count
                    )
                    partial_confirmed = False
                    if has_held_rows:
                        partial_confirmed = st.checkbox(
                            "I confirm importing only valid rows; INVALID, DUPLICATE and REVIEW rows will remain excluded.",
                            key=f"partial_confirm_{current_preview.preview_id}",
                        )
                    if current_preview.valid_count == 0:
                        st.warning("There are no valid rows to commit. Resolve the preview issues or upload another file.")
                    elif st.button(
                        f"Confirm import of {current_preview.valid_count} valid rows",
                        type="primary",
                        disabled=has_held_rows and not partial_confirmed,
                        key=f"commit_import_{current_preview.preview_id}",
                    ):
                        try:
                            with session_factory() as db, db.begin():
                                company_context = resolve_company_context(
                                    db, user_id=user.id, company_id=chosen
                                )
                                summary = ImportService.commit(
                                    db,
                                    preview_id=current_preview.preview_id,
                                    context=company_context,
                                    confirm=True,
                                    confirm_partial=partial_confirmed,
                                )
                            st.success(
                                f"Import completed: {summary.imported_count} transactions committed. "
                                f"Batch status: {summary.status}."
                            )
                            st.session_state.pop("import_preview", None)
                            st.session_state.pop("import_preview_company", None)
                            st.rerun()
                        except ImportServiceError as exc:
                            st.error(str(exc))
                        except PermissionError:
                            st.error("You are no longer authorized to import into this company.")


# Phase 4 — categories, deterministic rules and human review queue.
if companies:
    st.divider()
    st.subheader("Categories and categorization rules")

    with session_factory() as db:
        try:
            company_context = resolve_company_context(
                db, user_id=user.id, company_id=chosen
            )
            categories = CategoryService.list_categories(db, company_context)
            all_categories = CategoryService.list_categories(
                db, company_context, include_inactive=True
            )
            rules = CategorizationRuleService.list_rules(
                db, company_context, include_inactive=True
            )
        except PermissionError:
            categories = []
            all_categories = []
            rules = []

    if all_categories:
        st.dataframe(
            [
                {
                    "Category": category.name,
                    "Direction": category.kind.value,
                    "Active": category.is_active,
                }
                for category in all_categories
            ],
            use_container_width=True,
            hide_index=True,
        )

    if workspace_context.role in {MembershipRole.ADMIN, MembershipRole.ACCOUNTANT}:
        with st.expander("Create a category", expanded=False):
            with st.form(f"create_category_{chosen}"):
                category_name = st.text_input("Category name", max_chars=80)
                category_kind = st.selectbox(
                    "Category direction",
                    options=list(CategoryKind),
                    format_func=lambda value: value.value,
                )
                create_category = st.form_submit_button("Create category")
            if create_category:
                try:
                    with session_factory() as db, db.begin():
                        company_context = resolve_company_context(
                            db, user_id=user.id, company_id=chosen
                        )
                        created = CategoryService.create_category(
                            db,
                            company_context,
                            name=category_name,
                            kind=category_kind,
                        )
                    st.success(f"Category '{created.name}' created.")
                    st.rerun()
                except CategorizationError as exc:
                    st.error(str(exc))
                except PermissionError:
                    st.error("You are not authorized to manage categories in this company.")

        if all_categories:
            with st.expander("Edit or deactivate a category", expanded=False):
                category_edit_labels = {
                    category.id: f"{category.name} · {category.kind.value} · "
                    f"{'active' if category.is_active else 'inactive'}"
                    for category in all_categories
                }
                selected_category_edit_id = st.selectbox(
                    "Category to edit",
                    options=list(category_edit_labels),
                    format_func=lambda value: category_edit_labels[value],
                    key=f"category_edit_select_{chosen}",
                )
                selected_category_edit = next(
                    category
                    for category in all_categories
                    if category.id == selected_category_edit_id
                )
                with st.form(f"edit_category_{chosen}"):
                    edited_category_name = st.text_input(
                        "Category name",
                        value=selected_category_edit.name,
                        max_chars=80,
                    )
                    edited_category_kind = st.selectbox(
                        "Category direction",
                        options=list(CategoryKind),
                        index=list(CategoryKind).index(selected_category_edit.kind),
                        format_func=lambda value: value.value,
                    )
                    edited_category_active = st.checkbox(
                        "Active",
                        value=selected_category_edit.is_active,
                    )
                    save_category = st.form_submit_button("Save category changes")
                if save_category:
                    try:
                        with session_factory() as db, db.begin():
                            company_context = resolve_company_context(
                                db, user_id=user.id, company_id=chosen
                            )
                            CategoryService.update_category(
                                db,
                                company_context,
                                category_id=selected_category_edit_id,
                                name=edited_category_name,
                                kind=edited_category_kind,
                                is_active=edited_category_active,
                            )
                        st.success("Category updated.")
                        st.rerun()
                    except CategorizationError as exc:
                        st.error(str(exc))
                    except PermissionError:
                        st.error("You are not authorized to update categories.")

        if categories:
            with st.expander("Create a categorization rule", expanded=False):
                category_labels = {
                    category.id: f"{category.name} · {category.kind.value}"
                    for category in categories
                }
                with st.form(f"create_rule_{chosen}"):
                    rule_category_id = st.selectbox(
                        "Destination category",
                        options=list(category_labels),
                        format_func=lambda value: category_labels[value],
                    )
                    rule_field = st.selectbox(
                        "Match field",
                        options=list(MatchField),
                        format_func=lambda value: {
                            MatchField.KEYWORD: "Keyword in description",
                            MatchField.COUNTERPARTY: "Counterparty",
                            MatchField.REFERENCE: "Transaction reference",
                        }[value],
                    )
                    rule_operator = st.selectbox(
                        "Match operator",
                        options=list(MatchOperator),
                        format_func=lambda value: {
                            MatchOperator.CONTAINS: "Contains",
                            MatchOperator.EQUALS: "Equals",
                            MatchOperator.STARTS_WITH: "Starts with",
                        }[value],
                    )
                    rule_value = st.text_input("Match value", max_chars=200)
                    rule_priority = st.number_input(
                        "Priority (higher number wins; ties require manual review)",
                        min_value=1,
                        max_value=10_000,
                        value=100,
                        step=1,
                    )
                    create_rule = st.form_submit_button("Create rule")
                if create_rule:
                    try:
                        with session_factory() as db, db.begin():
                            company_context = resolve_company_context(
                                db, user_id=user.id, company_id=chosen
                            )
                            created_rule = CategorizationRuleService.create_rule(
                                db,
                                company_context,
                                category_id=rule_category_id,
                                match_field=rule_field,
                                operator=rule_operator,
                                match_value=rule_value,
                                priority=int(rule_priority),
                            )
                        st.success(f"Rule created with priority {created_rule.priority}.")
                        st.rerun()
                    except CategorizationError as exc:
                        st.error(str(exc))
                    except PermissionError:
                        st.error("You are not authorized to manage rules in this company.")

        if rules and categories:
            with st.expander("Edit a categorization rule", expanded=False):
                editable_rule_labels = {
                    rule.id: (
                        f"{rule.priority} · {rule.match_field.value} "
                        f"{rule.operator.value} {rule.match_value}"
                    )
                    for rule in rules
                }
                selected_rule_edit_id = st.selectbox(
                    "Rule to edit",
                    options=list(editable_rule_labels),
                    format_func=lambda value: editable_rule_labels[value],
                    key=f"rule_edit_select_{chosen}",
                )
                selected_rule_edit = next(
                    rule for rule in rules if rule.id == selected_rule_edit_id
                )
                category_label_options = {
                    category.id: f"{category.name} · {category.kind.value}"
                    for category in categories
                }
                selected_rule_category_default = (
                    selected_rule_edit.category_id
                    if selected_rule_edit.category_id in category_label_options
                    else categories[0].id
                )
                with st.form(f"edit_rule_{chosen}"):
                    edited_rule_category = st.selectbox(
                        "Destination category",
                        options=list(category_label_options),
                        index=list(category_label_options).index(selected_rule_category_default),
                        format_func=lambda value: category_label_options[value],
                    )
                    edited_rule_field = st.selectbox(
                        "Match field",
                        options=list(MatchField),
                        index=list(MatchField).index(selected_rule_edit.match_field),
                        format_func=lambda value: {
                            MatchField.KEYWORD: "Keyword in description",
                            MatchField.COUNTERPARTY: "Counterparty",
                            MatchField.REFERENCE: "Transaction reference",
                        }[value],
                    )
                    edited_rule_operator = st.selectbox(
                        "Match operator",
                        options=list(MatchOperator),
                        index=list(MatchOperator).index(selected_rule_edit.operator),
                        format_func=lambda value: {
                            MatchOperator.CONTAINS: "Contains",
                            MatchOperator.EQUALS: "Equals",
                            MatchOperator.STARTS_WITH: "Starts with",
                        }[value],
                    )
                    edited_rule_value = st.text_input(
                        "Match value", value=selected_rule_edit.match_value, max_chars=200
                    )
                    edited_rule_priority = st.number_input(
                        "Priority (higher number wins)",
                        min_value=1,
                        max_value=10_000,
                        value=selected_rule_edit.priority,
                        step=1,
                    )
                    edited_rule_active = st.checkbox(
                        "Active", value=selected_rule_edit.is_active
                    )
                    save_rule = st.form_submit_button("Save rule changes")
                if save_rule:
                    try:
                        with session_factory() as db, db.begin():
                            company_context = resolve_company_context(
                                db, user_id=user.id, company_id=chosen
                            )
                            CategorizationRuleService.update_rule(
                                db,
                                company_context,
                                rule_id=selected_rule_edit_id,
                                category_id=edited_rule_category,
                                match_field=edited_rule_field,
                                operator=edited_rule_operator,
                                match_value=edited_rule_value,
                                priority=int(edited_rule_priority),
                                is_active=edited_rule_active,
                            )
                        st.success("Categorization rule updated.")
                        st.rerun()
                    except CategorizationError as exc:
                        st.error(str(exc))
                    except PermissionError:
                        st.error("You are not authorized to update rules.")

        if rules:
            st.markdown("**Active and inactive rules**")
            st.dataframe(
                [
                    {
                        "Priority": rule.priority,
                        "Match field": rule.match_field.value,
                        "Operator": rule.operator.value,
                        "Match value": rule.match_value,
                        "Category": next(
                            (item.name for item in all_categories if item.id == rule.category_id),
                            "(inactive or unavailable)",
                        ),
                        "Active": rule.is_active,
                    }
                    for rule in rules
                ],
                use_container_width=True,
                hide_index=True,
            )
            active_rules = [rule for rule in rules if rule.is_active]
            if active_rules:
                rule_labels = {
                    rule.id: f"{rule.priority} · {rule.match_field.value} {rule.operator.value} {rule.match_value}"
                    for rule in active_rules
                }
                rule_to_disable = st.selectbox(
                    "Deactivate a rule",
                    options=list(rule_labels),
                    format_func=lambda value: rule_labels[value],
                    key=f"deactivate_rule_select_{chosen}",
                )
                if st.button("Deactivate selected rule", key=f"deactivate_rule_{chosen}"):
                    try:
                        with session_factory() as db, db.begin():
                            company_context = resolve_company_context(
                                db, user_id=user.id, company_id=chosen
                            )
                            CategorizationRuleService.update_rule(
                                db,
                                company_context,
                                rule_id=rule_to_disable,
                                is_active=False,
                            )
                        st.success("Rule deactivated.")
                        st.rerun()
                    except CategorizationError as exc:
                        st.error(str(exc))
                    except PermissionError:
                        st.error("You are not authorized to manage rules in this company.")

    if all_categories and workspace_context.role in {MembershipRole.ADMIN, MembershipRole.ACCOUNTANT}:
        with session_factory() as db:
            transactions_for_categorization = list(
                db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.company_id == chosen,
                        Transaction.deleted_at.is_(None),
                    )
                    .order_by(Transaction.transaction_date.desc(), Transaction.id)
                    .limit(100)
                ).all()
            )
        if transactions_for_categorization:
            st.markdown("**Transactions for manual categorization or rule application**")
            category_names = {category.id: category.name for category in all_categories}
            transaction_labels = {
                transaction.id: (
                    f"{transaction.transaction_date.isoformat()} · "
                    f"{transaction.amount} {transaction.currency} · "
                    f"{transaction.description or transaction.counterparty or 'Transaction'} · "
                    f"{category_names.get(transaction.category_id, 'Uncategorized')}"
                )
                for transaction in transactions_for_categorization
            }
            selected_transaction_id = st.selectbox(
                "Select transaction",
                options=list(transaction_labels),
                format_func=lambda value: transaction_labels[value],
                key=f"categorization_transaction_{chosen}",
            )
            selected_category_options = [None, *[category.id for category in categories]]
            selected_category_labels = {
                category.id: f"{category.name} · {category.kind.value}"
                for category in categories
            }
            manual_category_id = st.selectbox(
                "Manual primary category (or clear)",
                options=selected_category_options,
                format_func=lambda value: (
                    "— No category —" if value is None else selected_category_labels[value]
                ),
                key=f"manual_category_{chosen}",
            )
            action_col_a, action_col_b = st.columns(2)
            with action_col_a:
                if st.button(
                    "Apply matching rules",
                    key=f"apply_rules_{selected_transaction_id}",
                ):
                    try:
                        with session_factory() as db, db.begin():
                            company_context = resolve_company_context(
                                db, user_id=user.id, company_id=chosen
                            )
                            result = CategorizationService.apply_rules(
                                db, company_context, transaction_id=selected_transaction_id
                            )
                        st.success(f"Categorization result: {result.outcome.value}.")
                        st.rerun()
                    except CategorizationError as exc:
                        st.error(str(exc))
                    except PermissionError:
                        st.error("You are not authorized to run categorization rules.")
            with action_col_b:
                if st.button(
                    "Save manual category",
                    key=f"save_manual_category_{selected_transaction_id}",
                ):
                    try:
                        with session_factory() as db, db.begin():
                            company_context = resolve_company_context(
                                db, user_id=user.id, company_id=chosen
                            )
                            CategorizationService.assign_manual_category(
                                db,
                                company_context,
                                transaction_id=selected_transaction_id,
                                category_id=manual_category_id,
                            )
                        st.success("Manual category saved.")
                        st.rerun()
                    except CategorizationError as exc:
                        st.error(str(exc))
                    except PermissionError:
                        st.error("You are not authorized to correct transactions.")

    if workspace_context.role in {MembershipRole.ADMIN, MembershipRole.ACCOUNTANT}:
        st.divider()
        st.subheader("Manual import review queue")
        try:
            with session_factory() as db:
                company_context = resolve_company_context(
                    db, user_id=user.id, company_id=chosen
                )
                pending_review_count = ReviewService.count_pending(db, company_context)
                review_page_count = max(1, (pending_review_count + 99) // 100)
                review_page = st.number_input(
                    "Review queue page",
                    min_value=1,
                    max_value=review_page_count,
                    value=1,
                    step=1,
                    key=f"review_page_{chosen}",
                )
                review_items = ReviewService.list_pending(
                    db,
                    company_context,
                    limit=100,
                    offset=(int(review_page) - 1) * 100,
                )
            st.caption(
                f"{pending_review_count} pending rows · page {int(review_page)} of {review_page_count}."
            )
            if review_items:
                review_labels = {
                    item.row_id: (
                        f"{item.file_name} · source row {item.source_row_number}"
                        + (
                            f" · PDF page {item.source_page_number}"
                            if item.source_page_number
                            else ""
                        )
                    )
                    for item in review_items
                }
                selected_review_id = st.selectbox(
                    "Select a row to review",
                    options=list(review_labels),
                    format_func=lambda value: review_labels[value],
                    key=f"review_row_{chosen}",
                )
                selected_review = next(
                    item for item in review_items if item.row_id == selected_review_id
                )
                st.write("**Extracted source values**")
                st.json(selected_review.raw_values)
                if selected_review.issues:
                    st.write("**Review reasons**")
                    st.dataframe(
                        list(selected_review.issues),
                        use_container_width=True,
                        hide_index=True,
                    )
                decision = st.selectbox(
                    "Decision",
                    options=[
                        ReviewDecision.CONFIRMED_DUPLICATE,
                        ReviewDecision.REJECTED,
                        ReviewDecision.CORRECTED_AND_ACCEPTED,
                    ],
                    format_func=lambda value: {
                        ReviewDecision.CONFIRMED_DUPLICATE: "Confirm duplicate",
                        ReviewDecision.REJECTED: "Reject row",
                        ReviewDecision.CORRECTED_AND_ACCEPTED: "Correct and accept",
                    }[value],
                    key=f"review_decision_{selected_review.row_id}",
                )
                with st.form(f"resolve_review_{selected_review.row_id}"):
                    review_note = st.text_area("Review note (required)", max_chars=500)
                    correction = {}
                    if decision is ReviewDecision.CORRECTED_AND_ACCEPTED:
                        current = selected_review.normalized_values or {}
                        st.caption(
                            "A unique manual reference is required to accept an ambiguous row safely."
                        )
                        corrected_date = st.text_input(
                            "Transaction date (YYYY-MM-DD)",
                            value=str(current.get("transaction_date") or ""),
                        )
                        corrected_amount = st.text_input(
                            "Amount (positive Decimal)", value=str(current.get("amount") or "")
                        )
                        corrected_currency = st.text_input(
                            "Currency code", value=str(current.get("currency") or "XAF"), max_chars=3
                        )
                        corrected_direction = st.selectbox(
                            "Direction",
                            options=["INFLOW", "OUTFLOW"],
                            index=0 if current.get("direction") != "OUTFLOW" else 1,
                        )
                        corrected_reference = st.text_input(
                            "Unique manual reference",
                            value=str(current.get("reference") or ""),
                            max_chars=200,
                        )
                        corrected_counterparty = st.text_input(
                            "Counterparty", value=str(current.get("counterparty") or ""), max_chars=200
                        )
                        corrected_description = st.text_input(
                            "Description", value=str(current.get("description") or ""), max_chars=500
                        )
                        corrected_account = st.text_input(
                            "Account name", value=str(current.get("account_name") or ""), max_chars=120
                        )
                        correction = {
                            "transaction_date": corrected_date,
                            "amount": corrected_amount,
                            "currency": corrected_currency,
                            "direction": corrected_direction,
                            "reference": corrected_reference,
                            "counterparty": corrected_counterparty,
                            "description": corrected_description,
                            "account_name": corrected_account,
                        }
                    resolve_review = st.form_submit_button("Save review decision", type="primary")
                if resolve_review:
                    try:
                        with session_factory() as db, db.begin():
                            company_context = resolve_company_context(
                                db, user_id=user.id, company_id=chosen
                            )
                            result = ReviewService.resolve(
                                db,
                                company_context,
                                row_id=selected_review_id,
                                decision=decision,
                                note=review_note,
                                corrected_values=(
                                    correction
                                    if decision is ReviewDecision.CORRECTED_AND_ACCEPTED
                                    else None
                                ),
                            )
                        st.success(
                            f"Review saved: {result.decision} · "
                            f"batch {result.batch_status} · "
                            f"{result.remaining_review_count} rows remain in REVIEW."
                        )
                        st.rerun()
                    except ReviewResolutionError as exc:
                        st.error(str(exc))
                    except PermissionError:
                        st.error("You are no longer authorized to review this company data.")
        except PermissionError:
            st.error("You are not authorized to access the import review queue.")
