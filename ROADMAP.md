# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Delivery Focus

Make the dashboard the trustworthy daily home it should be — fix data visibility bugs, improve layout density and section priority, ensure the hero reflects real workspace state, and then connect dashboard insights to a filterable activity view so users can investigate what they see.

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
3. **Overview dashboard facelift** — fix data bugs (balance sheet card non-functional, hero CTA ignoring workspace state), reorder sections to prioritize recent activity, compress layout, and add stale-data awareness to the hero CTA. See active `TASK.md`.
4. **Dashboard drill-down and activity view** — make dashboard insights actionable by linking category trends and cash flow rows to a filterable cross-account activity view on the transactions page. See Feature 4 below.
5. **Transaction editing** — deferred. See Deferred for Now.

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

### Feature 4: Dashboard Drill-Down and Activity View

The dashboard surfaces insights — category spending spikes, negative cash flow months — but provides no path to investigate them. Category trend rows and cash flow month rows are visual dead ends. The transactions page only shows per-account registers with no date or category filtering, so even navigating there manually doesn't help.

This feature closes the gap between dashboard insight and transaction-level detail:

- **Clickable category trends**: each category row on the dashboard links to the transactions page filtered by that category and the current month. The `categoryTrends` API response already includes the raw `account` field needed as the filter key.
- **Clickable cash flow months**: each cash flow row links to the transactions page filtered to that month.
- **Cross-account activity view**: the transactions page gains an "all activity" mode alongside the existing per-account register. This mode shows transactions across all tracked accounts, with date range filtering (presets: this month, last 30 days, last 3 months, custom) and category filtering.
- **New backend endpoint**: a cross-account transaction query that accepts optional date-range and category filters. The existing `build_dashboard_overview` already queries all activity transactions — the new endpoint can share the same query infrastructure with filter parameters.
- **URL-param filter state**: filters are encoded in query params (`?category=Expenses:Shopping&period=2026-03`) so dashboard links work as deep links and the browser back button preserves filter state.

This is the minimum needed to make "What needs attention next?" actionable. Without it, every dashboard insight is a dead end.

### Constraints

- Preserve the existing `new` / `duplicate` / `conflict` import model.
- Keep `workspace/` canonical and `.workflow/` disposable.
- Keep transfer-resolution logic, import-identity generation, and journal writes in backend services.
- Hide transfer-clearing and journal-file details from default UI copy.
- Fail closed when the system cannot safely protect against future duplicate imports.
- The `:manual:` tag is standard ledger metadata — no custom extensions to the format.

## Standing Work: Incremental Refactoring

Large page components should be decomposed opportunistically — when a feature task touches a page that has a decomposition plan, perform the most relevant extraction step first, then build the feature on the cleaner foundation. No dedicated refactoring sprints; the cost is spread across feature work.

### Unknowns page decomposition

The review page (2535 lines, 50+ functions, 10+ concerns) is the highest-priority target. A step-by-step extraction plan is in [`plans/unknowns-decomposition.md`](plans/unknowns-decomposition.md). Each step is independently shippable and behavior-preserving. Expected outcome: page drops to ~900 lines with logic distributed across focused modules and components.

### Accounts configure page decomposition

The accounts configuration page (1807 lines) combines listing, editing, and CSV profile inspection. Plan: [`plans/accounts-configure-decomposition.md`](plans/accounts-configure-decomposition.md). 6 steps, expected outcome ~750 lines. Step 2 (`$lib/format.ts`) has cross-page value — it deduplicates formatting helpers shared with the transactions page.

### Import flow decomposition

The import flow component (1708 lines) renders two near-duplicate layouts (setup vs standalone) with interleaved workflow, preview, inbox, and history concerns. Plan: [`plans/import-flow-decomposition.md`](plans/import-flow-decomposition.md). 6–7 steps, expected outcome ~650 lines. Steps 5–6 (inbox + preview extraction) eliminate the template duplication.

### Transactions page decomposition

The transactions page (1442 lines) is the cleanest of the four — functional as-is. Plan: [`plans/transactions-decomposition.md`](plans/transactions-decomposition.md). 4 lightweight steps, expected outcome ~800 lines. Lower priority; becomes high-value before transaction editing lands.

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
