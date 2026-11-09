# Data Dictionary — SME Financial Dashboard
**Status: APPROVED FOR DEVELOPMENT — owner approval recorded 2026-11-09 after inclusion of PDF import metadata.**
UUID primary keys; UTC timestamps; SQL NUMERIC/Python Decimal; company-scoped financial records.

## Shared conventions
Currency uppercase ISO 4217 alpha-3; no implicit conversion. amount is positive Decimal, direction INFLOW/OUTFLOW. transaction_date is DATE. Proposed NUMERIC(20,6), subject to currency precision review. Never store bank credentials, PINs or secrets.

## Entities
**Workspace:** id, name(120), created_at, updated_at.
**Company:** id, workspace_id FK, name(160), base_currency(3; display preference only), timezone IANA, is_demo, timestamps.
**User:** id, normalized unique email, password_hash (Argon2id), display_name, is_active, must_change_password, timestamps.
**WorkspaceMembership:** id, workspace_id FK, user_id FK, role ADMIN/ACCOUNTANT/VIEWER, is_active, created_at; unique(workspace_id,user_id). Inactive membership retains history but grants no access.
**ImportBatch:** id, company_id, uploaded_by_user_id, sanitized file_name, file_sha256, file_type CSV/XLSX/PDF, extraction_method CSV_ROWS/XLSX_SHEET/PDF_TABLE/PDF_TEXT, source_page_count nullable, parser_version nullable, versioned mapping_json, status PREVIEWED/PARTIALLY_COMMITTED/COMMITTED/FAILED/CANCELLED, total/blank/valid/invalid/duplicate/review/outlier counts, created_at, committed_at; optional company+file hash idempotency.
**ImportRow:** id, company_id, import_batch_id (same-company composite FK), source_row_number (unique within batch), source_page_number nullable, source_table_index nullable, sanitized raw_values_json, normalized_values_json nullable, row_status BLANK/INVALID/VALID/DUPLICATE/VALID_WITH_WARNING/REVIEW, issues_json, source_fingerprint nullable, transaction_id nullable (unique same-company composite FK to Transaction), reviewed_by_user_id nullable, reviewed_at nullable, review_decision nullable (ACCEPTED/REJECTED/CONFIRMED_DUPLICATE/CORRECTED_AND_ACCEPTED), resolution_note nullable. REVIEW rows cannot have a transaction link.
**Category:** id, company_id, name(80), normalized_name unique per company, kind INFLOW/OUTFLOW/BOTH, is_active, timestamps.
**CategorizationRule:** id, company_id, category_id (same-company FK), match_field KEYWORD/COUNTERPARTY/REFERENCE, operator CONTAINS/EQUALS/STARTS_WITH, match_value(200), priority, is_active, timestamps.
**Transaction:** id, company_id, nullable import_batch_id (same-company composite FK), transaction_date, optional value_date, amount NUMERIC(20,6), currency(3), direction, description(500), counterparty(200), reference(200), account_name(120), nullable primary category_id (same-company FK), categorization_source RULE/MANUAL/NONE, nullable categorization_rule_id (same-company FK), fingerprint_version, source_fingerprint, is_validated (true means accepted/committed for operational reporting), deleted_at, deleted_by_user_id, deletion_reason, timestamps; unique(company_id,fingerprint_version,source_fingerprint). ImportRow.transaction_id provides the optional one-to-one source-row link. Preserve source provenance after correction.
**AccountSnapshot:** id, company_id, account_name, as_of_date, currency, opening_balance, is_verified, source_description, created_by_user_id, created_at. is_verified is an explicit ADMIN/ACCOUNTANT attestation that the opening amount was reconciled to authoritative statement evidence. as_of_date means start of day, before movements dated that day. Provisional snapshots (false) are retained/audited but never used in closing balances. Conflicting snapshots flagged.
**MonthlyMetric:** derived query result, not authoritative persisted data in MVP: company, month, currency, inflows, outflows, net_cash_flow, transaction_count.
**AuditEvent:** id, nullable company_id for workspace events, actor_user_id, action, entity_type, entity_id, redacted before_json/after_json, correlation_id, created_at. Append-only through app services; no secrets or unnecessary financial payloads.

## Relationships and constraints
Workspace 1:N Company; Workspace N:N User via membership; Company 1:N batches, categories, rules, transactions, snapshots and audit events; batch 1:N rows; row 0..1 transaction; category 1:N transactions; rule 1:N transaction provenance. All tenant-owned foreign keys must enforce same-company ownership.

