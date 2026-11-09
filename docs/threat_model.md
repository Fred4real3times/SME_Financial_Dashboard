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
