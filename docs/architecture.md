# Architecture — SME Financial Dashboard
**Status: APPROVED FOR DEVELOPMENT — owner approval recorded 2026-11-09 after inclusion of the PDF import contract.**
Version 0.2. Phase 1 foundation implementation recorded 2026-11-09.

## Goals and stack
Local-first demonstrable modular monolith. Python 3.11+; Streamlit 1.67.0 UI; Pandas 2.2.3 ingestion; Python Decimal money; SQLAlchemy 2.0.50; SQLite local single-instance; PostgreSQL before concurrent/hosted multi-user use; Alembic 1.18.4 migrations; Pydantic 2.13.5 command/filter validation; Plotly 6.5.2 charts; pytest 9.0.2; openpyxl 3.1.5 XLSX; pdfplumber 0.11.9 for text/table extraction from digital PDFs; ReportLab 4.4.9 for PDF report generation; Ruff 0.17.4. Docker Compose optional. Runtime and development dependencies are pinned in requirements.txt and requirements-dev.txt.

## Boundaries
Streamlit app → application services (Workspace, Authorization, Import, Transaction, Categorization, Dashboard, Export, Audit) → domain (money, cashflow, validation, rules, fingerprint) → repositories/SQLAlchemy/models/migrations → SQLite. Keep calculations testable without UI. No FastAPI/React in MVP unless separately approved.

## Proposed layout
src/sme_financial_dashboard/{domain,db,security,repositories}; alembic/{versions,env.py}; tests/{unit,integration,workflows,security}; scripts/; sample_data/; docs/; .env.example; .gitignore; pyproject.toml; requirements.txt; requirements-dev.txt; README.md; optional Dockerfile/compose.yaml.

## Tenant isolation
Workspace contains Companies; WorkspaceMembership links User and role. Every financial record carries company_id. Resolve CompanyContext from authenticated identity and membership; never trust a UI-supplied company_id. Every repository query and export includes company scope. Validate same-company foreign keys. Test cross-company reads, writes, dashboard, audit and exports. SQLite has no PostgreSQL RLS; hosted/concurrent deployment requires PostgreSQL and RLS/security assessment.

## Import pipeline
Allow CSV, XLSX and PDF only. Validate allowlisted extension and actual file signature/content, size/page/row limits and parser output; show bounded preview; no writes before confirmation. Require date, amount, currency and direction or an explicitly configured signed-amount convention. Use explicit date/decimal parsing settings, normalized uppercase currency codes and Decimal; retain sanitized source row/mapping and import provenance.

- CSV: explicit delimiter/encoding and field mapping.
- XLSX: explicit worksheet selection and field mapping; never execute macros or workbook formulas.
- PDF: pdfplumber text/table extraction from digital PDFs, page by page, with source page/table/row provenance. Require preview and manual mapping. No OCR, scanned/image-only PDF parsing, password-protected PDF parsing or embedded-file extraction in MVP. Never execute PDF actions or JavaScript.
- Classification: BLANK, INVALID, DUPLICATE, VALID, VALID_WITH_WARNING and REVIEW. Identical candidates with no distinguishing reference enter REVIEW.
- Partial commit: show separate counts and require explicit confirmation. Accepted VALID rows are committed atomically with ImportBatch, ImportRow, Transaction and AuditEvent; REVIEW rows remain staged without a transaction link until resolved by an authorized user. Invalid and duplicate rows are not imported.
- Fingerprint: versioned SHA-256 scoped by company; exact field normalization is finalized in the import vertical before production use.
- Fail safely on malformed/unsupported/over-limit input. Uncertain date, amount, currency, direction or table alignment must not be guessed.

## Financial contract
amount > 0 Decimal; direction INFLOW/OUTFLOW. inflows=sum(INFLOW), outflows=sum(OUTFLOW), net=inflows-outflows. Partition by currency. Closing balance = a unique verified opening snapshot + validated net flow for the same company/account/currency from the snapshot date through the report end date; absent or conflicting snapshot => Unavailable. Snapshot date is the start of day, before movements dated that day. Closing balance is displayed only for one account and currency with no category/direction filter. Label as an estimated cash-management balance, not accounting profit or a certified bank balance. MonthlyMetric derived at query time. Dashboard reports include only non-deleted, validated transactions; all financial aggregation uses Decimal and keeps currencies separate.

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
DashboardService.report(filters, CompanyContext) → Decimal KPIs, previous-period comparison, monthly values, spend rankings and conditional balance state. AccountSnapshotService creates/list opening-balance evidence with role checks and audit.
ExportService.export_csv/export_pdf(filters, CompanyContext) → bounded, filtered CSV/PDF bytes; same DashboardFilters and tenant scope as dashboard.
ImportHistoryService.list_batches/list_rows(CompanyContext) → company-scoped paginated import provenance.
AuditService.list_events(CompanyContext) → company-scoped paginated audit metadata; ADMIN/ACCOUNTANT only.
No public HTTP API required for MVP.