## Indexes
Transaction(company_id, transaction_date); Transaction(company_id,currency,direction,transaction_date); unique tenant fingerprint; ImportBatch(company_id,created_at); ImportRow(company_id,batch_id,row_status); AuditEvent(company_id,created_at); unique Category(company_id,normalized_name); CategorizationRule(company_id,is_active,priority).

## Implementation defaults / items to finalize in their vertical phase
- One primary category only; split allocations are excluded by owner decision.
- `account_name` is used initially; no dedicated Account entity in the foundation.
- Fingerprint v1 field normalization is finalized during the import vertical; identical rows without a distinguishing reference remain REVIEW.
- Amounts are stored in NUMERIC(20,6); input accepts no more than six decimal places and never rounds silently. Currency-specific minor-unit display/rounding policy must be explicit before import/reporting release.
- Upload byte/page/row limits are fixed and tested in the import vertical before accepting user files.
- Snapshot/dashboard semantics are finalized in Phase 5: only non-deleted, is_validated transactions are reported; the snapshot date is start-of-day; only a unique latest verified opening snapshot is used; conflict or missing evidence means closing balance Unavailable.


## Decision addendum — 2026-11-09
Accepted schema implications: WorkspaceMembership is the access anchor for multi-company access. Soft deletion requires transaction lifecycle metadata (preferred explicit `deleted_at`, `deleted_by_user_id`, `deletion_reason`; `is_active` may be derived or retained for query convenience) and an AuditEvent; do not physically delete the transaction or its ImportRow. ImportRow must support a REVIEW status and structured issue/review reason; staged ambiguous rows must not have a committed transaction_id. Add review resolution metadata (reviewed_by, reviewed_at, resolution/status) if approved. Open: role scope (workspace-wide or per-company), restore permissions/semantics, partial batch commit, and exact review resolutions.

## Final owner decisions — 2026-11-09
- WorkspaceMembership.role is the single role authority for the member and applies to all companies in that workspace; no company-specific role override in MVP.
- Transaction soft-delete metadata is required (deleted_at, deleted_by_user_id, deletion_reason; active status may be derived). ADMIN and ACCOUNTANT may delete; ADMIN alone may restore. All transitions audited.
- ImportRow must support REVIEW state and resolution metadata. Partial import is explicit opt-in at confirmation: VALID rows are committed atomically; REVIEW rows remain staged without Transaction linkage until resolved. Invalid and duplicate rows are not imported.
- Identical normalized business rows without a unique reference are REVIEW, not auto-deduplicated.
- Transaction.category_id is a single nullable primary category FK. No split-category/allocation table in MVP.


## PDF import schema addendum — approved 2026-11-09
ImportBatch.file_type includes PDF. extraction_method identifies PDF_TABLE or PDF_TEXT, and source_page_count/parser_version support traceability and diagnostics. ImportRow.source_page_number and source_table_index are nullable for CSV/XLSX and populated when applicable for PDF; source_row_number is a stable sequence within the batch. PDF-extracted cells/lines use the same sanitized raw_values_json pathway. REVIEW is a first-class row status; review decision metadata records reviewer, timestamp, decision and optional note. A REVIEW row has no Transaction link until accepted/corrected, validated and committed. No OCR artifact model is required in MVP. Transaction.category_id remains the only nullable primary category association; no allocation table is introduced.


## Phase 1 implementation alignment — 2026-11-09
The initial SQLAlchemy schema implements the entities above. `ImportRow.transaction_id` is the single optional one-to-one source-row link to a same-company Transaction; Transaction stores `import_batch_id` but not a duplicate reverse `import_row_id` field. Composite foreign keys enforce same-company ownership for import batch, category, categorization rule and import-row/transaction associations. Database checks enforce positive amounts, three-character currency fields, complete soft-delete metadata and no transaction link on a REVIEW row.


## Phase 2 authentication entities — approved implementation detail
**AuthSession:** id UUID, user_id FK, token_hash SHA-256 (never raw token), created_at, expires_at, nullable revoked_at, nullable last_seen_at. Index (user_id, expires_at); unique token_hash. Signed token payload contains version, session ID, user ID, expiry and nonce; token signature uses HMAC-SHA256.
**BootstrapState:** singleton integer id constrained to 1, initial_admin_user_id unique FK, initialized_at. Inserted in the same transaction as first ADMIN, workspace and membership; its presence permanently closes first-run setup.
User adds `must_change_password` to force newly provisioned users to replace temporary credentials. WorkspaceMembership adds `is_active` to support membership deactivation without deleting historical role/audit information.


