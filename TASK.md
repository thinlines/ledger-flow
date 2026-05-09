# Category Insights + Detail Panel (10c)

## Objective

Replace the CSS category trends section with interactive ECharts visuals: a spending-drivers donut showing category breakdown for the focused month, per-row mini sparklines showing 6-month category history, and a selected-category detail panel with a time-series bar chart and lazy-fetched transaction list. Clicking a category anywhere sets `selectedCategory`; clicking a month in the cash flow chart already sets `focusedPeriod` (from 10b). Together these two state variables drive all the new visuals. Clean up dead CSS and deprecated response fields that this task replaces.

## Scope

### Included

1. **Register `PieChart` in `$lib/echarts.ts`.** Add the `PieChart` import from `echarts/charts` and register it alongside `BarChart`. The sparkline and detail-panel time series both use `BarChart` (already registered).

2. **Create `SpendingDriversDonut.svelte`.** New component at `$lib/components/dashboard/SpendingDriversDonut.svelte`. Renders a donut chart (pie with inner radius) showing the category breakdown for a single month. Props: `breakdown` (array of `{ categoryLabel: string; amount: number }`), `formatCurrency` (formatter function). Events: `onCategoryClick(category: string)` — fires with the `categoryLabel` value. Chart lifecycle follows the `CashFlowChart` pattern: `onMount` → `init` + click handler; `$:` reactive update → `setOption`; `onDestroy` → `dispose` + `ResizeObserver` disconnect.

3. **Create `CategorySparkline.svelte`.** New component at `$lib/components/dashboard/CategorySparkline.svelte`. Renders a tiny (no-axis, no-tooltip) ECharts bar chart from an array of amounts. Props: `amounts` (number[]). No events. Fixed height ~24px. Grid: zero padding. Uses muted color (`#94a3b8`). Chart lifecycle: `onMount`/`onDestroy`/`ResizeObserver` same pattern.

4. **Create `CategoryDetailPanel.svelte`.** New component at `$lib/components/dashboard/CategoryDetailPanel.svelte`. Appears when `selectedCategory` is set. Shows:
   - Heading: the category label + a close button.
   - A time-series bar chart (ECharts `BarChart`) showing monthly spending for the selected category, derived from `categoryHistory`.
   - A lazy-fetched transaction list from `GET /api/dashboard/transactions?period={focusedPeriod}&category={selectedCategory}`. Falls back to the most recent month if `focusedPeriod` is null.
   - Each transaction row: date, payee, amount (formatted).
   - Loading state while fetching; empty state if no transactions.
   Props: `category` (ledger account path), `categoryLabel` (pretty name), `categoryHistory` (full array), `focusedPeriod` (string | null), `currentMonth` (string), `formatCurrency` (formatter). Events: `onClose()`.

5. **Replace the category trends section in `+page.svelte`.** The current `categories-panel` article renders a current-vs-previous CSS meter for each category from `categoryTrends`. Replace with:
   - A spending-drivers donut showing categories for the focused month (or current month if no drill). Driven by `categoryHistory` filtered to `focusedPeriod ?? currentMonth`.
   - Below the donut: a category list where each row shows category name, amount for the focused month, and a 6-month mini sparkline. Each row is clickable → sets `selectedCategory`.
   - The `CategoryDetailPanel` renders conditionally when `selectedCategory` is not null.

6. **Add `selectedCategory` state to `+page.svelte`.** New reactive variable: `let selectedCategory: string | null = null;` and a derived `selectedCategoryLabel`. Wire it:
   - Donut click → sets `selectedCategory`.
   - Category row click → sets `selectedCategory`.
   - Detail panel close → resets to null.

7. **Derive category data from `categoryHistory` instead of `categoryTrends`.** Add reactive declarations:
   - `categoryBreakdown`: `categoryHistory` filtered to `focusedPeriod ?? currentMonth`, sorted by amount descending.
   - `categorySparklineData`: a Map from category → last 6 months of amounts.
   These replace `filteredCategoryTrends` and `categoryMax`.

8. **Clean up dead code.**
   - Remove `filteredCategoryTrends`, `categoryMax`, `formatTrend` function, `barWidth` function.
   - Remove `categoryTrends` from the `DashboardOverview` type (no longer consumed).
   - Remove `.bar-income`, `.bar-spending`, `.category-meter.current`, `.category-meter.previous`, `.category-row + .category-row` CSS rules.
   - Keep `.drilldown-link`, `.transaction-row`, `.balance-group`, `.date-group` CSS (still used).

### Explicitly Excluded

- Global date range picker (10d).
- Weekly/daily drill-down (10e).
- Backend changes.
- Changes to the cash flow chart, balance sheet, direction panel, hero stats, or recent transactions sections.
- Removing `cashFlow.series` from the `DashboardOverview` type (the cash flow section still reads `cashFlow.currentMonth`/`cashFlow.net`; full deprecation is a follow-up).
- Pagination in the transaction list (10c shows up to 50 transactions — the endpoint default).

