# Data Dictionary — SME Financial Dashboard
**Status: DRAFT / NOT APPROVED. Align schema with architecture.md before implementation.**
UUID primary keys; UTC timestamps; SQL NUMERIC/Python Decimal; company-scoped financial records.

## Shared conventions
Currency uppercase ISO 4217 alpha-3; no implicit conversion. amount is positive Decimal, direction INFLOW/OUTFLOW. transaction_date is DATE. Proposed NUMERIC(20,6), subject to currency precision review. Never store bank credentials, PINs or secrets.

## Entities
**Workspace:** id, name(120), created_at, updated_at.
**Company:** id, workspace_id FK, name(160), base_currency(3; display preference only), timezone IANA, is_demo, timestamps.
**User:** id, normalized unique email, password_hash, display_name, is_active, timestamps.
**WorkspaceMembership:** id, workspace_id FK, user_id FK, role ADMIN/ACCOUNTANT/VIEWER, created_at; unique(workspace_id,user_id).
**ImportBatch:** id, company_id, uploaded_by_user_id, sanitized file_name, file_sha256, file_type CSV/XLSX, versioned mapping_json, status PREVIEWED/COMMITTED/FAILED/CANCELLED, total/blank/valid/invalid/duplicate/outlier counts, created_at, committed_at; optional company+file hash idempotency.
**ImportRow:** id, company_id, import_batch_id, source_row_number, sanitized raw_values_json, normalized_values_json nullable, row_status BLANK/INVALID/VALID/DUPLICATE/VALID_WITH_WARNING, issues_json, source_fingerprint, transaction_id nullable; unique(batch_id,row_number).
**Category:** id, company_id, name(80), normalized_name unique per company, kind INFLOW/OUTFLOW/BOTH, is_active, timestamps.
**CategorizationRule:** id, company_id, category_id (same-company FK), match_field KEYWORD/COUNTERPARTY/REFERENCE, operator CONTAINS/EQUALS/STARTS_WITH, match_value(200), priority, is_active, timestamps.
**Transaction:** id, company_id, import_batch_id, import_row_id, transaction_date, optional value_date, amount NUMERIC(20,6), currency(3), direction, description(500), counterparty(200), reference(200), account_name(120), nullable category_id, categorization_source RULE/MANUAL/NONE, nullable categorization_rule_id, fingerprint_version, source_fingerprint, is_validated, timestamps; unique(company_id,fingerprint_version,source_fingerprint). Preserve source provenance after correction.
**AccountSnapshot:** id, company_id, account_name, as_of_date, currency, opening_balance, is_verified, source_description, created_by_user_id, created_at. Conflicting snapshots flagged.
**MonthlyMetric:** derived query result, not authoritative persisted data in MVP: company, month, currency, inflows, outflows, net_cash_flow, transaction_count.
**AuditEvent:** id, nullable company_id for workspace events, actor_user_id, action, entity_type, entity_id, redacted before_json/after_json, correlation_id, created_at. Append-only through app services; no secrets or unnecessary financial payloads.

## Relationships and constraints
Workspace 1:N Company; Workspace N:N User via membership; Company 1:N batches, categories, rules, transactions, snapshots and audit events; batch 1:N rows; row 0..1 transaction; category 1:N transactions; rule 1:N transaction provenance. All tenant-owned foreign keys must enforce same-company ownership.

## Indexes
Transaction(company_id, transaction_date); Transaction(company_id,currency,direction,transaction_date); unique tenant fingerprint; ImportBatch(company_id,created_at); ImportRow(company_id,batch_id,row_status); AuditEvent(company_id,created_at); unique Category(company_id,normalized_name); CategorizationRule(company_id,is_active,priority).

## Decisions still open
Can transactions split categories? Proposal no. Dedicated Account entity? Proposal account_name initially. Exact fingerprint fields and identical legitimate rows. Currency exponent/rounding and amount bounds. File size/row limits and raw-row retention. Snapshot conflict and closing-balance cutoff. Exact meaning of is_validated.


## Decision addendum — 2026-11-09
Accepted schema implications: WorkspaceMembership is the access anchor for multi-company access. Soft deletion requires transaction lifecycle metadata (preferred explicit `deleted_at`, `deleted_by_user_id`, `deletion_reason`; `is_active` may be derived or retained for query convenience) and an AuditEvent; do not physically delete the transaction or its ImportRow. ImportRow must support a REVIEW status and structured issue/review reason; staged ambiguous rows must not have a committed transaction_id. Add review resolution metadata (reviewed_by, reviewed_at, resolution/status) if approved. Open: role scope (workspace-wide or per-company), restore permissions/semantics, partial batch commit, and exact review resolutions.