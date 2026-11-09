# Architecture — SME Financial Dashboard
**Status: DRAFT / NOT APPROVED. Do not modify application code until owner validates this file and data_dictionary.md.**
Version 0.1. Repository baseline: initial commit with README.md only.

## Goals and stack
Local-first demonstrable modular monolith. Python 3.11+; Streamlit UI; Pandas ingestion; Python Decimal money; SQLAlchemy 2.x; SQLite local single-instance; PostgreSQL before concurrent/hosted multi-user use; Alembic migrations; Pydantic command/filter validation; Plotly charts; pytest; openpyxl XLSX; ReportLab proposed PDF; Ruff. Docker Compose optional. Pin exact dependency versions during implementation after environment check.

## Boundaries
Streamlit app → application services (Workspace, Authorization, Import, Transaction, Categorization, Dashboard, Export, Audit) → domain (money, cashflow, validation, rules, fingerprint) → repositories/SQLAlchemy/models/migrations → SQLite. Keep calculations testable without UI. No FastAPI/React in MVP unless separately approved.

## Proposed layout
app/; services/; domain/; data/models, repositories, migrations; tests/unit, integration, workflows, security; scripts/; sample_data/; docs/; .env.example; .gitignore; pyproject.toml; README.md; optional Dockerfile/compose.yaml.

## Tenant isolation
Workspace contains Companies; WorkspaceMembership links User and role. Every financial record carries company_id. Resolve CompanyContext from authenticated identity and membership; never trust a UI-supplied company_id. Every repository query and export includes company scope. Validate same-company foreign keys. Test cross-company reads, writes, dashboard, audit and exports. SQLite has no PostgreSQL RLS; hosted/concurrent deployment requires PostgreSQL and RLS/security assessment.

## Import pipeline
Allow CSV/XLSX only; size/row limits; bounded preview; no writes before confirmation. Require date, amount, currency and direction or explicit signed convention. Parse explicit date/decimal settings; normalize currency uppercase; use Decimal; retain sanitized source row/mapping. Classify BLANK/INVALID/DUPLICATE/VALID/VALID_WITH_WARNING. Versioned SHA-256 fingerprint from normalized business fields, scoped by company. Atomic commit of ImportBatch, ImportRow, Transaction and AuditEvent. Repeated exact rows are idempotent. Identical legitimate rows lacking a distinguishing reference are inherently ambiguous and must be reviewed, not artificially distinguished.

## Financial contract
amount > 0 Decimal; direction INFLOW/OUTFLOW. inflows=sum(INFLOW), outflows=sum(OUTFLOW), net=inflows-outflows. Partition by currency. Closing balance = coherent opening snapshot + net flow for same company/account/currency/period; absent snapshot => Unavailable. Label estimated/unverified balance. These are cash-management indicators, not accounting profit or certified bank balance. MonthlyMetric derived at query time.

## Categorization contract
Rule fields: company, category, match_field KEYWORD/COUNTERPARTY/REFERENCE, operator CONTAINS/EQUALS/STARTS_WITH, normalized match_value, integer priority, active. Unique highest-priority match assigns category; tie/no match => manual review. Manual override is audited.

## Duplicate/outlier semantics
Unique(company_id, fingerprint_version, source_fingerprint). Fingerprint field list/version requires approval. Outlier: explainable IQR per company/currency/direction after minimum sample size; warning only. Threshold and minimum sample size require approval.

## Service contracts
ImportService.preview(file_bytes, mapping, CompanyContext) → Preview DTO/issues, no writes.
ImportService.commit(preview_id, CompanyContext) → atomic batch summary or typed error.
TransactionService.list(filters, CompanyContext) → scoped DTOs.
TransactionService.update_category(transaction_id, category_id, actor_context) → updated DTO + audit.
Category/Rule services create/update with validation and audit.
DashboardService.summary/monthly(filters, CompanyContext) → Decimal KPIs, balance state, provenance.
ExportService.export(filters, format, CompanyContext) → filtered CSV/PDF bytes.
AuditService.list(filters, CompanyContext) → scoped events.
No public HTTP API required for MVP.

## Proposed permissions
ADMIN: all functions and membership/settings management. ACCOUNTANT: view/export/import/categories/rules/corrections/audit. VIEWER: view/export only. Enforce in services.

## Security and operations
Hash local passwords; no default production credential; secrets in environment only; .env.example contains placeholders; bounded file parsing; no macro execution; ORM parameterization; CSV formula escaping; redacted logs; append-only audit through application services; demo seed/reset and backup/restore instructions. No live financial integrations.

## External integrations
None required. CSV/XLSX ingress and local PDF generation only. Any future bank/Mobile Money adapter requires approved contract, authorization, legal basis, credentials and security review.

## Approval checklist
Approve A-01..A-10 in product_scope.md; workspace/company/membership and roles; amount/direction/currency; fingerprint and identical-row ambiguity; outlier algorithm; opening-balance semantics; SQLite/PostgreSQL gate; service contracts and audit scope. **Code implementation is blocked until approval.**
