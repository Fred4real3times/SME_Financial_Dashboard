# SME Financial Dashboard

A local-first MVP that turns SME bank statements and sales/expense exports into traceable cash-flow management information. It is **not** certified accounting software and does not replace statutory books, tax advice or a bank statement.

## Approved MVP boundaries

- Input formats: CSV, XLSX and text-based/digital PDF statements.
- PDF extraction uses text/table extraction only. Scanned/image-only PDFs, OCR, encrypted PDFs and embedded-file extraction are out of scope for the MVP.
- Positive `Decimal` amounts with explicit `INFLOW` / `OUTFLOW` direction.
- No automatic FX conversion; figures are partitioned by ISO 4217 currency.
- Workspace membership supplies one role (`ADMIN`, `ACCOUNTANT`, `VIEWER`) uniformly across companies in that workspace.
- `ADMIN` and `ACCOUNTANT` can soft-delete transactions with a reason; only `ADMIN` can restore.
- Ambiguous import rows remain in `REVIEW`. After explicit confirmation, valid rows may be committed while review rows remain staged.
- One primary category per transaction.
- Closing balance is unavailable without a reliable opening snapshot.

See `docs/` for the approved scope, architecture, data dictionary, threat model and acceptance criteria.

## Requirements

- Python 3.11, 3.12 or 3.13
- Windows 10/11, Linux or WSL2
- SQLite for the local single-instance MVP

## Windows PowerShell setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
Copy-Item .env.example .env
# Generate a local signing secret and paste it into SESSION_SECRET in .env:
python scripts/generate_session_secret.py
python -m pip install -e .
```

For WSL/Linux, replace venv activation with `source .venv/bin/activate` and copy `.env.example` to `.env`.

## Database

The default database URL is `sqlite:///./.data/sme_financial_dashboard.db`. The directory is created automatically. Apply schema migrations with:

```bash
alembic upgrade head
```

## Tests and lint

```bash
pytest
ruff check .
ruff format --check .
```

## Current implementation status

Phase 1 foundation includes project metadata, exact dependency pins, environment configuration, money-domain primitives, SQLAlchemy models, SQLite session factory, workspace RBAC/company scope, company-scoped repositories, an Alembic initial migration and foundation tests.

Phase 2 adds first-run ADMIN bootstrap, Argon2id password hashing, HMAC-signed session tokens backed by revocable database sessions, workspace/company creation, membership and role management, and an authenticated Streamlit shell. Import adapters, transaction services, dashboards and exports remain later vertical phases. A passing foundation or Phase 2 test suite does not mean the end-to-end MVP is complete.

## Security notes

- Do not place bank passwords, PINs, API keys or real customer data in the repository.
- `.env` and local database files are ignored by Git.
- Uploaded content is untrusted. Parsers must be bounded, and PDF actions/macros are never executed.
- SQLite has no row-level security. Every application query must enforce server-side company scope. Hosted/concurrent deployment requires PostgreSQL and a separate security review.


## First run and authentication

1. Apply migrations: `alembic upgrade head`.
2. Generate a unique local secret: `python scripts/generate_session_secret.py`.
3. Put the generated value in `.env` as `SESSION_SECRET=...`. Never commit `.env`.
4. Start the app: `streamlit run app.py`.
5. On an empty database, create the one-time first ADMIN and its workspace. The initial setup endpoint is then permanently closed by a singleton database record.
6. Sign in. The ADMIN can create companies and manage members/roles from Workspace Management.

Sessions are opaque HMAC-SHA256 signed tokens held in Streamlit server-side session state and backed by revocable database records. They expire after `SESSION_TTL_HOURS` (default 12 hours); logout revokes the current session. This is not an external SSO or persistent browser-cookie integration. In production, use a unique secret of at least 32 characters and protect the host/database.


## Statement import (Phase 3)
The import workflow accepts CSV, XLSX and digital/text-based PDF statements. Uploads are capped at 10 MiB both in Streamlit and in the parser; XLSX archives at 1,000 entries, 50 MiB expanded size and 200:1 compression ratio; PDF files at 100 pages, 50 tables per page, 250,000 extracted characters per page and 5,000,000 per document; and imports at 10,000 rows / 100 columns. CSV delimiter/encoding, XLSX worksheet, date format, decimal and thousands separators and direction convention are explicitly selected. XLSX formula cells are rejected; macros are not run. Scanned/image-only or encrypted PDFs are unsupported (no OCR).

