# Feature 10: Interactive Dashboard

Power BI-style dashboard with ECharts charts, cross-filter state, time-hierarchy drill-down, and a global date range picker. Replaces CSS-bar charts with interactive visuals. Drill-through to individual transactions uses a scoped lazy fetch rather than embedding raw data in the dashboard payload.

## Architecture Decisions

### AD-1: Dashboard payload carries aggregates, not raw transactions

The dashboard endpoint returns `categoryHistory: [{month, category, amount}]` at (month × category) grain.

- Already computed by `category_spending: defaultdict[(month, account), Decimal]` in `dashboard_service.py` — no new computation, just expose more of it
- Small payload (~24 months × ~20 categories ≈ 480 rows)
- Covers all chart views: cash flow bars, category sparklines, spending-drivers donut, selected-category time series

Raw transactions are excluded from the dashboard payload. Individual transaction detail is fetched lazily via `GET /api/dashboard/transactions` when the user drills into a specific period + category. This limits blast radius if a session is compromised — a single credential theft yields aggregates, not the full transaction corpus.

### AD-2: Drill-down is time-hierarchy navigation, not a flat granularity toggle

The granularity control is a zoom hierarchy with context:

```
All months → [click April] → Weeks in April → [click Week 17] → Days in Week 17
```

State shape:
```typescript
type DrillState = {
  level: 'month' | 'week' | 'day';
  focusedPeriod: string | null; // null = top; "2026-04" = April; "2026-W17" = week 17
};
```

A flat granularity toggle applied to a full year at day grain produces ~365 bars. The hierarchy keeps the x-axis readable at every level (~12 bars at month, ~4–5 at week, 7 at day).

Monthly pre-aggregates cannot satisfy weekly/daily views — April's total cannot be disaggregated back into weeks after summing. Supporting below-month drill requires finer-grain data on the backend.

**Decision:** Implement month-level only for 10a–10d. `DrillState.level` is a union type designed to extend cleanly. Weekly/daily drill-down (10e) is deferred; it requires either daily pre-aggregates or raw transactions in the payload.

### AD-3: Backend caches parsed transactions by journal mtime

`load_transactions()` re-parses the journal on every request today. An mtime-based in-memory cache eliminates redundant parses on repeat dashboard loads.

```python
# In journal_query_service.py or a new cache module
import threading, os

_tx_cache: list[ParsedTransaction] | None = None
_tx_cache_mtime: float | None = None
_tx_cache_lock = threading.Lock()

def get_transactions_cached(config: AppConfig) -> list[ParsedTransaction]:
    journal_path = _primary_journal_path(config)
    current_mtime = os.path.getmtime(journal_path)
    with _tx_cache_lock:
        global _tx_cache, _tx_cache_mtime
        if _tx_cache is None or current_mtime != _tx_cache_mtime:
            _tx_cache = load_transactions(config)
            _tx_cache_mtime = current_mtime
    return _tx_cache
```

Cache hit costs one `stat()` syscall. Cache miss re-parses (happens only after an import, manual edit, or reconciliation write). Thread-safe via lock. Module-level (process lifetime) — appropriate for single-user local app. Multi-tenant deployment would need per-user keying with LRU eviction.

### AD-4: ECharts with tree-shaking ESM imports

Install: `pnpm add echarts` in `app/frontend`.

Import pattern (register once, reuse across components):

```typescript
// $lib/echarts.ts  — import and register; other components import from here
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import { TooltipComponent, GridComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([BarChart, LineChart, PieChart, TooltipComponent, GridComponent, LegendComponent, CanvasRenderer]);

export { echarts };
```

Each chart component manages its own instance. Lifecycle pattern:

```svelte
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { echarts } from '$lib/echarts';

  let container: HTMLDivElement;
  let chart: ReturnType<typeof echarts.init>;

  onMount(() => {
    chart = echarts.init(container);
    chart.on('click', handleClick);
  });

  $effect(() => {
    chart?.setOption(buildOption(/* reactive props */));
  });

  onDestroy(() => chart?.dispose());
</script>

<div bind:this={container} class="h-48 w-full" />
```

`$effect` runs after every reactive dependency change, keeping chart state in sync without manual subscriptions.

### AD-5: Cross-filter state is a single Svelte `$state` object in the dashboard page