## System Behavior

### Inputs

- Dashboard loads `GET /api/dashboard/overview`. Response includes `categoryHistory[]` and `cashFlowHistory[]`.
- User clicks a donut slice or category row → `selectedCategory` is set.
- User clicks close on the detail panel → `selectedCategory` is reset.
- `focusedPeriod` (set by CashFlowChart click from 10b) drives which month the donut and category list show.
- When `selectedCategory` is set, the detail panel fetches `GET /api/dashboard/transactions?period={period}&category={selectedCategory}`.

### Logic

**Category breakdown derivation:**
```typescript
$: focusedMonth = focusedPeriod ?? dashboard?.cashFlow.currentMonth ?? '';
$: categoryBreakdown = (dashboard?.categoryHistory ?? [])
  .filter(r => r.month === focusedMonth)
  .sort((a, b) => b.amount - a.amount);
```

**Sparkline data derivation:**
```typescript
$: sparklineMonths = (dashboard?.cashFlowHistory ?? []).slice(-6).map(r => r.month);
$: categorySparklineData = (() => {
  const byCategory = new Map<string, number[]>();
  for (const row of dashboard?.categoryHistory ?? []) {
    if (!sparklineMonths.includes(row.month)) continue;
    if (!byCategory.has(row.category)) {
      byCategory.set(row.category, new Array(sparklineMonths.length).fill(0));
    }
    const idx = sparklineMonths.indexOf(row.month);
    byCategory.get(row.category)![idx] = row.amount;
  }
  return byCategory;
})();
```

Note: sparkline amounts must be aligned to the `sparklineMonths` array — months with no spending for that category show 0, not a missing slot.

**Donut option builder:**
```typescript
function buildDonutOption(breakdown, formatCurrency) {
  return {
    tooltip: { trigger: 'item', valueFormatter: v => formatCurrency(Number(v)) },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      label: { show: false },
      data: breakdown.map(r => ({ name: r.categoryLabel, value: r.amount }))
    }]
  };
}
```

**Detail panel transaction fetch:**
The fetch fires reactively when `selectedCategory` changes (or `focusedPeriod` changes while a category is selected). Use the existing `apiGet` helper. The `period` param defaults to `focusedMonth` (same month the donut shows). An `AbortController` cancels in-flight requests when the category changes.

**Detail panel time-series chart:**
Filter `categoryHistory` to the selected category, render as a bar chart with month labels on x-axis — same option shape as `CashFlowChart` but single series.

### Outputs

- Spending-drivers donut replaces the old category trends current/previous meters.
- Category rows show name, amount, and a 6-month sparkline.
- Clicking a category opens a detail panel with time-series chart + transaction list.
- Close button dismisses the detail panel.
- Changing `focusedPeriod` (from the cash flow chart) updates the donut and category list reactively.

## System Invariants

- `categoryHistory` is the sole data source for all category visuals. `categoryTrends` from the API response is no longer consumed.
- The donut and category list must show data for the same month — both driven by `focusedMonth`.
- The detail panel must not fetch transactions until `selectedCategory` is set. No speculative loading.
- All ECharts instances (`dispose()`) must be cleaned up in `onDestroy`.
- The cash flow chart, balance sheet, direction panel, hero stats, and recent transactions sections must render identically to before this change.
- Sparkline data must be aligned: if a category has no spending in a month, that slot is 0 (not omitted).

## States

- **Default (no selection):** Donut shows categories for current month. Category list shows all categories with sparklines. No detail panel.
- **Month focused:** `focusedPeriod` is set from the cash flow chart. Donut and category list update to show that month's data.
- **Category selected:** Detail panel appears. Time-series chart shows the selected category's history. Transaction list shows loading, then transactions.
- **Transaction list loading:** Spinner or "Loading..." text inside the detail panel.
- **Transaction list empty:** "No transactions found for this period."
- **Empty categoryHistory:** "No spending data available." in place of donut + list.
- **Category selected + no transactions for period:** Transaction list shows empty state; time-series chart still shows (category may have data in other months).

## Edge Cases

- **focusedPeriod changes while detail panel is open:** The transaction list re-fetches for the new period. AbortController cancels the in-flight request.
- **Category exists in sparkline months but not in focused month:** Category does not appear in the donut or list for that month. If it was previously selected, the detail panel stays open (the time-series chart still has data from other months).
- **Single category:** Donut renders as a full ring. Category list has one row.
- **Many categories (>10):** Donut shows all slices. Category list scrolls naturally. No truncation.
- **Very long category names:** Truncate with ellipsis in the row; full name in the detail panel heading and tooltip.

## Failure Behavior

- If the transaction fetch fails (network error, 422, 500), show "Could not load transactions." in the detail panel. Do not crash or dismiss the panel.
- If `categoryHistory` is missing from the response, treat as empty array. Show empty state.

