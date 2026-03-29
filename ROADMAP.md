# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Delivery Focus

Give users full control over their financial data through the UI — transaction status visibility, transaction editing for corrections and metadata, and statement reconciliation — without sacrificing import safety or data trust.

### Current Status

- Transfer-specific flows are complete:
  - Unknown review supports direct transfers, pending import-match transfers, and automatic matching.
  - Grouped-settlement trust fix is shipped.
  - Guided manual resolution is shipped.
  - Bilateral auto-reconciliation is shipped (read-time detection, no journal writes).
  - Transfer suggestion matching works correctly after the CSV comment parsing fix.
- Import-time auto-linking (bypassing the unknowns review queue) was considered and rejected — it reduces trust by removing the human confirmation step. The current flow (import → review → confirm → auto-reconcile display) is the correct trust model.
- Manual transaction entry with import matching is shipped:
  - Users can add transactions from the register with a `:manual:` tag.
  - Unknowns review offers a "match" mode to match imports to manual entries.
  - Match quality ranking, amount-delta display, and metadata carryover are complete.

### Delivery Sequence

1. ~~**Manual transaction entry**~~ — shipped.
2. **Transaction clearing status** — parse the native ledger clearing flag (`*`, `!`, unmarked), display it in the register, and let users toggle it. Consolidates duplicated header-parsing regex across six services into a shared module.
3. **Transaction editing** — users can edit any transaction (imported or manual): payee, date, posting amounts, splits (add/remove/rebalance postings), and user metadata (tags, KV pairs, comments). System metadata stays hidden. Full split management from the first pass.

### Feature 1: Manual Entry + Import Matching ✓

Shipped. See git history for implementation details.

### Feature 2: Transaction Clearing Status

- The ledger format's native clearing flags (`*` cleared, `!` pending, unmarked) represent data provenance: `*` means bank-confirmed (imported from CSV), unmarked means manually entered, `!` means user-flagged for attention.
- The register displays a visible status indicator per transaction row, using plain-language tooltips ("Bank-confirmed", "Flagged", "Manual entry").
- Users can toggle status by clicking the indicator (cycles: unmarked → flagged → bank-confirmed → unmarked).
- Six duplicated `HEADER_RE` definitions across backend services are consolidated into a shared `header_parser.py` module.
- No changes to the import pipeline or manual entry pipeline — both already write the correct flags.
- Foundation for future statement reconciliation (which will use metadata, not the clearing flag).

### Feature 3: Transaction Editing

- Users can edit payee, date, and posting amounts on existing transactions.
- Full split management: add, remove, and rebalance postings. The UI enforces the zero-sum constraint interactively.
- User metadata: tags (`:vacation:`), KV pairs (`; project: kitchen-remodel`), and freeform comments are visible and editable.
- System metadata (import identities, transfer state, source hashes) stays hidden from the UI.
- `--strict`-style validation at the UI layer: autocomplete for accounts, tags, and metadata keys drawn from the journal; warn before writing unknown values. Preventive, not after-the-fact.

### Constraints

- Preserve the existing `new` / `duplicate` / `conflict` import model.
- Keep `workspace/` canonical and `.workflow/` disposable.
- Keep transfer-resolution logic, import-identity generation, and journal writes in backend services.
- Hide transfer-clearing and journal-file details from default UI copy.
- Fail closed when the system cannot safely protect against future duplicate imports.
- The `:manual:` tag is standard ledger metadata — no custom extensions to the format.

## Deferred for Now

These are valid ideas, but they are not current priorities:

- Settings interface for configurable parameters (e.g., match date window)
- Merchant management UI
- Expanding the rule language beyond the current limited matching model
- Debt-payment decomposition and richer liability servicing workflows such as principal-vs-interest splits, amortization guidance, and lender-specific debt management beyond pure transfer handling
- Declarative CSV import row rules for advanced conditional parsing or categorization, inspired by hledger-style `if` matching, unless they can be introduced without making account setup feel heavy or surprising
- Full budgeting system
- Zero-based/envelope budgeting workflow
- Long-range forecasting and goals
- Detailed FI planner with retirement-timeline modeling
- Statement reconciliation against print/PDF bank statements (will use metadata like `; reconciled: YYYY-MM-DD`, not the clearing flag)
- Advanced reconciliation features beyond the current safe-edit workflow
