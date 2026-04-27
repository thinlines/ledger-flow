# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Delivery Focus

Statement reconciliation (Feature 8) is now the active focus. Feature 7 is closed (direction panel, transactions screen rethink through 7d-4b, shell/copy polish). Feature 5 is closed: semantic undo + toast (5e) shipped in full — six undoable mutations (delete, recategorize, unmatch, manual-entry-create, notes-update, status-toggle), the 8s toast on the five destructive ones (status-toggle stays toast-less by design), and a `Recent activity` sheet listing the 20 newest events with per-row Undo / Undone controls, reached via a History trigger in the desktop sidebar and mobile top bar. Feature 8 backend (8a) and reconciliation modal (8b) are shipped: `POST /api/accounts/{id}/reconcile` with the assertion writer and last-on-its-date invariant, the reconciled-date import fence, read-side failure detection, and a two-step Reconcile modal on every tracked asset/liability card backed by `GET /api/accounts/{id}/reconciliation-context`. Currency parsing is shared between backend and frontend through a fixture-driven parity test. Assertion rendering (8c) is next. See `DECISIONS.md` §14–§17, §19 and `plans/statement-reconciliation.md`.

### Current Status

- Event-sourced undo (Feature 5) is fully shipped: 5a–5d plus 5e. Six undoable event types (delete, recategorize, unmatch, manual-entry-create, notes-update, status-toggle), the 8s `Undo` toast (Gmail/Simplifi pattern) on the five destructive ones, and a `Recent activity` sheet listing the 20 newest events with per-row Undo / Undone controls. The sheet's History trigger lives in the desktop sidebar brand card and the mobile top bar — one click from any route. Status-toggle has no toast by design (one-click cycle reverts it) but appears in the sheet so it remains reachable for asynchronous undo.
- Dashboard drill-down infrastructure (Feature 6) is shipped: clickable category trends and cash flow rows, cross-account activity view with date-range and category filtering, URL-param filter state. The quality and depth of those drilldowns is the gap Feature 7 closes.
- Dashboard direction panel (7b) is shipped: runway gauge (with liability minimum-payment obligations), 6-month net worth sparkline with y-axis labels, recurring vs discretionary spending split, notable signals, and loose-ends aggregator. Runway limits spendable cash to liquid assets (checking, savings, cash) and excludes fixed assets from stale-account alerts.
- Transactions screen rethink (7d) through 7d-4b is shipped: unified filter-driven page, running balance, N-1 posting rule, inline category combobox, detail sheet, filter bar with dialog. Two 7d-4c polish items shipped: live totals strip and search formula syntax (amount, category, date, account, status, payee field prefixes with AND-combining).
- Shell and copy polish (7c) is shipped, closing Feature 7: finance-first sidebar byline and /rules nav note, hero "Review your direction" CTA in the all-caught-up state, /rules loading state, dashboard zero-row filtering for cash flow and category trends, mobile top bar + slide-in drawer under 980px, Edit demoted into the Accounting details disclosure on accounts, and a `signMode: 'good-change-plus'` extension on `formatCurrency` with ArrowLeftRight icon on transfer rows.
- CSV parser refactor is complete (2026-04-15). Five additional bank adapters (Chase, Ally, U.S. Bank, Bank of America, Citibank) shipped alongside the refactor.
- Manual transaction entry with import matching is complete: users add transactions from the register with a `:manual:` tag, unknowns review offers a "match" mode to match imports to manual entries, and match quality ranking, amount-delta display, and metadata carryover are all in place.
- Transfer-specific flows are complete: unknown review supports direct transfers, pending import-match transfers, and automatic matching; grouped-settlement trust fix and guided manual resolution shipped; bilateral auto-reconciliation is read-time only with no journal writes.
- Import-time auto-linking (bypassing the unknowns review queue) was considered and rejected — it removes the human confirmation step. The current flow (import → review → confirm → auto-reconcile display) is the correct trust model.

### Delivery Sequence

