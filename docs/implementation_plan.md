# Implementation Plan — SME Financial Dashboard
**Status:** APPROVED TO START DEVELOPMENT — owner approval of architecture.md and data_dictionary.md recorded 2026-11-09.

## Phase 0 — Baseline and contracts
Preserve existing files; initial repo contains README.md only. Review product scope, flows, architecture, dictionary, threat model and acceptance criteria. Resolve open decisions; freeze service contracts/schema. Exit: owner explicitly approves architecture.md and data_dictionary.md.

## Phase 1 — Domain and foundation [COMPLETE]
Created Python metadata, pinned dependencies, config and .env.example. Implemented Decimal money, direction, cashflow and per-currency partitioning. Added SQLAlchemy models, Alembic, repositories, verified company context and RBAC. Exit achieved: 33 unit/integration tests pass and a clean migration upgrades, downgrades and re-upgrades successfully. Evidence is recorded below.

## Phase 2 — Workspace, user and company [COMPLETE — automated CI; manual UI smoke test outstanding]
Local authentication with Argon2id passwords, one-time first-run ADMIN bootstrap, signed revocable sessions, temporary-password change, workspace/company/membership/roles management and authorized selectors. Test generic login errors, expiry/revocation, last-admin protection, membership deactivation, audit events and tenant boundaries.

## Phase 3 — Import vertical [COMPLETE — automated QA; manual UI smoke test outstanding]
CSV/XLSX/PDF template and mapping UI; PDF text/table extraction adapter with page provenance and scanned-PDF detection; preview; explicit parse settings; validation/classification including REVIEW; explicitly confirmed partial import; atomic batch/rows/transactions/audit commit; repeat import and rollback tests. Exit AC-01/02 and PDF-01..08.

## Phase 4 — Categorization and audit [COMPLETE — automated CI; manual UI smoke test outstanding]
Category CRUD, deterministic rules/conflict handling, manual correction and before/after audit; KPI refresh test. Exit AC-03.

## Phase 5 — Dashboard [COMPLETE — automated CI; manual browser smoke test outstanding]
Canonical filters; inflow/outflow/net; conditional balances; monthly charts, top spend/counterparties and period comparison; independent Decimal reconciliation. Exit AC-04.

## Phase 6 — Exports and history [AUTOMATED TESTS PASS ON MAIN]
CSV/PDF from the same company-scoped DashboardFilters; CSV formula-injection defense; import-batch/row history; company audit history; export history/audit events; bounded export size and pagination. Exit AC-05 after backend and UI tests.

## Phase 7 — Synthetic data and backup/restore tooling [AUTOMATED TESTS PASS ON PRE-REBASE FEATURE BRANCH]
Generate 12 months for three SME profiles through the production import workflow; validate counts, categorization, REVIEW quarantine and verified snapshots. Add verified SQLite backup/restore tooling with atomic publication, integrity checks and explicit overwrite controls. Run unit/integration/workflow/security regression tests; record independent QA report and limitations. External security review and manual browser QA remain separate release gates. Re-run CI after rebasing before merge. Exit AC-06 and all required automated tests.

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


## Phase 4 — categorization and review queue [IN PROGRESS]
Backend services and Streamlit screens are being added on feat/phase-4-categorization-review:
- Category creation/list/update/deactivation with company scope and audit; one primary category only.
- Categorization rule CRUD and deterministic matching on description keyword, counterparty or reference.
- Higher numeric priority wins; ties produce NEEDS_REVIEW; direction compatibility required; manual assignments are protected.
- Confirmed imports apply rules once per batch. Corrected REVIEW acceptance uses the same rule engine.
- Review queue decisions: CONFIRMED_DUPLICATE, REJECTED, CORRECTED_AND_ACCEPTED; corrected acceptance requires a unique manual reference and preserves the original source fingerprint for future re-import detection.
Exit requires CAT-07..CAT-11 and REV-01..REV-06 automated evidence plus manual Streamlit smoke testing. No Phase 4 code is merged to main.


