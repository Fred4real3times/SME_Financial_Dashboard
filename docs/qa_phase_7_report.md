# Phase 7 — Internal QA report

**Date:** 2026-11-09  
**Reviewed implementation commit:** `a471b888bd4ad42cc07cec0502fccbb39d733d39`  
**GitHub Actions run:** [42660405294](https://github.com/Fred4real3times/SME_Financial_Dashboard/actions/runs/42660405294)  
**Status:** Automated acceptance PASS; release acceptance remains BLOCKED.

> This is an internal implementation and test-evidence review. It is not an independent security audit, penetration test, or manual browser visual inspection.

## 1. Scope reviewed

- Three-profile synthetic SME dataset generation through the normal workspace, category/rule, import preview and explicitly confirmed partial-commit services.
- SQLite online backup and restore operations, including path safety, atomic publication, explicit overwrite controls, integrity checks, foreign-key checks and application-schema validation.
- Integration tests, CI matrix evidence and documented operational limitations.

## 2. Automated evidence

The exact reviewed code commit passed GitHub Actions run **42660405294**:

| Check | Python 3.11 | Python 3.12 | Python 3.13 |
|---|---:|---:|---:|
| Ruff lint | PASS | PASS | PASS |
| Unit/integration tests | 143 passed | 143 passed | 143 passed |
| Alembic upgrade/check/downgrade/re-upgrade | PASS | PASS | PASS |
| SQLite foreign-key check | Clean | Clean | Clean |

CI job evidence:
- Python 3.11: [job 129310127678](https://github.com/Fred4real3times/SME_Financial_Dashboard/actions/runs/42660405294)
- Python 3.12: [job 129310127674](https://github.com/Fred4real3times/SME_Financial_Dashboard/actions/runs/42660405294)
- Python 3.13: [job 129310127063](https://github.com/Fred4real3times/SME_Financial_Dashboard/actions/runs/42660405294)

## 3. Acceptance results

| ID | Result | Evidence |
|---|---|---|
| SYN-01 | PASS | Three fictional companies share one generated workspace and are marked demo-only. |
| SYN-02 | PASS | Each company has 100 committed transactions across 12 months; XAF and USD remain separate. |
| SYN-03 | PASS | Per company: 100 valid, 1 invalid, 1 duplicate and 2 REVIEW source rows; held rows are not linked to transactions. |
| SYN-04 | PASS | Company-specific categories/rules assign primary categories; two verified opening snapshots use separate currency accounts. |
| BAK-01 | PASS | Online backup/restore validation checks SQLite integrity, foreign keys and the complete ORM-mapped application schema. |
| BAK-02 | PASS | SHA-256 reporting and no-overwrite-by-default behavior are integration-tested. |
| BAK-03 | PASS | Restore requires explicit replacement and preserves the source backup. |
| BAK-04 | PASS | Regression test rejects a file containing only the former four core table names and missing other mapped application tables. |

## 4. Review finding resolved

The initial backup validator required only `alembic_version`, `users`, `companies` and `transactions`. That could accept an incomplete SQLite file missing other required application tables.

**Correction:** the validator now derives the required application-table set from SQLAlchemy's mapped metadata and adds the Alembic version table. A regression test verifies that an incomplete file is rejected and no destination backup is published.

## 5. Security and operational observations

**Controls confirmed by code and automated tests**
- The synthetic generator requires explicit synthetic-only confirmation, refuses `APP_ENV=production`, rejects existing or symbolic-link destinations, and checks that the output does not equal the configured SQLite database path.
- Generated records are fictional and flow through application services instead of being inserted directly as transactions.
- Invalid, duplicate and ambiguous reference-less rows remain held; only valid rows are committed after explicit partial-import confirmation.
- Backup creation uses SQLite's online backup API, a temporary file in the destination directory and guarded publication. Existing files are not replaced without an explicit flag.
- Restore validates the source and destination result; replacing an existing target requires an explicit flag.
- The helper reports a SHA-256 digest and attempts restrictive file permissions where supported.

**Residual risks and limitations**
1. Backup contents are not encrypted by the helper. They contain financial and authentication data; the destination volume or backup file must be encrypted and access-controlled externally.
2. File-permission hardening is best-effort; Windows ACLs and the actual storage location must be checked operationally.
3. The restore command cannot establish whether the running Streamlit process still has the target database open. Stop the application before restoring.
4. The interactive synthetic-data CLI has not been manually executed in a clean Windows/WSL environment. Integration tests cover the service and database behavior, not every terminal interaction.
5. Headless Streamlit `AppTest` coverage exists, but it does not replace manual browser visual QA of layout, navigation and real user interaction.
6. No independent external security review or penetration test has been performed.
7. The application remains a local-first, single-instance SQLite MVP. Public exposure and concurrent hosted deployment are not approved. The parser worker has a 30-second wall-clock deadline but is not an OS sandbox and has no memory quota.

## 6. Release decision

**Phase 7 automated QA: PASS.**  
**Phase 7 release acceptance: BLOCKED** until:
- the synthetic-data CLI and backup/restore flow are exercised in a clean Windows or WSL environment;
- manual browser visual/workflow QA is completed;
- an independent security review is completed and any in-scope high/critical findings are closed.

Do not treat the green CI matrix as proof that these manual or independent checks have been performed.

## 7. Phase 8 release-hardening verification

**Candidate commit:** `118b367dc5784c5990a68590a05b08ab5800bbca`  
**GitHub Actions:** [run 42670094234 — all jobs successful](https://github.com/Fred4real3times/SME_Financial_Dashboard/actions/runs/42670094234)

| Platform | Test suite | Ruff | Alembic round-trip | SQLite FK check |
|---|---:|---:|---:|---:|
| Linux / Python 3.11 | 148 passed | PASS | PASS | Clean |
| Linux / Python 3.12 | 148 passed | PASS | PASS | Clean |
| Linux / Python 3.13 | 148 passed | PASS | PASS | Clean |
| Windows / Python 3.11 | 148 passed | PASS | PASS | Clean |

The run includes the new partial unique index for verified opening snapshots, its duplicate-insert regression test, parser worker timeout tests, Windows SQLite backup/restore tests, and the new migration upgrade/check/downgrade/re-upgrade sequence.

**Phase 8 automated hardening: PASS on the candidate commit.** This is not manual browser acceptance, WSL2 installation evidence or an independent security review.

## 8. Updated release decision

**Automated candidate CI: PASS.**  
**Release acceptance: BLOCKED** until:
- clean Windows and WSL2 installation and interactive synthetic-data CLI execution are recorded;
- manual browser visual/workflow QA is completed;
- backup and restore are manually exercised on the candidate database;
- an independent security review is completed and any in-scope high/critical findings are closed.

Do not treat successful Windows CI as proof that a user has completed the clean-clone Windows acceptance run, nor treat the CI matrix as an independent security audit.
