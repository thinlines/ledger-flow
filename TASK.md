# Current Task

**Status: COMPLETED — 2026-04-12**

## Title

Transactions screen rethink — Phase 4b: Frontend unification

## Objective

Replace the dual-mode transactions page (register view + activity view toggled by `activityMode`) with a single filter-driven screen backed by `GET /api/transactions`. Account scope becomes a filter chip, not a mode toggle. Single-account features (running balance, clearing toggle, add transaction, manual resolution, pending transfers) auto-activate when exactly one account is selected. The page drops from ~1400 lines to ~500.

After this task: one screen, Monarch-shaped, running balance visible in single-account scope, filter bar with chips, day-grouped rows, detail sheet, all existing actions preserved. Two-mode toggle gone.

See [`plans/transactions-rethink.md`](plans/transactions-rethink.md) for the full design.

## Scope

### Included

**New files:**
- `app/frontend/src/lib/transactions/transactionFilters.ts` — `TransactionFilters` type, `EMPTY_FILTERS` constant, `filtersFromUrl(url)` (with migration from old `?view=activity&...` and `?accountId=...` params), `filtersToUrl(filters)`, `filtersToApiParams(filters)`, `activeFilterCount(filters)`.
- `app/frontend/src/lib/transactions/loadTransactions.ts` — `loadTransactions(filters): Promise<TransactionsResponse>` using `apiGet` with params from `filtersToApiParams()`.
- `app/frontend/src/lib/components/transactions/TransactionsFilterBar.svelte` — horizontal bar with search input (debounced 300ms), period segmented control, active filter chips (accounts, category, status) with ✕ clear, "+ Filters" button.
- `app/frontend/src/lib/components/transactions/TransactionsFilterDialog.svelte` — bits-ui Dialog with Accounts tab (checkbox list of tracked accounts), Categories tab (grouped checkbox list from `/api/accounts`), Status tab (radio: cleared / pending / unmarked / any). Works on a draft copy; Apply commits.

**Modified files:**
- `app/frontend/src/lib/transactions/types.ts` — add `TransactionRow`, `TransactionsResponse`, `TransactionFilters` types. Keep old types during transition.
- `app/frontend/src/lib/transactions/helpers.ts` — add `groupByDate(rows: TransactionRow[])` returning `{header, rows, dailySum}[]`. Add `canDeleteRow(row)`, `canRecategorizeRow(row)`, `canUnmatchRow(row)`.
- `app/frontend/src/lib/components/transactions/TransactionRow.svelte` — remove `mode` prop and dual `{#if}` branches. Single layout: `[clearing-dot] [category-pills] [payee + secondary line] [amount] [running-balance?] [chevron]`. Accept `row: TransactionRow`.
- `app/frontend/src/lib/components/transactions/TransactionDetailSheet.svelte` — replace dual `entry`/`transaction` props with single `row: TransactionRow | null`. Adapt category combobox and notes to work with unified type.
- `app/frontend/src/lib/components/transactions/TransactionDayGroup.svelte` — add `dailySum: number | null` and `baseCurrency: string` props. Render daily sum right-aligned.
- `app/frontend/src/routes/transactions/+page.svelte` — full rewrite (~500 lines). Single data flow: `filters → loadTransactions → result`. Remove `activityMode` toggle, duplicate hero, legacy loaders.
- `app/frontend/src/routes/+page.svelte` — update dashboard drill-down links to new URL format.
- `app/frontend/src/routes/accounts/+page.svelte` — update "Transactions" link to new URL format.

### Explicitly Excluded

- **Transfer-pair collapse** — deferred. Both sides of a tracked-to-tracked transfer still appear as separate rows. The plan file specifies collapse rules but the edge cases (clearing-status conflicts, mismatched dates, manual-resolution tokens across collapsed pairs) need a dedicated task with trust-level specification.
- **Deleting legacy backend endpoints** — `/api/transactions/register` and `/api/transactions/activity` remain. Removal is a separate cleanup task after the frontend is stable.
- **Phase 4c polish items** — live totals strip, search formula syntax, mobile bottom sheet, keyboard shortcuts. Each is an independent follow-up.
- **Notes and tags** — the detail sheet already has a notes textarea from Phase 3. No new notes/tags work.
- **Split editing, merchant management, transaction editing** — per plan exclusions.

## System Behavior

### Inputs

