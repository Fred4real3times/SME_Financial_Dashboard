# User Flows — SME Financial Dashboard
**Status:** DRAFT

## Roles
ADMIN manages workspace/company/members and all finance functions. ACCOUNTANT imports, manages categories/rules, corrects transactions, views and exports. VIEWER reads dashboard/transactions and exports. Permissions are checked in services, not only hidden in UI.

## Flow 1 — Workspace and company
Authenticate/local first-run admin setup → create workspace/company → set timezone and display currency → grant membership/role → select authorized company. Reject duplicate/invalid names and unauthorized company IDs. Audit administrative changes.

## Flow 2 — Import and map
Select company → upload CSV/XLSX/PDF → enforce file type, signature, size and content limits → preview bounded sample without DB writes → select worksheet if XLSX; for PDF, extract text/tables page by page and show page provenance → map date, amount, currency and direction (or explicitly configure signed amount) → configure date and decimal separators → validate rows → classify BLANK/INVALID/DUPLICATE/VALID/VALID_WITH_WARNING/REVIEW → show separate counts → explicitly confirm partial import → atomically commit valid unambiguous rows while REVIEW rows remain staged → show imported/ignored/rejected/review/warning counts.

Failures: unsupported/oversized/corrupt file, missing mappings, ambiguous parsing, all rows invalid or DB failure. Failed commit rolls back.

## Flow 3 — Categorize and correct
Apply active rules by descending priority. A unique highest-priority match assigns category and rule provenance. No match or tied top priority remains for review. Accountant changes category; service validates transaction/category company ownership; before/after change and actor are audited; dashboard recalculates.

## Flow 4 — Dashboard
Choose date range, currency, category and direction filters → show inflows, outflows, net flow, monthly trend, top expense categories/counterparties and comparison period. Closing balance shown only when a coherent opening snapshot exists for same company/account/currency. Distinguish zero from unavailable.

## Flow 5 — Export
CSV/PDF uses same canonical filter contract and authorized company context. Include company, period, currency, generated timestamp and demo label. Escape formula-leading CSV cells. Audit export metadata, not full financial payloads.

## Flow 6 — History and audit
Company-scoped import batches, row issues and audit events; show file checksum, mapping, counts, status, actor and timestamp. Never expose another company's data.

## Invariants
Company context comes from authenticated membership; UI/session company IDs are untrusted. All reads, writes, dashboards, histories and exports are tenant-scoped. Corrections preserve original source provenance.


## Decision addendum — 2026-11-09
Ambiguous rows enter a review queue with reason codes and retained source row; no automatic acceptance. Confirmed unambiguous rows may be committed only through an explicitly previewed partial import, while ambiguous rows remain staged. Soft-deleted transactions disappear from normal lists and KPI/export totals but remain available in authorized history with actor/time/reason and full provenance. Workspace membership allows access to multiple companies; company selection is limited to companies in that workspace and all services enforce scope.

## Final owner decisions — 2026-11-09
Workspace membership carries one role uniformly across all companies in that workspace. ADMIN and ACCOUNTANT may soft-delete transactions with a reason; only ADMIN may restore. Partial import is allowed after explicit confirmation: valid rows commit while REVIEW rows remain staged and excluded from KPIs. Identical transactions without a distinguishing reference enter REVIEW. Each transaction has at most one primary category.

## PDF-specific import flow
For PDF, extract text/tables page by page, show page and table provenance, and allow manual field mapping after a bounded preview. Require explicit user confirmation before committing. Scanned/image-only pages, encrypted PDFs and unsupported or unstable layouts are reported with stable issue codes; they must not silently disappear from the batch summary or be converted into guessed transaction values. OCR is not part of the MVP.