## Phase 3 import runtime implementation defaults — 2026-11-09
- ImportBatch and ImportRow are created at preview time as isolated staging records. No Transaction is inserted until explicit confirmation. Preview staging is company-scoped and audited.
- File constraints: 10 MiB upload; XLSX expanded ZIP 50 MiB / 200:1 maximum ratio; PDF 100 pages; extracted data rows 10,000; UI preview sample 20 rows.
- Mapping JSON persists column indexes and explicit parser settings (date format, decimal/thousands separator, CSV delimiter/encoding, XLSX worksheet, direction mode). Required: transaction_date, amount, currency and either direction column or signed-amount mode.
- The original file bytes are not retained. ImportBatch stores a sanitized filename, SHA-256, file type, parser version, extraction metadata and mapping; ImportRow stores bounded sanitized source values, normalized values, stable issues and PDF source page/table/row.
- Fingerprint v1 hashes company_id, transaction_date, normalized Decimal amount, uppercase currency, direction, normalized reference and normalized counterparty. NFKC, whitespace collapse and casefold are applied to text. Rows identical without reference enter REVIEW.
- VALID and VALID_WITH_WARNING are the only statuses linked to new Transactions. INVALID, DUPLICATE, BLANK and REVIEW rows remain unlinked. Review resolution is a later vertical; outlier count is not populated until the outlier policy is approved.


## Phase 4 categorization and review implementation details
- Category and CategorizationRule remain company-scoped. Category.kind is checked against Transaction.direction; a transaction stores exactly one nullable category_id.
- Numeric rule priority is descending (larger number wins). Equal highest priority across matching rules does not assign a category; the result is NEEDS_REVIEW.
- Manual category assignment sets categorization_source=MANUAL and categorization_rule_id=NULL. Rule application must preserve MANUAL assignments.
- Review resolution stores reviewed_by_user_id, reviewed_at, review_decision and resolution_note on ImportRow. CONFIRMED_DUPLICATE maps to row_status=DUPLICATE; REJECTED maps to INVALID; CORRECTED_AND_ACCEPTED maps to VALID_WITH_WARNING and creates a linked Transaction.
- A corrected acceptance needs a nonempty manual unique reference. ImportRow.source_fingerprint keeps the original reference-less fingerprint for future re-import review detection; the linked Transaction stores the corrected fingerprint.
- Batch counts/status are recomputed after every review decision. No schema migration is expected for this phase; all required review/category fields exist in the approved foundation schema.


## Phase 5 dashboard/reporting semantics
- Dashboard filters are inclusive start/end dates with optional currency, account, category and direction.
- Totals, month buckets, outflow rankings and comparisons are computed with Decimal and partitioned by currency. The immediately preceding comparison interval has the same number of days and identical non-date filters.
- Only committed/accepted transactions (\`is_validated = true\`) that are not soft-deleted enter dashboard reporting. REVIEW rows remain ImportRow staging and are excluded.
- AccountSnapshot.as_of_date is the start of the day before transactions dated that day. A closing balance is calculated from a unique verified snapshot for the selected company/account/currency plus all validated net movements from as_of_date through the report end date, inclusive.
- No account or currency selection, category/direction subsetting, absence of a verified snapshot, or conflicting verified snapshots means the closing balance is explicitly unavailable.
- Snapshot creation requires ADMIN or ACCOUNTANT, an evidence description, a Decimal opening amount (up to six places) and an explicit verification checkbox. Every creation is audited. A provisional snapshot is not used as opening balance evidence.


## Phase 6 exports and history — no new persistence entities
- CSV/PDF artifacts are generated on demand and are not stored as financial records.
- Export preparation is recorded in the existing AuditEvent entity using \`EXPORT_CSV_PREPARED\` or \`EXPORT_PDF_PREPARED\`, with company, actor, date range, selected filters, safe filename and row count.
- Import history is a company-scoped view over ImportBatch and ImportRow. Original row values, issues, review metadata and source page/table/row provenance remain in their existing columns.
- No export file contents or duplicated import-history data are persisted in the MVP.
