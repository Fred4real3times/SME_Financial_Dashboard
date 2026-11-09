# Threat Model — SME Financial Dashboard
**Status:** DRAFT — local/sandbox MVP

## Assets and boundaries
Credentials/session; workspace/company memberships; uploaded files and staged rows; transactions/categories/rules/snapshots/reports; audit history; provenance and configuration. Boundaries: browser/Streamlit→services, upload→parser, services→database, app→downloads, local host/container→filesystem/logs/env. No external financial-provider boundary exists.

## Threats, controls and tests
- Cross-company IDOR/data leakage: authenticated CompanyContext, tenant-scoped repositories/exports, same-company FK validation; negative tests for reads/writes/dashboard/audit/export.
- Role bypass: service-level authorization; tests for every role/action.
- Malicious/oversized CSV/XLSX, zip bomb/path traversal: allowlist, content checks, limits, bounded preview, safe parser, never extract arbitrary paths or execute macros; crafted upload tests.
- CSV formula injection: escape formula-leading cells including whitespace/control prefixes; export payload tests.
- SQL injection: SQLAlchemy parameterized operations; adversarial input tests.
- Duplicate/replay: versioned fingerprint, DB uniqueness, atomic commit; repeat import tests.
- Locale/currency parsing: explicit formats and Decimal; boundary tests.
- Credential/session compromise: password hashing, no default production password, logout/session controls; auth tests.
- Secret/PII leakage: redacted logs, no raw payloads/secrets; scan logs and repository.
- Audit tampering: append-only service API and restricted permissions; negative tests.
- DB loss: backup/reset/restore exercise.
- Supply chain: pinned dependencies and dependency review.
- UI injection: render imported text safely; malicious-description test.

## Risk ranking
Critical: tenant leakage, role bypass, secret exposure. High: upload/parser abuse, formula injection, duplicate replay, financial parsing error. Medium: audit gaps, restore failure, dependency risk, resource exhaustion.

## Security gates
No imported value can override tenant identity; unauthorized roles cannot mutate; exports are scoped; import atomic/idempotent; no secrets in repo/logs/demo; live integrations absent/disabled; restore documented/tested.

## Limitations
SQLite lacks PostgreSQL row-level security. This is a local single-instance demo relying on service authorization and tenant-scoped repositories. Hosted/concurrent deployment requires PostgreSQL, RLS/security review and deployment controls.


## Decision addendum — 2026-11-09
Soft deletion is not physical erasure: retain transaction, source provenance and audit; ordinary dashboards/exports exclude deleted rows. Only authorized service actions may mark/restore lifecycle state, and each transition is audited. Ambiguous rows remain quarantined in review and must not be treated as valid financial transactions until an authorized human resolves them. Workspace membership grants access to multiple companies, but never bypasses company-level authorization. Role scope and restore permissions remain pending.

## Final owner decisions — 2026-11-09
Authorization uses one workspace-wide role per membership, consistently enforced across all companies in the workspace. ADMIN and ACCOUNTANT can soft-delete; only ADMIN can restore. Deletion requires reason and produces append-only audit events. Partial imports require explicit confirmation; REVIEW rows stay quarantined and out of all financial totals until resolved. Ambiguous identical rows without reference require manual review. One primary category only; no allocation/splitting. Security tests must cover all of these transitions and role boundaries.

## PDF upload and parsing threats — approved MVP scope
- Malformed or malicious PDF/parser abuse: allowlist .pdf, verify actual file signature/content, enforce byte/page/table/row/character limits, pin and review parser dependency, reject malformed or over-limit documents. The MVP does not enforce a hard wall-clock CPU timeout; parser execution is limited to the local single-instance app and is not a public upload service.
- Filename and MIME are untrusted; validate actual file content.
- Encrypted/password-protected PDFs are rejected; do not request or store passwords.
- Extract text/tables only; never execute PDF JavaScript/actions or extract/open embedded attachments.
- Detect scanned/image-only pages with no text layer; OCR is excluded from MVP. Report unsupported pages; never fabricate transactions.
- Unstable table alignment, split/merged cells or uncertain values require REVIEW or rejection; preserve page/table/row provenance.
- Test renamed non-PDF, malformed/encrypted/image-only files, empty text, excessive pages, broken/split tables, repeated headers, multi-page statements and valid synthetic digital PDFs.


## Phase 3 QA findings and residual risks — 2026-11-09
Automated hardening added:
- Streamed CSV row iteration and 10,000-row / 100-column ceilings.
- XLSX limits of 1,000 ZIP entries, 50 MiB expanded size, 200:1 compression ratio and 100 columns; formula cells rejected.
- PDF limits of 100 pages, 50 tables per page, 250,000 characters per page, 5,000,000 characters per document and 10,000 rows; encrypted PDFs and inconsistent table widths fail safely.
- SQLite fingerprint lookup chunks of 500 and batched transaction flushes with source-row links updated only after transaction inserts flush.
- Integration coverage for idempotent repeat commit and rollback of the whole batch on a concurrent fingerprint collision.

Residuals: no hard wall-clock parser timeout or automatic cleanup/expiry for abandoned PREVIEWED batches; no external penetration test or manual browser-based Streamlit smoke test has been performed in this environment. The app is local-first and should not be exposed publicly before further operational controls and independent review.
