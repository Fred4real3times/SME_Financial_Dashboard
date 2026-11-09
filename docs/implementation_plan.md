# Implementation Plan — SME Financial Dashboard
**Status:** APPROVED TO START DEVELOPMENT — owner approval of architecture.md and data_dictionary.md recorded 2026-11-09.

## Phase 0 — Baseline and contracts
Preserve existing files; initial repo contains README.md only. Review product scope, flows, architecture, dictionary, threat model and acceptance criteria. Resolve open decisions; freeze service contracts/schema. Exit: owner explicitly approves architecture.md and data_dictionary.md.

## Phase 1 — Domain and foundation [COMPLETE]
Created Python metadata, pinned dependencies, config and .env.example. Implemented Decimal money, direction, cashflow and per-currency partitioning. Added SQLAlchemy models, Alembic, repositories, verified company context and RBAC. Exit achieved: 33 unit/integration tests pass and a clean migration upgrades, downgrades and re-upgrades successfully. Evidence is recorded below.

## Phase 2 — Workspace, user and company [IN PROGRESS]
Local authentication with Argon2id passwords, one-time first-run ADMIN bootstrap, signed revocable sessions, temporary-password change, workspace/company/membership/roles management and authorized selectors. Test generic login errors, expiry/revocation, last-admin protection, membership deactivation, audit events and tenant boundaries.

## Phase 3 — Import vertical
CSV/XLSX/PDF template and mapping UI; PDF text/table extraction adapter with page provenance and scanned-PDF detection; preview; explicit parse settings; validation/classification including REVIEW; explicitly confirmed partial import; atomic batch/rows/transactions/audit commit; repeat import and rollback tests. Exit AC-01/02 and PDF-01..08.

## Phase 4 — Categorization and audit
Category CRUD, deterministic rules/conflict handling, manual correction and before/after audit; KPI refresh test. Exit AC-03.

## Phase 5 — Dashboard
Canonical filters; inflow/outflow/net; conditional balances; monthly charts, top spend/counterparties and period comparison; independent Decimal reconciliation. Exit AC-04.

## Phase 6 — Exports and history
CSV/PDF from same filtered report DTO; formula injection defense; import history and audit views; tenant/filter export tests. Exit AC-05.

## Phase 7 — Synthetic data and QA
Generate 12 months for three SME profiles with deliberate noisy rows. Run unit/integration/workflow/security tests; backup/restore; independent QA report; fix in-scope P0/P1 and rerun. Exit AC-06 and all required tests.

## Phase 8 — Release
Clean clone install on Windows/WSL; Docker optional; synthetic samples only; demo script; PASS/FAIL/BLOCKED evidence matrix; residual limitations.

## Exclusive ownership
Product: product_scope.md, user_flows.md and acceptance wording. Architecture/Data: architecture.md, data_dictionary.md, models/migrations. Backend: domain/, services/, repositories and unit/integration tests. Frontend: app/ and UI workflow tests. QA/Security: tests/security/ and independent QA report. Orchestrator: integration, README, implementation plan and acceptance matrix. Contract changes require written proposal and orchestrator/owner approval. If only one agent is available, execute roles sequentially.

## Phase report
Record files changed, exact commands run, exact test results, acceptance IDs/status, limitations/risks and next phase. Never claim an unexecuted test or integration passed.


## Decision addendum — 2026-11-09
Update Phase 0 contract freeze to include: soft-delete lifecycle and restore policy; REVIEW queue and partial-commit semantics; workspace membership role scope and cross-company authorization. Add schema migration and tests for these decisions before import/dashboard implementation. Do not begin application code until owner explicitly approves the revised architecture.md and data_dictionary.md, including the remaining decisions.

## Final owner decisions — 2026-11-09
Phase 0 contract freeze now records: workspace-wide uniform role; ADMIN/ACCOUNTANT soft-delete and ADMIN-only restore; mandatory deletion reason/audit; explicitly confirmed partial import with REVIEW quarantine; identical unreferenced rows sent to REVIEW; one primary category per transaction. Update architecture and schema/migrations/tests to these contracts only after owner approval of architecture.md and data_dictionary.md. No application-code development before that approval.

## Approved PDF implementation scope — 2026-11-09
Implement text-based/digital PDF statement ingestion with pdfplumber, page/table/row provenance, bounded preview, manual mapping, Decimal/locale validation and mandatory confirmation. Scanned/image-only PDFs, OCR, password-protected PDFs and embedded-file extraction are excluded from MVP. Unsupported or ambiguous PDF layouts must fail safely or enter REVIEW; they must not create guessed transactions.


## Phase 1 delivery report — 2026-11-09
**Status: COMPLETE for the foundation scope; later product workflows remain unimplemented.**

Implemented files include:
- `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.env.example`, `.gitignore`, `.python-version`, `README.md`.
- `src/sme_financial_dashboard/config.py`, `domain/money.py`, `db/base.py`, `db/models.py`, `db/session.py`.
- `security/rbac.py`, `security/company_scope.py`.
- `repositories/companies.py`, `repositories/transactions.py`, `repositories/import_batches.py`.
- Alembic environment and initial tenant-aware schema.
- Unit and integration tests covering monetary validation, currency partitioning, role permissions, active membership, workspace-wide role propagation, company-scoped repository reads, same-company foreign keys, soft-delete metadata and REVIEW-row linkage.