- User navigates to `/transactions` → unified screen loads with default filters (all accounts, last 3 months).
- User navigates to `/transactions?accounts=checking` → single-account scope activates.
- User navigates with old params (`?view=activity&category=X`, `?accountId=X`) → URL migrated silently via `filtersFromUrl()`.
- User clicks a filter chip ✕ → that filter removed, data reloads.
- User changes period preset → period filter updates, data reloads.
- User types in search → debounced 300ms, data reloads.
- User opens "+ Filters" → dialog opens with draft filter state.
- User applies filters in dialog → filters update, data reloads, URL updates.
- User clicks row chevron → detail sheet opens for that row.
- User clicks clearing dot (single-account only) → clearing status toggles via existing `POST /api/transactions/toggle-status`.
- User clicks "Add transaction" (single-account only) → `AddTransactionForm` opens.
- User opens manual resolution (single-account, pending transfer) �� `ManualResolutionDialog` opens.

### Logic

**Page data flow:**
1. `onMount` → read URL via `filtersFromUrl($page.url)`. If old params detected, rewrite URL with `replaceState`. Load app state, tracked accounts, all accounts (for category combobox). Call `loadData()`.
2. `loadData()` → call `loadTransactions(filters)` → set `result: TransactionsResponse`. Derive `isSingleAccount`, `selectedAccount`, `dayGroups`, `postedRows`, `pendingRows`.
3. `handleFiltersChange(next)` → set `filters = next`, update URL via `goto()` with `replaceState`, call `loadData()`.

**Single-account auto-activation (`filters.accounts.length === 1`):**
- `showRunningBalance = true` on `TransactionRow`
- Clearing dot becomes clickable (`onToggleClearing` callback provided)
- "Add transaction" button appears in hero
- Pending transfers section appears if `pendingRows.length > 0`
- Summary cards appear (balance, balance with pending, latest activity) from `result.accountMeta`
- `TransactionsExplanationHeader` hidden (summary is account-level, not category-level)

**Multi-account mode (`filters.accounts.length !== 1`):**
- `showRunningBalance = false` (hidden unless same-currency, which is `runningBalance !== null`)
- Clearing dot is a static indicator (no toggle callback)
- "Add transaction" button hidden
- Pending transfers section hidden
- Summary cards hidden
- `TransactionsExplanationHeader` shown when `result.summary` is non-null

**Filter state type:**
```typescript
type TransactionFilters = {
  accounts: string[];
  period: string | null;     // 'this-month' | 'last-30' | 'last-3-months' | null (= no period, show all)
  month: string | null;      // 'YYYY-MM'
  category: string | null;   // full ledger account path
  search: string;
  status: string | null;     // 'cleared' | 'pending' | 'unmarked'
};
```

**URL param mapping:**
- `accounts` → `?accounts=checking,savings` (omit when empty)
- `period` → `?period=last-3-months` (omit when null — null means no date filter, show all time)
- `month` → `?month=2026-03` (overrides period)
- `category` → `?category=Expenses:Food`
- `search` → `?q=trader`
- `status` → `?status=cleared`

**URL migration (`filtersFromUrl`):**
- `?view=activity&period=X` → `{ accounts: [], period: X }`
- `?view=activity&month=M` → `{ accounts: [], month: M }`
- `?view=activity&category=C` → `{ accounts: [], category: C }`
- `?accountId=X` → `{ accounts: [X], period: null }`
- Any combination of above → mapped field by field

### Outputs

- One unified transactions screen for all scopes.
- Filter bar above the list with active filters as removable chips.
- Day-grouped transaction rows with daily sum in group headers.
- Detail sheet opens from chevron, shows all row data, category combobox works, notes work.
- Single-account features auto-activate.
- Old URLs from dashboard and accounts page continue to work.

## System Invariants

- The `amount` displayed on each row matches `row.amount` from the backend. The frontend never recomputes amounts.
- Running balance, when shown, matches `row.runningBalance` from the backend. The frontend never recomputes it.
- Filter state in the URL is the single source of truth. Refreshing the page with the same URL produces the same view.
- All existing transaction actions (delete, recategorize, reset category, unmatch, toggle clearing, add transaction, manual resolution) must continue to work. They call the same POST endpoints and reload data via `loadData()` after mutation.
- Dashboard drill-down links and accounts page links must land on the correct filtered view.

## States