## Approved permissions
One role per WorkspaceMembership applies uniformly across every company in that workspace. ADMIN: all functions and workspace/membership management, including transaction restore. ACCOUNTANT: view/export/import/categories/rules/corrections/audit and soft-delete. VIEWER: view/export only. ADMIN and ACCOUNTANT may soft-delete with a reason; only ADMIN may restore. Enforce permissions in services, not only in UI.

## Security and operations
Hash local passwords; no default production credential; secrets in environment only; .env.example contains placeholders; bounded file parsing; no macro execution; ORM parameterization; CSV formula escaping; redacted logs; append-only audit through application services; demo seed/reset and backup/restore instructions. No live financial integrations.

## External integrations
None required. CSV/XLSX ingress and local PDF generation only. Any future bank/Mobile Money adapter requires approved contract, authorization, legal basis, credentials and security review.

## Contract approval and change control
The owner explicitly approved architecture.md and data_dictionary.md for development on 2026-11-09, including this PDF import addendum. The approved MVP contract includes CSV/XLSX/PDF import with digital/text-based PDF extraction only, preview and manual mapping, no OCR, source-page provenance, REVIEW quarantine and explicitly confirmed partial commit. Implementation may proceed against these contracts. Any material change to file types, OCR, schema, permissions or financial semantics requires a written change proposal and owner approval.


## Decision addendum — 2026-11-09 (accepted)
- Deletion policy: SOFT DELETE. Add lifecycle fields (e.g. is_active/deleted_at/deleted_by_user_id/deletion_reason) or an equivalent auditable status. Exclude deleted rows from standard dashboard/list/export queries; retain records, ImportRow links and AuditEvent. Restore behavior and permission to delete/restore remain open.
- Ambiguous import policy: REVIEW. Ambiguous rows are staged with stable reason codes and cannot become transactions until manual resolution. Batch preview must report accepted, invalid, duplicate and review counts separately. Whether valid rows can be committed while review rows remain staged is still open; safest proposal is explicit partial commit after user confirmation.
- Access model: WORKSPACE. A user can access multiple companies via WorkspaceMembership. Resolve authorization on every request/service call and enforce company_id on all finance queries. Whether membership role applies uniformly to all workspace companies or supports company-specific overrides remains open.


## Final owner decisions — 2026-11-09 (accepted)
1. **Workspace role scope:** one role per WorkspaceMembership, applied uniformly to every company in that workspace. Membership still does not grant access to companies outside that workspace.
2. **Soft deletion/restoration:** ADMIN and ACCOUNTANT may soft-delete with mandatory reason; ADMIN alone may restore. Preserve transaction, import provenance and audit; exclude soft-deleted rows from default operational views, KPIs and exports.
3. **Partial import:** after explicit confirmation of the preview, commit valid unambiguous rows; keep REVIEW rows staged and excluded from transactions/KPIs until resolved. Invalid and duplicate rows remain separately classified. Commit accepted rows atomically.
4. **Identical rows without reference:** classify as REVIEW for manual resolution; do not silently deduplicate.
5. **Categorization:** one primary category per transaction; split allocations are out of MVP scope.
These decisions supersede earlier proposals where they differ.


## PDF import decision record — approved 2026-11-09
Supported input formats: CSV, XLSX and PDF. Implement a PDF adapter using pdfplumber for text/table extraction from digital PDFs. Retain page number, table index and extracted row position for each PDF-derived candidate. Require bounded preview, manual mapping and explicit confirmation; use the same Decimal, currency, duplicate, REVIEW, audit, company-isolation and partial-commit rules as other import formats. Scanned/image-only PDFs without a text layer, encrypted/password-protected PDFs, OCR, password cracking and embedded-file extraction are out of MVP. Never execute PDF JavaScript/actions or treat parsed content as instructions. Reject malformed or over-limit documents; when table structure is uncertain, return a clear error or stage rows as REVIEW rather than guessing. No persistent retention of the original uploaded PDF is required for the MVP; retain checksum, filename metadata, extraction metadata and row provenance.


## Phase 1 foundation implementation — 2026-11-09
Implemented and locally verified:
- `src/sme_financial_dashboard/config.py`: environment settings and SQLite directory preparation.
- `domain/money.py`: positive Decimal parsing, six-place NUMERIC(20,6) capacity guard, inflow/outflow and per-currency cash-flow totals; no float conversion or cross-currency netting.
- `db/models.py`: workspace, company, user, membership, import batch/row, category/rule, transaction, account snapshot and audit-event SQLAlchemy models.
- `db/session.py`: SQLite-aware engine, foreign-key enforcement and session scope.
- `security/rbac.py` and `security/company_scope.py`: workspace-wide role permissions and verified company context.
- Company, transaction and import-history repositories with company-scoped reads.
- Alembic initial migration, pinned dependency manifests, README and .env.example.
- Integration and unit tests for Decimal behavior, permissions, workspace role propagation, active-company access, tenant-scoped reads, soft-delete defaults, same-company foreign keys and REVIEW-row invariants.

