# Yiriwa Business UI — design and implementation notes

## Visual direction

The supplied mobile prototype is the visual reference. The Streamlit application adopts its dark fintech direction while preserving the repository's existing backend and security model.

- Background: `#05070C`; primary surface: `#0B0F1A`; raised surface: `#131A2B`.
- Primary accent: neon green `#00E5A0`; positive movement: `#2BFFB3`; outflow/warning accent: coral `#FF5C72`.
- Supporting accents: blue `#4D8DFF` and violet `#8B5CF6`.
- Typography: Inter for interface copy and Space Grotesk for display figures, with system fallbacks.
- Cards use restrained borders, rounded corners, low-contrast gradients and tabular financial figures.
- Streamlit navigation tabs become the page-level navigation; the sidebar holds active workspace/company selection and session information.

## Screen mapping

| Prototype screen | Streamlit implementation |
|---|---|
| Accueil | Existing company-scoped financial dashboard |
| Transactions | New database-backed list of validated operations and selected-operation detail |
| Analyse | Included in the dashboard: monthly cash flow, period comparison, categories, counterparties and balance status |
| Virement | Not activated; no transfer or payment service exists in the approved MVP |
| Profil | Workspace, company and member-role administration |
| Import / history | Existing import, REVIEW, export and audit workflows in dedicated navigation tabs |

## Data integrity rules

- All transaction reads use `TransactionRepository.list_active` with a resolved active-company context.
- The transaction list displays validated, non-deleted transactions only.
- Currency values remain separated. The UI does not convert or add balances across currencies.
- The UI does not use the sample transactions embedded in the reference HTML.
- Payment execution, bank connectivity, external SSO and card management are not represented as working features.

## Screenshot files

The SVGs in `docs/screenshots/` are static interface previews. They are not screenshots captured from a running browser session. Replace them after visual QA on Windows and WSL2, retaining the same filenames to keep the README gallery links stable.
