# Acceptance Criteria — SME Financial Dashboard
**Status:** DRAFT. Every criterion requires executed evidence; BLOCKED is never PASS.

## Required acceptance
| ID | Criterion | Evidence |
|---|---|---|
| AC-01 | Valid CSV imported; imported/ignored counts displayed | Workflow test + batch summary |
| AC-02 | Re-import strict duplicate does not insert twice | DB counts before/after |
| AC-03 | Category correction updates KPIs and is audited | Integration test for transaction/KPI/AuditEvent |
| AC-04 | Dashboard totals equal independent calculation | Independent Decimal control |
| AC-05 | Date/category filters work; CSV/PDF exports honor same filters | Compare export content with filtered service result |
| AC-06 | Company A cannot read/modify Company B transactions | Cross-tenant negative tests |

## Import
IMP-01 CSV template documented. IMP-02 XLSX worksheet selection. IMP-03 Missing required mapping blocks commit. IMP-04 Invalid date, nonnumeric amount, missing currency, blank row and malformed input have stable issue codes. IMP-05 Ambiguous locale requires explicit settings. IMP-06 Size/row limits. IMP-07 Failed commit atomic. IMP-08 Retry idempotent.

## Finance
FIN-01 Positive Decimal + direction. FIN-02 Correct inflow/outflow/net formulas. FIN-03 Currency partitioning. FIN-04 No opening snapshot => closing balance Unavailable. FIN-05 Snapshot coherent for company/account/currency. FIN-06 Correction refreshes KPI. FIN-07 Equivalent filters in period comparison.

## Categorization, exports and audit
CAT-01 keyword/counterparty/reference rules. CAT-02 deterministic priority. CAT-03 conflicting top priority flagged. CAT-04 correction records actor/time/before/after. CAT-05 cross-company category/rule rejected.
EXP-01 CSV contains exactly the validated, non-deleted rows matching the selected company/date/currency/account/category/direction filters — implementation and automated test added; CI pending.
EXP-02 PDF contains the same company, filters, per-currency totals and filtered transaction rows — implementation and automated test added; CI pending.
EXP-03 CSV formula-like text is escaped before opening in spreadsheet software — implementation and automated test added; CI pending.
AUD-01 imports, corrections, rules, role changes and export preparation are audited — export preparation events added; full action matrix continues to be tested.
AUD-02 import source provenance remains available through company-scoped ImportBatch/ImportRow history — history view/service added; automated tests pending CI.
AUD-03 audit history is restricted to roles with VIEW_AUDIT and cannot cross companies — implementation and automated tests added; CI pending.

## Security and operations
SEC-01 invalid/inactive authentication rejected. SEC-02 role matrix enforced in services. SEC-03 cross-tenant list/detail/correction/dashboard/audit/export denied. SEC-04 malformed/oversized files rejected safely. SEC-05 injection-like inputs harmless. SEC-06 no secrets or real bank data in repo/sample.
OPS-01 12 months synthetic data for commerce/services/distribution. OPS-02 deliberate duplicate, invalid date, inconsistent labels, missing amounts. OPS-03 reset and backup/restore documented/tested. OPS-04 clean-clone Windows/WSL README. OPS-05 all controls perform advertised action.

## Required test suites
Unit: Decimal calculations, parsing, fingerprint, categorization, filters. Integration: migrations, constraints, atomic import, tenant isolation, audit. Workflow: import/re-import/correction/dashboard/export. Security: roles, IDOR, formula injection, malformed uploads. Clean install and restore.

## Evidence matrix template
| ID | Status | Command/test | Expected | Observed | Evidence |
|---|---|---|---|---|---|
| AC-01 | BLOCKED | Not run — import vertical is Phase 3 | Valid import and counts | Not observed | Foundation only; no import workflow yet |

## Definition of Done
All required criteria PASS with reproducible evidence; no P0/P1 issue; clean-clone README works; limits documented; no fake integration or inert control presented as operational.


## Decision addendum — 2026-11-09
Add required acceptance tests: (1) soft delete preserves DB row, import provenance and audit; removes transaction from default list/dashboard/export; restore, if approved, is authorized and audited. (2) ambiguous import row is staged as REVIEW, excluded from KPIs and transaction table until resolved; review decision records actor/time/reason; preview clearly distinguishes review from invalid/duplicate. (3) workspace member can access each authorized company but cannot access a company outside the workspace; all roles are tested across multiple companies. (4) if partial commit is approved, valid rows commit atomically while review rows remain staged. These criteria remain BLOCKED until implementation and test evidence exist.

