# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Delivery Focus

Dashboard direction: the dashboard answers "Where do I stand right now?" and "What changed recently?" well, and now the third question — **"Where should I go next?"** — has a real home. The direction panel (7b, shipped) surfaces derived health signals: runway gauge with liability minimum-payment obligations, 6-month net worth sparkline, recurring vs discretionary spending split, notable signals (largest transaction, category spikes, spending streaks), and a loose-ends aggregator. The transactions screen (7d, shipped through 7d-4b) is unified into one Monarch-shaped filter-driven page with running balance, N-1 posting rule, and inline category combobox. Two polish items from 7d-4c are shipped (live totals strip, search formula syntax). Remaining focus: transactions polish (7d-4c remaining items: day-group daily sums, mobile bottom sheet) and shell polish (7c). Keyboard shortcuts are deferred until a proper design pass is greenlit. Semantic undo + toast (5e) is paused and resumes after Feature 7 ships. See `DECISIONS.md` §13.

### Current Status

- Event-sourced undo sub-features 5a–5d are shipped: archive journal for matched manual entries, append-only event log with drift detection, git snapshot commits, and the transaction actions menu (delete, re-categorize, unmatch). Semantic undo + toast (5e) is paused until after Feature 7.
- Dashboard drill-down infrastructure (Feature 6) is shipped: clickable category trends and cash flow rows, cross-account activity view with date-range and category filtering, URL-param filter state. The quality and depth of those drilldowns is the gap Feature 7 closes.
- Dashboard direction panel (7b) is shipped: runway gauge (with liability minimum-payment obligations), 6-month net worth sparkline with y-axis labels, recurring vs discretionary spending split, notable signals, and loose-ends aggregator. Runway limits spendable cash to liquid assets (checking, savings, cash) and excludes fixed assets from stale-account alerts.
- Transactions screen rethink (7d) through 7d-4b is shipped: unified filter-driven page, running balance, N-1 posting rule, inline category combobox, detail sheet, filter bar with dialog. Two 7d-4c polish items shipped: live totals strip and search formula syntax (amount, category, date, account, status, payee field prefixes with AND-combining).
- CSV parser refactor is complete (2026-04-15). Five additional bank adapters (Chase, Ally, U.S. Bank, Bank of America, Citibank) shipped alongside the refactor.
- Manual transaction entry with import matching is complete: users add transactions from the register with a `:manual:` tag, unknowns review offers a "match" mode to match imports to manual entries, and match quality ranking, amount-delta display, and metadata carryover are all in place.
- Transfer-specific flows are complete: unknown review supports direct transfers, pending import-match transfers, and automatic matching; grouped-settlement trust fix and guided manual resolution shipped; bilateral auto-reconciliation is read-time only with no journal writes.
- Import-time auto-linking (bypassing the unknowns review queue) was considered and rejected — it removes the human confirmation step. The current flow (import → review → confirm → auto-reconcile display) is the correct trust model.

### Delivery Sequence

1. ~~**Manual transaction entry**~~ — shipped.
2. ~~**Transaction clearing status**~~ — shipped.
3. ~~**Overview dashboard facelift**~~ — shipped.
4. ~~**Dashboard polish**~~ — shipped (4a–4d: momentum line, day-grouped activity, per-account staleness, cash flow presets).
5. **Event-sourced undo** — trust fix. Sub-features 5a–5d shipped. 5e paused until after Feature 7.
   - ~~**5a. Archive journal for matched manual entries**~~ — shipped.
   - ~~**5b. Event log foundation**~~ — shipped.
   - ~~**5c. Git snapshot commits**~~ — shipped.
   - ~~**5d. Transaction actions menu**~~ — shipped.
   - **5e. Semantic undo + toast** — paused. Resumes after Feature 7.
