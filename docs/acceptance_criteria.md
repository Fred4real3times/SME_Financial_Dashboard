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
EXP-01 CSV exactly filtered rows. EXP-02 PDF same company/currency/period/totals/filters. EXP-03 formula cells escaped. AUD-01 imports/corrections/rules/roles audited. AUD-02 source provenance retained. AUD-03 restricted audit views denied.

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
These criteria remain BLOCKED until CI/local test evidence for the Phase 2 branch is recorded.


## CI gate
A green GitHub Actions run for the tested commit is required before a phase is reported complete. The CI job must run the whole test suite, Ruff checks and fresh-database migration round-trip on each supported Python minor version.


## Phase 2 review note
The first CI run identified Ruff findings (unused imports, an unused test variable and a forward-reference annotation). These were corrected in the follow-up commit. The lint profile was narrowed to correctness/security-adjacent rules rather than enforcing import layout and line-length style at this stage.
