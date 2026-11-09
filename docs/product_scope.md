# Product Scope — SME Financial Dashboard
**Status:** DRAFT — architecture approval required before application-code changes.

## 1. Problem and objective
SMEs often have fragmented bank exports and sales/expense files, making cash movements and operational performance difficult to understand. Convert CSV/XLSX exports into traceable cash-basis management information. This is not certified accounting software.

## 2. Users
- SME Owner/Director: dashboard, trends, filtered reports (VIEWER).
- Accountant/Finance Assistant: imports, validation, categorization and corrections (ACCOUNTANT).
- Workspace Administrator: companies, memberships, roles and settings (ADMIN).

## 3. Included in MVP
Workspace/company setup; CSV/XLSX upload and mapping; preview and validation; blank/invalid/duplicate/outlier detection; editable categories and deterministic rules; cash-basis inflow/outflow/net KPIs; opening/closing balance when supported by snapshots; monthly charts; top expenses/customers/suppliers; filters and period comparison; CSV/PDF exports; import history and audit trail; synthetic demo data for three SMEs over 12 months.

## 4. Explicitly excluded
General ledger/double-entry bookkeeping, statutory accounts, certified accounting, tax filing/advice, live bank/Mobile Money integrations, scraping/webhooks, payment initiation or movement of funds, credit scoring/approval, FX conversion, public SaaS deployment, mobile app and production identity integrations.

## 5. Core business rules
- Positive Decimal amount plus explicit INFLOW/OUTFLOW direction.
- Aggregate by currency; never add different currencies or convert implicitly.
- Missing opening balance means closing balance is Unavailable, not zero.
- Outliers are warnings for review, never silently deleted.
- Invalid rows are never silently coerced.
- Every accepted transaction retains import batch/row provenance.
- Repeated strict duplicates are not inserted twice.
- Exports use exactly the dashboard's canonical filters.
- Every financial query and export is company-scoped and authorized server-side.
- Demo data is synthetic and visibly labelled.

## 6. Dependencies
Python, Streamlit, Pandas, SQLAlchemy, SQLite, Alembic, Plotly, pytest; openpyxl for XLSX; ReportLab proposed for PDF; PostgreSQL before concurrent/hosted multi-user deployment. No external financial provider is required.

## 7. Risks
Tenant data leakage; duplicate legitimate rows with no unique reference; ambiguous date/decimal formats; mixed currencies; false closing balances; malicious/oversized uploads; CSV formula injection; weak local authentication; SQLite concurrency limitations; misleading interpretation as accounting profit or certified balances.

## 8. Acceptance summary
Valid CSV import with counts; idempotent strict duplicate handling; audited category correction and KPI refresh; independently reconciled dashboard totals; filters honored by exports; cross-company access denied; tests and clean-clone Windows/WSL README reproducible.

## 9. Initial conservative assumptions — require approval
A-01 Streamlit-only modular monolith; no FastAPI initially.
A-02 SQLite for local single-instance demo; PostgreSQL before concurrent/hosted use.
A-03 Workspace can contain multiple companies; membership grants workspace role.
A-04 Roles ADMIN, ACCOUNTANT, VIEWER.
A-05 Amount is positive Decimal; direction is separate.
A-06 No automatic FX; report one currency at a time.
A-07 Duplicate fingerprint is company-scoped and versioned.
A-08 IQR outlier flag only after minimum sample size; warning only.
A-09 MonthlyMetric calculated at query time, not stored as source of truth.
A-10 Africa/Douala proposed demo timezone, configurable per company.

**Release boundary:** local synthetic demo first. Real-data pilot only after explicit authorization and review. Production integrations require contracts, legal basis, credentials/secrets and security approval.


## Decision addendum — 2026-11-09 (owner decisions)
The following decisions are accepted and supersede conflicting provisional assumptions: (1) transaction deletion is SOFT DELETE only: mark inactive/deleted with actor, timestamp and reason; retain original row, provenance and audit history; exclude inactive transactions from ordinary KPIs/exports by default, with authorized history access. Hard deletion is not an ordinary user operation. (2) Ambiguous import rows use REVIEW: stage and isolate them for manual resolution; do not auto-import or silently discard them; valid unambiguous rows may proceed only if batch preview clearly separates review rows and the user confirms the partial outcome. (3) Access model is WORKSPACE: one user may belong to a workspace and access multiple companies through workspace membership/role; company-level authorization and company scoping remain mandatory. The exact role scope (workspace-wide vs per-company overrides) remains to be finalized below.

## Final owner decisions — 2026-11-09
- Workspace role scope: one role per user membership applies uniformly to every company in that workspace. Company-level access remains restricted to companies in that workspace.
- Soft deletion: ADMIN and ACCOUNTANT may soft-delete transactions; ADMIN alone may restore. Deletion reason required; retain record, provenance and audit.
- Ambiguous import: allow partial commit only after explicit confirmation; valid unambiguous rows commit, REVIEW rows remain staged and excluded from financial totals until resolved.
- Identical rows without a distinguishing reference: REVIEW manually; never silently deduplicate.
- Categorization: exactly one primary category per transaction in MVP; no split allocation.
