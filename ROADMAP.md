# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Delivery Focus

Make the dashboard the trustworthy daily home it should be — fix data visibility bugs, improve layout density and section priority, and ensure the hero reflects real workspace state — while transaction clearing status ships in parallel on a separate branch.

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
2. ~~**Transaction clearing status**~~ — shipped.
3. **Overview dashboard facelift** — fix data bugs (balance sheet card non-functional, hero CTA ignoring workspace state), reorder sections to prioritize recent activity, and compress layout to reduce scroll depth. See active `TASK.md`.
4. **Transaction editing** — deferred. See Deferred for Now.

### Feature 1: Manual Entry + Import Matching ✓

Shipped. See git history for implementation details.

### Feature 2: Transaction Clearing Status

Shipped. See git history for implementation details.

### Feature 3: Overview Dashboard Facelift

- Balance sheet card is non-functional: shows 0 tracked accounts despite $19K in tracked balances. The dashboard API builds `balances` from `config.tracked_accounts` but the data path is broken.
- Hero CTA shows "Open setup" after setup is fully complete with months of imported data. The reactive declaration computes stale state.
- Recent activity and category trends — the most actionable daily-use sections — sit ~1400px below the fold, buried under structural summary content.
- Snapshot band duplicates figures shown in the hero and cash flow sections.
- Cash flow section is vertically expensive: 6 months of double-bar rows consume ~900px.
- Coverage strip in the hero shows setup/accounts metrics that compete with financial summary.

### Constraints

- Preserve the existing `new` / `duplicate` / `conflict` import model.
- Keep `workspace/` canonical and `.workflow/` disposable.
- Keep transfer-resolution logic, import-identity generation, and journal writes in backend services.
- Hide transfer-clearing and journal-file details from default UI copy.
- Fail closed when the system cannot safely protect against future duplicate imports.
- The `:manual:` tag is standard ledger metadata — no custom extensions to the format.

## Deferred for Now

These are valid ideas, but they are not current priorities:

- Transaction editing — users can edit any transaction (imported or manual): payee, date, posting amounts, splits (add/remove/rebalance postings), and user metadata (tags, KV pairs, comments). System metadata stays hidden. Full split management from the first pass. `--strict`-style validation at the UI layer.
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