1. ~~**Manual transaction entry**~~ — shipped.
2. ~~**Transaction clearing status**~~ — shipped.
3. ~~**Overview dashboard facelift**~~ — shipped.
4. ~~**Dashboard polish**~~ — shipped (4a–4d: momentum line, day-grouped activity, per-account staleness, cash flow presets).
5. ~~**Event-sourced undo**~~ — shipped (5a–5e). Trust fix complete.
   - ~~**5a. Archive journal for matched manual entries**~~ — shipped.
   - ~~**5b. Event log foundation**~~ — shipped.
   - ~~**5c. Git snapshot commits**~~ — shipped.
   - ~~**5d. Transaction actions menu**~~ — shipped.
   - ~~**5e. Semantic undo + toast**~~ — shipped. Endpoint `POST /api/events/undo/{event_id}` walks the log, dispatches on event type, checks per-file hash drift, applies the compensating action, and writes a compensating event. Six handlers: `transaction.deleted.v1`, `transaction.recategorized.v1`, `transaction.status_toggled.v1`, `manual_entry.created.v1`, `transaction.unmatched.v1`, `transaction.notes_updated.v1`. Toast UI (`UndoToast.svelte` + `undo-toast.ts`) shows after delete, recategorize, unmatch, manual-entry-create, and notes-update with 8s auto-dismiss; status-toggle has no toast by design. `GET /api/events` returns the 20 newest events with `undoable` and `compensated` flags. `RecentActivitySheet.svelte` (right-side `bits-ui` Sheet) lists them with per-row Undo / Undone, reachable via a History trigger in the desktop sidebar and mobile top bar.
6. ~~**Dashboard drill-down and activity view**~~ — shipped. Drill-through links, cross-account activity view, and URL-param filters are live. Quality and depth addressed by Feature 7.
7. **Dashboard insight loop and financial direction** — current focus. Four sub-features:
   - ~~**7a. Activity view explanation and hierarchy**~~ — shipped. Activity endpoint returns a `summary` block with prior-period and 6-month rolling baselines; the activity view leads with a context-aware hero and an explanation header; rows promote category to a leading pill and truncate raw bank payees.
   - ~~**7d. Transactions screen rethink**~~ — shipped through Phase 4b. Dual-mode page collapsed into one Monarch-shaped filter-driven screen. Running balance, N-1 posting rule, inline category combobox, detail sheet, filter bar with dialog. See `plans/transactions-rethink.md`.
     - ~~**7d-4a. Unified backend endpoint**~~ — shipped. `GET /api/transactions` returning unified `TransactionRow[]` with N-1 posting rule, running balance, filters, summary, and accountMeta. Shared helpers extracted to `transaction_helpers.py`. 30 tests. Transfer-pair collapse deferred to a follow-up.
     - ~~**7d-4b. Frontend unification**~~ — shipped. `+page.svelte` rewritten to one filter-driven screen. New `TransactionsFilterBar`, `TransactionsFilterDialog`, `transactionFilters.ts`, `loadTransactions.ts`. `activityMode` toggle removed. Single-account features auto-activate. URL migration for old params.
     - **7d-4c. Polish** — two items shipped (~~live totals strip~~, ~~search formula syntax~~). Remaining: day-group daily sums, mobile bottom sheet. Keyboard shortcuts deferred until a design pass is greenlit.
   - ~~**7b. Dashboard direction panel and health signals**~~ — shipped. "Where should I go next?" section with runway gauge (including liability minimum-payment obligations), 6-month net worth sparkline with y-axis labels, recurring vs discretionary spending split, notable signals, and loose-ends aggregator. Runway scoped to liquid assets; fixed assets excluded from stale-account alerts.
   - ~~**7c. Shell and copy polish**~~ — shipped. Finance-first sidebar copy, hero CTA fallthrough, /rules loading state, dashboard zero-row filtering, mobile nav drawer, accounts Edit demotion, and good-change-plus sign convention with ArrowLeftRight transfer glyph. Closes Feature 7.
