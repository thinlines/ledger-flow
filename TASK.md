# Current Task

**Status: COMPLETED — 2026-04-12**

## Title

Transactions screen rethink — Phase 4b follow-up: UI polish and dead code cleanup

## Objective

Close the three UX gaps reported against the shipped Phase 4b screen — redundant row dates, scroll context loss on long day groups, and jarring list flash on filter change — and delete the Phase 4b cleanup debt identified in code review. After this task the transactions screen reads cleanly, scrolls with stable context, updates in place, and leaves no orphaned legacy types/helpers behind.

## Scope

### Included

**Modified files:**

- `app/frontend/src/lib/components/transactions/TransactionRow.svelte` — drop the date from the secondary line; secondary line becomes `account.label` when multi-account, empty otherwise (pills still render).
- `app/frontend/src/lib/components/transactions/TransactionDayGroup.svelte` — make the day header `position: sticky`, offset by the filter bar's measured height, with a solid background so underlying rows don't bleed through.
- `app/frontend/src/lib/components/transactions/TransactionsFilterBar.svelte` — remove per-chip labels ("Category", "Status", "Month"), make the bar a single flex-wrap row of `[search] [period-presets | month-chip] [account chips...] [category chip] [status chip] [+ Filters]`, capitalize the status chip label to "Cleared"/"Pending"/"Unmarked".
- `app/frontend/src/routes/transactions/+page.svelte` — make the filter bar section `position: sticky` at the top of the page scroll, expose a `--filter-bar-height` CSS var via `ResizeObserver` for day headers to consume; rework the transactions list render so an in-flight reload keeps the previous `result` mounted and shows a subtle inline loading indicator instead of swapping to the empty-panel skeleton; on error during a reload, keep the previous list and surface an inline error banner rather than clearing to an empty panel.
- `app/frontend/src/lib/transactions/helpers.ts` — delete the five orphaned legacy helpers (`entryHasActions`, `canDelete`, `canRecategorize`, `canUnmatch`, `groupActivityByDate`) and the now-unused `RegisterEntry` and `ActivityTransaction` imports.
- `app/frontend/src/lib/transactions/types.ts` — delete the five orphaned legacy types (`ActivityResult`, `ActivityDateGroup`, `RegisterAction`, `ActionLink`, `AccountRegister`). Keep `RegisterEntry`, `ActivityTransaction`, `ActivitySummary`, `ActivityTopTransaction` — still used by `ManualResolutionDialog`, `TransactionsExplanationHeader`, and the `TxRow → RegisterEntry`/`toExplTx` bridges.

### Explicitly Excluded

- **Multi-category filtering** — QA/review medium finding M3. `TransactionFilters.category` stays scalar; the filter dialog stays single-pick. Widening to `categories: string[]` is a separate task that needs a type migration + backend filter-param plumbing + URL-serialization update.
- **Stale-bookmark behavior change** — the current silent-drop of deleted account IDs stays as-is pending PM confirmation. Not touched here.
- **`replaceState` → `pushState` for filter history** — UX choice deferred; not touched.
- **Transfer-pair collapse** — still deferred, tracked separately.
- **Migrating `ManualResolutionDialog` or `TransactionsExplanationHeader`** off the legacy `RegisterEntry` / `ActivityTransaction` types. The bridge in `+page.svelte` stays; only orphaned types are deleted.
- **Any new filter or polish feature** from 7d-4c (live totals strip, search formula syntax, mobile bottom sheet, keyboard shortcuts).

## System Behavior

### Inputs

- User scrolls the transactions page with a long day group visible.
- User changes any filter (account, period, category, status, search, month) or clears all filters.
- User loads `/transactions` while a backend reload is in flight.
- User triggers an action (delete, recategorize, reset category, unmatch, toggle clearing, add transaction) that causes `loadData()` to refetch.

### Logic

**Row secondary line (`TransactionRow.svelte`):**

- Compute `secondaryText` as:
  - `row.account.label` when `!isSingleAccount && showAccountLabel`
  - empty string otherwise
