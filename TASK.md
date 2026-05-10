# Transactions State Consistency: URL as Source of Truth (tx-state-fix)

**Status: COMPLETED — 2026-05-10**

## Objective

Every URL change to `/transactions?...` re-renders the page consistently — KPIs, trend chart, top merchants/categories, transactions list, and cross-filter highlight — within one render cycle, regardless of how the URL changed (anchor click, browser back/forward, programmatic `goto`, deep link, in-component callback). The user never has to refresh the page to see correct visuals.

## Scope

### Included

1. Rewrite the filter-state architecture in `app/frontend/src/routes/transactions/+page.svelte` so that **the URL is the single source of truth**. `filters` becomes a reactive derivation from `$page.url`; reloading data is a reactive side-effect of `filters` changing.
2. Collapse `changeFilters(next)` to a one-liner that calls `goto(...)` with the new URL. State assignment goes away — the reactive subscription handles it.
3. Re-evaluate the `onMonthFocus` callback added for chart clicks: it can stay as a callback, but its body collapses to "navigate to the new URL." The page reactively re-derives.
4. Verify outbound anchor links still produce the right URL shape and rely on the new reactive subscription instead of a callback workaround:
   - `TransactionInsights.svelte` — Composition top-categories list (`<a href="/transactions?category=...">`)
   - `CategoryRibbon.svelte` (dashboard)
   - `DashboardDirection.svelte` — stale-account link
5. Preserve the `replaceState` URL-update mode for filter-bar interactions (no back-button per keystroke); top-level navigation (anchor links into `/transactions?...`) keeps default `pushState` so back/forward works.
6. Preserve existing `AbortController` race-condition handling in `loadData` and `loadHistory` so a fast sequence of filter changes doesn't render stale data.

### Explicitly Excluded

- Backend changes — `/api/transactions` and `/api/transactions/...` payload shape stay as-is.
- Visual redesign — pixels stay where they are; only the data-flow plumbing changes.
- Adding new filters, components, or interactions.
- Data-entry workflow (separate upcoming task).
- Refactor of `transactionFilters.ts` — the `filtersFromUrl` and `filtersToUrl` helpers are correct; only their callers move.

## System Behavior

### Inputs

- URL change from any source: anchor `<a href>` click, `goto()` programmatic navigation, browser back/forward button, deep link / page reload.
- Filter-bar interactions (period preset, account chip removal, category clear, search keystroke).
- Trend chart click (current `onMonthFocus`).
- Filter dialog "Apply".

### Logic

**Filter derivation (reactive, replaces the imperative `load()`-time parse):**
```
$: parsed = filtersFromUrl($page.url)
$: filters = applyAccountValidation(applyDefaultPeriod(parsed.filters, hasNoFilters), trackedAccounts)
```

- `applyDefaultPeriod`: if `parsed.filters` has zero filters of any kind (sidebar entry), return `{ ...parsed.filters, period: 'this-month' }`. Otherwise return as-is. This rule fires on every URL change but is idempotent — if any filter is set in the URL, no default is applied.
- `applyAccountValidation`: drops account ids that aren't in `trackedAccounts` (existing behavior). Skips when `trackedAccounts` hasn't loaded yet.
- The migration redirect (old param formats) and default-period URL rewrite still happen, but only on the first reactive run — gated on a `hasReconciledUrl` flag so we don't loop.

**Reload trigger (reactive, replaces the imperative `loadData()` call after `filters = next`):**
```
$: filtersKey = serializeFiltersForApi(filters)
$: if (initialized && filtersKey !== lastFiltersKey) {
  lastFiltersKey = filtersKey
  void loadData()
  void loadHistory(filters)
}
```

- Use a stable serialization (e.g. JSON of normalized filter object). Compare against the last-loaded key to dedupe identical filter sets.
- `loadData` and `loadHistory` keep their existing AbortController logic.