## Final owner decisions — 2026-11-09
Add mandatory acceptance criteria:
- AUTH-01 one WorkspaceMembership role applies uniformly across every company in the workspace; no company-specific override in MVP.
- DEL-01 ADMIN and ACCOUNTANT can soft-delete with reason; VIEWER cannot. DEL-02 only ADMIN can restore; ACCOUNTANT restore is denied. DEL-03 soft-deleted transaction and provenance remain stored/auditable and are excluded from default KPIs/lists/exports.
- IMP-09 explicit partial-commit confirmation commits valid rows atomically while REVIEW rows remain staged and excluded from KPIs. IMP-10 identical rows without distinguishing reference are REVIEW, not silently deduplicated. IMP-11 unresolved REVIEW rows have no committed Transaction record/link.
- CAT-06 exactly one primary category per transaction; split allocation is unsupported.
All criteria remain BLOCKED until implementation and evidence exist.

## PDF import — mandatory acceptance tests
- PDF-01 Valid synthetic digital/text-based PDF statement accepted; file type and page count recorded.
- PDF-02 Extracted candidates shown in bounded preview; explicit field mapping and confirmation required before commit.
- PDF-03 Every imported PDF row retains source page/table/row provenance.
- PDF-04 Scanned/image-only PDF detected and clearly reported unsupported in MVP; no false successful empty import or invented rows.
- PDF-05 Encrypted, malformed, wrong-signature, oversized and over-page-limit PDFs rejected safely with stable issue codes.
- PDF-06 Unclear table structure, split/merged values or ambiguous date/amount/direction staged as REVIEW or rejected with explicit reason; never guessed.
- PDF-07 PDF import obeys the same tenant isolation, role authorization, duplicate detection, Decimal validation, partial commit, audit and provenance rules as CSV/XLSX.
- PDF-08 PDF actions/scripts and embedded attachments are never executed or extracted.
All PDF criteria remain BLOCKED until automated tests and workflow evidence are produced.


## Foundation verification — Phase 1 evidence (not a substitute for product acceptance)
| Check | Status | Command / evidence |
|---|---|---|
| Decimal parsing and currency partitioning | PASS | Covered by unit tests |
| Workspace role permission matrix | PASS | Covered by unit tests |
| Membership-based company context | PASS | Cross-workspace and inactive-user negative tests |
| Company-scoped repository reads | PASS | Cross-company transaction cannot be returned |
| Database tenant constraints | PASS | Cross-company category and transaction links rejected |
| Soft-delete metadata / REVIEW invariants | PASS | Database check-constraint integration tests |
| Initial database migration | PASS | Fresh upgrade, Alembic check, downgrade and re-upgrade |
| SQLite foreign-key integrity | PASS | `PRAGMA foreign_key_check` returned no rows |
| Full foundation suite | PASS | `PYTHONPATH=src pytest -q` — 33 passed |
| Ruff lint/format | NOT RUN | Ruff executable not installed in the development session |

Product acceptance IDs AC-01..AC-06, IMP, FIN, CAT, EXP, AUD, SEC, OPS and PDF remain BLOCKED until their respective vertical workflows are built and tested. Foundation test success must not be represented as end-to-end MVP acceptance.


## Authentication and workspace management — mandatory acceptance tests
- AUTH-02 Bootstrap succeeds only once; first ADMIN, workspace, membership, BootstrapState and audit record are created atomically.
- AUTH-03 Passwords are stored as Argon2id hashes; wrong password and unknown email return the same generic error.
- AUTH-04 Session token signature, expiry, database record and revocation are validated; tampered, expired, revoked and inactive-user sessions are rejected.
- AUTH-05 Logout and password change revoke existing sessions.
- AUTH-06 Newly created member receives a one-time temporary password and must change it on first login.
- WS-01 Active user may create a workspace and becomes its ADMIN; the same user may belong to multiple workspaces with independent roles.
- WS-02 Only workspace ADMIN may create companies and manage memberships/roles.
- WS-03 Company creation validates currency format/timezone and records an audit event.
- WS-04 New user/member provision and role changes are audited; inactive membership loses access without physical deletion.
- WS-05 The last active ADMIN cannot be demoted or deactivated.
- WS-06 All workspace/company lists and company selection are membership-scoped and checked server-side.
Phase 2 CI evidence: PASS on commit 1dd3367d85c3f320d2685ab38f9885a55a2c3635, run 42619664693. Python 3.11, 3.12 and 3.13 each passed Ruff, 54 tests, Alembic round-trip and SQLite foreign_key_check.