- The date (`activityShortDate(row.date)`) is no longer included anywhere in the row — the day group header owns that information.
- The secondary-line `<p>` always renders so the pill slot (Needs review, Starting balance, Grouped transfer) is available. When `secondaryText` is empty and no pills apply, the `<p>` collapses to empty but keeps its top margin so row height stays stable.

**Sticky filter bar + day headers (`+page.svelte`, `TransactionsFilterBar.svelte`, `TransactionDayGroup.svelte`):**

- The filter bar section gets `position: sticky; top: 0; z-index: 10;` with a solid background (`view-card` already has one) and a bottom shadow or border that appears only when it is pinned (use `backdrop-filter` or a `box-shadow` on the sticky state — simplest path: always-on subtle shadow when sticky).
- On mount, attach a `ResizeObserver` to the filter bar's root `<section>` element. On every resize entry, write `document.documentElement.style.setProperty('--filter-bar-height', \`${entry.contentRect.height}px\`)`. Disconnect the observer on page unmount.
- `TransactionDayGroup` header uses `position: sticky; top: var(--filter-bar-height, 0px); z-index: 5;` with a solid background (opaque white or the card's background color — not transparent) so the rows scrolling past don't bleed through.
- The day header must sit **below** the filter bar in z-order when they overlap.
- When the filter bar wraps (multiple rows), `--filter-bar-height` updates automatically and day headers pin under the new height on the next layout pass.

**Filter bar layout (`TransactionsFilterBar.svelte`):**

- Single flex row: `flex flex-wrap items-center gap-2`.
- Order of elements: search input, period presets (or month chip when `filters.month` is set), account chips (one per `filters.accounts[]`), category chip (if `filters.category`), status chip (if `filters.status`), "+ Filters" button as the last element.
- Remove all per-chip label wrappers (the `<div class="flex items-center gap-1.5"><span class="filter-label">Category</span>...</div>` structure). All chips become direct siblings in the same flex row.
- Status chip text: display the value title-cased — `'cleared' → 'Cleared'`, `'pending' → 'Pending'`, `'unmarked' → 'Unmarked'`. No prefix label.
- Month chip: keep the existing `monthTitle()` formatted value. No "Month" label prefix.
- Category chip: keep the existing `categoryDisplayName()` (leaf-segment path). No "Category" label prefix.

**In-place list updates on reload (`+page.svelte`):**

- Split the current list render into two states based on `result` and `dataLoading`:
  - **First load** (`result === null && dataLoading`): show the existing "Loading transactions" empty panel. Unchanged.
  - **Reload with existing data** (`result !== null && dataLoading`): render the day groups from the stale `result` exactly as on success. Overlay a subtle loading indicator — a 2px indeterminate progress bar at the top of the `.view-card` transactions section, or a dim of the list content via `opacity: 0.6`. Prefer the progress bar; it preserves legibility of the content while it updates.
  - **Success** (`result !== null && !dataLoading`): current render.
  - **Empty** (`result !== null && !dataLoading && postedRows.length === 0`): current "No transactions match these filters" empty panel.
  - **Error during reload** (`result !== null && error !== ''`): render the stale list plus an inline error banner at the top of the section (using the existing `.error-text` or a new `.reload-error` style). Do **not** null `result` on reload errors.
  - **Error on first load** (`result === null && error !== ''`): current "Error loading transactions" empty panel.
- Do not clear `selectedRow` at the start of `loadData()` when the reload is triggered by an action handler. When triggered by `changeFilters()`, clearing is still correct (user navigated away). Implement this by removing the `selectedRow = null` assignment from `loadData()` and instead nulling `selectedRow` inside `changeFilters()` before it calls `loadData()`. Action handlers already null `selectedRow` themselves on success, so their path is unaffected.
- The request-sequence counter (`requestSeq`) stays as-is. The only change is that stale `result` is preserved across the await, and `result = null` is no longer set on reload errors.

**Dead code cleanup:**

- Delete the following exports from `helpers.ts`: `entryHasActions`, `canDelete`, `canRecategorize`, `canUnmatch`, `groupActivityByDate`.
- Remove `RegisterEntry` and `ActivityTransaction` from the `helpers.ts` import at the top of the file — they become unused after the helper deletions.
- Delete the following type exports from `types.ts`: `ActivityResult`, `ActivityDateGroup`, `RegisterAction`, `ActionLink`, `AccountRegister`.
- Verify via grep that no other file in `app/frontend/src/` imports any of the deleted symbols. (Local `ActionLink` definitions in `routes/+page.svelte` and `routes/accounts/+page.svelte` are unrelated — they declare their own local type aliases and must remain untouched.)

### Outputs

- Transaction rows no longer show the date in their secondary line; multi-account rows show the account label; single-account rows show a blank secondary line or pills only.
- Day group headers remain pinned at the top of the scroll area (tucked under the sticky filter bar) while their rows scroll underneath, then are pushed up by the next day group's header.
- Filter bar chips wrap as a single flat flex row. "+ Filters" sits at the end of whichever row has space.
- Filter bar pins to the top of the viewport while the page body scrolls.
- Changing filters updates the list in place: the old rows stay visible, a progress bar appears briefly, then the new rows replace them without an empty-panel flash.
- A reload error surfaces inline without clearing the existing data.

## System Invariants

- `row.amount` and `row.runningBalance` continue to come from the backend — nothing in this task recomputes them.
- Filter state in the URL remains the single source of truth. Sticky positioning, in-place updates, and the layout change do not introduce any new client-only state that survives navigation.
- All existing transaction actions (delete, recategorize, reset category, unmatch, toggle clearing, add transaction, notes save, manual resolution) continue to work through their existing POST endpoints and reload via `loadData()`. None of their handlers changes in behavior.
- `actionError` continues to render inline in the detail sheet and in the delete/unmatch confirm modals. Its lifecycle (clear on row change, clear on success) is unchanged.
- Dashboard drill-down links, accounts page links, and old-URL migration (`?view=activity&...`, `?accountId=...`) are untouched.
- The orphaned legacy exports (`entryHasActions`, `canDelete`, `canRecategorize`, `canUnmatch`, `groupActivityByDate`, `ActivityResult`, `ActivityDateGroup`, `RegisterAction`, `ActionLink`, `AccountRegister`) are genuinely orphaned. Their deletion must not break the live bridges `toExplTx()` in `+page.svelte` or `manualResolutionEntry` construction.

## States

- **Default**: filter bar visible and pinned, list below, day headers present. No filters active → last-3-months preset selected as before.
- **Reloading with stale data**: existing list stays visible, thin progress bar at the top of the transactions section, filter bar responsive to user input.
- **Reloading with no prior data** (first load): hero skeleton + "Loading transactions" empty panel. Unchanged.
- **Success**: list rendered from latest `result`, no loading indicator, no error banner.
- **Empty for current filters**: "No transactions match these filters" panel with clear-all button. Unchanged.
- **Reload error**: stale list still visible with an inline error banner above it. User can retry by changing filters.
- **First-load error**: "Error loading transactions" empty panel. Unchanged.

## Edge Cases

- **Filter bar wraps to multiple rows on narrow viewports**: `ResizeObserver` updates `--filter-bar-height` after each wrap, day headers reposition on the next layout. No manual measurement.
- **User scrolls a day group that contains more rows than the viewport**: day header stays pinned under the filter bar for the entire length of the group, then is pushed out by the next group's header.
- **Rapid filter changes**: request-sequence counter still prevents stale responses from winning. The in-place update preserves the most-recently-successful `result` across rapid typing, so the screen never blanks.
- **Reload error after success**: inline banner appears, prior rows remain; another successful reload replaces the rows and clears the banner.
- **Single-account mode with a starting balance row**: the "Starting balance" pill still renders in the row's secondary slot even though `secondaryText` is empty.
- **Detail sheet open when an action triggers a reload**: sheet already closes on action success (existing behavior). The `selectedRow = null` removed from `loadData()` does not affect this.
- **Detail sheet open when the user changes a filter**: `changeFilters()` nulls `selectedRow` before calling `loadData()`, so the sheet closes on filter change.
- **Transitioning from first-load error to success on retry**: when the user changes a filter after a first-load error, `result === null && error !== ''` → `result !== null && error === ''`. The reload error banner path is not taken (there's no stale list to preserve). Behavior matches the current flow.
- **Very short day groups** (one row): sticky header still engages and releases normally.
- **Single-row multi-account list** with `showAccountLabel=false`: secondary line is empty, pills only. No layout regression.

## Failure Behavior

- `loadTransactions()` error during reload: inline banner above the list, stale data preserved, `dataLoading = false`, no modal, no toast.
- `loadTransactions()` error on first load: unchanged — "Error loading transactions" empty panel.
- `ResizeObserver` not available (old browser): fall back to a static `--filter-bar-height: 0px` and accept that the day headers pin to `top: 0` under the filter bar that scrolls with the page (no sticky filter bar). The page must still render and scroll. Do not throw.
- Sticky positioning disabled by a parent `overflow` setting: headers revert to normal block flow. No crash.
- Deleted legacy helpers/types still referenced anywhere: `pnpm check` fails and the task is not done. Grep verification in the proposed sequence catches this before commit.

## Regression Risks

- **Row layout regression**: removing the date from the secondary line can change row height or pill alignment. Verify both single-account and multi-account rows, and rows with/without pills.
- **Sticky stacking context bugs**: `position: sticky` requires no ancestor with `overflow: hidden`, `overflow: auto`, or `transform`. The `.view-card` ancestor and any shell wrapper must be checked. If a wrapper blocks sticky, the fix is to move the sticky element out — not to introduce a new scroll container.
- **Filter bar z-index collisions**: the sticky filter bar (`z-index: 10`) must not overlap the detail sheet (higher) or confirm modals (`z-index: 30/31`). Verify visually.
- **Filter bar background bleed**: day headers scrolling under a transparent filter bar produces a visual double-render. Ensure the filter bar has a solid background.
- **In-place update leaking a wrong-filter row momentarily**: during reload, the stale list is shown. If the user scrolls and clicks a row whose filter no longer applies, the detail sheet still opens correctly (the row data is valid) but the list below changes underneath them. This is acceptable — the alternative (locking interactions) is worse.
- **Dead-code deletion breaking a hidden consumer**: verify with grep across `app/frontend/src/` before deletion. `RegisterEntry` is still used by `ManualResolutionDialog` and `+page.svelte:53`; `ActivityTransaction` still used by `TransactionsExplanationHeader`. Do not delete those.
- **`AccountRegister` is already dead**: the reviewer flagged four legacy types but missed this one. Confirm by grep; delete if dead.
- **Action reload clearing `selectedRow`**: removing the `selectedRow = null` from `loadData()` could leave the sheet open after a manual resolution or add-transaction flow if those paths don't close the sheet themselves. Audit each caller: `changeFilters`, `doDelete`, `doResetCat`, `doRecat`, `doUnmatch`, `handleResolved`, `handleAddSuccess`, `handleToggleClearing`. Close the sheet explicitly in `changeFilters` and leave the action handlers as-is (they already null on success).
- **Filter bar labels removal affecting screen readers**: chips relied on visible `<span class="filter-label">` text for context. After removal, the chip button aria labels must still be descriptive. Status chip especially — "Cleared" alone may be ambiguous to a screen reader, but combined with the "Remove status filter" aria label on its clear button it stays accessible.

## Acceptance Criteria

- Transaction rows show no date in their body. In multi-account scope the secondary line shows the account label; in single-account scope the secondary line is empty unless a pill applies.
- Scrolling a day group longer than one screen keeps that group's header pinned directly under the filter bar for the whole duration of the group.
- The filter bar stays pinned at the top of the viewport while the page body scrolls.
- With no filters active, the filter bar renders as a single line (search + presets + "+ Filters") with no second row.
- With one account chip + one category chip active, the filter bar renders as a single line (search + presets + account chip + category chip + "+ Filters"). At standard desktop widths there is no wrap.
- At narrow widths where wrapping is unavoidable, chips wrap as peers in a flat row; there is no per-group label creating an awkward sub-row.
- Status chip reads "Cleared", "Pending", or "Unmarked" — not lowercase, not prefixed with "Status".
- Changing a filter does not empty the list before the new results arrive. A thin progress indicator appears, old rows stay, new rows replace them when ready.
- Changing a filter while the reload fails keeps the previous rows visible and shows an inline error banner; it does not swap the list for an empty-panel error state.
- The four existing actions that auto-reload (delete, recategorize, unmatch, toggle clearing) still work and still close their sheet/modal on success.
- `grep -r "entryHasActions\|canDelete\b\|canRecategorize\b\|canUnmatch\b\|groupActivityByDate" app/frontend/src/` returns no matches.
- `grep -rE "\b(ActivityResult|ActivityDateGroup|RegisterAction|AccountRegister)\b" app/frontend/src/` returns no matches. (`ActionLink` still appears in `routes/+page.svelte` and `routes/accounts/+page.svelte` as local type definitions — those are unrelated and must stay.)
- `pnpm check` passes with 0 errors and 0 warnings.
- `uv run pytest -q` is not expected to pass — the pre-existing `ModuleNotFoundError: fastapi` environment issue on master blocks it. This task does not fix that. Verify only that the error is the same pre-existing one and not a new failure caused by this branch.
- `wc -l app/frontend/src/routes/transactions/+page.svelte` stays under 600.

## Proposed Sequence

1. **Dead code cleanup** — delete the five helper functions in `helpers.ts` plus unused imports; delete the five legacy type exports in `types.ts`. Run `pnpm check` to confirm nothing else was consuming them. This is the smallest independently-verifiable step and frees the mental model for the polish work.
2. **Row secondary line** — update `TransactionRow.svelte` to drop the date from `secondaryLine` and collapse to account-label-only (multi-account) or empty (single-account). Verify pills still render. Visual check in the dev server.
3. **Filter bar layout cleanup** — rewrite `TransactionsFilterBar.svelte`'s markup to a single flat flex-wrap row, drop per-chip labels, title-case the status chip value. Verify chip ordering and wrap behavior at desktop and narrow viewports.
4. **Sticky filter bar + measured height** — in `+page.svelte`, wrap the `<TransactionsFilterBar>` render in a sticky container (or set sticky styles on the filter bar itself), attach a `ResizeObserver` in `onMount` to expose `--filter-bar-height` on `document.documentElement`, disconnect on `onDestroy`.
5. **Sticky day headers** — update `TransactionDayGroup.svelte`'s `.date-header-row` to `position: sticky; top: var(--filter-bar-height, 0px);` with a solid background and the correct z-order below the filter bar. Visual check by scrolling a long day group.
6. **In-place list reload** — in `+page.svelte`, move `selectedRow = null` out of `loadData()` and into `changeFilters()`. Update the transactions section markup: the "Loading transactions" empty panel is only shown when `result === null`. When `result !== null && dataLoading`, render the list with a loading indicator on top (thin indeterminate progress bar via CSS animation). On error during reload, render the list plus an inline error banner; do not clear `result`.
7. **Verify** — `pnpm check`, grep for deleted symbols, line count, and a full manual pass of the acceptance criteria in the dev server.

## Definition of Done

- All acceptance criteria met.
- All regression risks above verified manually or by code inspection.
- `pnpm check` passes with 0 errors and 0 warnings.
- No `grep` hit for any deleted symbol.
- Page stays under 600 lines.
- No new dead code introduced — every new helper, prop, or state has a live caller.
- The sticky filter bar and sticky day headers behave correctly across at least one "long day group scroll" manual test and one filter-change test in the dev server.

## UX Notes

- **Row secondary line when empty**: always render the `<p>` with `min-height: 1.1em` (or equivalent) so row heights stay consistent between multi-account rows and single-account rows that have no secondary text or pills. Do not conditionally omit the element.
- **Loading indicator style**: a 2px indeterminate progress bar (`animation: shimmer 1.2s linear infinite`) pinned to the top of the `.view-card` transactions section is preferred. Reserve background dimming for cases where the content is actually unreadable during load.
- **Error banner during reload**: use the same `.error-text` style from the current first-load error path, placed inside a small inline card at the top of the transactions section. Do not use a modal or toast — the list needs to stay focal.
- **Filter bar visual separation when pinned**: once scrolled, the sticky filter bar should look deliberately attached to the top of the viewport. A subtle bottom `box-shadow` when pinned is enough. Do not add a heavy border.
- **Day header background**: must be opaque. If the app background is a gradient, use a solid color that matches the card background (`rgba(255, 255, 255, 0.96)` or the `.view-card` surface color). Rows bleeding through the header is the highest-severity visual bug for this feature.
- **Accessibility**: day headers are still `<h4>` elements inside the group — no change to heading semantics. The filter bar's chip clear buttons keep their `aria-label`s. If the status chip changes from "Status: Cleared" markup to just "Cleared", make sure the chip container or its clear button has an aria-label that includes the word "status".

## Out of Scope

- Multi-category filtering (type widen, dialog multi-select, URL serialization).
- Stale-bookmark behavior change.
- `pushState` vs `replaceState` for filter history.
- Any Phase 4c polish items (live totals strip, search formula, mobile bottom sheet, keyboard shortcuts).
- Migrating `ManualResolutionDialog` or `TransactionsExplanationHeader` off their legacy types.
- Transfer-pair collapse.
- Fixing the pre-existing `fastapi` pytest environment issue.

## Delivery Notes

Shipped on branch `worktree-phase-4b-polish` over two commits: implementation (`0537e15`) and review fixes (`c5f45be`). `pnpm check` green (0 errors / 0 warnings, 667 files). All acceptance-criteria greps return zero matches. `+page.svelte` sits at 463 lines.

One fix cycle was needed. Code review caught:

- **Blocker — sticky-ancestor trap**: the transactions section had inherited `overflow-hidden` which would have broken `position: sticky` day headers (TASK.md Regression Risks called this out by name). Fixed by removing the class from the outer section and insetting the `.reload-progress` shimmer horizontally by `var(--radius-card)` so it stays clear of the card's rounded corners without needing parent clipping.
- **Convention slip on utility-first CSS**: three simple scoped selectors (`.filter-bar-sticky` positioning, `.transactions-section { position: relative }`, `.reload-error`) were moved to Tailwind utilities. The remaining scoped CSS is justified (piercing `:global(.filter-bar)` box-shadow, `.reload-progress` keyframe+gradient). Raw rgba values on the error banner swapped for `bg-bad/10 border-bad/20` theme tokens.
- **Status chip a11y**: `aria-label` on a non-interactive `<span>` is ignored by screen readers; replaced with a visually-hidden `"Status: "` prefix inside the chip so SRs read "Status: Cleared" instead of the ambiguous "Cleared".
- Two low-severity tidy-ups (dropped the redundant `typeof document` SSR guard in `onDestroy` since Svelte lifecycles don't run on the server; kept the `typeof ResizeObserver` feature-detect since the task explicitly requires an old-browser fallback; replaced `.tx-secondary { min-height }` with a `min-h-[1.1em]` utility).

QA verdict: **PASS** (both cycles). Review verdict: **REQUEST CHANGES** → **SHIP** after fix cycle 1.

Visual verification was code-level only — no browser screenshot pass. The dev server booted clean and `/transactions` returned 200, but the sticky-scroll behavior, filter-bar wrap responsiveness, and shimmer timing should be exercised manually before merge.