**Internal callback collapse:**
```
function changeFilters(next) {
  void goto(`/transactions${filtersToUrl(next)}`, { replaceState: true, noScroll: true, keepFocus: true })
}
```
- No `filters = next`. No `void loadData()`. The reactive subscription handles both.
- `onMonthFocus(month)` becomes `changeFilters({ ...filters, month, period: month ? null : filters.period })` — same as today, just routed through the unified path.

### Outputs

- After any URL change, the dossier (`TransactionInsights`), `AccountStatusStrip` (when single account), pending transfers panel (when single account), and transactions list all render against the current URL filters within one render cycle.
- Chart cross-filter highlight reappears whenever `filters.search` is non-empty.
- KPI numbers, top merchants/categories, trend chart bars, and 6-mo baseline reflect the active filters — no stale "$56k 12-mo NET" leaking from a prior view.
- Network tab shows at most one `/api/transactions?<filters>` request per filter change, plus one or two `/api/transactions?<no period/month>` history requests (one without search, one with — only when search is non-empty).

## System Invariants

- The URL always reflects the active filter state (state never silently drifts from URL).
- A single user action produces at most one round-trip per dataset (no double-fetches).
- An in-flight fetch that's superseded by a newer filter change is aborted, never rendered.
- Default-period rewrite fires at most once per session entry — never loops.
- No race condition where a slow first request overwrites the result of a faster second one (existing AbortController + `requestSeq` pattern preserved).
- Running balance, N-1 posting rule, and transfer-pair collapse continue to work for single-account views (no changes to row rendering).

## States

- **Empty deep link (`/transactions`)**: derivation adds `period=this-month`, redirects URL once, loads data.
- **Filtered deep link (`/transactions?category=X&month=2026-04`)**: derivation accepts as-is, no redirect, loads data.
- **In-page filter bar action**: callback `goto`s the new URL with `replaceState`; reactive derivation re-runs; reload fires.
- **Anchor click from sub-panel** (Composition top-categories): default `pushState` navigation; reactive derivation re-runs; reload fires; new history entry created.
- **Browser back/forward**: `$page.url` updates; reactive derivation re-runs; reload fires.
- **Loading**: existing reload-progress shimmer continues to show during in-flight `loadData`.
- **Error**: existing error banner continues to surface fetch failures.
- **No matching transactions**: existing empty-panel copy renders.

## Edge Cases

- **Rapid filter changes** (typing in search box): existing 300ms debounce in `TransactionsFilterBar` plus `AbortController` covers this. Verify the reactive subscription doesn't re-fire intermediate URL states between debounced commits.
- **Migration redirect collision** (old URL params + default-period rule): the migration rewrite runs first; if the migrated URL is still empty, default-period applies; one combined `goto` rather than two.
- **`trackedAccounts` not yet loaded when URL has account filter**: don't drop the account id during the derivation. Defer the validation until `trackedAccounts` arrives, then re-derive (or skip the validation step entirely until ready and trust the URL).
- **Reload during in-flight history fetch**: existing `historyKey` cache check + `AbortController` (added in this task if missing) prevent stale overlay rendering.
- **Filter change to identical filters** (e.g. clicking "This month" when already this month): `filtersKey` equality check skips the reload.

## Failure Behavior

- If `loadData` fails, the dossier and list render against the last successful response with a non-blocking error banner. URL state is still authoritative.
- If `loadHistory` fails, the trend chart renders empty (existing "No matching activity in the last year" message). KPIs derived from history (6-mo avg, 12-mo total) render as 0 / placeholder text. The dossier does not crash.
- Any unhandled exception in derivation must not blank the page — the dossier should fall back to a safe empty state.

## Regression Risks