8. **Statement reconciliation (Feature 8)** — current focus. Pulled forward from Deferred. Camp 1 (Quicken/YNAB-style explicit reconciliation) over a journal-native balance-assertion substrate. See [`plans/statement-reconciliation.md`](plans/statement-reconciliation.md). MVP sub-features:
   - ~~**8a. Backend**~~ — shipped. `POST /api/accounts/{id}/reconcile` writes a single zero-amount transaction with a balance assertion, verifies via `ledger bal --strict`, rolls back byte-equivalent on failure, and emits `account.reconciled.v1` with the same id stamped into the journal metadata. Reconciled-date import fence flips on-or-before-reconciliation rows to `conflict` with `conflictReason: "reconciled_date_fence"` and `reconciledThrough` for the frontend to render. Read-side failure detection runs ledger strict-balance once per request and surfaces broken assertions on `/api/accounts`, `/api/tracked-accounts`, and the dashboard balance sheet. Hand-written assertions trip detection but stay out of the fence and the future history view. See `DECISIONS.md` §14–§17, §19 and `plans/statement-reconciliation.md`.
   - ~~**8b. Reconciliation modal on `/accounts`**~~ — shipped. Reconcile button on every tracked asset/liability card opens a two-step (Setup → Review) modal: dates and closing balance up front, then a live Opening · Ticked · Closing · Difference strip with checkbox rows from `GET /api/accounts/{id}/reconciliation-context`. Finish posts to 8a's endpoint and refreshes the accounts list on 200; 422/409/400 stay open with a banner exposing `expected`/`actual` and the raw ledger error. Currency parser is shared with the backend through a JSON fixture and a Vitest parity test. Mobile (<980px) renders as a bottom sheet on the same bits-ui Dialog primitive.
   - **8c. Assertion rendering + failure surfacing** — current focus. Subtle row style in transactions list; failure state on account card and loose-ends aggregator; translated error copy.

   Phased follow-ups (each independently shippable, sequenced after MVP): **8d** statement PDF attachment, **8e** reconciliation history view on the account page, **8f** subset-sum "find the difference" solver, **8g** adjustment-transaction button, **8h** confirmation modal for edits/deletes of pre-reconciliation transactions.
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

### Feature 5e: Semantic Undo + Toast ✓

Shipped. Endpoint `POST /api/events/undo/{event_id}` dispatches on forward-event type, verifies per-file hash drift, applies the compensating action, and writes a `<event_type>.compensated.v1` event linked back via `compensates`. Idempotent — re-running undo on the same event returns the existing compensating-event id. Linearity ("most recent → earliest") is enforced implicitly by drift detection: an older event in the same file fails drift if a newer one ran after it.

Handlers: `transaction.deleted.v1`, `transaction.recategorized.v1`, `transaction.status_toggled.v1`, `manual_entry.created.v1`, `transaction.unmatched.v1`, `transaction.notes_updated.v1`. The notes handler captures `previous_notes` on each save so the prior value can be restored (or removed); pre-migration events lacking `previous_notes` fail closed. Tests in `app/backend/tests/test_undo_service.py` cover not-found, unsupported, already-compensated, drift, round-trip restore for each handler, and compensating-event emission.

`GET /api/events` returns the 20 newest events with `undoable` (event type is in the handler dispatch table) and `compensated` (later event has `compensates == this.id`) flags. The compensation lookup is bounded by the same window since any compensator must follow its forward in the log.

UX: `UndoToast.svelte` shows after delete, recategorize, unmatch, manual-entry-create, and notes-update with 8s auto-dismiss (Gmail/Simplifi pattern), `Undoing…` → `Restored` confirmation, and an error state. Status-toggle has no toast by design — the status pill cycles in one click, so a toast would be unwelcome noise. `RecentActivitySheet.svelte` (right-side `bits-ui` Sheet) lists the 20 newest events with per-row Undo when `undoable && !compensated`, muted `Undone` when compensated, and nothing for non-undoable rows. Inline error on failure, refetch on open and after every successful undo, `ALREADY_COMPENSATED` treated as success-equivalent so concurrent undos collapse cleanly. The History trigger (lucide `History` icon) lives in the desktop sidebar brand card and the mobile top bar — one click from any route. Drift / failed errors surface the backend `message` instead of the JSON envelope.

