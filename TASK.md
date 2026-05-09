# Dashboard Redesign: The Pulse (10c-redesign)

## Objective

Redesign the dashboard layout to prioritize the cash flow chart as the hero visual, replace the donut + category list with a compact horizontal category ribbon using SVG line sparklines, remove the detail panel in favor of transaction page drill-through, and reorder sections for progressive disclosure. The user should say "wow" when they open the app.

## Scope

### Included

1. **Promote cash flow chart to position 2** (immediately after hero stats). Remove the two-column `[recent activity | spending breakdown]` layout that currently sits between hero and cash flow. The chart becomes the dashboard's visual centerpiece.

2. **Make the chart taller and interactive.** Increase from `h-48` to `h-56`. Add selected-month emphasis: when `focusedPeriod` is set, the selected month's bars stay full opacity while others fade to 35%. Add `cursor: 'pointer'` to the ECharts config. Integrate the breadcrumb inline into the cash flow section header (remove `DrillBreadcrumb.svelte` as a separate component).

3. **Replace donut + category list with `CategoryRibbon.svelte`.** A horizontal scrolling strip of category chips. Each chip shows: category name, amount, an inline SVG polyline sparkline (2px line, not ECharts bars), and a % change indicator. Chips link to `/transactions?category={account}` — drill-through, not in-page panel. Horizontal scroll with CSS scroll-snap. ~80px total height replaces ~500px of donut + list.

4. **Inline SVG sparklines.** Replace ECharts `CategorySparkline.svelte` with a simple `<svg><polyline>` component — ~20 lines, no ECharts instance, no dispose needed, renders instantly. Line color uses `--brand`. Height: 16px.

5. **Remove detail panel and donut.** Delete `CategoryDetailPanel.svelte`, `SpendingDriversDonut.svelte`, `CategorySparkline.svelte`. Remove `selectedCategory` state, `selectedCategoryLabel`, and all detail panel wiring from `+page.svelte`. Remove `PieChart` from `$lib/echarts.ts` (no longer needed).

6. **Reorder sections.** New flow: hero → cash flow chart → category ribbon → direction panel → `[recent activity | balance sheet]`. The direction panel moves below the category ribbon (was between recent activity and cash flow). Recent activity and balance sheet stay side-by-side as the reference layer.

7. **Clean up `DrillBreadcrumb.svelte`.** The breadcrumb is now inline in the cash flow section header. Delete the separate component file.

### Explicitly Excluded

- Backend changes.
- Changes to the direction panel component (`DashboardDirection.svelte`).
- Changes to the balance sheet section or recent activity section content (only their position changes).
- Global date range picker (10d).
- Mobile-specific redesign beyond what flows naturally from the new layout.

## System Behavior

### Inputs

- Dashboard loads `GET /api/dashboard/overview` (unchanged).
- User clicks a bar in the cash flow chart → `focusedPeriod` is set, bars dim/highlight, category ribbon updates.
- User clicks "All months" in the inline breadcrumb → `focusedPeriod` resets, bars restore full opacity.
- User clicks a category chip → navigates to `/transactions?category={account}`.

### Logic

**Cash flow chart emphasis:**
When `focusedPeriod` is set, pass a `focusedIndex` prop to `CashFlowChart`. The chart sets `itemStyle.opacity: 0.35` on non-focused bars and `1.0` on the focused month. Transition via ECharts animation (default 300ms).

**Category ribbon derivation:**
```typescript
$: focusedMonth = focusedPeriod ?? dashboard?.cashFlow.currentMonth ?? '';
$: categoryBreakdown = (dashboard?.categoryHistory ?? [])
  .filter(r => r.month === focusedMonth)
  .sort((a, b) => b.amount - a.amount);
$: sparklineMonths = (dashboard?.cashFlowHistory ?? []).slice(-6).map(r => r.month);
$: categorySparklineData = /* same Map<string, number[]> derivation as current */;
```

**SVG sparkline component (`SparklineLine.svelte`):**
```svelte
<script>
  export let values: number[];
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const w = 100;
  const h = 16;
  $: points = values
    .map((v, i) => `${(i / Math.max(values.length - 1, 1)) * w},${h - ((v - min) / range) * h}`)
    .join(' ');
</script>

<svg viewBox="0 0 {w} {h}" class="h-4 w-full" preserveAspectRatio="none">
  <polyline
    points={points}
    fill="none"
    stroke="var(--brand)"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
  />
</svg>
```

**Category chip:**
Each chip is an `<a>` tag linking to `/transactions?category={account}`. Shows category label, amount for focused month, SVG sparkline, and a change indicator vs prior month.

**Inline breadcrumb:**
Replaces the `DrillBreadcrumb` component. Rendered directly in the cash flow section header:
- No focus: `<h3>Monthly income and spending</h3>`
- Focused: `<button>All months</button> → <span>April 2026</span>`

### Outputs

- Dashboard loads with net worth hero + cash flow chart visible above the fold.
- Category ribbon shows a compact horizontal strip of clickable category chips.
- Clicking a chart bar dims other months and updates the category ribbon.
- Clicking a category chip navigates to the transactions page.
- No donut, no detail panel, no vertical category list.

## System Invariants