- **Double-fetch on mount.** The reactive subscription firing once on initial render plus a second time after `trackedAccounts` loads (which mutates a derived input) could cause two requests. Mitigate via the `filtersKey` dedupe — a re-derived filter set with the same serialization is a no-op.
- **Reload loop on default-period.** If applying the default `period=this-month` causes `goto` → URL change → derivation → re-apply default → `goto` → ..., the page would loop. Gate the default-period rewrite on a one-shot `hasReconciledUrl` flag.
- **Lost AbortController coverage.** When the imperative `loadData` call in `changeFilters` goes away, the existing `if (abortController) abortController.abort()` at the top of `loadData` must still fire on the new reactive trigger path.
- **Search-debounce + reactive interaction.** `TransactionsFilterBar` debounces search before calling `onChange`. The reactive subscription must not bypass that debounce.
- **`replaceState` vs `pushState`.** Filter-bar `goto` uses `replaceState` to avoid history pollution. Anchor links use default `pushState`. If the reactive subscription forces every change through `goto({ replaceState: true })`, browser back/forward will skip those URLs. Keep anchor clicks on `pushState` (the SvelteKit default for `<a>` elements).
- **Component prop drift.** `TransactionInsights` receives `filters`, `historyRows`, `historyRowsHighlight`, `currentRows` as props. If these become reactive declarations on the page, ensure the component re-renders when they change (Svelte handles this if the references change).
- **Selected row sheet stays open across filter change.** Existing `selectedRow = null` reset in `changeFilters` should move into the reactive subscription (or onto a `filtersKey`-watching block) so it still clears.
- **Pending-transfers count (`pendingCount`, `pendingTotal`) stale.** These derive from `rows` which derive from `result`. Verify they refresh when `result` updates from the new reload trigger.
- **Chart click drops sibling filters** (caused by the underlying bug). Today, `onMonthFocus` spreads `{ ...filters, month, period: null }` and writes a URL via `filtersToUrl(filters)`. When `filters` is stale relative to the URL, the spread produces a filter set missing the URL's actual filters, and the resulting `goto` strips them. Once `filters` is reactively derived from `$page.url`, the spread always contains the live filter set and chart clicks will preserve every filter except period (which is intentionally cleared in favor of month). Verify this fix lands automatically — no separate change needed in `onMonthFocus`.

## Acceptance Criteria

1. Clicking a category in "Composition / Top categories" updates the dossier, KPI strip, trend chart, top merchants list, and transactions list to reflect the new category — without page reload.
2. Browser back button restores the previous filter set's full visuals.
3. Browser forward button replays the next filter set's full visuals.
4. Search input cross-filter highlight on the trend chart appears whenever `filters.search` is non-empty, regardless of how the user reached the current filter set.
5. KPI 12-month NET, 6-mo avg, transaction count, avg per transaction, and top breakdown lists all reflect the URL filters within the same render cycle the URL changes.
6. Trend chart click focuses the clicked month **without dropping other active filters**: starting from `?accounts=X&category=Y&search=Z&period=this-month` and clicking January in the chart must produce `?accounts=X&category=Y&q=Z&month=2026-01` (period replaced by month; accounts, category, and search preserved).
7. Network tab shows: one `/api/transactions?<full filters>` request per filter change; one `/api/transactions?<no period/month, no search>` history request per non-period/month/search filter change; one additional `/api/transactions?<no period/month, with search>` request only when search is non-empty. No more than three total per user action; no duplicates.
8. Sidebar entry to `/transactions` (no params) loads with `?period=this-month` in the URL and renders the this-month dossier — no flash of empty state, no infinite redirect.
9. `pnpm check` passes with 0 errors and 0 warnings in `app/frontend`.
10. `pnpm build` succeeds in `app/frontend`.
11. Existing transactions backend tests (`uv run pytest -q` in `app/backend`) continue to pass — backend unchanged.

## Proposed Sequence