- **Default**: all accounts, no date filter, no category/search/status filter. Shows all transactions newest first.
- **Loading**: page skeleton or spinner while `loadTransactions()` is in flight.
- **Success**: filter bar + day-grouped rows + optional summary/cards.
- **Error**: error message card. Retry by changing filters.
- **Empty — no accounts**: hero with "Add first account" CTA (existing pattern).
- **Empty — no results for filters**: empty panel with "No transactions match these filters" + clear-filters button.
- **Empty — not initialized**: hero with "Create a workspace first" CTA (existing pattern).

## Edge Cases

- **Stale account bookmark**: `/transactions?accounts=deleted-id` → backend returns 404, frontend shows error state. User clears filter or navigates away.
- **Dashboard link with old URL format**: `?view=activity&category=Expenses:Food` → silently migrates to `?category=Expenses:Food`. No visible redirect.
- **Rapid filter changes**: debounced search (300ms). Period/account/category changes fire immediately but cancel in-flight requests (use a request sequence counter or abort controller).
- **Detail sheet open during filter change**: close the sheet, clear `selectedRow`.
- **Single account with zero transactions**: show empty state + summary cards (balance, etc.) from `accountMeta`.
- **All accounts with zero transactions in range**: show empty state with filter-clear CTA. `summary` is null.

## Failure Behavior

- API error from `loadTransactions()`: show error text in an error card. Do not show stale data from a previous successful load.
- Action error (delete, recategorize, etc.): show error message inline. Do not close the detail sheet on failure.
- If `filtersFromUrl()` encounters unrecognized params: ignore them, use defaults for missing fields.

## Regression Risks

- **Dashboard drill-down breaks**: links in `+page.svelte` (dashboard) use `?view=activity&category=...` and `?view=activity&month=...`. These must land on the correct filtered view after migration. Test by clicking category trend rows and cash flow month rows.
- **Accounts page link breaks**: `?accountId=checking` must land on single-account view with running balance and clearing toggles.
- **Clearing toggle regression**: must still persist via `POST /api/transactions/toggle-status` and optimistically update the row.
- **Category combobox regression**: the detail sheet's category combobox was just shipped in Phase 3. Must still work with the new `TransactionRow` type.
- **Notes regression**: the detail sheet's notes textarea was just shipped in Phase 3. Must still work with the new type.
- **Manual resolution regression**: the dialog must still open from pending transfer rows in single-account scope.
- **Add transaction regression**: the form must still work in single-account scope, bound to the selected account.
- **Old `activityMode` state leakage**: ensure no code path references `activityMode` after the rewrite.

## Acceptance Criteria

- `/transactions` with no params shows all accounts, day-grouped, newest first. No `activityMode` toggle visible.
- `/transactions?accounts=checking` shows single-account view: running balance column, clickable clearing dots, "Add transaction" button, pending transfers section (if any), summary cards.
- `/transactions?category=Expenses:Food` shows only transactions with that category. Explanation header appears with summary stats.
- `/transactions?period=this-month` shows current month transactions with summary.
- Filter bar shows active filters as chips with ✕ to remove.
- "+ Filters" button opens a dialog where the user can select accounts, categories, and status. Apply updates the view.
- Search input filters by payee substring (debounced).
- Old URL `?view=activity&category=Expenses:Food` auto-migrates and shows the correct filtered view.
- Old URL `?accountId=checking` auto-migrates to single-account view.
- Dashboard category-trend click lands on correct category-filtered view.
- Dashboard cash-flow month click lands on correct month-filtered view.
- Accounts page "Transactions" link lands on single-account view.
- Clicking a row chevron opens the detail sheet with correct data.
- Detail sheet category combobox recategorizes and reloads.
- Detail sheet notes textarea saves on blur.
- Detail sheet delete/unmatch actions work and reload.
- Clearing dot toggle works in single-account mode.
- "Add transaction" form works in single-account mode.
- Day group headers show daily sum right-aligned.
- `pnpm check` passes.
- `uv run pytest -q` passes (backend unchanged, verify no breaks).
- Page line count is under 600.

## Proposed Sequence

