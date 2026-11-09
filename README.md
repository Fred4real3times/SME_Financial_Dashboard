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

The Streamlit UI, authentication lifecycle, import adapters, transaction services, dashboards and exports are implemented in later vertical phases. A passing foundation test suite does not mean the end-to-end MVP is complete.

## Security notes

- Do not place bank passwords, PINs, API keys or real customer data in the repository.
- `.env` and local database files are ignored by Git.
- Uploaded content is untrusted. Parsers must be bounded, and PDF actions/macros are never executed.
- SQLite has no row-level security. Every application query must enforce server-side company scope. Hosted/concurrent deployment requires PostgreSQL and a separate security review.