## Regression Risks

- **Cash flow chart.** Must not be touched. `CashFlowChart.svelte` and the cash flow section template stay as-is.
- **Balance sheet, direction panel, recent transactions, hero stats.** All untouched.
- **`barWidth` removal.** Verify it's not used anywhere else before removing. (It was only used in the old category meters and the old cash flow bars, both now replaced.)
- **`categoryTrends` type removal.** Verify no other code reads this field. The only consumer was the old `filteredCategoryTrends` reactive block.
- **ECharts instance leaks.** Each new component (`SpendingDriversDonut`, `CategorySparkline`, `CategoryDetailPanel`) creates an ECharts instance. Each must `dispose()` in `onDestroy`. Sparklines are rendered per-row — if 10 categories are visible, 10 sparkline instances exist. This is fine for <20 categories; flag if performance degrades.

## Acceptance Criteria

- `pnpm check` passes in `app/frontend`.
- `pnpm build` succeeds in `app/frontend`.
- `PieChart` is registered in `$lib/echarts.ts`.
- `SpendingDriversDonut.svelte` renders a donut chart from `categoryBreakdown`.
- Clicking a donut slice sets `selectedCategory`.
- `CategorySparkline.svelte` renders a mini bar chart (~24px tall) with no axes from an amounts array.
- Each category row in the list shows: category name, amount for the focused month, and a sparkline.
- Clicking a category row sets `selectedCategory`.
- `CategoryDetailPanel.svelte` appears when `selectedCategory` is set.
- The detail panel shows a time-series bar chart for the selected category.
- The detail panel fetches and displays transactions from `GET /api/dashboard/transactions`.
- The detail panel close button resets `selectedCategory` to null.
- Changing `focusedPeriod` updates the donut and category list reactively.
- Dead code removed: `filteredCategoryTrends`, `categoryMax`, `formatTrend`, `barWidth`, `.bar-income`, `.bar-spending`, `.category-meter` CSS, `categoryTrends` from `DashboardOverview` type.
- The old CSS category trends section (current/previous meters) is fully replaced.
- All other dashboard sections render unchanged.
- All ECharts instances call `dispose()` in `onDestroy`.

## Proposed Sequence

1. **Register `PieChart` in `$lib/echarts.ts`.** Verify `pnpm check` passes.

2. **Create `CategorySparkline.svelte`.** Minimal component — fixed height, no axes, no events. Verify it renders from hardcoded data.

3. **Create `SpendingDriversDonut.svelte`.** Donut chart with click handler. Verify it renders and fires `onCategoryClick`.

4. **Create `CategoryDetailPanel.svelte`.** Time-series chart + lazy transaction list with loading/empty/error states. Wire the `apiGet` fetch with AbortController.

5. **Wire into `+page.svelte`.** Add `selectedCategory`, `focusedMonth`, `categoryBreakdown`, `sparklineMonths`, `categorySparklineData` reactive declarations. Replace the `categories-panel` article content. Add `CategoryDetailPanel` conditionally. Import new components.

6. **Clean up dead code.** Remove `filteredCategoryTrends`, `categoryMax`, `formatTrend`, `barWidth`, `categoryTrends` from type, dead CSS (`.bar-income`, `.bar-spending`, `.category-meter.*`, `.category-row + .category-row`).

7. **Verify.** `pnpm check`, `pnpm build`. All other dashboard sections unchanged.

## Definition of Done

- All acceptance criteria pass.
- `pnpm check` and `pnpm build` succeed.
- Donut, sparklines, and detail panel render correctly.
- Lazy transaction fetch works with loading/empty/error states.
- All ECharts instances disposed on destroy.
- Dead CSS and deprecated type fields removed.
- Cash flow chart, balance sheet, direction panel, recent transactions, hero stats unchanged.

## UX Notes

- **Donut height:** ~200px. Centered in the panel.
- **Donut colors:** Use ECharts default palette — distinct colors per slice. No custom palette for 10c.
- **Sparkline height:** ~24px. Width: fill available (match the row).
- **Sparkline color:** Muted (`#94a3b8`).
- **Category list row:** Category name (left), amount for focused month (right), sparkline below spanning the row width. Clickable — cursor pointer, hover highlight.
- **Detail panel:** Appears below the category section (not a modal or sidebar). Card style (`view-card`). Close button top-right (X icon or "Close" text button).
- **Transaction rows in detail panel:** Simple list — date, payee, amount. No actions, no overflow menu. Styled like the recent transactions section for consistency.
- **Heading for focused month:** When `focusedPeriod` is set, show "{Month Name} spending" above the donut. When null, show "This month's spending".

## Out of Scope

- Global date range picker (10d).
- Weekly/daily drill-down (10e).
- Backend changes.
- Transaction pagination in the detail panel.
- Changes to cash flow chart, balance sheet, direction panel, hero stats, or recent transactions.
- Custom donut color palette.