6. ~~**Dashboard drill-down and activity view**~~ — shipped. Drill-through links, cross-account activity view, and URL-param filters are live. Quality and depth addressed by Feature 7.
7. **Dashboard insight loop and financial direction** — current focus. Four sub-features:
   - ~~**7a. Activity view explanation and hierarchy**~~ — shipped. Activity endpoint returns a `summary` block with prior-period and 6-month rolling baselines; the activity view leads with a context-aware hero and an explanation header; rows promote category to a leading pill and truncate raw bank payees.
   - ~~**7d. Transactions screen rethink**~~ — shipped through Phase 4b. Dual-mode page collapsed into one Monarch-shaped filter-driven screen. Running balance, N-1 posting rule, inline category combobox, detail sheet, filter bar with dialog. See `plans/transactions-rethink.md`.
     - ~~**7d-4a. Unified backend endpoint**~~ — shipped. `GET /api/transactions` returning unified `TransactionRow[]` with N-1 posting rule, running balance, filters, summary, and accountMeta. Shared helpers extracted to `transaction_helpers.py`. 30 tests. Transfer-pair collapse deferred to a follow-up.
     - ~~**7d-4b. Frontend unification**~~ — shipped. `+page.svelte` rewritten to one filter-driven screen. New `TransactionsFilterBar`, `TransactionsFilterDialog`, `transactionFilters.ts`, `loadTransactions.ts`. `activityMode` toggle removed. Single-account features auto-activate. URL migration for old params.
     - **7d-4c. Polish** — two items shipped (~~live totals strip~~, ~~search formula syntax~~). Remaining: day-group daily sums, mobile bottom sheet. Keyboard shortcuts deferred until a design pass is greenlit.
   - ~~**7b. Dashboard direction panel and health signals**~~ — shipped. "Where should I go next?" section with runway gauge (including liability minimum-payment obligations), 6-month net worth sparkline with y-axis labels, recurring vs discretionary spending split, notable signals, and loose-ends aggregator. Runway scoped to liquid assets; fixed assets excluded from stale-account alerts.
   - **7c. Shell and copy polish** — next. Sidebar copy, nav notes, hero CTA fallthrough, /rules loading state, mobile nav drawer.
8. **Semantic undo + toast (5e)** — resumes after Feature 7.
9. **Transaction editing** — deferred. See Deferred for Now.

### Feature 1: Manual Entry + Import Matching ✓

Shipped. See git history for implementation details.

### Feature 2: Transaction Clearing Status

Shipped. See git history for implementation details.

### Feature 3: Overview Dashboard Facelift ✓

Shipped. Balance sheet data path fixed (`dashboard.balances` from `config.tracked_accounts`), hero CTA reactivity fixed (explicit Svelte dependencies), sections reordered (activity and trends above cash flow and balance sheet), snapshot band merged into hero stat chips, coverage strip removed, cash flow compressed to 3-month default with expand toggle, Today rail compacted to status line + CTA, stale-data awareness added (7-day threshold). See git history for implementation details.

### Feature 3b: Dashboard Polish ✓

Shipped. Momentum line replaces Net chip, recent activity day-grouped (5-item cap, linked review badges), per-account staleness and missing opening balance indicators in balance sheet (backend `lastTransactionDate`), cash flow segmented preset toggle (This month / Last 3 / Last 6). See git history for implementation details.

### Feature 5a: Archive Journal for Matched Manual Entries ✓

Shipped. Matched manual entries are preserved in `workspace/journals/archived-manual.journal` with `match-id:` UUID tags linking them to imported transactions. See git history for implementation details.

### Feature 5b: Event Log Foundation ✓

Shipped. Append-only event log at `workspace/events.jsonl` with UUIDv7 ids, drift detection, and pre-mutation hash checks. All 7 mutating endpoints emit events. See git history for implementation details.

### Feature 5c: Git Snapshot Commits ✓

Shipped. Periodic workspace snapshots on shutdown and stale startup (>24h). Managed `.gitignore` excludes transient artifacts. See git history for implementation details.

### Feature 5d: Transaction Actions Menu ✓

Shipped. Three-dot overflow menu on register rows with delete, re-categorize, and unmatch actions. Each action emits a structured event to the event log following the established mutation pattern (drift check, backup, modify, emit). See git history for implementation details.

### Feature 5e: Semantic Undo + Toast

**Paused until after Feature 7.** Endpoint `POST /api/events/undo/<event_id>` walks the log backward, dispatches on forward-event type to compute the inverse, checks `hash_after` against current state per-transaction, applies the compensating action for unchanged transactions, skips drifted ones, and returns a partial-undo report. Writes a new compensating event.

UX: toast with Undo button appears after each mutating action and persists ~8 seconds (Gmail/Simplifi pattern). A lightweight operation history list provides access to older events. Undo is linear from most recent to earliest.

Depends on 5b (event log) and 5d (coherent per-transaction compensating semantics).

### Feature 6: Dashboard Drill-Down and Activity View ✓

Shipped. Clickable category trends and cash flow rows link to a filtered cross-account activity view. The activity view supports period presets (this month, last 30 days, last 3 months) and category filtering. URL-param filter state preserves browser back-button behavior. The backend exposes `GET /api/transactions/activity` for cross-account queries with optional date-range and category filters.

Feature 6 delivered the *infrastructure* for drilldowns. Feature 7a addresses the *quality* gap: every drilldown currently lands on a raw transaction list with no period comparison, decomposition, or top-mover context. See Feature 7 below.

### Feature 7: Dashboard Insight Loop and Financial Direction