Depends on 5b (event log) and 5d (coherent per-transaction compensating semantics).

The "partial-undo report" language in the original 5e blurb is N/A for the current handler set — every handler mutates exactly one transaction, so any drift fails the whole undo. If a future handler touches multiple transactions in a single event, partial-undo becomes relevant.

### Feature 6: Dashboard Drill-Down and Activity View ✓

Shipped. Clickable category trends and cash flow rows link to a filtered cross-account activity view. The activity view supports period presets (this month, last 30 days, last 3 months) and category filtering. URL-param filter state preserves browser back-button behavior. The backend exposes `GET /api/transactions/activity` for cross-account queries with optional date-range and category filters.

Feature 6 delivered the *infrastructure* for drilldowns. Feature 7a addresses the *quality* gap: every drilldown currently lands on a raw transaction list with no period comparison, decomposition, or top-mover context. See Feature 7 below.

### Feature 7: Dashboard Insight Loop and Financial Direction

The dashboard answers all three questions: "Where do I stand?" and "What changed?" were already covered; "Where should I go next?" is now answered by the direction panel (7b). The third question was reframed from "What needs my attention next?" (which sounded like an inbox of chores) to **"Where should I go next?"** (which encompasses tasks, investigable questions, and health checks). The bookkeeping work — review queue, statement inbox, conflicts — is the price of admission for a financial conversation, not the point of the product.

This feature closed three gaps (two shipped, one remaining):

- **Explanation over data** ✓: every drilldown leads with a period comparison, frequency decomposition, rolling baseline, and top mover before showing transactions (7a, shipped).
- **Financial direction** ✓: the dashboard's "Where should I go next?" section shows derived health signals as compact charts — runway (months of spending + obligations covered by liquid assets), net worth trend (6-month sparkline), and recurring vs discretionary split. Plus notable signals and a loose-ends aggregator (7b, shipped).
- **Shell polish** ✓: sidebar copy is finance-first, the hero CTA in the all-caught-up state points to the direction panel, /rules shows a proper loading state, the mobile layout leads with financial data via a top bar + drawer, accounts demote Edit into the details disclosure, and transaction amounts follow a good-change-plus sign convention with an ArrowLeftRight glyph on transfer rows. (7c, shipped.)

#### Sub-features

- **7a. Activity view explanation and hierarchy** ✓: shipped. Activity endpoint returns a `summary` block with prior-period and 6-month rolling baselines. Context-aware hero title, explanation header above activity list when filters are active, category promoted to a leading pill, raw bank payees truncated.

- **7b. Dashboard direction panel and health signals** ✓: shipped. Dashboard section with three chart tiles: a runway gauge (`spendable_cash / (avg_monthly_spending + monthly_obligations)`, scoped to liquid assets, with liability minimum-payment support), a 6-month net worth sparkline with y-axis labels, and a recurring vs discretionary stacked bar. Three notable signals as one-line bullets: largest transaction this week, category spikes >2× rolling average, spending-exceeds-income streaks. Loose-ends aggregator: review queue, statement inbox, stale accounts (excluding fixed assets), missing opening balances. Minimum-payment metadata stored on opening balance journal entries; runway subtitle shows expenses + obligations breakdown when obligations exist.

- **7c. Shell and copy polish** ✓: shipped. Finance-first sidebar byline and /rules nav note; hero "Review your direction" CTA in the all-caught-up state, pointing at the direction panel; /rules loading state replaces the misleading "not initialized" flash; dashboard cash flow and category trends suppress zero-vs-zero rows; mobile (<980px) replaces the stacked sidebar with a top bar + slide-in drawer built on bits-ui; accounts demote Edit into the Accounting details disclosure; `formatCurrency` gains a `signMode: 'good-change-plus'` option so transaction amounts render with a green `+` for "good" balance changes (asset-up and liability-down) and unsigned neutral otherwise; transfer rows prepend an ArrowLeftRight glyph. Closes Feature 7.

