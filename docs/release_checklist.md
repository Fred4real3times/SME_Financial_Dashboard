# Phase 8 — Release readiness checklist

**Status:** Preparation/runbook only. This document does not declare the MVP released.  
**Target environment:** Clean Windows 10/11 or WSL2 installation, local single-instance use.  
**Data rule:** Use fictional/demo records only. Do not import real customer or bank data during this acceptance run.

## 1. Release boundary

The MVP is a local-first financial dashboard, not certified accounting software and not a production multi-user banking platform.

- SQLite is the supported local database for this release candidate.
- Do not expose the Streamlit process to the public internet.
- Do not enable real bank APIs, payment rails, money movement or FX conversion.
- PDF import is limited to digital/text-based statements. Scanned PDFs, OCR, encrypted PDFs and embedded-file extraction are out of scope.
- A cash closing balance is an estimated cash-management indicator supported by a verified opening snapshot; it is not profit.
- Backup files contain financial and authentication data and must be stored on encrypted, access-controlled storage.

## 2. Clean-clone installation — Windows PowerShell

Run from a new folder and a supported Python version (3.11, 3.12 or 3.13). The clone command checks out the current release-candidate branch, not the older `main` branch.

```powershell
git clone --branch feat/phase-7-qa-tooling https://github.com/Fred4real3times/SME_Financial_Dashboard.git
Set-Location SME_Financial_Dashboard

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

Copy-Item .env.example .env
python scripts/generate_session_secret.py
```

Paste the newly generated random secret into `.env` as `SESSION_SECRET`. Keep `.env` local and uncommitted. Set `APP_ENV=development` and use a local SQLite path. Never copy a production secret into the demo environment.

If PowerShell blocks activation, use a process-scoped execution-policy adjustment only for the current terminal; do not change the machine-wide policy.

## 3. Clean-clone installation — WSL2

Use a Linux filesystem path (for example, `~/projects`) rather than `/mnt/c` for the virtual environment and SQLite database where possible.

```bash
git clone --branch feat/phase-7-qa-tooling https://github.com/Fred4real3times/SME_Financial_Dashboard.git
cd SME_Financial_Dashboard

python3 --version   # Must be 3.11, 3.12 or 3.13
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

cp .env.example .env
python scripts/generate_session_secret.py
```

Put the generated random secret in `.env`, keep `APP_ENV=development`, and do not commit the file. Docker is not required for this local validation.

## 4. Baseline automated checks

From the activated virtual environment:

```bash
ruff check .
pytest -q
alembic upgrade head
alembic check
```

For a fresh database migration round-trip, use a disposable test database and follow the CI workflow; do not downgrade a database containing data you wish to retain.

The Phase 7 report records 143 passing tests on Python 3.11, 3.12 and 3.13 for the reviewed Phase 7 implementation. The release-hardening commit must independently pass the same matrix and migration round-trip before it is accepted.

## 5. Generate the synthetic demonstration database

From the repository root:

```powershell
python scripts/generate_synthetic_data.py --confirm-synthetic-only
```

The script prompts twice for a synthetic ADMIN password (12–128 characters). Use a unique demo password; do not reuse a real account password.

Expected output:
- One synthetic workspace and three demo companies: retail, professional services and light manufacturing.
- Twelve calendar months per company.
- Per company: 100 committed valid transactions, one INVALID row, one DUPLICATE row and two REVIEW rows.
- Aggregate: 300 committed transactions and 312 staged source rows.
- XAF and USD remain in separate accounts and are never added together.

After generation, set `DATABASE_URL` in the local `.env` file to:

```text
sqlite:///./.data/sme_financial_dashboard_synthetic.db
```

Keep `SESSION_SECRET` as a fresh local random value. The synthetic administrator email is `demo-admin@example.test`; sign in with the password entered during generation.

## 6. Start the application

With the synthetic database URL and local session secret configured in `.env`:

```powershell
streamlit run app.py
```

Open the local address printed by Streamlit. Do not configure public network binding for this acceptance run.

## 7. Manual browser acceptance checklist

Record PASS, FAIL or BLOCKED, the tester, date, browser/OS and evidence for each item. Do not mark an unexecuted test as PASS.

### Authentication, workspace and role boundaries

- [ ] First-run ADMIN can sign in; wrong password produces a generic failure.
- [ ] Logout and session expiry/revocation behave as expected.
- [ ] The synthetic workspace contains the three expected demo companies.
- [ ] An ADMIN can manage companies and members.
- [ ] ACCOUNTANT can perform permitted accounting/import tasks but cannot restore a soft-deleted transaction.
- [ ] VIEWER can read/export permitted reports but cannot import, categorize, delete, restore or inspect audit history.
- [ ] The workspace-wide role applies consistently to all companies in that workspace.
- [ ] Switching company never exposes another workspace's data.

### Import and review

