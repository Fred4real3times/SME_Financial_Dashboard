# Phase 3 QA Report — SME Financial Dashboard

**QA branch:** `feat/phase-3-qa-hardening`  
**Base:** `feat/phase-2-auth-workspace`  
**Scope:** CSV/XLSX/PDF parser, import preview and commit, tenancy, role checks, resource limits and transaction atomicity.

## Findings and fixes

| Finding | Risk | Remediation |
|---|---|---|
| CSV reader materialized all rows before checking 10,000-row ceiling | Resource exhaustion | Stream row iteration and stop at the row limit |
| Source columns / ZIP entries not sufficiently bounded | Resource exhaustion | 100-column and 1,000-entry limits |
| PDF short table rows were padded | Financial data misalignment | Require exact row/header width; reject ambiguous rows |
| Encrypted PDF surfaced as generic malformed input | Diagnostic / acceptance gap | Stable `PDF_ENCRYPTED` error |
| PDF extracted text and table counts lacked ceilings | Resource exhaustion | 100 pages, 50 tables/page, 250k chars/page, 5m chars/document |
| Fingerprint lookup could exceed older SQLite bind limits | Portability at batch scale | Query fingerprints in chunks of 500 |
| Per-row flush caused unnecessary DB round trips | Large batch performance | Batch transaction insert, flush, then link source rows |
| Same-preview retry / concurrent unique collision needed explicit evidence | Duplicate / partial-write risk | Idempotency and full rollback integration tests |

## Automated test coverage

- CSV signature/encoding/delimiter, streaming row ceiling, column ceiling, upload-size ceiling and malformed widths.
- XLSX worksheet selection, formula rejection, column ceiling, ZIP entry count, expanded-size and compression-ratio bounds.
- PDF text/table extraction and provenance, scanned-PDF rejection, encrypted-PDF error, page/table/row/column-width and character limits.
- Preview stages rows without inserting transactions.
- Explicit partial commit imports only valid rows; REVIEW rows have no transaction link.
- Referenced duplicates and reference-less ambiguous rows use the approved classifications.
- Viewer and forged cross-company contexts are denied.
- Repeated commit of the same preview is idempotent.
- Simulated concurrent fingerprint collision rolls back every transaction/link from that batch.
- 1,200-row preview exercises chunked fingerprint lookup.

## CI evidence

Final QA head `5471e5851c347237a7b1cebea15427d67770d24a`, run `42623635331`: all matrix jobs Python 3.11, 3.12 and 3.13 passed Ruff, 92 tests, Alembic migration round-trip and SQLite foreign-key integrity. The preceding code head `f94b6b1c9473b64a71ec13dbae3e194cc36b7c6e`, run `42623496040`, also passed 92 tests on all three Python versions.

## Residual / not performed

- Manual browser-based Streamlit smoke test has not been run.
- No external third-party penetration test has been performed.
- No hard wall-clock CPU timeout or automatic cleanup/expiry of abandoned PREVIEWED imports is implemented.
- The project remains a local-first single-instance MVP; public exposure is not approved by this QA report.
- Category/rule CRUD and manual REVIEW resolution are not part of the import-engine implementation.

**QA conclusion:** automated parser/service controls are materially hardened; full release acceptance remains open until latest CI and manual UI/security review are completed.
