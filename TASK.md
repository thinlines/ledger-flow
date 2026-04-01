# Current Task

## Title

Dashboard drill-down: clickable insights and cross-account activity view (Feature 4)

## Objective

Dashboard category trends and cash flow rows become clickable links that open a filterable cross-account activity view on the transactions page. Users can investigate what they see on the dashboard without switching mental context or manually navigating to per-account registers.

## Scope

### Included

- Backend: new `/api/transactions/activity` endpoint returning cross-account transactions with optional category and month filters.
- Frontend (transactions page): new "All activity" view mode alongside the existing per-account register, with date-period presets and optional category filter.
- Frontend (dashboard): category trend rows link to `/transactions?view=activity&category={account}` filtered to the current month. Cash flow month rows link to `/transactions?view=activity&month={YYYY-MM}`.
- URL-param filter state so dashboard links work as deep links and browser back preserves context.

### Explicitly Excluded

- Changes to the per-account register view (existing behavior untouched).
- Transaction editing (deferred).
- Custom date-range picker (presets only for now).
- Changes to the dashboard layout, hero, balance sheet, or recent activity panel.
- Changes to import, review, rules, setup, or accounts pages.
- Pagination (the activity view returns all matching transactions; the 6-month window keeps volume manageable).

## System Behavior

### 1. Backend: Cross-Account Activity Endpoint

**Inputs**

- `GET /api/transactions/activity`
- Optional query params:
  - `category`: ledger account path (e.g., `Expenses:Food:Groceries`). Filters to transactions that have a posting to this account.
  - `month`: `YYYY-MM` string. Filters to transactions with `posted_on` in that calendar month.
  - `period`: preset name — `this-month`, `last-30`, `last-3-months`. Applied only when `month` is absent. Default: `last-3-months`.

**Logic**

- Load all transactions via `load_transactions(config)` (same as dashboard service).
- Exclude generated opening balance transactions (`is_generated_opening_balance_transaction`).
- Apply filters:
  - If `month` is provided, include only transactions where `posted_on` falls within that calendar month.
  - If `month` is absent, apply `period` preset relative to today: `this-month` = current calendar month, `last-30` = last 30 calendar days inclusive, `last-3-months` = current month and two prior months.
  - If `category` is provided, include only transactions that have at least one posting whose account matches `category` exactly or starts with `category:` (to support parent-category filtering like `Expenses:Food` matching `Expenses:Food:Groceries`).
- For each matching transaction, build a row using the same `_primary_posting`, `_primary_account_display`, and `_transaction_category` helpers from `dashboard_service.py`. Extract these helpers to a shared location if needed, or import them directly.
- Sort results most-recent-first.
- Return:
  ```json
  {
    "baseCurrency": "USD",
    "period": "last-3-months",
    "category": "Expenses:Food:Groceries" | null,
    "month": "2026-03" | null,
    "transactions": [
      {
        "date": "2026-03-28",
        "payee": "Grocery Market",
        "accountLabel": "Wells Fargo Checking",
        "importAccountId": "checking" | null,
        "category": "Food / Groceries",
        "categoryAccount": "Expenses:Food:Groceries",
        "amount": -84.30,
        "isIncome": false,
        "isUnknown": false
      }
    ],
    "totalCount": 42
  }
  ```

**Outputs**

- JSON response with filtered transaction list, echo of active filters, and total count.

### 2. Frontend: Activity View on Transactions Page

**Inputs**

- URL query params: `view=activity`, optional `category`, `month`, `period`.
- User interactions: period preset selector, optional category badge/clear.

**Logic**

- On mount, read `$page.url.searchParams`. If `view=activity`, enter activity mode; otherwise, existing per-account register behavior (unchanged).
- In activity mode:
  - Fetch `/api/transactions/activity` with the active filters.
  - Display a period preset selector: **This month** | **Last 30 days** | **Last 3 months**. Default: `last-3-months` unless `month` param overrides it.
  - When `month` is present, show it as the active time filter (e.g., "March 2026") with a clear button that returns to the default preset.
  - When `category` is present, show it as an active filter chip (e.g., "Food / Groceries") with a clear button.
  - Render transactions in a flat list grouped by date (reuse the day-grouping pattern from the dashboard: "Today", "Yesterday", "Mar 27").
  - Each transaction row shows: payee, date, account label, category, amount (signed, colored).