```typescript
let drillState = $state<DrillState>({ level: 'month', focusedPeriod: null });
let selectedCategory = $state<string | null>(null);
let globalDateRange = $state<{ start: string; end: string } | null>(null);
```

All derived data uses `$derived`. Charts call `setOption()` inside `$effect` when derived data changes. Click handlers update state; reactive propagation drives all visuals simultaneously.

## API Contracts

### Modified: `GET /api/dashboard/overview`

Two new top-level fields. Existing fields (`categoryTrends`, `cashFlow.series`) remain for backward compatibility and are deprecated — removed in the 10c cleanup step once the frontend no longer reads them.

```typescript
// Added to DashboardOverview response
categoryHistory: Array<{
  month: string;         // "2026-04"
  category: string;     // ledger account path: "Expenses:Shopping:Groceries"
  categoryLabel: string; // pretty name: "Shopping / Groceries"
  amount: number;        // absolute spending (positive)
}>;

cashFlowHistory: Array<{  // full history; replaces cashFlow.series (6-month window)
  month: string;
  label: string;          // "Apr"
  income: number;
  spending: number;
  net: number;
}>;
```

`categoryHistory` is derived from the already-computed `category_spending` dict — expose all `(month, account)` entries instead of filtering to 2 months.

`cashFlowHistory` is derived from `monthly_income` and `monthly_spending` — all keys present, not just the 6-month window.

### New: `GET /api/dashboard/transactions`

Lazy fetch for drill-down detail. Called only when the user drills into a specific period + category in the detail panel.

**Query params:**
| Param | Required | Format | Example |
|---|---|---|---|
| `period` | yes | Month key or future week/day key | `2026-04` |
| `category` | no | Ledger account path | `Expenses:Shopping:Groceries` |
| `limit` | no | int, default 50 | `50` |
| `offset` | no | int, default 0 | `0` |

**Response:**
```typescript
{
  transactions: Array<{
    date: string;          // "2026-04-15"
    payee: string;
    amount: number;        // signed (negative = expense)
    category: string;      // ledger account path
    categoryLabel: string;
    accountLabel: string;
  }>;
  total: number;           // total matching count (for pagination)
  period: string;          // echoes request period
  category: string | null; // echoes request category
}
```

**Backend logic:** Filter cached transactions by `period` date range (all days in the month), optionally by `posting.account.startswith(category)`, return paginated slice. Uses the mtime cache — no re-parse.

## Frontend State Model

```typescript
// Reactive state ($state)
let drillState = $state<DrillState>({ level: 'month', focusedPeriod: null });
let selectedCategory = $state<string | null>(null);
let globalDateRange = $state<DateRange | null>(null); // null = all time

// Derived cash flow series for chart x-axis ($derived)
let cashFlowSeries = $derived(() => {
  let series = dashboard!.cashFlowHistory;
  if (globalDateRange) {
    const startMonth = globalDateRange.start.slice(0, 7);
    const endMonth = globalDateRange.end.slice(0, 7);
    series = series.filter(r => r.month >= startMonth && r.month <= endMonth);
  }
  return series;
});

// Derived category breakdown for selected/focused month (drives donut)
let categoryBreakdown = $derived(() => {
  const month = drillState.focusedPeriod ?? currentMonth;
  return dashboard!.categoryHistory
    .filter(r => r.month === month)
    .sort((a, b) => b.amount - a.amount);
});

// Derived sparkline data per category (last 6 months in view)
let sparklineMonths = $derived(() =>
  cashFlowSeries.slice(-6).map(r => r.month)
);

let categorySparklineData = $derived(() => {
  const byCategory = new Map<string, number[]>();
  for (const row of dashboard!.categoryHistory) {
    if (!sparklineMonths.includes(row.month)) continue;
    if (!byCategory.has(row.category)) byCategory.set(row.category, []);
    byCategory.get(row.category)!.push(row.amount);
  }
  return byCategory;
});
```

## ECharts Option Shapes

### Cash flow grouped bar

```typescript
function buildCashFlowOption(series: CashFlowRow[], partialMonth: string): EChartsOption {
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number) => formatCurrency(v)
    },
    xAxis: {
      type: 'category',
      data: series.map(r => r.month === partialMonth ? `${r.label}*` : r.label)
    },
    yAxis: { type: 'value' },
    series: [
      { name: 'Income', type: 'bar', data: series.map(r => r.income) },
      { name: 'Spending', type: 'bar', data: series.map(r => r.spending) }
    ]
  };
}
```

