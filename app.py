"""Authenticated Streamlit entry point for the SME Financial Dashboard."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select
from sme_financial_dashboard.config import Settings
from sme_financial_dashboard.db.models import (
    BootstrapState,
    CategoryKind,
    Direction,
    MatchField,
    MatchOperator,
    MembershipRole,
    Transaction,
)
from sme_financial_dashboard.domain.import_parsing import ImportFileError
from sme_financial_dashboard.domain.parser_runtime import list_xlsx_worksheets_bounded
from sme_financial_dashboard.db.session import build_engine, build_session_factory
from sme_financial_dashboard.repositories.transactions import TransactionRepository
from sme_financial_dashboard.ui import apply_yiriwa_theme, render_brand_header
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
from sme_financial_dashboard.services.dashboard_service import (
    AccountSnapshotService,
    BalanceStatus,
    DashboardError,
    DashboardFilters,
    DashboardService,
)
from sme_financial_dashboard.services.reporting_service import (
    AuditService,
    ExportService,
    ImportHistoryService,
    ReportingError,
)

st.set_page_config(page_title="Yiriwa Business", page_icon="📈", layout="wide")
apply_yiriwa_theme()


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
    st.title("Yiriwa Business — configuration initiale")
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
    st.title("Yiriwa Business")
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

if not workspaces:
    st.warning("You do not currently belong to an active workspace.")
    st.stop()

workspace_labels = {
    workspace.id: f"{workspace.name} · {role.value}"
    for workspace, role in workspaces
}
current_workspace = st.session_state.get("active_workspace_id")
workspace_ids = list(workspace_labels)
if current_workspace not in workspace_labels:
    current_workspace = workspace_ids[0]
    st.session_state["active_workspace_id"] = current_workspace

with st.sidebar:
    st.markdown("## Yiriwa Business")
    st.caption("Votre espace de pilotage financier")
    selected_workspace_id = st.selectbox(
        "Workspace",
        options=workspace_ids,
        format_func=lambda value: workspace_labels[value],
        index=workspace_ids.index(current_workspace),
        key="active_workspace_selector",
    )
    st.session_state["active_workspace_id"] = selected_workspace_id

with session_factory() as db:
    workspace_context = resolve_workspace_context(
        db, user_id=user.id, workspace_id=selected_workspace_id
    )
    companies = WorkspaceService.list_companies(db, workspace_context)

with st.sidebar:
    if companies:
        company_labels = {
            company.id: f"{company.name} · {company.base_currency}"
            for company in companies
        }
        previous_company = st.session_state.get("active_company_id")
        if previous_company not in company_labels:
            previous_company = companies[0].id
        chosen = st.selectbox(
            "Entreprise active",
            options=list(company_labels),
            format_func=lambda value: company_labels[value],
            index=list(company_labels).index(previous_company),
            key="active_company_selector",
        )
        st.session_state["active_company_id"] = chosen
    else:
        chosen = None
        st.info("Aucune entreprise n'est encore configurée.")
    st.divider()
    st.caption(f"Connecté : {user.display_name}")
    st.caption(f"Rôle : {workspace_context.role.value}")

active_company_name = next(
    (company.name for company in companies if company.id == chosen),
    None,
)
active_workspace_name = next(
    workspace.name for workspace, _role in workspaces
    if workspace.id == selected_workspace_id
)
render_brand_header(
    user_name=user.display_name,
    workspace_name=active_workspace_name,
    role=workspace_context.role.value,
    company_name=active_company_name,
)
st.caption(
    "Un espace sécurisé pour suivre les flux de trésorerie, contrôler les imports "
    "et analyser les opérations de votre entreprise."
)

tab_home, tab_transactions, tab_import, tab_categories, tab_exports, tab_profile = st.tabs(
    ["Accueil", "Transactions", "Importer", "Catégories & revue", "Exports", "Profil"]
)

with tab_home:
    # Phase 5 — financial dashboard and verified opening-balance context.
    dashboard_filters: DashboardFilters | None = None
    if companies:
        st.divider()
        st.subheader("Financial dashboard")
        active_company = next(company for company in companies if company.id == chosen)
        try:
            with session_factory() as db:
                company_context = resolve_company_context(
                    db, user_id=user.id, company_id=chosen
                )
                dashboard_options = DashboardService.filter_options(db, company_context)
                recent_snapshots = AccountSnapshotService.list_recent(db, company_context)
        except (DashboardError, PermissionError) as exc:
            st.error(f"Dashboard options could not be loaded: {exc}")
        else:
            try:
                today = datetime.now(ZoneInfo(active_company.timezone)).date()
            except Exception:
                today = date.today()
            default_start = today - timedelta(days=29)
            date_col_a, date_col_b = st.columns(2)
            with date_col_a:
                dashboard_start = st.date_input(
                    "Start date",
                    value=default_start,
                    key=f"dashboard_start_{chosen}",
                )
            with date_col_b:
                dashboard_end = st.date_input(
                    "End date",
                    value=today,
                    key=f"dashboard_end_{chosen}",
                )

            currency_choices = [None, *dashboard_options.currencies]
            account_choices = [None, *dashboard_options.account_names]
            category_ids = [category_id for category_id, _name in dashboard_options.categories]
            category_names = dict(dashboard_options.categories)
            category_choices = [None, *category_ids]
            direction_choices = [None, Direction.INFLOW, Direction.OUTFLOW]
            filter_col_a, filter_col_b, filter_col_c, filter_col_d = st.columns(4)
            with filter_col_a:
                dashboard_currency = st.selectbox(
                    "Currency",
                    options=currency_choices,
                    format_func=lambda value: "All currencies (separate totals)" if value is None else value,
                    key=f"dashboard_currency_{chosen}",
                )
            with filter_col_b:
                dashboard_account = st.selectbox(
                    "Account",
                    options=account_choices,
                    format_func=lambda value: "All accounts" if value is None else value,
                    key=f"dashboard_account_{chosen}",
                )
            with filter_col_c:
                dashboard_category = st.selectbox(
                    "Category",
                    options=category_choices,
                    format_func=lambda value: "All categories" if value is None else category_names[value],
                    key=f"dashboard_category_{chosen}",
                )
            with filter_col_d:
                dashboard_direction = st.selectbox(
                    "Direction",
                    options=direction_choices,
                    format_func=lambda value: "Both directions" if value is None else value.value,
                    key=f"dashboard_direction_{chosen}",
                )

            report = None
            try:
                with session_factory() as db:
                    company_context = resolve_company_context(
                        db, user_id=user.id, company_id=chosen
                    )
                    dashboard_filters = DashboardFilters(
                        start_date=dashboard_start,
                        end_date=dashboard_end,
                        currency=dashboard_currency,
                        account_name=dashboard_account,
                        category_id=dashboard_category,
                        direction=dashboard_direction,
                    )
                    report = DashboardService.report(
                        db,
                        company_context,
                        dashboard_filters,
                    )
            except (DashboardError, PermissionError) as exc:
                st.error(f"Dashboard could not be calculated: {exc}")

            if report is not None:
                if report.current.totals:
                    for currency_totals in report.current.totals:
                        st.markdown(f"**{currency_totals.currency}**")
                        metric_cols = st.columns(4)
                        metric_cols[0].metric("Inflows", f"{currency_totals.inflows:,.6f}")
                        metric_cols[1].metric("Outflows", f"{currency_totals.outflows:,.6f}")
                        metric_cols[2].metric("Net cash flow", f"{currency_totals.net:,.6f}")
                        metric_cols[3].metric("Transactions", currency_totals.transaction_count)
                else:
                    st.info("No committed transactions match the selected period and filters.")

                st.markdown("**Period comparison**")
                previous_totals = {item.currency: item for item in report.previous.totals}
                current_totals = {item.currency: item for item in report.current.totals}
                comparison_currencies = sorted(set(previous_totals) | set(current_totals))
                if comparison_currencies:
                    comparison_rows = []
                    for currency in comparison_currencies:
                        current = current_totals.get(currency)
                        previous = previous_totals.get(currency)
                        current_net = current.net if current is not None else Decimal("0")
                        previous_net = previous.net if previous is not None else Decimal("0")
                        comparison_rows.append(
                            {
                                "Currency": currency,
                                "Current net": f"{current_net:,.6f}",
                                "Previous net": f"{previous_net:,.6f}",
                                "Change": f"{current_net - previous_net:,.6f}",
                                "Current transactions": current.transaction_count if current else 0,
                                "Previous transactions": previous.transaction_count if previous else 0,
                            }
                        )
                    st.caption(
                        f"Current: {report.current.start_date.isoformat()} to {report.current.end_date.isoformat()} · "
                        f"Previous: {report.previous_start_date.isoformat()} to {report.previous_end_date.isoformat()}"
                    )
                    st.dataframe(comparison_rows, use_container_width=True, hide_index=True)
                else:
                    st.caption("No transactions are available in either comparison period.")

                st.markdown("**Monthly cash flow**")
                chart_currencies = sorted({item.currency for item in report.current.monthly})
                if chart_currencies:
                    for currency in chart_currencies:
                        currency_months = [
                            item for item in report.current.monthly if item.currency == currency
                        ]
                        figure = go.Figure()
                        # Float conversion is confined to chart rendering; all KPIs remain Decimal.
                        figure.add_trace(
                            go.Bar(
                                name="Inflows",
                                x=[item.month for item in currency_months],
                                y=[float(item.inflows) for item in currency_months],
                            )
                        )
                        figure.add_trace(
                            go.Bar(
                                name="Outflows",
                                x=[item.month for item in currency_months],
                                y=[float(item.outflows) for item in currency_months],
                            )
                        )
                        figure.update_layout(
                            title=f"Monthly movements — {currency}",
                            barmode="group",
                            xaxis_title="Month",
                            yaxis_title=f"Amount ({currency})",
                            legend_title="Direction",
                        )
                        st.plotly_chart(
                            figure,
                            use_container_width=True,
                            key=f"monthly_cashflow_{chosen}_{currency}",
                        )
                        monthly_rows = [
                            {
                                "Month": item.month,
                                "Inflows": f"{item.inflows:,.6f}",
                                "Outflows": f"{item.outflows:,.6f}",
                                "Net": f"{item.net:,.6f}",
                                "Transactions": item.transaction_count,
                            }
                            for item in currency_months
                        ]
                        st.dataframe(monthly_rows, use_container_width=True, hide_index=True)

                st.markdown("**Top spending categories and counterparties**")
                spend_currencies = sorted(
                    {item.currency for item in report.current.top_categories}
                    | {item.currency for item in report.current.top_counterparties}
                )
                for currency in spend_currencies:
                    category_rows = [
                        {
                            "Category": item.label,
                            "Outflows": f"{item.amount:,.6f}",
                            "Transactions": item.transaction_count,
                        }
                        for item in report.current.top_categories
                        if item.currency == currency
                    ]
                    counterparty_rows = [
                        {
                            "Counterparty": item.label,
                            "Outflows": f"{item.amount:,.6f}",
                            "Transactions": item.transaction_count,
                        }
                        for item in report.current.top_counterparties
                        if item.currency == currency
                    ]
                    spend_col_a, spend_col_b = st.columns(2)
                    with spend_col_a:
                        st.caption(f"Categories — {currency}")
                        st.dataframe(category_rows, use_container_width=True, hide_index=True)
                    with spend_col_b:
                        st.caption(f"Counterparties — {currency}")
                        st.dataframe(counterparty_rows, use_container_width=True, hide_index=True)

                st.markdown("**Closing balance availability**")
                balance = report.current.balance
                if balance.status is BalanceStatus.AVAILABLE:
                    st.metric(
                        f"Estimated closing balance — {balance.account_name}",
                        f"{balance.closing_balance:,.6f} {balance.currency}",
                    )
                    st.caption(
                        f"Opening snapshot: {balance.opening_balance:,.6f} {balance.currency} "
                        f"as of {balance.snapshot_date.isoformat()} · {balance.source_description}. "
                        "Transactions dated on the snapshot date are included."
                    )
                else:
                    balance_messages = {
                        BalanceStatus.ACCOUNT_REQUIRED: "Select one account to calculate its closing balance.",
                        BalanceStatus.CURRENCY_REQUIRED: "Select one currency; balances are never combined across currencies.",
                        BalanceStatus.INCOMPATIBLE_FILTERS: "Remove the category and direction filters; a closing balance requires all movements for the selected account and currency.",
                        BalanceStatus.NO_VERIFIED_SNAPSHOT: "No verified opening-balance snapshot exists for this account and currency at or before the selected end date.",
                        BalanceStatus.CONFLICTING_SNAPSHOTS: "Multiple verified opening snapshots share the latest date. The closing balance is withheld until the conflict is resolved.",
                    }
                    st.info(balance_messages[balance.status])

            if workspace_context.role in {MembershipRole.ADMIN, MembershipRole.ACCOUNTANT}:
                with st.expander("Register a verified or provisional opening balance", expanded=False):
                    snapshot_currency_choices = sorted(
                        set(dashboard_options.currencies) | {active_company.base_currency}
                    )
                    default_currency_index = snapshot_currency_choices.index(active_company.base_currency)
                    with st.form(f"opening_snapshot_form_{chosen}"):
                        snapshot_account = st.text_input("Account name", max_chars=120)
                        snapshot_currency = st.selectbox(
                            "Snapshot currency",
                            options=snapshot_currency_choices,
                            index=default_currency_index,
                        )
                        snapshot_date = st.date_input(
                            "Opening balance as of",
                            value=today,
                            key=f"snapshot_date_{chosen}",
                        )
                        snapshot_amount = st.text_input("Opening balance (Decimal; up to 6 places)")
                        snapshot_source = st.text_input(
                            "Statement or evidence reference", max_chars=250
                        )
                        snapshot_verified = st.checkbox(
                            "I have reconciled this opening balance to an authoritative statement.",
                            value=False,
                        )
                        save_snapshot = st.form_submit_button("Save opening balance")
                    if save_snapshot:
                        try:
                            with session_factory() as db, db.begin():
                                company_context = resolve_company_context(
                                    db, user_id=user.id, company_id=chosen
                                )
                                created_snapshot = AccountSnapshotService.create(
                                    db,
                                    company_context,
                                    account_name=snapshot_account,
                                    as_of_date=snapshot_date,
                                    currency=snapshot_currency,
                                    opening_balance=snapshot_amount,
                                    is_verified=snapshot_verified,
                                    source_description=snapshot_source,
                                )
                            if created_snapshot.is_verified:
                                st.success("Verified opening-balance snapshot saved and audited.")
                            else:
                                st.warning("Provisional snapshot saved; it will not be used in closing balances.")
                            st.rerun()
                        except (DashboardError, PermissionError) as exc:
                            st.error(str(exc))

            if recent_snapshots:
                st.caption("Recent opening-balance snapshots")
                st.dataframe(
                    [
                        {
                            "Account": item.account_name,
                            "As of": item.as_of_date.isoformat(),
                            "Currency": item.currency,
                            "Opening balance": f"{item.opening_balance:,.6f}",
                            "Verified": item.is_verified,
                            "Evidence": item.source_description,
                        }
                        for item in recent_snapshots
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

with tab_transactions:
    st.subheader("Transactions")
    st.caption(
        "Consultez les opérations validées de l'entreprise active. "
        "Les montants restent séparés par devise : aucune conversion automatique."
    )
    if not companies or chosen is None:
        st.info("Créez ou sélectionnez une entreprise pour consulter ses transactions.")
    else:
        active_company = next(company for company in companies if company.id == chosen)
        try:
            with session_factory() as db:
                company_context = resolve_company_context(
                    db, user_id=user.id, company_id=chosen
                )
                all_transactions = TransactionRepository.list_active(db, company_context)
                category_items = CategoryService.list_categories(
                    db, company_context, include_inactive=True
                )
            category_names = {item.id: item.name for item in category_items}
            transactions = [
                item for item in all_transactions if item.is_validated
            ]
        except (PermissionError, CategorizationError) as exc:
            st.error(f"Transactions could not be loaded: {exc}")
            transactions = []
            category_names = {}

        try:
            tx_today = datetime.now(ZoneInfo(active_company.timezone)).date()
        except Exception:
            tx_today = date.today()
        tx_filter_a, tx_filter_b, tx_filter_c = st.columns(3)
        with tx_filter_a:
            tx_start = st.date_input(
                "Du",
                value=tx_today - timedelta(days=29),
                key=f"transactions_start_{chosen}",
            )
        with tx_filter_b:
            tx_end = st.date_input(
                "Au",
                value=tx_today,
                key=f"transactions_end_{chosen}",
            )
        currencies = sorted({item.currency for item in transactions})
        with tx_filter_c:
            tx_currency = st.selectbox(
                "Devise",
                options=["Toutes", *currencies],
                key=f"transactions_currency_{chosen}",
            )

        filter_a, filter_b = st.columns([1.5, 1])
        with filter_a:
            tx_search = st.text_input(
                "Rechercher une opération",
                placeholder="Description, bénéficiaire ou référence…",
                key=f"transactions_search_{chosen}",
            )
        with filter_b:
            tx_direction = st.selectbox(
                "Sens de l'opération",
                options=["Tous", Direction.INFLOW, Direction.OUTFLOW],
                format_func=lambda value: (
                    "Tous les mouvements"
                    if value == "Tous"
                    else "Entrées" if value is Direction.INFLOW else "Sorties"
                ),
                key=f"transactions_direction_{chosen}",
            )

        filtered_transactions = [
            item for item in transactions
            if tx_start <= item.transaction_date <= tx_end
            and (tx_currency == "Toutes" or item.currency == tx_currency)
            and (tx_direction == "Tous" or item.direction is tx_direction)
            and (
                not tx_search
                or tx_search.casefold() in (item.description or "").casefold()
                or tx_search.casefold() in (item.counterparty or "").casefold()
                or tx_search.casefold() in (item.reference or "").casefold()
            )
        ]
        filtered_transactions.sort(
            key=lambda item: (item.transaction_date, str(item.id)), reverse=True
        )
        st.metric("Opérations affichées", len(filtered_transactions))
        if filtered_transactions:
            st.dataframe(
                [
                    {
                        "Date": item.transaction_date.isoformat(),
                        "Date de valeur": (
                            item.value_date.isoformat() if item.value_date else "—"
                        ),
                        "Description": item.description or "—",
                        "Contrepartie": item.counterparty or "—",
                        "Sens": "Entrée" if item.direction is Direction.INFLOW else "Sortie",
                        "Montant": f"{item.amount:,.2f} {item.currency}",
                        "Compte": item.account_name or "—",
                        "Catégorie": category_names.get(item.category_id, "Non catégorisé"),
                        "Référence": item.reference or "—",
                    }
                    for item in filtered_transactions
                ],
                use_container_width=True,
                hide_index=True,
            )
            transaction_labels = {
                item.id: (
                    f"{item.transaction_date.isoformat()} · "
                    f"{item.amount:,.2f} {item.currency} · "
                    f"{item.counterparty or item.description or 'Opération'}"
                )
                for item in filtered_transactions
            }
            selected_transaction_id = st.selectbox(
                "Ouvrir le détail d'une opération",
                options=list(transaction_labels),
                format_func=lambda value: transaction_labels[value],
                key=f"transaction_detail_{chosen}",
            )
            selected_transaction = next(
                item for item in filtered_transactions
                if item.id == selected_transaction_id
            )
            st.markdown("---")
            st.subheader("Détail opération")
            detail_amount, detail_direction, detail_category = st.columns(3)
            detail_amount.metric(
                "Montant",
                f"{selected_transaction.amount:,.2f} {selected_transaction.currency}",
            )
            detail_direction.metric(
                "Mouvement",
                "Entrée" if selected_transaction.direction is Direction.INFLOW else "Sortie",
            )
            detail_category.metric(
                "Catégorie",
                category_names.get(selected_transaction.category_id, "Non catégorisé"),
            )
            detail_left, detail_right = st.columns(2)
            with detail_left:
                st.markdown(f"**Date d'opération**  \n{selected_transaction.transaction_date.isoformat()}")
                st.markdown(
                    f"**Date de valeur**  \n"
                    f"{selected_transaction.value_date.isoformat() if selected_transaction.value_date else '—'}"
                )
                st.markdown(f"**Compte**  \n{selected_transaction.account_name or '—'}")
            with detail_right:
                st.markdown(f"**Contrepartie**  \n{selected_transaction.counterparty or '—'}")
                st.markdown(f"**Description**  \n{selected_transaction.description or '—'}")
                st.markdown(f"**Référence**  \n{selected_transaction.reference or '—'}")
        else:
            st.info("Aucune transaction validée ne correspond aux filtres sélectionnés.")


with tab_import:
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
                        worksheets = list_xlsx_worksheets_bounded(file_bytes)
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

with tab_categories:
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

with tab_exports:
    # Phase 6 — filtered exports, import history and audit history.
    if companies and dashboard_filters is not None:
        st.divider()
        st.subheader("Exports and history")
        export_signature = hashlib.sha256(
            (
                f"{chosen}|{dashboard_filters.start_date.isoformat()}|"
                f"{dashboard_filters.end_date.isoformat()}|{dashboard_filters.currency}|"
                f"{dashboard_filters.account_name}|{dashboard_filters.category_id}|"
                f"{dashboard_filters.direction}"
            ).encode()
        ).hexdigest()[:12]
        csv_state_key = f"csv_export_{chosen}_{export_signature}"
        pdf_state_key = f"pdf_export_{chosen}_{export_signature}"

        export_col_csv, export_col_pdf = st.columns(2)
        with export_col_csv:
            if st.button("Prepare filtered CSV", key=f"prepare_csv_{export_signature}"):
                try:
                    with session_factory() as db, db.begin():
                        company_context = resolve_company_context(
                            db, user_id=user.id, company_id=chosen
                        )
                        artifact = ExportService.export_csv(
                            db, company_context, dashboard_filters
                        )
                    st.session_state[csv_state_key] = artifact
                    st.success(f"CSV prepared: {artifact.row_count} transactions.")
                except (ReportingError, DashboardError, PermissionError) as exc:
                    st.error(f"CSV export failed: {exc}")
            csv_artifact = st.session_state.get(csv_state_key)
            if csv_artifact is not None:
                st.download_button(
                    "Download CSV",
                    data=csv_artifact.data,
                    file_name=csv_artifact.filename,
                    mime=csv_artifact.content_type,
                    key=f"download_csv_{export_signature}",
                )
        with export_col_pdf:
            if st.button("Prepare filtered PDF", key=f"prepare_pdf_{export_signature}"):
                try:
                    with session_factory() as db, db.begin():
                        company_context = resolve_company_context(
                            db, user_id=user.id, company_id=chosen
                        )
                        artifact = ExportService.export_pdf(
                            db, company_context, dashboard_filters
                        )
                    st.session_state[pdf_state_key] = artifact
                    st.success(f"PDF prepared: {artifact.row_count} transactions.")
                except (ReportingError, DashboardError, PermissionError) as exc:
                    st.error(f"PDF export failed: {exc}")
            pdf_artifact = st.session_state.get(pdf_state_key)
            if pdf_artifact is not None:
                st.download_button(
                    "Download PDF",
                    data=pdf_artifact.data,
                    file_name=pdf_artifact.filename,
                    mime=pdf_artifact.content_type,
                    key=f"download_pdf_{export_signature}",
                )

        st.subheader("Import history")
        try:
            with session_factory() as db:
                company_context = resolve_company_context(
                    db, user_id=user.id, company_id=chosen
                )
                import_batches = ImportHistoryService.list_batches(
                    db, company_context, limit=100
                )
            if import_batches:
                st.dataframe(
                    [
                        {
                            "File": item.file_name,
                            "Type": item.file_type.value,
                            "Extraction": item.extraction_method.value,
                            "Status": item.status.value,
                            "Rows": item.total_count,
                            "Valid": item.valid_count,
                            "Invalid": item.invalid_count,
                            "Duplicate": item.duplicate_count,
                            "Review": item.review_count,
                            "Created": item.created_at,
                            "Committed": item.committed_at,
                        }
                        for item in import_batches
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                batch_labels = {
                    item.id: (
                        f"{item.file_name} · {item.status.value} · "
                        f"{item.created_at.isoformat()}"
                    )
                    for item in import_batches
                }
                selected_batch_id = st.selectbox(
                    "Inspect import batch",
                    options=list(batch_labels),
                    format_func=lambda value: batch_labels[value],
                    key=f"history_batch_{chosen}",
                )
                with session_factory() as db:
                    company_context = resolve_company_context(
                        db, user_id=user.id, company_id=chosen
                    )
                    history_rows = ImportHistoryService.list_rows(
                        db,
                        company_context,
                        batch_id=selected_batch_id,
                        limit=100,
                    )
                if history_rows:
                    row_labels = {
                        item.id: f"Source row {item.source_row_number} · {item.row_status.value}"
                        for item in history_rows
                    }
                    selected_history_row = st.selectbox(
                        "Inspect imported source row",
                        options=list(row_labels),
                        format_func=lambda value: row_labels[value],
                        key=f"history_row_{chosen}_{selected_batch_id}",
                    )
                    history_row = next(
                        item for item in history_rows if item.id == selected_history_row
                    )
                    st.dataframe(
                        [
                            {
                                "Source row": item.source_row_number,
                                "Status": item.row_status.value,
                                "PDF page": item.source_page_number,
                                "PDF table": item.source_table_index,
                                "Decision": (
                                    item.review_decision.value if item.review_decision else None
                                ),
                                "Reviewed at": item.reviewed_at,
                            }
                            for item in history_rows
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption("Selected source values and parser diagnostics")
                    st.json(
                        {
                            "raw_values": history_row.raw_values_json,
                            "normalized_values": history_row.normalized_values_json,
                            "issues": history_row.issues_json,
                            "source_fingerprint": history_row.source_fingerprint,
                            "transaction_id": (
                                str(history_row.transaction_id)
                                if history_row.transaction_id
                                else None
                            ),
                            "resolution_note": history_row.resolution_note,
                        }
                    )
                else:
                    st.info("The selected batch has no staged source rows.")
            else:
                st.info("No import batches have been recorded for this company.")
        except (ReportingError, PermissionError) as exc:
            st.error(f"Import history could not be loaded: {exc}")

        if workspace_context.role in {MembershipRole.ADMIN, MembershipRole.ACCOUNTANT}:
            st.subheader("Audit trail")
            try:
                with session_factory() as db:
                    company_context = resolve_company_context(
                        db, user_id=user.id, company_id=chosen
                    )
                    audit_events = AuditService.list_events(
                        db, company_context, limit=100
                    )
                if audit_events:
                    st.dataframe(
                        [
                            {
                                "When (UTC)": item.created_at,
                                "Action": item.action,
                                "Entity": item.entity_type,
                                "Entity ID": str(item.entity_id),
                                "Actor user ID": str(item.actor_user_id),
                            }
                            for item in audit_events
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No company audit events have been recorded yet.")
            except (ReportingError, PermissionError) as exc:
                st.error(f"Audit history could not be loaded: {exc}")
        else:
            st.caption("Audit history is restricted to ADMIN and ACCOUNTANT roles.")

with tab_profile:
    st.subheader("Profil et espace de travail")
    st.caption(
        f"{user.display_name} · {user.email} · Workspace : {active_workspace_name} · "
        f"Rôle : {workspace_context.role.value}"
    )
    if workspace_context.role is MembershipRole.ADMIN:
        with st.expander("Créer une entreprise", expanded=False):
            with st.form("create_company_form"):
                company_name = st.text_input("Nom de l'entreprise")
                currency = st.text_input("Devise de base (ISO 4217)", value="XAF", max_chars=3)
                timezone = st.text_input("Fuseau horaire IANA", value="Africa/Douala")
                create_company = st.form_submit_button("Créer l'entreprise")
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
                    st.success("Entreprise créée.")
                    st.rerun()
                except WorkspaceError as exc:
                    st.error(str(exc))

    with st.expander("Créer un autre workspace", expanded=False):
        with st.form("create_workspace_form"):
            new_workspace_name = st.text_input("Nom du nouveau workspace")
            create_workspace = st.form_submit_button("Créer le workspace")
        if create_workspace:
            try:
                with session_factory() as db, db.begin():
                    WorkspaceService.create_workspace(
                        db, actor_user_id=user.id, name=new_workspace_name
                    )
                st.success("Workspace créé ; vous en êtes ADMIN.")
                st.rerun()
            except WorkspaceError as exc:
                st.error(str(exc))

    st.markdown("### Membres et autorisations")
    if workspace_context.role is MembershipRole.ADMIN:
        with st.form("add_member_form"):
            member_email = st.text_input("E-mail du nouveau membre")
            member_name = st.text_input("Nom complet")
            member_role = st.selectbox(
                "Rôle",
                options=[
                    MembershipRole.ACCOUNTANT,
                    MembershipRole.VIEWER,
                    MembershipRole.ADMIN,
                ],
                format_func=lambda value: value.value,
            )
            add_member = st.form_submit_button("Ajouter le membre")
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
                st.success(f"{result.user.email} ajouté.")
                if result.temporary_password:
                    st.warning(
                        "Copiez ce mot de passe temporaire maintenant ; "
                        "il ne sera plus affiché."
                    )
                    st.code(result.temporary_password)
            except WorkspaceError as exc:
                st.error(str(exc))

        with session_factory() as db:
            members = WorkspaceService.list_members(db, workspace_context)
        for membership, member_user in members:
            status = "actif" if membership.is_active else "inactif"
            st.markdown(
                f"**{member_user.display_name}** · {member_user.email} · "
                f"{membership.role.value} · {status}"
            )
            if membership.is_active:
                role_col, action_col = st.columns([2, 1])
                with role_col:
                    proposed_role = st.selectbox(
                        f"Rôle de {member_user.email}",
                        options=list(MembershipRole),
                        index=list(MembershipRole).index(membership.role),
                        key=f"role_{membership.id}",
                        format_func=lambda value: value.value,
                    )
                with action_col:
                    if st.button("Mettre à jour", key=f"update_role_{membership.id}"):
                        try:
                            with session_factory() as db, db.begin():
                                WorkspaceService.update_member_role(
                                    db,
                                    workspace_context,
                                    membership_id=membership.id,
                                    new_role=proposed_role,
                                )
                            st.success("Rôle mis à jour.")
                            st.rerun()
                        except WorkspaceError as exc:
                            st.error(str(exc))
                    if st.button("Désactiver", key=f"deactivate_{membership.id}"):
                        try:
                            with session_factory() as db, db.begin():
                                WorkspaceService.deactivate_member(
                                    db, workspace_context, membership_id=membership.id
                                )
                            st.success("Membre désactivé.")
                            st.rerun()
                        except WorkspaceError as exc:
                            st.error(str(exc))
    else:
        st.info("Seul un ADMIN du workspace peut gérer les membres.");