- The cash flow chart must display the same data as before (from `cashFlowHistory`).
- Category ribbon must show the same categories and amounts as the old breakdown (from `categoryHistory` filtered to `focusedMonth`).
- All existing links (transactions drill-through, manage accounts, review, etc.) must continue to work.
- The direction panel, recent activity, and balance sheet sections must render with identical content — only their position on the page changes.
- No ECharts instance leaks — the removed components' instances are gone; the remaining `CashFlowChart` still disposes properly.

## States

- **Default:** Hero + cash flow chart + category ribbon visible. No month focused.
- **Month focused:** Chart bars dim except selected. Breadcrumb appears. Ribbon updates to show that month's categories.
- **Empty categoryHistory:** Ribbon shows "No spending data yet."
- **Empty cashFlowHistory:** Chart area shows "No income or spending recorded yet."
- **Loading:** Existing loading behavior unchanged.

## Edge Cases

- **Category with no sparkline data:** Show flat line (all zeros → horizontal line at midpoint).
- **Single month of data:** Sparkline is a single point (dot, not line).
- **Many categories (>8):** Ribbon scrolls horizontally. Fade mask on right edge hints at more content.
- **Very long category name:** Truncated with ellipsis in the chip (`truncate` class).
- **Ribbon on mobile:** Touch-scrollable horizontally.

## Regression Risks

- **Section reordering.** Moving sections could break the `{#if dashboard}` gate or the `{:else}` branches. The gate must still wrap all data-dependent sections.
- **Removing PieChart from echarts.ts.** Verify no other component imports it.
- **Removing selectedCategory state.** Verify no other code references it after the donut/detail panel are removed.
- **Cash flow chart prop change.** Adding `focusedIndex` must not break the existing chart when no month is focused (null index → all bars full opacity).

## Acceptance Criteria

- `pnpm check` passes.
- `pnpm build` succeeds.
- Cash flow chart is the first visual after the hero stats (no two-column section between them).
- Cash flow chart is taller (`h-56`) with pointer cursor on bar hover.
- Clicking a month bar dims other months (opacity transition) and shows inline breadcrumb.
- Category ribbon renders as a horizontal scrolling strip of chips.
- Each chip shows: category name, amount, SVG line sparkline, and links to `/transactions?category=...`.
- Clicking a chip navigates to the transactions page (not an in-page panel).
- No donut chart on the page.
- No detail panel on the page.
- `SpendingDriversDonut.svelte`, `CategorySparkline.svelte`, `CategoryDetailPanel.svelte`, `DrillBreadcrumb.svelte` are deleted.
- `PieChart` removed from `$lib/echarts.ts`.
- Direction panel renders below the category ribbon.
- Recent activity and balance sheet render side-by-side below the direction panel.
- All content and links are preserved — only layout position changes.

## Proposed Sequence

1. **Create `SparklineLine.svelte`.** Inline SVG polyline component. ~20 lines.
2. **Create `CategoryRibbon.svelte`.** Horizontal scrolling category chips with sparklines and drill-through links.
3. **Modify `CashFlowChart.svelte`.** Add `focusedIndex` prop for emphasis/de-emphasis. Add cursor pointer.
4. **Rewrite `+page.svelte` layout.** New section order: hero → cash flow → category ribbon → direction → [recent | balance sheet]. Inline breadcrumb in cash flow header. Remove selectedCategory state and donut/detail panel wiring. Remove old two-column layout for recent + categories.
5. **Delete removed components.** `SpendingDriversDonut.svelte`, `CategorySparkline.svelte`, `CategoryDetailPanel.svelte`, `DrillBreadcrumb.svelte`.
6. **Update `$lib/echarts.ts`.** Remove `PieChart` import and registration.
7. **Clean up dead CSS.** Remove `.category-item` styles, any remaining dead selectors.
8. **Verify.** `pnpm check`, `pnpm build`.

## Definition of Done

- All acceptance criteria pass.
- `pnpm check` and `pnpm build` succeed.
- The dashboard feels cohesive — cash flow chart dominates, categories are scannable, drill-through is obvious.
- No orphaned components or dead imports.
- Progressive disclosure: primary (hero + chart + ribbon) → secondary (direction) → tertiary (recent + accounts).

## UX Notes

- **Chart height:** `h-56` (224px) — gives bars room to breathe.
- **Ribbon chip size:** `min-w-[140px] max-w-[180px]`, `py-3 px-4`.
- **Sparkline:** 2px `var(--brand)` polyline, `h-4` (16px), `preserveAspectRatio="none"`.
- **Chip hover:** `translateY(-1px)` + `shadow-md` + `border-brand/30` transition (200ms).
- **Ribbon scroll:** `overflow-x-auto`, `scroll-snap-type: x mandatory`, `scroll-snap-align: start` per chip.
- **Bar emphasis:** 200ms opacity transition. Focused bar: `opacity: 1`. Others: `opacity: 0.35`.
- **Inline breadcrumb:** Same styling as the old `DrillBreadcrumb` — `text-brand font-semibold` button + `→` separator + month name.

## Out of Scope

- Global date range picker (10d).
- Backend changes.
- Direction panel redesign.
- Mobile-specific layout beyond natural responsive flow.
- Custom chart color palette.