Local evidence: `PYTHONPATH=src pytest -q` → 33 passed; Alembic fresh upgrade, `alembic check`, downgrade to base and re-upgrade → passed; SQLite `PRAGMA foreign_key_check` → no violations; `python -m compileall -q src tests alembic` → passed. Ruff was not executed in the session because the Ruff binary was not installed there; Ruff is pinned in the development requirements. No Streamlit UI or end-to-end import workflow is claimed complete.


## Phase 2 authentication and workspace contract
- Passwords use Argon2id through argon2-cffi. Enforce 12–128 characters; never store or log plaintext credentials.
- The one-time first-run bootstrap is guarded by a singleton BootstrapState database row and creates the initial ADMIN, workspace and membership atomically. Bootstrap is permanently closed after initialization.
- Authentication errors are generic. Inactive users cannot log in. New members receive a generated one-time temporary password and must change it at first login.
- Sessions are HMAC-SHA256 signed, opaque, short-lived tokens held in Streamlit server-side session state and backed by AuthSession rows storing only the token hash, expiry and revocation metadata. Logout and password changes revoke sessions. SESSION_SECRET is configured outside source control and must be at least 32 characters.
- WorkspaceMembership has an is_active flag for workspace-local deactivation without deleting history. Inactive memberships cannot resolve WorkspaceContext or CompanyContext.
- ADMIN may create companies, add/reactivate members, update member roles, and deactivate members. The last active ADMIN cannot be demoted or deactivated. A user may be a member of multiple workspaces with independent roles.
- Workspace and company/member changes create AuditEvent records. All service methods re-resolve actor membership and permissions from the database; do not trust UI context or role values as authorization.
- The first Streamlit shell provides setup/login/logout, forced temporary-password change, workspace/company selectors and ADMIN member/company management. It does not imply that financial dashboard/import screens already exist.


## Phase 2 review corrections
Workspace service inputs now normalize invalid values into explicit WorkspaceError responses for the Streamlit layer. Role updates coerce and validate the role enum before mutation. The CI lint profile checks correctness-focused Ruff rules (F, B, UP); import/line-length presentation rules are not configured as release gates in this phase.


## Phase 3 import implementation defaults — 2026-11-09
- Upload ceiling: 10 MiB; XLSX expanded archive ceiling: 50 MiB and maximum compression ratio 200:1; PDF maximum 100 pages; maximum 10,000 extracted data rows; preview table shows at most 20 rows.
- Accept only .csv, .xlsx and .pdf; reject mismatched signatures. XLSX must be a valid ZIP-based workbook; .xls/.xlsm are unsupported. Formula cells are rejected, never evaluated. Macro execution and external links are not enabled.
- CSV encodings are explicitly selected from UTF-8 BOM, UTF-8, Windows-1252 and Latin-1; delimiter is explicitly selected. XLSX sheet is explicitly selected when multiple sheets exist.
- Required mapping: transaction date, amount and currency; direction is either a mapped direction column or an explicitly selected signed-amount convention. Date format, decimal and thousands separators are user-selected. No locale guessing or silent rounding.
- Import preview persists sanitized ImportBatch/ImportRow staging data and a preview audit event; it does not create Transaction records. Only a separate explicit confirmation can commit VALID/VALID_WITH_WARNING rows. If INVALID/DUPLICATE/REVIEW rows exist, a second explicit partial-import confirmation is required. REVIEW rows remain staged with no transaction link.
- Fingerprint v1 uses company, transaction date, normalized amount, currency, direction, normalized reference and normalized counterparty. Text uses Unicode NFKC, whitespace collapse and casefold. Duplicate referenced rows are DUPLICATE; matching rows without a unique reference are REVIEW.
- PDF supports digital table extraction, with text-line fallback only where stable multi-column text is detectable. Each PDF-derived row stores page/table/row provenance. Scanned/image-only, encrypted, unstructured or ambiguous PDFs fail safely; no OCR, embedded-file extraction or PDF JavaScript execution.
- Outlier count remains zero in the first import vertical; the IQR warning threshold and minimum sample policy require a separate explicit product decision before outlier labels are enabled.