**Commands and results**
- `PYTHONPATH=src pytest -q` — PASS, 33 passed.
- `DATABASE_URL=sqlite:///./.data/schema-smoke.db PYTHONPATH=src alembic upgrade head` — PASS on a fresh test database.
- `DATABASE_URL=sqlite:///./.data/schema-smoke.db PYTHONPATH=src alembic check` — PASS, no new upgrade operations detected.
- `DATABASE_URL=sqlite:///./.data/schema-smoke.db PYTHONPATH=src alembic downgrade base` — PASS.
- Re-run `alembic upgrade head` after downgrade — PASS.
- SQLite `PRAGMA foreign_key_check` — PASS, no violations.
- `python -m compileall -q src tests alembic` — PASS.
- Ruff checks — NOT RUN in this environment because the Ruff executable was unavailable; exact dev version is pinned for installation.

**Not claimed complete:** Streamlit screens, local login/session management, first-admin bootstrap, workspace/company CRUD workflows, CSV/XLSX/PDF parser adapters, import preview/partial commit, review queue, categorization services, dashboard KPIs, exports, synthetic datasets and end-to-end QA.

**Next phase:** Phase 2 — local authentication, first-run ADMIN bootstrap, workspace/company/membership management and authorized company selector. Phase 3 follows with the import vertical.


## Phase 2 delivery scope
The Phase 2 branch contains the authentication service, Argon2id helpers, HMAC-signed session tokens backed by database session records, first-run bootstrap guard, workspace/company/member management services, a minimal authenticated Streamlit shell, migration and tests. The phase must not be reported complete until the branch test suite and clean migration checks have been executed against these exact committed files.


## Phase 2 CI hardening — 2026-11-09
Added automated GitHub Actions checks for Python 3.11–3.13: dependency installation, pytest, Ruff lint/format, clean Alembic upgrade/check/downgrade/re-upgrade and SQLite foreign-key integrity. Phase 2 completion depends on a green run for the branch head.


## Phase 3 execution update — 2026-11-09
The import vertical is being implemented on feat/phase-3-import-engine, stacked on the validated Phase 2 branch. Current scope: bounded CSV/XLSX/PDF parsers; explicit mapping and locale settings; Decimal validation; versioned fingerprint; company-authorized preview staging; duplicate and REVIEW classification; explicit partial commit; atomic transaction/audit creation; Streamlit upload/mapping/confirmation UI. Phase completion requires green CI on the exact branch head and evidence for IMP-12..IMP-19 and PDF-01..PDF-08. No outlier warning is enabled yet because its threshold policy remains unapproved.


## Phase 3 CI verification — 2026-11-09
Branch-head commit 64e50231bf228e251fb529b20655b89eba62b6cf passed GitHub Actions run 42621129042 on Python 3.11, 3.12 and 3.13. Each job passed Ruff, 76 pytest tests, Alembic upgrade/check/downgrade/re-upgrade and SQLite foreign_key_check. The Streamlit upload limit is also capped at 10 MiB through .streamlit/config.toml. PR #2 remains a draft stacked on Phase 2; no merge has occurred. Manual browser workflow testing, independent security review and exhaustive negative tests for all PDF/XLSX resource limits remain pending before marking the phase fully accepted.


## Phase 3 QA hardening delivery — 2026-11-09
QA found and corrected: unbounded CSV row materialization before row-limit enforcement; missing strict limits on CSV/XLSX dimensions and XLSX ZIP entry count; short PDF table rows being padded; encrypted PDF failures lacking a stable error code; missing PDF extracted-text/table count bounds; SQLite fingerprint lookup parameter scaling; and per-transaction flush overhead.
Added automated coverage for streaming row/column boundaries, XLSX entry/expanded-size/compression-ratio boundaries, PDF encryption/pages/tables/rows/per-page and total text bounds, uneven PDF rows, 1,200-row fingerprint lookup, same-preview commit idempotency, and full rollback on a simulated concurrent fingerprint collision.

The branch-head CI run for the 88-test baseline is 42623281625 on commit 8a855c2288306b4d256b89cb0f7cb177cdaa4c1c (all three Python versions green). Additional boundary tests and batched-commit performance changes must be verified on their own latest branch-head commit before creating the final Phase 3 integration PR. Manual Streamlit browser testing and external security review remain open.


## Final Phase 3 QA verification — 2026-11-09
Final QA branch head `5471e5851c347237a7b1cebea15427d67770d24a` passed GitHub Actions run `42623635331` on Python 3.11, 3.12 and 3.13. Each version passed Ruff, 92 tests, Alembic upgrade/check/downgrade/re-upgrade and SQLite foreign_key_check. Phase 3 backend/parser automation is validated. Manual Streamlit browser smoke testing and an external security review remain outstanding; release acceptance is not fully closed.