## Phase 4 final automated verification — 2026-11-09
Phase 4 (categorization and manual import review) is integrated into \`main\`. After PR #5 corrected the Ruff UP012 finding, main commit \`41cf26cb5231ceb3e540f402fb9b944048a2315e\` passed GitHub Actions run \`42634994455\`: Python 3.11, 3.12 and 3.13 each passed Ruff, 110 unit/integration tests, Alembic upgrade/check/downgrade/re-upgrade and SQLite foreign_key_check. PRs #4 and #3 integrated the Phase 4 and Phase 3 branches; PR #5 delivered the follow-up lint correction.

**Still open:** browser-based Streamlit smoke testing for login → import preview/commit → category/rule management → manual REVIEW resolution, and independent security review. Automated CI is not a substitute for these release checks.

## Phase 5 — Dashboard implementation decisions — 2026-11-09
- The dashboard reads only active, committed/validated transactions (\`deleted_at IS NULL\` and \`is_validated = true\`). REVIEW rows remain staging records and are excluded.
- Every amount remains a Python Decimal. KPIs, monthly values, rankings and comparisons are partitioned by currency; no exchange-rate conversion or cross-currency addition is performed.
- Canonical filters are inclusive start/end dates plus optional currency, account, category and direction.
- The comparison period is the immediately preceding contiguous interval with the same number of calendar days and the same non-date filters.
- The closing balance is an estimated cash-management indicator only. It is displayed only for one account and one currency, without category or direction filtering, and only when one unique verified opening snapshot exists at or before the selected end date.
- \`AccountSnapshot.as_of_date\` is interpreted as the start of that day, before transactions dated that day. Closing balance is opening balance plus all validated, non-deleted movements for the same company/account/currency from that date through the selected end date, inclusive.
- A provisional (\`is_verified = false\`) snapshot is retained and audited but never used in a closing-balance calculation. If multiple verified snapshots share the latest eligible date, the closing balance is withheld as conflicting. A later unique verified snapshot can supersede an older snapshot.
- ADMIN and ACCOUNTANT can create opening snapshots with an evidence description and an explicit verification attestation. Snapshot creation is company-scoped and audited. VIEWER can read reports but cannot create snapshots.
- Monthly charts convert Decimal values to float only at the plotting boundary; all authoritative KPI, ranking and comparison calculations remain Decimal.

Phase 5 exit requires automated tests for filter scope, Decimal and currency reconciliation, monthly buckets, rankings, equal-length comparison windows, snapshot selection/conflicts and role/audit controls. Browser smoke testing remains a separate release check.


## Phase 5 delivery report — 2026-11-09
**Status: automated implementation and CI PASS; manual browser validation remains open.**

Implemented:
- Company-scoped DashboardService filters for inclusive date range, optional currency, account, category and direction.
- Only validated, non-deleted transactions enter the dashboard.
- Decimal inflow/outflow/net totals and monthly cash flow, partitioned by currency.
- Top-10 outflow categories and counterparties per currency.
- Comparison with the immediately preceding contiguous interval of equal length.
- Conditional closing balance from the latest unique verified account/currency opening snapshot; missing/conflicting evidence or incompatible filters yields Unavailable.
- AccountSnapshotService with role authorization, Decimal validation and audit; provisional snapshots are excluded from balances.
- Streamlit controls, currency-separated KPIs/charts/rankings, period comparison and snapshot entry.

Automated evidence: commit \`62eb759f2c5c480a7b7385d6939d1d7377bc398e\`, PR #6 CI run \`42637974318\`, Python 3.11/3.12/3.13 each passed Ruff, 120 tests, Alembic upgrade/check/downgrade/re-upgrade and SQLite foreign_key_check.

**Still open:** manual browser testing of filter changes, charts, snapshot creation and balance unavailability states; independent security review; concurrency-safe DB uniqueness for duplicate snapshot submissions. The service checks duplicates and the report withholds balances for multiple latest-date snapshots, but the initial schema does not include a unique snapshot key.


## Phase 6 implementation details — 2026-11-09
- CSV and PDF exports consume the exact \`DashboardFilters\` used by the dashboard and re-resolve \`CompanyContext\` and \`Permission.EXPORT\` inside the service.
- Exports include only validated, non-deleted transactions; currency is retained per row and is never converted/combined.
- Export row reads are capped in SQL at 10,001 before applying the 10,000-row safety limit, avoiding unbounded materialization for oversized exports.
- CSV output uses UTF-8 with BOM and CRLF. User-controlled text fields are prefixed with an apostrophe when a spreadsheet formula prefix (=, +, -, @) appears after whitespace/control characters (spaces, tabs, CR/LF, vertical tab, form feed, NUL or BOM).
- PDF output uses ReportLab with escaped company/transaction text and wrapped cells; includes selected filters, per-currency cash-flow summary and filtered transaction detail.
- Export preparation emits an \`AuditEvent\` (\`EXPORT_CSV_PREPARED\` / \`EXPORT_PDF_PREPARED\`) containing only format, generated filename, row count and filters; no transaction payload is copied into audit metadata.
- Import history is read-only, company-scoped and paginated at the service layer. It exposes batch status/counters and source row/page/table provenance, raw/normalized values, issues and review outcome.
- Audit history is read-only and company-scoped. It is available only to ADMIN/ACCOUNTANT; the UI displays event metadata and does not render before/after payloads.
- VIEWER may export and inspect import history, but cannot inspect the audit log. No schema migration is required.

## Phase 6 remaining validation
Automated tests cover CSV formula injection, dashboard filter reuse, tenant isolation, viewer export permission, row limits, valid PDF generation/content, batch/row provenance, audit pagination and authorization. Post-merge CI run `42647921772` on main commit `bead79a0cb5930cd6e63eb5674ab9c2a91a3ef15` passed Ruff, 136 tests, Alembic round-trip and SQLite foreign_key_check on Python 3.11/3.12/3.13. Manual browser visual validation and independent security review remain outstanding.


## Phase 6 CI follow-up — 2026-11-09
The merged Phase 6 commit was followed by a matrix run that exposed a UI smoke assertion mismatch: the automated test expected an explicit "Audit trail" subheader while the interface rendered the label as bold Markdown "Audit history". The 135 other tests passed on all tested Python versions; this follow-up makes the audit heading explicit and retains the smoke-test expectation. It also removes Ruff UP012 in the export state-key hashing expression. Revalidation is required on the exact follow-up PR head.


## Phase 6 CI evidence on follow-up PR — 2026-11-09
- PR #8 was merged at \`83505c16d5bc71cc194e06ce92ff8a871967a602\` while its first merged-head CI did not pass. A subsequent matrix run exposed UI heading expectation and test-fixture expectation defects; the follow-up PR #10 corrects them and removes Ruff UP012 in \`app.py\`.
- Follow-up head \`e016434ce5a1fe0cf447f184cee1701e532bbd67\`, GitHub Actions run \`42647719755\`: Python 3.11, 3.12 and 3.13 all pass Ruff, 136 tests, Alembic upgrade/check/downgrade/re-upgrade and SQLite foreign_key_check.
- This is automated branch evidence. The merged \`main\` remains at the earlier Phase 6 commit until follow-up PR #10 is merged.

## Phase 7 implementation — 2026-11-09
- Synthetic dataset service defines three fictional SME profiles: retail, professional services and light manufacturing; each covers 12 calendar months in XAF with quarterly USD bank fees.
- Each company imports 100 valid rows plus four intentional noisy rows: one existing-reference duplicate within the file, one invalid amount and two identical reference-less rows that must remain REVIEW.
- Expected per-company classification: 100 VALID, 1 INVALID, 1 DUPLICATE and 2 REVIEW; explicit partial confirmation imports only the 100 valid rows. Expected aggregate: 300 transactions across three companies and 312 staged source rows.
- Each demo company receives deterministic categories/rules and verified opening snapshots for separate XAF and USD accounts. No currency conversion or cross-company aggregation is used.
- \`scripts/generate_synthetic_data.py\` creates a separate, new SQLite file only; it requires \`--confirm-synthetic-only\`, refuses \`APP_ENV=production\`, requires a new filename containing \`synthetic\` or \`demo\`, refuses existing destinations and prompts for an ADMIN password (only a hash is stored).
- \`scripts/sqlite_backup_restore.py\` uses SQLite's online backup API, verifies \`integrity_check\`, \`foreign_key_check\` and required SME tables, calculates SHA-256 and publishes a temporary copy atomically. Existing backup files are not overwritten unless \`--overwrite\` is passed. Restore requires \`--replace-existing\` to replace an existing target.
- Backup files contain account/user/session information and password hashes; protect them as confidential data and encrypt the storage volume or backup destination. The utility does not encrypt backup contents itself.


## Phase 7 automated implementation evidence — 2026-11-09
- Synthetic data generator and service implemented for retail, professional-services and light-manufacturing SMEs. Per company, the preview must classify exactly 100 valid rows, one invalid amount, one referenced duplicate and two reference-less REVIEW rows; explicit partial confirmation imports only the 100 valid rows.
- The integration test verifies three demo companies, 12 distinct transaction months per company, 300 total transactions, 312 staged source rows, category assignment, separate XAF/USD accounts and verified snapshots, held-row non-linkage and import audit.
- SQLite backup/restore tests exercise the online backup API, integrity and foreign-key checks, required schema validation, SHA-256 evidence, no-overwrite default, explicit backup overwrite, explicit restore replacement, backup preservation and invalid-source rejection.
- GitHub Actions run \`42651239061\` on branch head \`4687979753a7f6f4f444f2b541eac965a6d3cd2c\` passed Ruff, 142 tests, Alembic round-trip and SQLite foreign_key_check on Python 3.11, 3.12 and 3.13.
- The evidence validates services and integration tests. Manual execution of the interactive generation CLI, browser visual QA and independent external security review remain separate validation tasks.


Post-rebase CI is required on the new exact branch head before Phase 7 can be considered merge-ready.
