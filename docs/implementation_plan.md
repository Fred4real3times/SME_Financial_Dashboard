# Implementation Plan — SME Financial Dashboard
**Status:** DRAFT — implementation starts only after architecture and data dictionary approval.

## Phase 0 — Baseline and contracts
Preserve existing files; initial repo contains README.md only. Review product scope, flows, architecture, dictionary, threat model and acceptance criteria. Resolve open decisions; freeze service contracts/schema. Exit: owner explicitly approves architecture.md and data_dictionary.md.

## Phase 1 — Domain and foundation
Create Python metadata, pinned dependencies, config and .env.example. Implement Decimal money, direction, cashflow, currency partition and filters. Write unit tests first. Add SQLAlchemy models, Alembic, repositories, company context and RBAC. Exit: domain tests pass and clean migration works.

## Phase 2 — Workspace, user and company
Local authentication/password hashing, first-run admin bootstrap, workspace/company/membership/roles and authorized company selector. Test roles and tenant boundaries.

## Phase 3 — Import vertical
CSV/XLSX template and mapping UI; preview; explicit parse settings; validation/classification; atomic batch/rows/transactions/audit commit; repeat import and rollback tests. Exit AC-01/02.

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