The preview stores sanitized staging rows only. No financial transaction is created until the user confirms the import. A separate partial-import confirmation is required when invalid, duplicate or REVIEW rows are present. Only valid rows are committed; ambiguous reference-less matches remain in REVIEW. Imported amounts are Decimal, positive, and never automatically converted between currencies.


### Verification snapshot
Phase 3 branch head 64e50231bf228e251fb529b20655b89eba62b6cf passed GitHub Actions run 42621129042 on Python 3.11, 3.12 and 3.13 (76 tests per version, Ruff and migration round-trip). The branch is delivered as draft PR #2 stacked on Phase 2; it is not merged into main. Manual browser smoke testing remains part of final QA.


### Phase 3 QA hardening
CSV rows are streamed; XLSX ZIP entry, expanded-size, compression-ratio and column limits are checked; PDF encryption, table widths, page/table/row/character bounds are checked. SQLite duplicate lookups are chunked and transaction commits batch inserts before linking staged source rows. The parser has no hard wall-clock CPU timeout and is intended for the local single-instance app only, not a public upload endpoint.


## Categories, rules and manual import review (Phase 4)
Transactions support one primary category. Rules match description keywords, counterparty or reference; higher numeric priority wins, while equal top-priority matches remain unclassified for manual attention. A manual category assignment is audited and is not overwritten by rules. Confirmed imports apply applicable rules in the same transaction as the import.

Ambiguous import rows stay in the REVIEW queue until an ADMIN or ACCOUNTANT records a decision. A corrected acceptance requires a reviewer note and a unique manual reference. The original source fingerprint is retained so re-importing the same reference-less row returns to REVIEW rather than silently inserting it again.


### Current integration and verification snapshot — 2026-11-09
- Phase 3 import engine, Phase 4 categorization/manual REVIEW, and the Ruff correction are integrated into \`main\`.
- Current main commit at this snapshot: \`41cf26cb5231ceb3e540f402fb9b944048a2315e\`.
- Post-merge GitHub Actions run [42634994455](https://github.com/Fred4real3times/SME_Financial_Dashboard/actions/runs/42634994455) passed on Python 3.11, 3.12 and 3.13; each matrix job passed Ruff, 110 tests, Alembic round-trip and SQLite foreign_key_check.
- Manual browser-based Streamlit smoke testing and independent external security review remain outstanding.
- Phase 5 dashboard work is in progress. The dashboard excludes soft-deleted and unvalidated transactions, keeps Decimal calculations per currency, and only displays closing balance when a unique verified account/currency opening snapshot supports it.


### Phase 5 dashboard verification — 2026-11-09
The Phase 5 dashboard branch head \`62eb759f2c5c480a7b7385d6939d1d7377bc398e\` passed GitHub Actions run [42637974318](https://github.com/Fred4real3times/SME_Financial_Dashboard/actions/runs/42637974318): Python 3.11, 3.12 and 3.13 each passed Ruff, 120 tests, Alembic upgrade/check/downgrade/re-upgrade and SQLite foreign_key_check. PR #6 remains a draft. Manual browser smoke testing and independent security review remain open.


### Phase 6 — Exports and history (implementation in progress)
The Phase 6 branch adds filtered CSV/PDF export, spreadsheet-formula neutralization, company-scoped import batch/row history and restricted audit history. Exports reuse the exact dashboard filters and include only validated, non-deleted transactions. Automated verification and release status will be recorded after the branch-head CI completes.


### Phase 6 automated verification — follow-up branch
Follow-up PR #10 [fixes the Streamlit history headings and CI/test expectations](https://github.com/Fred4real3times/SME_Financial_Dashboard/pull/10). Its tested commit \`e016434ce5a1fe0cf447f184cee1701e532bbd67\` passed GitHub Actions run [42647719755](https://github.com/Fred4real3times/SME_Financial_Dashboard/actions/runs/42647719755): 136 tests per Python 3.11/3.12/3.13 matrix job, Ruff, Alembic round-trip and SQLite foreign_key_check. This evidence is on the follow-up branch and does not alter main until PR #10 is merged. Manual browser visual testing and independent external security review remain open.