## CI gate
A green GitHub Actions run for the tested commit is required before a phase is reported complete. The CI job must run the whole test suite, Ruff checks and fresh-database migration round-trip on each supported Python minor version.


## Phase 2 review note
The first CI run identified Ruff findings (unused imports, an unused test variable and a forward-reference annotation). These were corrected in the follow-up commit. The lint profile was narrowed to correctness/security-adjacent rules rather than enforcing import layout and line-length style at this stage.


## Phase 3 import engine — automated QA result
The import-engine automated acceptance tests are **PASS** on final QA branch head `5471e5851c347237a7b1cebea15427d67770d24a` (GitHub Actions run `42623635331`): Python 3.11, 3.12 and 3.13 each passed Ruff, the full test suite (92 tests), Alembic upgrade/check/downgrade/re-upgrade and SQLite foreign_key_check. Each matrix job also passed on the preceding code head `f94b6b1c9473b64a71ec13dbae3e194cc36b7c6e` (run `42623496040`).

- IMP-12: allowlist/signature, malformed/oversized input, streamed row limit, column limit, XLSX ZIP entry/expansion/compression controls and PDF page/row limits — automated tests.
- IMP-13: explicit CSV encoding/delimiter, XLSX worksheet, date format and decimal/thousands separators — automated tests and service validation.
- IMP-14: XLSX formula cells rejected; macros are never executed — automated test and code-level check.
- IMP-15: preview writes ImportBatch/ImportRow staging and audit only; no Transaction before confirmation — integration test.
- IMP-16: explicit partial confirmation commits only VALID/VALID_WITH_WARNING rows atomically; REVIEW/INVALID/DUPLICATE remain unlinked — integration test and forced fingerprint-collision rollback test.
- IMP-17: referenced duplicates are classified DUPLICATE; reference-less identical/matching rows are REVIEW — integration tests.
- IMP-18: PDF page/table/row provenance, scanned/image-only rejection, encryption rejection and ambiguous table-width rejection — automated tests.
- IMP-19: service-level role and CompanyContext checks reject VIEWER imports and forged cross-company contexts — integration tests.
- IMP-20: repeated commit of the same preview is idempotent; fingerprint lookup is chunked for large batches — integration tests.
- PDF-08: parser code only extracts PDF text/tables; no JavaScript/action execution or embedded-file extraction API is invoked — code-level review.

**Still BLOCKED / not performed:** manual browser-based Streamlit smoke test (login → upload → preview → confirm → verify transaction list) and third-party penetration/security review. These do not invalidate the passing automated backend/parser tests, but full release acceptance remains open until completed.