- **7d. Transactions screen rethink** ✓: shipped through Phase 4b. Dual-mode page collapsed into one Monarch-shaped filter-driven screen. Account scope is a filter chip. N-1 posting rule, running balance always shown, inline category combobox, right-side detail sheet with three-dot overflow menu. Backend unified to `GET /api/transactions`. Two 7d-4c polish items shipped (live totals strip, search formula syntax). Remaining 7d-4c: day-group daily sums, mobile bottom sheet. Keyboard shortcuts deferred. Transfer-pair row collapse deferred to a follow-up. See `plans/transactions-rethink.md`.

#### Constraints

- Health signals are derived metrics only. Goals, targets, and budgets remain deferred — no partial implementation. Runway, net worth trend, and recurring vs discretionary all compute from existing data without user input.
- Notable signals must be low-code arithmetic. Largest transaction (`max(abs(amount))`), category spike (`current > 2 × rolling avg`), spending streak (consecutive months `spending > income`). No statistical models, anomaly detection, or ML.
- GenAI analysis (Ollama, ChatGPT API) is a future direction for richer signals but requires data-privacy planning and is not in scope for Feature 7.
- Investment tracking (401(k), HSA, pretax contributions) is out of scope. These accounts don't appear in tracked balances and the runway/net worth signals reflect only what the workspace knows about.
- A consolidated "needs attention" panel is allowed here only because it's part of the broader direction section — it does not violate `DECISIONS.md` §11. The loose-ends list is one component of a panel whose primary purpose is health signals and investigation hooks, not a notification center. See §13 for the rationale.
- This feature does not introduce a notification center, dismissable cards, or persistent alert state. Signals are computed each load from current data.

### Feature 8: Statement Reconciliation

Pulled forward from Deferred. Camp 1 (explicit, statement-driven) reconciliation, expressed in the journal as a single zero-amount transaction with a balance assertion. The full spec lives in [`plans/statement-reconciliation.md`](plans/statement-reconciliation.md). Summary:

- **Why now:** users can enter manual transactions, so account balances drift from bank reality if a manual entry isn't matched on import. Periodic statement reconciliation is the trust mechanism that catches drift and keeps users vigilant.
- **Architecture:** reconciliation finish writes one transaction of the form `Statement reconciliation · <account> · ending YYYY-MM-DD` with a single zero-amount posting carrying a balance assertion (`Assets:Checking  $0 = $2,500.00`). No mutations to existing transactions. Undo = delete the assertion transaction (the existing actions menu already handles this). Detection of assertion failures runs on all assertions in the journal — including hand-written ones — but the reconciliation history view only lists assertions written by the flow (identified by `; reconciliation_event_id:` metadata).
- **MVP sub-features:** 8a backend (reconcile endpoint, assertion writer, import-merge fence, failure detection), 8b reconciliation modal on `/accounts`, 8c assertion rendering + failure surfacing.
- **Phased follow-ups:** 8d PDF attachment, 8e history view, 8f subset-sum solver, 8g adjustment-transaction button, 8h confirmation modal for pre-reconciliation edits.

#### Constraints

- The assertion transaction must be the last transaction on its date in the journal file, so the assertion checks the end-of-day balance. The writer enforces this; the import path enforces it on subsequent inserts.
- Once a date is reconciled, any new import on or before that date surfaces as a conflict, not a silent insert. Fail-closed.
- Reconciliation history surfaces only assertions written by the flow. Hand-written or imported balance assertions are honored for failure detection but do not appear in history.
- Single-currency MVP. Multi-currency accounts are out of scope until a real user need surfaces.
- No hard lock on reconciled transactions. Trust is enforced by event-sourced undo (5b–5d) and, in 8h, a confirmation modal for edits/deletes that fall before a reconciliation point.
- Statement PDFs (8d onward) live under `workspace/statements/<account-slug>/statement-ending-YYYY-MM-DD.pdf`. They are evidence, not data — the journal remains canonical.

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
- Multi-currency account support (reconciliation, balance assertions, dashboard rollups all assume single-currency per account today)
- Reconciliation against electronically downloaded statement files (OFX/QFX) — current Feature 8 plan covers human-attested reconciliation against PDF/print statements only