- The account-selector dropdown is hidden in activity mode. A "Back to account view" link or the account selector returning switches back to per-account mode.
- View mode toggle: a segmented control or tab-like element near the top — "All activity" | per-account dropdown. "All activity" is selected when `view=activity`.

**Outputs**

- Transactions page renders a cross-account activity list when `view=activity` is in the URL.
- Filters update the URL via `goto()` so back/forward work.

### 3. Frontend: Dashboard Clickable Links

**Inputs**

- Category trend rows: `row.account` (ledger account path, e.g., `Expenses:Food:Groceries`).
- Cash flow month rows: `row.month` (e.g., `2026-03`).

**Logic**

- Wrap each category trend row in an `<a>` linking to `/transactions?view=activity&category={row.account}`. The link filters to the current month implicitly (the default period will show recent activity including the current month).
- Wrap each cash flow month row in an `<a>` linking to `/transactions?view=activity&month={row.month}`.
- Links should be styled to not disrupt the existing visual pattern — no underlines or color changes. Use `text-decoration: none; color: inherit` with a subtle hover indicator (slight background shift or underline).

**Outputs**

- Category trend rows and cash flow rows are clickable. Clicking navigates to the transactions page with the appropriate filter pre-applied.

## System Invariants

- The activity view must use the same transaction data source as the dashboard (`load_transactions`). Numbers must be consistent — if the dashboard shows $84.30 in Groceries, the drill-down must include that transaction.
- Finance-first language only. No "ledger account", "posting", or "journal" in UI copy.
- The existing per-account register view must be completely unchanged. Activity mode is additive.
- URL param state must survive page reload — all filters are encoded in query params.
- Category filtering uses the ledger account path as the key (not the display name) to avoid ambiguity.

## States

### Activity View
- **Default (no filters)**: Shows last 3 months of cross-account activity.
- **Month filter active**: Shows all transactions in the specified month.
- **Category filter active**: Shows transactions matching the category, within the active time window.
- **Both filters active**: Intersection — transactions matching the category within the specified month.
- **No results**: "No transactions match these filters." with a clear-filters action.
- **Loading**: Spinner or skeleton consistent with existing transaction page loading state.
- **Error**: Existing error display pattern.

### Dashboard Links
- **Category row hover**: Subtle visual indicator (slight background, cursor pointer).
- **Cash flow row hover**: Same treatment.

## Edge Cases

- **Category with no activity in the time window**: Empty state with clear-filters option. Not an error.
- **Month with zero transactions**: Same empty state.
- **Category account path contains special characters**: URL-encode the `category` param. The backend receives the decoded path.
- **User navigates directly to `/transactions?view=activity` with no filters**: Shows last 3 months of all activity (default period).
- **User switches from activity view to per-account and back**: URL params update correctly; activity filters are preserved in the URL and restored when switching back.
- **Very large result set**: The 3-month default window and optional category filter keep volume reasonable. No pagination in this task — acceptable for personal finance volumes (typically <500 transactions/month).

## Failure Behavior

- If the activity endpoint returns an error, show the standard error state. Do not fall back to the per-account view silently — the user clicked a specific filter and should see that it failed.
- If a `category` param references a nonexistent account, return an empty result set (not a 404). The category may have existed in a prior month but have no current activity.

## Regression Risks

- **Per-account register**: The existing register view must work identically. The `view=activity` param triggers a separate code path; the default (no `view` param or `view` absent) must load the register as before.
- **Dashboard layout**: Wrapping rows in `<a>` tags could affect flex/grid layout or spacing. Verify category trend and cash flow sections render identically with clickable rows.
- **Transaction helper extraction**: If `_primary_posting`, `_primary_account_display`, or `_transaction_category` are moved to a shared module, existing dashboard service imports must be updated. Run `uv run pytest -q` to verify.
- **URL param conflicts**: The transactions page already uses `accountId` as a query param. Ensure `view=activity` and `accountId` don't produce conflicting states — when `view=activity`, `accountId` should be ignored.

