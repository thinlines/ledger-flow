# ECharts Cash Flow Chart + Drill State (10b)

## Objective

Replace the CSS-bar cash flow section on the dashboard with an interactive ECharts grouped bar chart. Clicking a month bar sets a drill-down focus (`drillState`) that downstream components (10c, 10d) will consume. A breadcrumb strip shows the current drill path and allows drilling back up. The chart reads from `cashFlowHistory` (shipped in 10a) instead of the old 6-month `cashFlow.series`.

## Scope

### Included

1. **Install `echarts`.** `pnpm add echarts` in `app/frontend`.

2. **Create `$lib/echarts.ts`.** Shared ECharts registration module using tree-shaking ESM imports. Registers `BarChart`, `TooltipComponent`, `GridComponent`, `LegendComponent`, and `CanvasRenderer`. Exports the configured `echarts` namespace. All chart components import from here — no per-component `echarts.use()` calls.

3. **Create `CashFlowChart.svelte`.** New component at `$lib/components/dashboard/CashFlowChart.svelte`. Renders a grouped bar chart (income + spending per month) from the `cashFlowHistory` data. Props: `series` (the cash flow rows to display), `currentMonth` (for partial-month labeling), `formatCurrency` (formatter function). Events: `onMonthClick(month: string)`. Chart lifecycle: `onMount` → `echarts.init()` + click handler registration; `$effect` → `setOption()` on data changes; `onDestroy` → `dispose()`. Must handle container resize (use `ResizeObserver` or ECharts `resize()` on window resize).

4. **Create `DrillBreadcrumb.svelte`.** New component at `$lib/components/dashboard/DrillBreadcrumb.svelte`. Shows the current drill path as a breadcrumb strip. When `drillState.focusedPeriod` is null, shows nothing (or just "All months" as static text, depending on layout). When focused on a month, shows: `All months → April 2026`. Clicking "All months" resets `drillState.focusedPeriod` to `null`. Props: `focusedPeriod` (string | null), `currentMonth` (string). Events: `onReset()`.