The dashboard answers all three questions: "Where do I stand?" and "What changed?" were already covered; "Where should I go next?" is now answered by the direction panel (7b). The third question was reframed from "What needs my attention next?" (which sounded like an inbox of chores) to **"Where should I go next?"** (which encompasses tasks, investigable questions, and health checks). The bookkeeping work — review queue, statement inbox, conflicts — is the price of admission for a financial conversation, not the point of the product.

This feature closed three gaps (two shipped, one remaining):

- **Explanation over data** ✓: every drilldown leads with a period comparison, frequency decomposition, rolling baseline, and top mover before showing transactions (7a, shipped).
- **Financial direction** ✓: the dashboard's "Where should I go next?" section shows derived health signals as compact charts — runway (months of spending + obligations covered by liquid assets), net worth trend (6-month sparkline), and recurring vs discretionary split. Plus notable signals and a loose-ends aggregator (7b, shipped).
- **Shell polish**: sidebar copy still leaks implementation language, the hero CTA is hollow when nothing is pending, /rules shows a misleading "not initialized" loading state, and mobile stacks the entire sidebar above financial data on every page. (7c, next.)

#### Sub-features

- **7a. Activity view explanation and hierarchy** ✓: shipped. Activity endpoint returns a `summary` block with prior-period and 6-month rolling baselines. Context-aware hero title, explanation header above activity list when filters are active, category promoted to a leading pill, raw bank payees truncated.

- **7b. Dashboard direction panel and health signals** ✓: shipped. Dashboard section with three chart tiles: a runway gauge (`spendable_cash / (avg_monthly_spending + monthly_obligations)`, scoped to liquid assets, with liability minimum-payment support), a 6-month net worth sparkline with y-axis labels, and a recurring vs discretionary stacked bar. Three notable signals as one-line bullets: largest transaction this week, category spikes >2× rolling average, spending-exceeds-income streaks. Loose-ends aggregator: review queue, statement inbox, stale accounts (excluding fixed assets), missing opening balances. Minimum-payment metadata stored on opening balance journal entries; runway subtitle shows expenses + obligations breakdown when obligations exist.

- **7c. Shell and copy polish**: rewrite the sidebar brand line and nav notes to remove implementation leaks. Fix the hero CTA fallthrough so an "all caught up" state doesn't surface a redundant "Open transactions" primary action. Fix the /rules loading-state copy that incorrectly says "not initialized". Filter zero-vs-zero rows from the dashboard cash flow and category trends panels. Replace the stacked sidebar on `< 980px` with a top bar plus drawer so financial data is the first thing on mobile.

- **7d. Transactions screen rethink** ✓: shipped through Phase 4b. Dual-mode page collapsed into one Monarch-shaped filter-driven screen. Account scope is a filter chip. N-1 posting rule, running balance always shown, inline category combobox, right-side detail sheet with three-dot overflow menu. Backend unified to `GET /api/transactions`. Two 7d-4c polish items shipped (live totals strip, search formula syntax). Remaining 7d-4c: day-group daily sums, mobile bottom sheet. Keyboard shortcuts deferred. Transfer-pair row collapse deferred to a follow-up. See `plans/transactions-rethink.md`.

#### Constraints

- Health signals are derived metrics only. Goals, targets, and budgets remain deferred — no partial implementation. Runway, net worth trend, and recurring vs discretionary all compute from existing data without user input.
- Notable signals must be low-code arithmetic. Largest transaction (`max(abs(amount))`), category spike (`current > 2 × rolling avg`), spending streak (consecutive months `spending > income`). No statistical models, anomaly detection, or ML.
- GenAI analysis (Ollama, ChatGPT API) is a future direction for richer signals but requires data-privacy planning and is not in scope for Feature 7.
- Investment tracking (401(k), HSA, pretax contributions) is out of scope. These accounts don't appear in tracked balances and the runway/net worth signals reflect only what the workspace knows about.
- A consolidated "needs attention" panel is allowed here only because it's part of the broader direction section — it does not violate `DECISIONS.md` §11. The loose-ends list is one component of a panel whose primary purpose is health signals and investigation hooks, not a notification center. See §13 for the rationale.
- This feature does not introduce a notification center, dismissable cards, or persistent alert state. Signals are computed each load from current data.

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

### CSV parser refactor — COMPLETED 2026-04-15

`Scripts/BankCSV.py` retired. All institution CSV parsing now routes through `app/backend/services/parsers/` adapters (Wells Fargo, Alipay, ICBC). Schwab and Bank of Beijing removed as YAGNI. `institution_registry.py` derives from the adapter registry. Import-identity hashes preserved byte-exact throughout.

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