## Phase 3 resource and transaction hardening — 2026-11-09
- CSV parsing iterates the reader instead of materializing the complete row matrix; stop after 10,000 data rows. All accepted formats cap the source width at 100 columns.
- XLSX ZIP containers allow at most 1,000 entries, 50 MiB expanded size and a 200:1 maximum compression ratio. Formula cells are rejected; workbook macros are never executed.
- PDF ingestion is limited to 100 pages, 50 detected tables per page, 250,000 extracted characters per page, 5,000,000 extracted characters per document and 10,000 data rows. Table rows must have exactly the detected header width; ambiguous rows are rejected. Encrypted PDFs receive a stable unsupported-file error.
- Existing-transaction fingerprint lookups are chunked in groups of 500 to remain below SQLite's historical bind-parameter limit. Import commits insert candidate transactions in a batch, flush them, then set ImportRow transaction links in a second flush, all inside the same savepoint.
- Parser controls are resource bounds, not a hard wall-clock CPU timeout. The app remains a local, single-instance application; do not expose the upload parser as a public service without process-level resource controls and separate security review.


## Phase 4 — categorization and manual REVIEW resolution
- One primary Category FK remains the only category assignment per Transaction; split allocations remain out of MVP.
- Category kinds INFLOW/OUTFLOW/BOTH must be compatible with the transaction direction.
- CategorizationRule matches KEYWORD (description), COUNTERPARTY or REFERENCE using CONTAINS/EQUALS/STARTS_WITH after Unicode NFKC, whitespace collapse and casefold normalization.
- Higher numeric priority wins. A unique highest-priority match applies the rule; a tie produces NEEDS_REVIEW and no automatic category. No match leaves the transaction uncategorized.
- Manual category assignments are audited, set categorization_source=MANUAL and are not overwritten by automated rules. Rule-based category changes/clears are audited.
- Confirmed imports apply one company-scoped rule snapshot to the batch inside the same atomic commit. REVIEW-corrected transactions run through the same rule engine.
- Category deactivation is blocked while active rules reference it; categories are deactivated, not physically deleted.
- Review queue is company-scoped and limited to ADMIN/ACCOUNTANT. Decisions are CONFIRMED_DUPLICATE, REJECTED or CORRECTED_AND_ACCEPTED. Every decision requires a note and records reviewer/time/decision.
- CORRECTED_AND_ACCEPTED requires canonical ISO date, positive Decimal amount, currency, direction and a manual unique reference. This is intentionally stricter than accepting an ambiguous no-reference row without a unique distinguishing value.
- Keep ImportRow.source_fingerprint as the original source fingerprint after manual correction. Transaction.source_fingerprint uses the corrected values and manual reference. Subsequent import of the original reference-less row is staged as REVIEW again, preventing silent double-import.


## Phase 5 dashboard reporting contract
- Canonical inclusive filters: start_date, end_date, optional currency, account_name, category_id and direction. Each report and comparison query re-resolves CompanyContext.
- Reporting includes only \`deleted_at IS NULL\` and \`is_validated = true\` transactions. REVIEW rows have no Transaction and cannot enter dashboard totals.
- Inflows, outflows and net are calculated with Decimal and partitioned per currency. No cross-currency sum/conversion is allowed.
- The comparison period is the contiguous interval immediately before the selected period, with an identical number of days and identical non-date filters.
- Monthly cash flow and top-10 outflow breakdowns are derived at query time and grouped by currency.
- AccountSnapshot verification is an explicit ADMIN/ACCOUNTANT attestation with an evidence description and an audit event. Unverified snapshots remain provisional and do not support a closing balance.
- For an account/currency, the most recent unique verified snapshot at or before end_date is selected. A conflicting set at the latest date makes the balance unavailable. Treat as_of_date as the start of day and include same-day activity through end_date.
- A closing balance is only meaningful for a single account and currency with no category/direction subset. Otherwise show an explicit unavailable reason.
- Plotly chart values may be converted to float only for visualization; all totals and reconciliations remain Decimal.


## Phase 6 exports and history
- CSV/PDF export must call the same DashboardService filter contract and re-resolve CompanyContext and EXPORT permission. Exported rows are validated, non-deleted and never combined across currencies.
- Limit the export query to \`MAX_EXPORT_ROWS + 1\` at SQL level; fail closed if the bound is exceeded. Do not stream unbounded row sets into application memory.
- Neutralize CSV formula injection in every user-controlled text field, including text preceded by whitespace/control characters. Keep monetary values as fixed-point Decimal strings.
- PDF generation escapes all dynamic text, wraps table cells and includes company/filter metadata, per-currency totals and selected transaction details.
- Export preparation is audit logged with only export metadata and selected filters; avoid copying full transaction payloads into AuditEvent.
- Import history and audit history queries always scope by verified company context, with bounded pagination.
- Audit events are visible only to roles with VIEW_AUDIT (ADMIN/ACCOUNTANT in MVP). VIEWER retains read/export and import-history access but not audit-log access.