5. **Add `DrillState` type and reactive state to `+page.svelte`.** Add `cashFlowHistory` and `categoryHistory` types to the `DashboardOverview` type. Add `drillState` reactive variable (`$state` or Svelte 4 `let` — match the page's current pattern, which uses `$:` reactive declarations, not Svelte 5 runes). The `drillState` only carries `focusedPeriod: string | null` for now (month-level only, `level` field deferred to 10e).

6. **Replace the CSS cash flow section.** Remove the `cashflow-presets` toggle buttons, the `visibleCashFlow` reactive chain, `cashFlowMax`, `barWidth` usage in the cash flow section, and the `{#each visibleCashFlow}` row loop. Replace with `<CashFlowChart>` consuming `cashFlowHistory`. The preset toggle is eliminated — the chart shows all available history natively (ECharts handles scrolling/zooming if needed). Keep the section card, eyebrow, and heading structure.

7. **Wire month click → drill state.** Clicking a bar in `CashFlowChart` sets `drillState.focusedPeriod` to the clicked month. Show `DrillBreadcrumb` above the chart when a month is focused. Clicking breadcrumb resets to null.

### Explicitly Excluded

- Category sparklines, spending-drivers donut, category detail panel (10c).
- Global date range picker (10d).
- Weekly/daily drill-down levels (10e).
- Backend changes — 10a already provides all needed data.
- Removing `categoryTrends` or `cashFlow.series` from the `DashboardOverview` type — the category trends section still reads `categoryTrends`. Removal happens in 10c.
- Changes to the category trends section, recent transactions, balance sheet, direction panel, or any other dashboard section.
- The `barWidth` function and category-meter CSS — still used by the category trends section. Do not remove.
- Mobile-specific layout changes beyond what ECharts handles natively.

## System Behavior

### Inputs

- Dashboard loads `GET /api/dashboard/overview` (existing). The response now includes `cashFlowHistory[]`.
- User clicks a bar in the cash flow chart → `drillState.focusedPeriod` is set.
- User clicks "All months" in the breadcrumb → `drillState.focusedPeriod` is reset to null.

### Logic

**ECharts registration (`$lib/echarts.ts`):**
```typescript
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { TooltipComponent, GridComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([BarChart, TooltipComponent, GridComponent, LegendComponent, CanvasRenderer]);

export { echarts };
export type EChartsInstance = ReturnType<typeof echarts.init>;
```

**CashFlowChart option builder:**
```typescript
function buildOption(series: CashFlowRow[], currentMonth: string, formatCurrency: (v: number) => string) {
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number) => formatCurrency(v)
    },
    legend: { show: true, bottom: 0 },
    grid: { top: 8, right: 0, bottom: 28, left: 0, containLabel: true },
    xAxis: {
      type: 'category',
      data: series.map(r =>
        r.month === currentMonth ? `${r.label}*` : r.label
      ),
      axisTick: { show: false },
      axisLine: { show: false }
    },
    yAxis: {
      type: 'value',
      axisLabel: { show: false },
      splitLine: { lineStyle: { type: 'dashed', color: 'rgba(10, 61, 89, 0.08)' } }
    },
    series: [
      {
        name: 'Income',
        type: 'bar',
        data: series.map(r => r.income),
        itemStyle: { color: '#1d9f6e', borderRadius: [3, 3, 0, 0] }
      },
      {
        name: 'Spending',
        type: 'bar',
        data: series.map(r => r.spending),
        itemStyle: { color: '#0a3d59', borderRadius: [3, 3, 0, 0] }
      }
    ]
  };
}
```

The colors (`#1d9f6e` for income, `#0a3d59` for spending) match the existing CSS gradient start colors for visual continuity.

**Click handler:**
```typescript
chart.on('click', (params) => {
  if (params.componentType === 'series') {
    onMonthClick(series[params.dataIndex].month);
  }
});
```

**Resize handling:** Use `ResizeObserver` on the chart container. Call `chart.resize()` when dimensions change. This handles window resize, sidebar toggle, and responsive layout changes.

**Drill state shape:**
```typescript
let focusedPeriod: string | null = null;
```

Use a simple `let` variable with `$:` reactive declarations (matching the page's current Svelte 4 pattern). Do not introduce Svelte 5 runes — the page uses `$:` throughout.

**DrillBreadcrumb rendering:**
- `focusedPeriod === null` → render nothing (empty fragment)
- `focusedPeriod === "2026-04"` → render: `<button>All months</button> <span>→</span> <span>April 2026</span>`

The month name is formatted with `Intl.DateTimeFormat` for locale awareness (same pattern as the existing `monthTitle()` helper).

### Outputs

- Cash flow section renders an interactive ECharts grouped bar chart instead of CSS bars.
- Clicking a month bar highlights it and sets `focusedPeriod`.
- Breadcrumb appears above the chart when drilled into a month.
- Clicking breadcrumb resets drill state.
- `focusedPeriod` is available as a reactive variable for downstream components (10c, 10d).

## System Invariants

- The chart must display the same income and spending values as the old CSS bars for the same data. The data source changes (`cashFlowHistory` instead of `cashFlow.series`), but both carry the same shape and values.
- The partial-month asterisk label must appear on the current month bar (matching the existing `cashFlow.currentMonth` value).
- `chart.dispose()` must be called on component destroy. Leaking ECharts instances causes memory growth.
- The `categoryTrends` section, recent transactions, balance sheet, direction panel, and all other dashboard sections must render identically to before this change.
- ECharts must not block SSR. The chart component must guard `echarts.init()` behind `onMount` (client-only). The container `div` renders on the server; the chart initializes client-side.

## States

- **Loading:** Dashboard data not yet loaded. Chart container shows nothing (same as current behavior — the entire dashboard section is gated by `{#if dashboard}`).
- **Default (no drill):** Chart shows all months from `cashFlowHistory`. No breadcrumb visible. `focusedPeriod` is null.
- **Drilled into month:** Breadcrumb shows `All months → {Month Name}`. Chart continues to show all months (the selected month is visually distinguished in 10c when the donut appears; for 10b the click simply sets the state variable).
- **Empty data:** `cashFlowHistory` is empty. Show the existing "No income or spending landed in the selected window." message instead of the chart.
- **Single month:** Chart renders one bar group. Clicking it sets `focusedPeriod`.

## Edge Cases

- **Window resize:** Chart must resize responsively. `ResizeObserver` handles this.
- **Rapid clicks:** Each click replaces `focusedPeriod`. No debouncing needed — ECharts click events are discrete.
- **Month with zero income and zero spending:** These months are filtered out of `cashFlowHistory` by the backend (only months with activity appear). No special handling needed.
- **Very long history (50+ months):** ECharts handles many bars natively. The chart may become dense; this is acceptable for 10b. 10d adds a date range picker for scoping.
- **SSR:** `echarts.init()` must only run in `onMount`. The `import` of `$lib/echarts.ts` is fine at module level (tree-shaken, no side effects until `.use()` which runs at import time but is safe in SvelteKit's SSR because ECharts checks for `document`).

## Failure Behavior

- If `echarts.init()` throws (e.g., container has zero dimensions), the chart is empty. No crash — the rest of the dashboard still renders.
- If `cashFlowHistory` is undefined or missing from the API response (e.g., old backend), fall back to empty array. The "no data" message appears.

## Regression Risks

- **Category trends section.** This task must not touch the `filteredCategoryTrends`, `categoryMax`, or `{#each filteredCategoryTrends}` block. Those still use `categoryTrends` from the old response shape. Removing them is 10c's job.
- **`barWidth` function and category CSS.** Still used by the category trends section. Do not remove.
- **`cashFlowPreset` and `visibleCashFlow`.** These reactive declarations become dead code after the CSS cash flow section is replaced. Remove them to avoid confusion, but verify the category trends section doesn't reference them.
- **Mobile layout.** The CSS cash flow section had specific mobile styles (`max-tablet:grid-cols-1`). The ECharts chart must render correctly on narrow viewports. ECharts handles this natively via `chart.resize()`, but verify.
- **Bundle size.** ECharts tree-shaken with `BarChart` + `TooltipComponent` + `GridComponent` + `LegendComponent` + `CanvasRenderer` adds ~180–250KB gzipped. This is the first external visualization dependency. Acceptable for the value delivered.

## Acceptance Criteria

- `pnpm check` passes in `app/frontend`.
- `pnpm build` succeeds in `app/frontend`.
- ECharts is installed as a dependency in `package.json`.
- `$lib/echarts.ts` exists and exports the configured `echarts` namespace.
- `CashFlowChart.svelte` renders a grouped bar chart with income (green) and spending (dark blue) bars per month.
- The current month's x-axis label includes an asterisk (e.g., `"May*"`).
- Clicking a month bar calls the `onMonthClick` callback with the month key.
- `DrillBreadcrumb.svelte` renders nothing when `focusedPeriod` is null.
- `DrillBreadcrumb.svelte` renders "All months → {Month}" when `focusedPeriod` is set, and clicking "All months" calls `onReset`.
- The cash flow section of the dashboard replaces CSS bars with the ECharts chart.
- The old `cashflow-presets` toggle and CSS cash flow row loop are removed from the template.
- Dead reactive declarations (`cashFlowPreset`, `filteredCashFlowSeries`, `visibleCashFlow`, `cashFlowMax`) are removed.
- The category trends section, recent transactions, balance sheet, direction panel, hero stats, and all other dashboard sections render unchanged.
- `chart.dispose()` is called in `onDestroy`.
- The chart resizes when the window resizes.

## Proposed Sequence

1. **Install ECharts.** `pnpm add echarts` in `app/frontend`. Verify `pnpm check` and `pnpm build` still pass.

2. **Create `$lib/echarts.ts`.** Register `BarChart`, `TooltipComponent`, `GridComponent`, `LegendComponent`, `CanvasRenderer`. Export `echarts` and `EChartsInstance` type.

3. **Create `CashFlowChart.svelte`.** Implement the grouped bar chart with click handler and resize observer. Test independently by temporarily rendering it in the page with hardcoded data.

4. **Create `DrillBreadcrumb.svelte`.** Implement the breadcrumb strip with `focusedPeriod` and `onReset` props.

5. **Wire into `+page.svelte`.** Add `cashFlowHistory` and `categoryHistory` to the `DashboardOverview` type. Add `focusedPeriod` state variable. Replace the CSS cash flow section with `<CashFlowChart>` and `<DrillBreadcrumb>`. Remove dead reactive declarations and CSS.

6. **Clean up dead code.** Remove `cashFlowPreset`, `filteredCashFlowSeries`, `visibleCashFlow`, `cashFlowMax`. Remove `.cashflow-presets`, `.cashflow-row` CSS rules. Keep `.bar-income`, `.bar-spending`, `barWidth()`, and category-meter CSS (used by category trends).

7. **Verify.** `pnpm check`, `pnpm build`. Visual inspection: chart renders, click works, breadcrumb appears/resets. All other dashboard sections unchanged.

## Definition of Done

- All acceptance criteria pass.
- `pnpm check` and `pnpm build` succeed.
- The cash flow chart is interactive — bars are clickable, tooltip shows formatted currency.
- No ECharts instance leaks (dispose on destroy).
- Category trends, balance sheet, direction panel, recent transactions, and hero stats are visually unchanged.
- Dead code from the old CSS cash flow section is removed.

## UX Notes

- **Chart height:** ~192px (`h-48`), matching the visual weight of the old CSS bars section.
- **Colors:** Income bars use `#1d9f6e` (matching existing `.bar-income` gradient start). Spending bars use `#0a3d59` (matching `.bar-spending` gradient start).
- **Tooltip:** Shows formatted currency on hover, triggered by axis (both bars at once).
- **Legend:** Small legend at the bottom showing Income / Spending labels.
- **Partial month:** Asterisk on x-axis label, tooltip footnote not required for 10b (can be added in polish).
- **Breadcrumb:** Minimal — text button "All months" + separator + focused month name. No heavy styling. Appears only when drilled.

## Out of Scope

- Spending-drivers donut (10c).
- Category sparklines (10c).
- Selected-category detail panel (10c).
- Global date range picker (10d).
- Weekly/daily drill-down (10e).
- Removing `categoryTrends` or `cashFlow.series` from the type / API consumption (10c).
- Backend changes.
- Vitest tests for chart components (ECharts requires DOM/canvas — visual verification is the primary test).
