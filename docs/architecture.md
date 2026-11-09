# Architecture — SME Financial Dashboard
**Status: APPROVED FOR DEVELOPMENT — owner approval recorded 2026-11-09 after inclusion of the PDF import contract.**
Version 0.1. Repository baseline: initial commit with README.md only.

## Goals and stack
Local-first demonstrable modular monolith. Python 3.11+; Streamlit UI; Pandas ingestion; Python Decimal money; SQLAlchemy 2.x; SQLite local single-instance; PostgreSQL before concurrent/hosted multi-user use; Alembic migrations; Pydantic command/filter validation; Plotly charts; pytest; openpyxl XLSX; pdfplumber for text/table extraction from digital PDFs; ReportLab for PDF report generation; Ruff. Docker Compose optional. Pin exact dependency versions during implementation after environment check.

## Boundaries
Streamlit app → application services (Workspace, Authorization, Import, Transaction, Categorization, Dashboard, Export, Audit) → domain (money, cashflow, validation, rules, fingerprint) → repositories/SQLAlchemy/models/migrations → SQLite. Keep calculations testable without UI. No FastAPI/React in MVP unless separately approved.

## Proposed layout
app/; services/; domain/; data/models, repositories, migrations; tests/unit, integration, workflows, security; scripts/; sample_data/; docs/; .env.example; .gitignore; pyproject.toml; README.md; optional Dockerfile/compose.yaml.

## Tenant isolation
Workspace contains Companies; WorkspaceMembership links User and role. Every financial record carries company_id. Resolve CompanyContext from authenticated identity and membership; never trust a UI-supplied company_id. Every repository query and export includes company scope. Validate same-company foreign keys. Test cross-company reads, writes, dashboard, audit and exports. SQLite has no PostgreSQL RLS; hosted/concurrent deployment requires PostgreSQL and RLS/security assessment.

## Import pipeline
Allow CSV, XLSX and PDF only; validate allowlisted extension and actual file signature/content, size/page/row limits and parser output; show bounded preview; no writes before confirmation. Require date, amount, currency and direction or explicit signed convention. Parse explicit date/decimal settings; normalize currency uppercase; use Decimal; retain sanitized source row/mapping. Classify BLANK/INVALID/DUPLICATE/VALID/VALID_WITH_WARNING. Versioned SHA-256 fingerprint from normalized business fields, scoped by company. Atomic commit of ImportBatch, ImportRow, Transaction and AuditEvent. Repeated exact rows are idempotent. Identical legitimate rows lacking a distinguishing reference are inherently ambiguous and must be reviewed, not artificially distinguished.

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
