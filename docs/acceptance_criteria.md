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
| AC-01 | BLOCKED | Not run — implementation awaits approval | Valid import and counts | Not observed | No application code yet |

## Definition of Done
All required criteria PASS with reproducible evidence; no P0/P1 issue; clean-clone README works; limits documented; no fake integration or inert control presented as operational.


## Decision addendum — 2026-11-09
Add required acceptance tests: (1) soft delete preserves DB row, import provenance and audit; removes transaction from default list/dashboard/export; restore, if approved, is authorized and audited. (2) ambiguous import row is staged as REVIEW, excluded from KPIs and transaction table until resolved; review decision records actor/time/reason; preview clearly distinguishes review from invalid/duplicate. (3) workspace member can access each authorized company but cannot access a company outside the workspace; all roles are tested across multiple companies. (4) if partial commit is approved, valid rows commit atomically while review rows remain staged. These criteria remain BLOCKED until implementation and test evidence exist.