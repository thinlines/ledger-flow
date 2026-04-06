# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Delivery Focus

Trust fix: journal mutations currently have no reliable undo mechanism. Matched manual entries are permanently lost on import undo, and the only safety net is scattered `.bak` files with no operation history. Current focus is an event-sourced undo stack: an append-only event log in the workspace, compensating events for reversal, drift detection for external edits, and a transaction actions menu with a semantic undo affordance. Git is demoted to periodic snapshot commits — an escape hatch, not the undo mechanism. See `DECISIONS.md` §12. Dashboard drill-down resumes after this sequence ships.

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
3. ~~**Overview dashboard facelift**~~ — shipped.
4. ~~**Dashboard polish**~~ — shipped (4a–4d: momentum line, day-grouped activity, per-account staleness, cash flow presets).
5. **Event-sourced undo** — trust fix. Five sub-features, shipped in order:
   - **5a. Archive journal for matched manual entries** — standalone data-loss fix. Active `TASK.md`.
   - **5b. Event log foundation** — append-only `workspace/events.jsonl`, event envelope, drift detection.
   - **5c. Git snapshot commits** — periodic workspace snapshots (shutdown + daily) as an escape hatch.
   - **5d. Transaction actions menu** — three-dot row menu: delete, re-categorize, unmatch. Each writes an event.
   - **5e. Semantic undo + toast** — compensating-event dispatcher, toast affordance, partial-undo report when drift is present.
6. **Dashboard drill-down and activity view** — clickable category trends + cash flow rows, cross-account activity view with filters. Paused until event-sourced undo ships.
7. **Transaction editing** — deferred. See Deferred for Now.

### Feature 1: Manual Entry + Import Matching ✓

Shipped. See git history for implementation details.

### Feature 2: Transaction Clearing Status

Shipped. See git history for implementation details.

### Feature 3: Overview Dashboard Facelift ✓

Shipped. Balance sheet data path fixed (`dashboard.balances` from `config.tracked_accounts`), hero CTA reactivity fixed (explicit Svelte dependencies), sections reordered (activity and trends above cash flow and balance sheet), snapshot band merged into hero stat chips, coverage strip removed, cash flow compressed to 3-month default with expand toggle, Today rail compacted to status line + CTA, stale-data awareness added (7-day threshold). See git history for implementation details.

### Feature 3b: Dashboard Polish ✓

Shipped. Momentum line replaces Net chip, recent activity day-grouped (5-item cap, linked review badges), per-account staleness and missing opening balance indicators in balance sheet (backend `lastTransactionDate`), cash flow segmented preset toggle (This month / Last 3 / Last 6). See git history for implementation details.

### Feature 5a: Archive Journal for Matched Manual Entries

When a manual entry is matched to an imported transaction during unknowns review, the manual entry is physically deleted from the journal today. If the import is later undone, the manual entry is gone for good. This is the acute data-loss bug behind the entire trust-fix sequence.

This feature stops deleting matched manual entries. Instead, the manual entry is moved to a dedicated `workspace/journals/archived-manual.journal` file (never `include`d in loaded journals, so `ledger` CLI ignores it) and stamped with a `match-id:` UUID. The matched imported transaction carries the same `match-id:` tag, establishing a reversible link that future unmatch operations will use.

Backend-only change. No UI. Standalone — does not depend on the event log or any other sub-feature. Delivers the data-preservation guarantee immediately. See active `TASK.md`.

### Feature 5b: Event Log Foundation

Append-only event log at `workspace/events.jsonl`. Each journal mutation emits an event with UUIDv7 id, `actor`, `type`, `summary`, `payload`, `journal_refs` (with `hash_before`/`hash_after`), and `compensates` link. Events are the primary causal record; journals remain canonical state.

Includes drift detection: pre-mutation and startup hash checks append `journal.external_edit_detected.v1` marker events when the journal was changed outside the app. Events are designed multi-user-ready (UUIDv7 for merge-friendly sorting, `actor` populated, file never rewritten) but multi-user sync itself is deferred.

Emits events from the same 7 mutating endpoints the original git safety layer targeted, plus archive-related events from 5a. No projections, no indexes, no snapshots — the log on disk is the entire system.

### Feature 5c: Git Snapshot Commits

Periodic snapshot commits of `workspace/` — one on server shutdown, and optionally one per 24h for long-running sessions. Preserves the file-level escape hatch (git log -p works as a last resort if events.jsonl is lost) and becomes the substrate for future multi-user file sync. Not per-mutation: the event log is the primary audit trail.

Lightweight implementation (~30 lines). Workspace is a git repo; `.gitignore` excludes `.bak` and inbox artifacts.

### Feature 5d: Transaction Actions Menu

Three-dot overflow menu on transaction register rows: Delete (remove transaction), Re-categorize (rewrite destination to Unknown, resurfaces in review queue), and Unmatch (restore manual entry from archive, revert imported transaction to pre-match state). Each action emits an event through the log.

Depends on 5a (archive journal for unmatch) and 5b (event log for recording actions).

### Feature 5e: Semantic Undo + Toast

Endpoint `POST /api/events/undo/<event_id>` walks the log backward, dispatches on forward-event type to compute the inverse, checks `hash_after` against current state per-transaction, applies the compensating action for unchanged transactions, skips drifted ones, and returns a partial-undo report. Writes a new compensating event.

UX: toast with Undo button appears after each mutating action and persists ~8 seconds (Gmail/Simplifi pattern). A lightweight operation history list provides access to older events. Undo is linear from most recent to earliest.

Depends on 5b (event log) and 5d (coherent per-transaction compensating semantics).

### Feature 6: Dashboard Drill-Down and Activity View

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