## Phase 4 categorization and review acceptance criteria — automated PASS
- CAT-07 Larger numeric priority wins; only a unique top-priority rule may assign a category — PASS, \`test_higher_numeric_priority_wins_and_repeat_application_is_idempotent\`.
- CAT-08 Equal highest-priority matches return NEEDS_REVIEW and do not auto-assign — PASS, \`test_tied_highest_priority_rules_require_manual_review\`.
- CAT-09 A manual category assignment is audited and not overwritten by rule application — PASS, \`test_manual_category_assignment_is_audited_and_not_overwritten_by_rules\`.
- CAT-10 Category kind must be BOTH or match the transaction's INFLOW/OUTFLOW direction — PASS, \`test_category_kind_must_match_transaction_direction\`.
- CAT-11 Confirmed imports apply company-scoped rules within the same atomic batch commit — PASS, \`test_confirmed_import_applies_unique_matching_category_rule\`.
- REV-01 Review queue is company-scoped and unavailable to VIEWER — PASS, \`test_review_queue_is_company_scoped_and_viewer_cannot_access\`.
- REV-02 Duplicate/reject decisions update status, reviewer, time, note and audit — PASS, \`test_review_resolution_can_confirm_duplicate_or_reject_with_audit\`.
- REV-03 Corrected acceptance validates values/manual reference and links the transaction — PASS, \`test_corrected_review_row_creates_transaction_with_manual_reference\` and negative validation tests.
- REV-04 Original source fingerprint is preserved and reference-less re-import returns to REVIEW — PASS, \`test_reference_less_row_reimport_after_manual_acceptance_returns_to_review\`.
- REV-05 Review decisions and corrected transactions are audited; batch counters/status are recomputed — PASS, integration review-resolution tests.
- REV-06 Repeated decisions and reference/fingerprint collisions are rejected without linking an invalid transaction — PASS, integration review-resolution tests.
- CI evidence: main commit \`41cf26cb5231ceb3e540f402fb9b944048a2315e\`, GitHub Actions run \`42634994455\`; Python 3.11/3.12/3.13 each passed Ruff, 110 tests, Alembic round-trip and SQLite foreign_key_check.
- **Still BLOCKED:** manual browser-based Streamlit smoke test and independent security review. Phase 4 automated backend/CI acceptance is PASS; full release acceptance is not closed.

## Phase 5 dashboard acceptance criteria — automated PASS
- DASH-01 Inclusive date/currency/account/category/direction filters are company-scoped and applied equally to current and comparison periods — PASS, dashboard filter integration tests.
- DASH-02 Only validated, non-deleted transactions are included; REVIEW/staged, deleted and unvalidated records are excluded — PASS, \`test_report_uses_decimal_and_keeps_currency_partitions_and_rankings_separate\`.
- DASH-03 Inflows, outflows and net cash flow use Decimal and remain partitioned by currency — PASS, independent XAF/USD expected-value assertions in the dashboard integration suite.
- DASH-04 Monthly cash flow emits month/currency buckets and direction totals — PASS, dashboard monthly aggregation tests.
- DASH-05 Top spending categories and counterparties rank outflows independently per currency — PASS, dashboard ranking integration test.
- DASH-06 Period comparison uses the immediately preceding equal-length interval and same non-date filters — PASS, \`test_comparison_uses_equal_length_previous_period_and_same_filters\`.
- DASH-07 Closing balance requires one account/currency, no category/direction subset and the latest unique verified snapshot — PASS, snapshot balance integration tests.
- DASH-08 Missing verified evidence and conflicting latest snapshots make the balance unavailable — PASS, \`test_balance_is_unavailable_without_required_scope_snapshot_or_unfiltered_flow\` and \`test_conflicting_latest_verified_snapshots_make_closing_balance_unavailable\`.
- DASH-09 Snapshot creation is company-scoped, role-authorized, Decimal-validated and audited; provisional snapshots do not affect balances — PASS, \`test_snapshot_creation_is_audited_company_scoped_and_validated\` and VIEWER denial test.
- DASH-10 Independent Decimal expected-value checks validate current totals and closing balance — PASS, dashboard reporting integration tests.
- CI evidence: branch head \`62eb759f2c5c480a7b7385d6939d1d7377bc398e\`, run \`42637974318\`; Python 3.11, 3.12 and 3.13 each passed Ruff, 120 tests, Alembic round-trip and SQLite foreign_key_check.
- **Still BLOCKED:** manual browser smoke test and independent security review. Concurrent duplicate opening-snapshot submissions are only guarded by the service lookup in this iteration; database-level uniqueness is a follow-up hardening item.


## Phase 6 export and history acceptance — implementation in progress
- EXPORT-01 Prepared CSV and PDF artifacts use DashboardFilters without broadening or changing the selected company or transaction scope.
- EXPORT-02 CSV formula neutralization covers cells beginning with spreadsheet formula prefixes (including leading whitespace/control characters).
- EXPORT-03 Export generation is audited with format, filter scope, filename and row count.
- HIST-01 Import history lists only the selected company's ImportBatch records and paginated source rows.
- HIST-02 Import history retains row status, source row/page/table provenance, issue codes and review-decision metadata.
- AUD-04 Audit trail displays company-scoped event metadata only; sensitive before/after JSON is not exposed in the current UI.
- EXPORT-04 CSV/PDF export is capped at 10,000 rows and rejects larger result sets with a clear error.
All Phase 6 criteria require a green CI run for the exact PR head; manual browser verification remains separate.