- [ ] CSV upload: valid rows appear in preview; no transaction is written before confirmation.
- [ ] XLSX upload: worksheet selection and mapping work; formula cells/macros are not executed.
- [ ] Digital/text-based PDF upload: preview exposes extracted values and page/table/row provenance.
- [ ] Scanned/image-only, encrypted, malformed, wrong-signature and oversized files fail safely with a clear explanation.
- [ ] Date and decimal locale settings are explicit; ambiguous values are not guessed.
- [ ] Partial import requires a separate confirmation; only valid unambiguous rows commit.
- [ ] INVALID, DUPLICATE and REVIEW rows stay held and do not enter transaction totals.
- [ ] Identical rows without a distinguishing reference go to REVIEW.
- [ ] Corrected REVIEW acceptance requires a unique manual reference and creates an audit record.
- [ ] Confirmed duplicate and rejected review decisions are recorded with actor/time/note.

### Categorization, dashboard and exports

- [ ] Categories and deterministic rules assign one primary category only.
- [ ] Equal-priority rule conflicts remain unassigned for manual attention.
- [ ] Manual category corrections are audited and are not overwritten by automated rules.
- [ ] Date, currency, account, category and direction filters update the dashboard consistently.
- [ ] XAF and USD KPIs, charts, rankings and comparisons remain separate; there is no cross-currency total.
- [ ] Closing balance appears only when the required verified snapshot and compatible filter scope exist; otherwise it is unavailable.
- [ ] CSV and PDF exports match the dashboard filters and exclude REVIEW, unvalidated and soft-deleted rows.
- [ ] CSV text beginning with spreadsheet formula prefixes is neutralized.
- [ ] Import history retains source provenance; audit history is restricted to ADMIN/ACCOUNTANT and does not expose full sensitive payloads.
- [ ] Soft delete requires a reason; ordinary dashboard/export views exclude the transaction; only ADMIN can restore it.

### Backup and restore

Create a backup while the application is running (SQLite online backup):

```powershell
New-Item -ItemType Directory -Force .data\backups
python scripts/sqlite_backup_restore.py backup --source .data/sme_financial_dashboard_synthetic.db --destination .data/backups/sme-synthetic-backup.db
```

Stop Streamlit before restore. Test restoration to a new file first; do not replace the working demo database:

```powershell
python scripts/sqlite_backup_restore.py restore --backup .data/backups/sme-synthetic-backup.db --destination .data/backups/restore-validation.db
```

- [ ] Backup reports `integrity=ok`, zero foreign-key violations, file size and SHA-256.
- [ ] Restore to a new target succeeds and preserves the backup.
- [ ] Existing targets are not replaced without the explicit overwrite/replace flag.
- [ ] A restored copy can be opened and the expected workspace/companies can be read.
- [ ] Backup storage is encrypted and access-controlled outside the helper.

## 8. Security review gate

An independent reviewer should assess, at minimum:
- Company/workspace isolation and IDOR attempts across list, detail, dashboard, review, history and export endpoints.
- Service-level role enforcement, including ACCOUNTANT restore denial and VIEWER mutation denial.
- Password/session handling, session revocation, secret handling and log redaction.
- CSV/XLSX/PDF parser limits, malformed and adversarial files, PDF action/attachment handling and formula injection.
- Import atomicity, replay/fingerprint behavior, review-queue quarantine and audit immutability.
- Backup path handling, symlink/race considerations, file permissions, confidential backup handling and restore procedure.
- Dependency vulnerabilities and the local-only deployment boundary.

The report must identify findings by severity, provide reproducible evidence and verify remediation. This checklist is not itself a security audit.

## 9. Release evidence matrix

| Gate | Status at checklist creation | Required evidence |
|---|---|---|
| Automated CI on Phase 7 implementation | PASS | 143 tests per supported Python version; Ruff; Alembic round-trip; foreign-key check |
| Synthetic dataset integration tests | PASS | Three demo SMEs; 300 committed transactions; 312 staged rows |
| SQLite backup/restore integration tests | PASS | Integrity, foreign-key, schema, checksum and overwrite tests |
| Incomplete-schema backup rejection | PASS | Regression test in Phase 7 |
| Verified snapshot uniqueness | PENDING CI | Partial unique index and duplicate-insert regression test |
| Parser wall-clock limit | PENDING CI | Worker timeout, normal parse and stable error-code tests |
| Clean Windows installation | BLOCKED | Tester completes section 2 |
| Clean WSL2 installation | BLOCKED | Tester completes section 3 |
| Interactive synthetic CLI | BLOCKED | Manual execution and observed output |
| Full manual browser workflow and visual QA | BLOCKED | Completed section 7 with evidence |
| Manual backup/restore operation | BLOCKED | Completed section 7 backup checklist |
| Independent external security review | BLOCKED | Signed review with severity/remediation tracking |
| Final release approval | BLOCKED | All required gates PASS; no open P0/P1 findings |

## 10. Release decision rule

Do not release or publicly expose the application while any required manual or independent gate is BLOCKED. A passing CI matrix proves only the automated checks on the tested commit; it does not prove Windows/WSL installation, browser usability, operational restore readiness or independent security assurance.