Click handler: `chart.on('click', params => onMonthClick(series[params.dataIndex].month))`

### Spending drivers donut

```typescript
function buildDonutOption(breakdown: CategoryHistoryRow[]): EChartsOption {
  return {
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: breakdown.map(r => ({ name: r.categoryLabel, value: r.amount }))
    }]
  };
}
```

Click handler: `chart.on('click', params => onCategoryClick(params.name))`

### Category sparkline (mini, no axes)

```typescript
function buildSparklineOption(amounts: number[]): EChartsOption {
  return {
    grid: { top: 0, bottom: 0, left: 0, right: 0 },
    xAxis: { type: 'category', show: false, data: amounts.map((_, i) => i) },
    yAxis: { type: 'value', show: false },
    series: [{ type: 'bar', data: amounts, itemStyle: { color: 'var(--muted-foreground)' } }]
  };
}
```

### Selected-category time series

```typescript
function buildCategoryTimeSeriesOption(history: CategoryHistoryRow[], category: string): EChartsOption {
  const rows = history.filter(r => r.category === category);
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => formatCurrency(v) },
    xAxis: { type: 'category', data: rows.map(r => r.month.slice(0, 7)) },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: rows.map(r => r.amount) }]
  };
}
```

## Component Map

| Component | Owns | Props in | Events out |
|---|---|---|---|
| `CashFlowChart.svelte` | ECharts grouped bar + resize observer | `series`, `partialMonth` | `onMonthClick(month)` |
| `SpendingDriversDonut.svelte` | ECharts pie/donut | `breakdown` | `onCategoryClick(category)` |
| `CategorySparkline.svelte` | ECharts mini bar, no axes | `amounts` | — |
| `CategoryDetailPanel.svelte` | Time series bar + lazy transaction list | `category`, `drillState`, `history` | `onClose()` |
| `DrillBreadcrumb.svelte` | Breadcrumb strip | `drillState` | `onDrillUp(level)` |
| `DashboardDateFilter.svelte` | bits-ui `DateRangePicker` + presets | `value` | `onChange(range)` |

## Sub-feature Sequencing

| # | Sub-feature | Depends on | Files touched |
|---|---|---|---|
| 10a | Backend history payload + mtime cache | — | `dashboard_service.py`, `journal_query_service.py`, `main.py` |
| 10b | ECharts cash flow chart + drill state | 10a | `+page.svelte`, `CashFlowChart.svelte`, `DrillBreadcrumb.svelte`, `$lib/echarts.ts` |
| 10c | Category sparklines + detail panel | 10b | `+page.svelte`, `CategorySparkline.svelte`, `CategoryDetailPanel.svelte`, `SpendingDriversDonut.svelte` |
| 10d | Global date range picker | 10b | `+page.svelte`, `DashboardDateFilter.svelte` |

10b, 10c, 10d all touch `+page.svelte` — they are sequential, not concurrent.

10e (weekly/daily drill-down) is explicitly deferred. It requires either daily pre-aggregates or raw transactions in the dashboard payload, plus a more complex bucketing function on the frontend. `DrillState.level` is typed as a union to extend without a breaking change.

## Partial-Month Handling

Current month is always partial (unless today is the last day). Two problems:
1. Category trends compare a partial current month against a full previous month, making everything appear "down"
2. Cash flow bars for the current month look low with no context

Mitigations:
- Label the current month bar with an asterisk in the chart tooltip: `"May*"` with a footnote "Partial month — {N} days elapsed"
- Category breakdown donut: show "Month to date" in the panel heading when `focusedPeriod === currentMonth`
- `priorComparisonLabel` logic in `TransactionsExplanationHeader.svelte` already handles this for drill-throughs

## Regression Risks

- `categoryTrends` and `cashFlow.series` are kept in the API response through 10c; removing them in 10c cleanup must be preceded by confirming the frontend no longer reads them
- ECharts `$effect` calling `setOption()` on every render can cause flickering if the option object is reconstructed unnecessarily — pass `notMerge: false` (default) and keep option objects stable
- `chart.dispose()` must be called in `onDestroy` on every component that calls `echarts.init()` — leaking instances causes memory growth and event handler accumulation
- The mtime cache uses a module-level global; if the FastAPI process forks workers, each worker has an independent cache. This is acceptable for a single-user local app; note it for future multi-user deployment.