## Acceptance Criteria

- Clicking a category trend row on the dashboard navigates to `/transactions?view=activity&category={account}` and shows matching transactions.
- Clicking a cash flow month row navigates to `/transactions?view=activity&month={YYYY-MM}` and shows matching transactions.
- The transactions page shows "All activity" mode with a cross-account transaction list when `view=activity` is in the URL.
- Period presets (This month, Last 30 days, Last 3 months) filter the visible transactions.
- Category and month filters can be cleared individually.
- The per-account register view is completely unchanged when `view` param is absent.
- Filters are encoded in URL params; page reload preserves filter state.
- Empty state renders when no transactions match the active filters.
- Transaction amounts and categories in the activity view match the dashboard exactly.
- No layout regression in dashboard category trends or cash flow sections.
- `pnpm check` passes.
- `uv run pytest -q` passes.

## Proposed Sequence

1. **Backend: build activity service** — create `build_activity_view()` in a new `activity_service.py` (or extend `dashboard_service.py`). Reuse `_primary_posting`, `_primary_account_display`, `_transaction_category` from dashboard service. Accept optional `category`, `month`, `period` params. Write tests covering: unfiltered, month-only, category-only, both filters, empty result, category prefix matching.
2. **Backend: wire endpoint** — add `GET /api/transactions/activity` in `main.py`. Pass query params to the service function.
3. **Frontend: activity view scaffold** — add `view` URL param handling to the transactions page. When `view=activity`, render a new activity panel instead of the per-account register. Add the period preset selector. Fetch from the new endpoint.
4. **Frontend: transaction list rendering** — render activity results with day-grouped date headers (reuse the pattern from dashboard 4b). Show payee, account label, category, and signed amount per row.
5. **Frontend: filter controls** — add category chip display with clear button. Add month display with clear button. Wire preset selector to update URL and refetch.
6. **Frontend: view toggle** — add "All activity" option alongside the account-selector dropdown so users can switch between modes.
7. **Dashboard: clickable category rows** — wrap each category trend row in an `<a>` to `/transactions?view=activity&category={row.account}`. Style for no visual disruption + hover indicator.
8. **Dashboard: clickable cash flow rows** — wrap each cash flow row in an `<a>` to `/transactions?view=activity&month={row.month}`. Same styling treatment.
9. **Verify** — run `pnpm check` and `uv run pytest -q`. Test drill-down from dashboard to activity view for both category and cash flow links. Test all period presets. Test filter clearing. Test per-account register is unchanged. Check both breakpoints (1100px, 720px).

## Definition of Done

- Dashboard insights are no longer dead ends — every category trend and cash flow row is a clickable path to transaction-level detail.
- The cross-account activity view answers "show me all the Groceries transactions this month" without requiring the user to know which account they came from.
- Per-account register is untouched.
- Filters persist in the URL.
- No regressions in dashboard layout, transaction page, or existing tests.
- `pnpm check` and `uv run pytest -q` pass.

## UX Notes

- The activity view should feel like a natural extension of the transactions page, not a separate feature. Same visual language: card layout, typography, spacing.
- Day-grouped date headers in the activity list should match the dashboard's recent activity pattern for visual consistency.
- Filter chips (category, month) should look like the pill/badge pattern used elsewhere in the app — small, muted, with an "x" to clear.
- The period preset selector should match the cash flow segmented toggle pattern (pill-shaped, text-level) for visual consistency.
- Dashboard link hover should be very subtle — the rows don't currently look clickable, so the hover state signals interactivity without changing the resting visual.
- Consider adding a small arrow or "View details" tooltip on hover for dashboard rows to signal the drill-down affordance.

## Out of Scope

- Per-account register changes. Transaction editing. Custom date-range picker. Pagination. Changes to dashboard layout beyond adding click handlers. Changes to import, review, rules, setup, or accounts pages.

## Replacement Rule

Replace this file when the next active engineering task begins.