1. **Types + filter state** — add `TransactionRow`, `TransactionsResponse` to `types.ts`. Create `transactionFilters.ts` with filter type, URL serialization, and migration. Create `loadTransactions.ts`.
2. **Updated helpers** — add `groupByDate`, `canDeleteRow`, `canRecategorizeRow`, `canUnmatchRow` to `helpers.ts`.
3. **TransactionRow.svelte rewrite** — remove `mode` prop, single unified layout accepting `TransactionRow`.
4. **TransactionDayGroup.svelte update** — add `dailySum` + `baseCurrency` props.
5. **TransactionDetailSheet.svelte update** — accept `TransactionRow | null` instead of dual props. Adapt combobox and notes.
6. **TransactionsFilterBar.svelte** — new component with search, period presets, filter chips.
7. **TransactionsFilterDialog.svelte** — new component with tabbed filter selection.
8. **+page.svelte rewrite** — single data flow, filter-driven. Remove `activityMode`, duplicate hero, legacy loaders. Wire all components.
9. **Update external links** — dashboard `+page.svelte` and accounts `+page.svelte` links to new URL format.
10. **Verify** — `pnpm check`, manual testing of all acceptance criteria, regression checks.

## Definition of Done

- One transactions screen with no mode toggle.
- All acceptance criteria met.
- All regression risks verified (dashboard links, accounts links, clearing, combobox, notes, manual resolution, add transaction).
- `pnpm check` passes.
- `uv run pytest -q` passes.
- Page is under 600 lines.
- No references to `activityMode` remain in the codebase.

## UX Notes

- **Filter bar** sits between the hero and the transaction list. It's always visible when initialized. Uses the existing `.view-card` pattern with tight padding.
- **Period presets** render as a segmented control (existing `.activity-presets` pattern). When a month filter is active from a drill-down, show it as a removable chip instead of the presets.
- **Account chips** show the tracked account's `displayName`. Multiple can be active.
- **Category chip** shows the leaf segment of the category path (e.g., "Food / Groceries" for `Expenses:Food:Groceries`).
- **Day group headers**: date on the left (e.g., "Mar 24 · Wednesday"), daily sum on the right in muted text.
- **Row layout**: `[clearing-dot] [category-pills] [payee + date/account secondary line] [amount] [running-balance?] [chevron]`. Running balance column hidden when multi-account or null.
- **Hero**: single hero for all scopes. Shows account name + balance trust when single-account. Shows "Transactions" + subtitle when multi-account.
- **Empty state**: centered message with "No transactions match these filters" and a "Clear all filters" button.

## Out of Scope

See "Explicitly Excluded" above. Transfer-pair collapse, legacy endpoint deletion, Phase 4c polish, and all deferred plan items are out of scope.

## Delivery Notes

Shipped 2026-04-12 on branch `worktree-agent-a0ee344f` (merged to master). `pnpm check` clean (0/0), page is 430 lines (target <600), zero `activityMode` references remain. QA: PASS WITH FINDINGS (Finding 1 fixed in branch before review). Code review: SHIP WITH NOTES.

**Follow-up items identified during review:**

- **Dead legacy helpers in `app/frontend/src/lib/transactions/helpers.ts`**: `entryHasActions`, `canDelete`, `canRecategorize`, `canUnmatch`, `groupActivityByDate` have no remaining callers and should be deleted.
- **Dead legacy type exports in `app/frontend/src/lib/transactions/types.ts`**: `ActivityResult`, `ActivityDateGroup`, `RegisterAction`, `ActionLink` have no consumers and should be removed. (`RegisterEntry`, `AccountRegister`, `ActivityTransaction`, `ActivitySummary`, `ActivityTopTransaction` still used by `ManualResolutionDialog` and `TransactionsExplanationHeader`; keep until those migrate.)
- **Multi-category filtering (design decision)**: the filter dialog is single-pick and `TransactionFilters.category` is scalar, even though the backend `UnifiedTransactionFilters.categories` is plural. Works for all current drill-down paths. Either widen `category → categories: string[]` or defer as a tracked Phase 4c item.
- **QA spec divergence on stale bookmarks**: `/transactions?accounts=deleted-id` silently drops the deleted ID and falls through to the all-accounts view, rather than showing an error state as specified. Arguably better UX; needs PM confirmation.
- **Filter history via `replaceState`**: all filter mutations use `replaceState`, so back-button does not traverse filter history. Consider `pushState` for top-level filter changes.
- **Polish items (low-severity)**: filter-dialog status "Any" radio doubles the toggle-off behavior of individual radios (redundant); notes save reads `row` at save time, not at focus time, so clicking a different row mid-edit posts against the wrong row (pre-existing pattern); detail sheet shows account label twice in single-account scope; `transactionActions.ts` error messages include `"Error: "` prefix from `String(e)`.
- **Pre-existing environment issue**: `uv run pytest -q` fails with `ModuleNotFoundError: No module named 'fastapi'` on master too — not caused by this branch. Backend code unchanged here.