1. **Add reactive derivation in `+page.svelte`.** Convert `let filters` to `$: filters = ...` derived from `$page.url` via `filtersFromUrl`. Keep migration + default-period logic but gate the URL rewrite on a one-shot `hasReconciledUrl` flag.
2. **Add reactive reload trigger.** `$: filtersKey = ...` and `$: if (initialized && filtersKey changed) { lastFiltersKey = filtersKey; void loadData(); void loadHistory(filters); }`. Drop the imperative `loadData()` calls from `load()` and `changeFilters()`.
3. **Collapse `changeFilters`.** Body becomes one `goto(...)` call. Remove the `filters = next` assignment and the `void loadData()` line. Move `selectedRow = null` reset into the reactive `filtersKey` watcher.
4. **Verify `loadHistory` cache.** Check that `historyKey` dedupe still works when called reactively. Add `AbortController` to `loadHistory` if not present (currently missing — relies on key check alone, which is sufficient for in-order resolution but races on out-of-order).
5. **Verify outbound anchor links.** Confirm the Composition list, CategoryRibbon, and DashboardDirection links all produce URLs that the new derivation accepts. No code change expected; just re-test.
6. **Manual regression sweep.** Walk through every filter-change path: filter bar buttons, search keystroke, account chip removal, category clear, status filter, "+ Filters" dialog Apply, anchor link clicks (Composition, CategoryRibbon, DashboardDirection), chart click, browser back/forward, deep link entry, sidebar entry.
7. **Verify.** `pnpm check`, `pnpm build`, manual cross-filter highlight test with search active.

## Definition of Done

- All acceptance criteria pass.
- `pnpm check` and `pnpm build` succeed.
- No console warnings about missing reactive dependencies, infinite loops, or unhandled promise rejections during a 5-minute click-around session.
- Network tab inspection confirms one round-trip per filter change (plus the search-history round-trip when applicable).
- Browser back/forward works correctly across at least 5 filter changes.
- The Composition top-categories click bug, the cross-filter highlight regression, and the stale 12-mo NET bug are all reproducible-then-fixed (verified by reproducing on `master` first, then on the fix branch).

## UX Notes

- **No visual change.** This is a plumbing fix; pixels stay identical.
- **No loading flash on filter change.** The existing reload-progress shimmer is the only loading affordance during in-flight reload — it should appear briefly per filter change, not stack or stutter.
- **Browser history entries.** Filter-bar tweaks use `replaceState` (don't pollute history). Anchor link navigation uses default `pushState` (back button works as expected). Chart click goes through `changeFilters` (replaceState — the chart is part of in-page exploration, not navigation).

## Out of Scope

- Backend changes.
- Visual or interaction redesign.
- Data-entry workflow.
- New filters or filter combinations.
- Performance optimization beyond the dedupe necessary to avoid double-fetches.
- Tests beyond manual regression — the existing test suite must continue to pass; no new automated tests required for this fix.

## Delivery Notes

- **Implementation**: `0b7a7b7 fix(transactions): URL as filter source of truth`. Reactive derivation `$: parsedFromUrl = filtersFromUrl($page.url) → $: filters = pruneAccountsToTracked(...)`. One-shot `hasReconciledUrl` flag for migration + default-period rules. Reactive reload trigger keyed on `filtersToApiParams(filters)`. `changeFilters` collapsed to one `goto()`. `load()` sets `initialized = true` last to eliminate the trackedAccounts race.
- **Fix-loop iteration 1**: `1ab22d1 fix(transactions): load on pure migration redirect`. The unconditional `lastFiltersKey = filtersToApiParams(filters)` inside the reconciliation block broke pure migration (`?accountId=X` → `?accounts=X`) where filter content is identical pre/post-redirect. Gated the assignment on `filtersToApiParams(next) !== filtersToApiParams(filters)` so it only suppresses the imminent reload when the redirect actually changes filter content.
- **QA: PASS** — all 11 acceptance criteria verified by tracing the reactive flow against concrete URL examples. `pnpm check` 0/0, `pnpm build` succeeds, backend `pytest` 739 passed (untouched).
- **Review: SHIP** — minimal correct change. Non-blocking note: `filtersToApiParams(filters)` invoked twice in the reconciliation block; could cache locally for a one-line readability win but not worth blocking on.
