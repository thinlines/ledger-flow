# Current Task

## Title

Activity view explanation header and transaction hierarchy

## Objective

Make the cross-account activity view the explanation layer behind every dashboard insight. Today, clicking a category trend or cash flow row from the dashboard lands the user on a generic "All activity" page with one filter chip and a date-sorted list of raw bank descriptors — no period comparison, no decomposition, no top mover, and the category (the dimension the user came to investigate) is the smallest, lowest-contrast text in every row. This task fixes both gaps:

1. **Explanation header.** When any filter is active (category, month, or period preset), the page leads with a period summary, prior-period comparison, 6-month rolling baseline, and top mover, computed server-side and rendered as a card above the transaction list. The same explanation appears whether the user arrived from a dashboard insight or opened the activity view directly.
2. **Row hierarchy.** Category is promoted from the muted meta line to a leading pill before the payee. Raw bank payees are truncated. The meta line collapses to date and account.

This is the bridge between "What changed recently?" and "Where should I go next?". Without it, every dashboard insight is a dead end. With it, every dashboard click answers *why* before it shows the data. See `DECISIONS.md` §13 for the broader rationale.

## Scope

### Included

- **Backend:** Extend `build_activity_view` in `app/backend/services/activity_service.py` to return a `summary` block alongside the existing `transactions` list. The summary contains period totals, prior-period comparison, 6-month rolling monthly average, and the top transaction by absolute amount.
- **Backend:** A single-pass refactor of the existing transaction loop that buckets matching transactions by month while filtering, so the summary fields can be derived without additional `load_transactions()` calls.
- **Backend:** Tests covering category filter, month filter, period preset filter, insufficient-history fallback, and top-transaction selection.
- **Frontend:** Update `ActivityResult` type in `app/frontend/src/routes/transactions/+page.svelte` with the new `summary` field. The field is optional so the page degrades gracefully if the backend response is missing it.
- **Frontend:** Context-aware activity hero title — render the category display name or month title when those filters are active, fall back to "All activity" otherwise.
- **Frontend:** New `ExplanationHeader` rendered as a `view-card` between the filters card and the transaction list card. Reads from `summary` and conditionally renders each line based on data availability.
- **Frontend:** Activity row layout change — extract category from the meta line into a leading pill, truncate payees longer than 50 characters, simplify the meta line to date + account.
- **Frontend:** Hide the per-row category pill when a category filter is active (the explanation header already says what these all are).

### Explicitly Excluded

- Dashboard panel changes, health signals, or charts (Feature 7b).
- Notable-signal generation or category spike detection on the dashboard (Feature 7b).
- Sidebar copy rewrites, hero CTA fallthrough, /rules loading-state fix, mobile nav drawer (Feature 7c).
- Per-account register view changes. This task only touches the cross-account activity view (`activityMode === true`).
- Sort-order toggle (amount vs date). Default date-descending sorting is preserved.
- Color-coding category pills by category type (expense vs income). Neutral pills are sufficient for this cut.
- Goals, targets, budgets (deferred per roadmap).
- GenAI trend analysis (deferred — needs data-privacy planning).
- Payee alias suggestions or "clean up this payee" affordances from the activity view.
- Investment tracking (401(k), HSA, pretax contributions — out of scope).
- Changes to dashboard category trend rows or cash flow rows. Their existing `?view=activity&category=...` and `?view=activity&month=...` link patterns are unchanged.

## System Behavior

### Inputs

- User clicks a category trend row on the dashboard → navigates to `/transactions?view=activity&category=Expenses:Shopping:Groceries`.
- User clicks a cash flow month row on the dashboard → navigates to `/transactions?view=activity&month=2026-03`.
- User opens the activity view directly and selects a period preset (This month / Last 30 days / Last 3 months).
- User opens the activity view with the default `last-3-months` period and no category or month filter.

### Logic

#### 1. Activity endpoint summary block

`GET /api/transactions/activity` currently returns:

```json
{
  "baseCurrency": "USD",
  "period": "last-3-months",
  "category": null,
  "month": null,
  "transactions": [...],
  "totalCount": 24
}
```

Add a `summary` field:

```json
{
  "summary": {
    "periodTotal": -1800.00,
    "periodCount": 5,
    "averageAmount": -360.00,
    "priorPeriodTotal": -1200.00,
    "priorPeriodCount": 4,
    "deltaAmount": -600.00,
    "deltaPercent": 50.0,
    "rollingMonthlyAverage": -1350.00,
    "rollingMonths": 6,
    "topTransaction": {
      "date": "2026-03-22",
      "payee": "Costco",
      "amount": -420.00,
      "accountLabel": "Wells Fargo Credit Card"
    }
  }
}
```

Field definitions:

| Field | Type | Description |
|---|---|---|
| `periodTotal` | `number` | Sum of `amount` across all transactions in the filtered period. Negative for net spending. |
| `periodCount` | `int` | Transaction count in the filtered period. Equal to `len(transactions)` from the existing response. |
| `averageAmount` | `number` | `periodTotal / periodCount`. Returns `0` if `periodCount` is `0`. |
| `priorPeriodTotal` | `number \| null` | Same filter applied to the immediately prior period of equal length. `null` when no prior data exists or when the prior window has zero matching transactions and zero matching transactions in any preceding window (i.e., this is genuinely the first period of activity). |
| `priorPeriodCount` | `int \| null` | Transaction count in the prior period. `null` when `priorPeriodTotal` is `null`. |
| `deltaAmount` | `number \| null` | `periodTotal - priorPeriodTotal`. `null` when `priorPeriodTotal` is `null`. |
| `deltaPercent` | `number \| null` | Percentage change from prior period. `null` when `priorPeriodTotal` is `null` or when `priorPeriodTotal` is exactly `0` (division by zero). |
| `rollingMonthlyAverage` | `number \| null` | Average monthly total for the filter over the 6 calendar months immediately preceding the current period's start month. `null` when fewer than 2 of those 6 months have any matching transactions (insufficient history). |
| `rollingMonths` | `int` | How many of the 6 preceding months had at least one matching transaction. Always `0..6`. |
| `topTransaction` | `object \| null` | The transaction in the filtered period with the largest absolute amount. `null` when `periodCount == 0`. Object shape: `{ date, payee, amount, accountLabel }` — same field names as items in the existing `transactions` array. |

**Prior period definition:**

| Active filter | Current period | Prior period |
|---|---|---|
| `month=YYYY-MM` | The named calendar month | The preceding calendar month |
| `period=this-month` | 1st of current month → today | 1st of prior month → same day-of-month in prior month (or last day of prior month if shorter) |
| `period=last-30` | (today - 29 days) → today | (today - 59 days) → (today - 30 days) |
| `period=last-3-months` (default) | First day of (current_month - 2) → today | First day of (current_month - 5) → last day of (current_month - 3) |

When a category filter is also active, it applies identically to both the current and prior windows. The category never mixes filtered and unfiltered data.

**Rolling average definition:**

The 6-month window is the 6 calendar months immediately preceding the current period's *start month*. For each of those 6 months, sum the amounts of all transactions matching the active category filter (or all transactions if no category filter). The rolling monthly average is `total_across_window / count_of_months_with_data`. If fewer than 2 of the 6 months have any matching transactions, return `null` (insufficient history). `rollingMonths` reports how many of the 6 had data.

Examples:
- Current filter: `month=2026-03`, no category. The window is 2025-09 through 2026-02. Sum monthly totals for those 6 months. Average across months that had any transactions.
- Current filter: `period=this-month` evaluated on 2026-04-09. The current period start month is 2026-04. The window is 2025-10 through 2026-03.
- Current filter: `period=last-3-months` evaluated on 2026-04-09. The current period covers 2026-02 through 2026-04, so the start month is 2026-02. The window is 2025-08 through 2026-01.

**Computation approach:**

The existing function iterates `load_transactions(config)` once and applies time + category filters inline. Refactor to a single pass that:

1. Walks every transaction once.
2. For each transaction, applies the category filter (the same `posting.account == category or posting.account.startswith(category + ":")` test that exists today).
3. If the transaction passes the category filter, place it in a per-month bucket keyed by `transaction.posted_on.strftime("%Y-%m")`.

After the pass, derive:

- The current-period bucket: union of months that fall within the resolved current period date range. Sum amounts for `periodTotal`, count for `periodCount`. Build the `transactions` array from this bucket (preserving the existing field shape and date-descending sort). Find `max(abs(amount))` for `topTransaction`.
- The prior-period bucket: union of months that fall within the resolved prior period date range. Sum and count.
- The rolling 6-month window: the 6 calendar months preceding the current period's start month. For each month in the window, sum the bucketed transactions. Average across months with data.

Edge case: when the user specifies `month=YYYY-MM`, the "current period" is exactly that one month. The prior period is the immediately preceding calendar month. The rolling window is the 6 months before the named month.

Edge case: a transaction whose `posted_on` falls within a partial-month current-period window (e.g., `period=this-month` evaluated mid-month) is bucketed into its calendar month, but only counted toward the current-period totals if it also falls within the resolved date range. The bucketing is by calendar month, but the period-membership filter is by date range.

#### 2. Context-aware activity hero title

The activity hero today renders:

```svelte
<div class="hero-copy">
  <p class="eyebrow">Transactions</p>
  <h2 class="page-title">All activity</h2>
  <p class="subtitle">Cross-account transactions matching your filters.</p>
</div>
```

Replace with conditional copy based on the active filter:

| Filter state | Eyebrow | Title | Subtitle |
|---|---|---|---|
| Category active (any period) | "Spending category" or "Income category" (derived from the leading account segment) | `categoryDisplayName` (e.g., "Shopping / Groceries") | Period label (e.g., "March 2026" if month filter, otherwise "Last 30 days" / "Last 3 months" / "This month") |
| Month active (no category) | "Activity" | `monthTitle(month)` (e.g., "March 2026") | "All cross-account spending and income" |
| Period preset only (no category, no month) | "Transactions" | "All activity" | Period label |

`categoryDisplayName` is derived the same way the existing filter chip does it: `category.split(':').slice(1).join(' / ')`. The eyebrow uses the leading segment of the category account: `Expenses:*` → "Spending category", `Income:*` → "Income category", anything else → "Activity".

The view toggle button group on the right side of the hero is unchanged.

#### 3. Explanation header card

A new `view-card` rendered between the existing `activity-filters-card` and the existing `activity-list-card`. Visible whenever `activityResult?.summary` is non-null and `activityResult.totalCount > 0`. Hidden in empty / loading / error states (the existing handling for those states is unchanged).

Markup outline:

```svelte
{#if activityResult?.summary && activityResult.totalCount > 0}
  <section class="view-card explanation-header-card">
    <p class="explanation-period">
      {formatCurrency(summary.periodTotal)} across {summary.periodCount} {nounForCount(summary.periodCount)}
      {#if !mixedSigns}
        · avg {formatCurrency(summary.averageAmount)} each
      {/if}
    </p>

    {#if summary.priorPeriodTotal !== null}
      <p class="explanation-prior">
        {priorPeriodLabel}: {formatCurrency(summary.priorPeriodTotal)} across {summary.priorPeriodCount}
        {#if summary.deltaPercent !== null}
          — <span class={deltaClass}>{deltaArrow}{Math.abs(summary.deltaPercent).toFixed(0)}%</span> from prior period
        {/if}
      </p>
    {/if}

    {#if summary.rollingMonthlyAverage !== null}
      <p class="explanation-baseline">
        6-month average: {formatCurrency(summary.rollingMonthlyAverage)}/mo
      </p>
    {/if}

    {#if summary.topTransaction && summary.periodCount > 1}
      <p class="explanation-top">
        Biggest: {formatCurrency(Math.abs(summary.topTransaction.amount))}
        at {truncatePayee(summary.topTransaction.payee, 30)}
        on {activityShortDate(summary.topTransaction.date)}
      </p>
    {/if}
  </section>
{/if}
```

Conditional rendering rules:

| Line | Show when |
|---|---|
| Period summary | Always (when the header is visible at all) |
| Prior comparison | `summary.priorPeriodTotal !== null` |
| Delta percent within prior comparison | `summary.deltaPercent !== null` |
| Rolling baseline | `summary.rollingMonthlyAverage !== null` |
| Top transaction | `summary.topTransaction !== null && summary.periodCount > 1` |

Helpers:

- `nounForCount(count)`: returns `"purchase" / "purchases"` when the active category filter is an `Expenses:*` account, `"deposit" / "deposits"` when it's `Income:*`, and `"transaction" / "transactions"` otherwise. Singular when `count === 1`.
- `mixedSigns`: `true` when the filtered transactions contain both positive and negative amounts. When `true`, the "avg X each" clause is omitted (the average across mixed signs is misleading).
- `priorPeriodLabel`: `"Last month"` when the current period is exactly one calendar month, otherwise `"Prior period"`.
- `deltaArrow`: `"↑"` when spending increased (more negative for expenses, more positive for income), `"↓"` when decreased, omitted when zero.
- `deltaClass`: applies the existing `negative` class for unfavorable deltas (more spending, less income), `positive` for favorable deltas, neutral otherwise. Reuses the same coloring convention as the rest of the app.

Styling:

- Card uses the existing `.view-card` base. Add `.explanation-header-card` for spacing tweaks (slightly tighter padding than the activity hero, no section heading, lines stacked vertically with 0.4rem gap).
- The period summary line is the headline (~1.05rem, semibold).
- The prior comparison line is body text (~0.95rem, normal weight).
- The rolling baseline line is muted (`var(--muted-foreground)`, ~0.88rem).
- The "Biggest" line is muted (~0.88rem) — it's a subtle nudge, not an alert.

#### 4. Activity row layout change

Current row template (`+page.svelte:889-904`):

```svelte
<div class="activity-row">
  <div class="activity-main">
    <p class="activity-payee">{tx.payee}</p>
    <p class="activity-meta">
      {activityShortDate(tx.date)} · {tx.accountLabel} · {tx.category}
    </p>
  </div>
  <div class="activity-side">
    <p class:positive={tx.amount > 0} class:negative={tx.amount < 0} class="activity-amount">
      {formatCurrency(tx.amount, { signed: true })}
    </p>
    {#if tx.isUnknown}
      <a class="pill warn" href="/unknowns">Needs review</a>
    {/if}
  </div>
</div>
```

New row template:

```svelte
<div class="activity-row">
  <div class="activity-main">
    <div class="activity-headline">
      {#if !activityCategory}
        <span class="activity-category-pill">{tx.category}</span>
      {/if}
      <span class="activity-payee" title={tx.payee}>{truncatePayee(tx.payee)}</span>
    </div>
    <p class="activity-meta">
      {activityShortDate(tx.date)} · {tx.accountLabel}
    </p>
  </div>
  <div class="activity-side">
    <p class:positive={tx.amount > 0} class:negative={tx.amount < 0} class="activity-amount">
      {formatCurrency(tx.amount, { signed: true })}
    </p>
    {#if tx.isUnknown}
      <a class="pill warn" href="/unknowns">Needs review</a>
    {/if}
  </div>
</div>
```

Changes:

- Category extracted from the meta line and promoted into a new `activity-headline` flex container alongside the payee.
- Category pill hidden when `activityCategory` is set (the explanation header already shows the category).
- Payee wrapped in a `<span>` (not `<p>`) to sit inline with the category pill. Truncated via `truncatePayee()` with `title={tx.payee}` for the full text on hover.
- Meta line simplified to date + account (category removed).

Helper:

```ts
function truncatePayee(payee: string, max = 50): string {
  if (payee.length <= max) return payee;
  return payee.slice(0, max - 1) + '…';
}
```

Styling additions to the existing `<style>` block:

```css
.activity-headline {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-width: 0;
}

.activity-category-pill {
  flex-shrink: 0;
  font-size: 0.76rem;
  font-weight: 600;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  background: rgba(15, 95, 136, 0.08);
  color: var(--brand-strong);
  white-space: nowrap;
}

.activity-payee {
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

@media (max-width: 720px) {
  .activity-headline {
    flex-wrap: wrap;
  }
}
```

The existing `.activity-payee` class is repurposed from a block `<p>` selector to an inline `<span>` selector. The `font-weight: 700` rule from the existing `.activity-payee` block is preserved.

### Outputs

- `GET /api/transactions/activity` returns a `summary` block alongside the existing fields.
- Activity hero title and eyebrow reflect the active filter.
- Explanation header card appears between filters and the transaction list whenever a filter has results.
- Activity rows show the category as a leading pill before the payee (when no category filter is active).
- Long payees are truncated with `…` and reveal the full text on hover.
- Existing dashboard drilldown URLs continue to work without modification.

## System Invariants

- The summary is computed in a single pass alongside the existing transaction filtering. No additional `load_transactions()` calls and no second walk over the full transaction list.
- The existing `transactions` array, `totalCount`, `period`, `category`, and `month` fields are unchanged in shape and meaning. The summary is purely additive.
- Prior-period and rolling-average computations apply the same category filter as the main query. They never mix filtered and unfiltered data.
- Payee truncation is display-only. The underlying `tx.payee` value is never modified. Full payee is always accessible via the `title` attribute.
- The per-account register view (`activityMode === false`) is untouched. All changes are scoped to the cross-account activity view.
- The explanation header reads exclusively from the `summary` block returned by the backend. The frontend does no client-side aggregation, comparison math, or rolling-average computation.
- The dashboard's existing drilldown link patterns (`?view=activity&category=...`, `?view=activity&month=...`) are unchanged. No frontend or backend code outside the activity view is touched.

## States

- **No filter active (default `last-3-months`)**: hero title is "All activity" with the period as subtitle. Explanation header shows period summary and (when there is enough history) prior-period comparison and rolling baseline. Top transaction line appears when `periodCount > 1`. Category pills visible on every row.
- **Category filter active**: hero shows the category display name with the period or month as subtitle. Explanation header shows full comparison (current vs prior vs rolling). Category pills hidden on rows.
- **Month filter active (no category)**: hero shows the month title. Explanation header compares the named month against the immediately preceding month with a 6-month rolling baseline.
- **Category + month active**: hero shows the category name with the month name as subtitle. Explanation header shows category-scoped comparison for that month vs the preceding month, with the category-scoped rolling average.
- **Empty result (no transactions match filters)**: existing empty state ("No transactions match these filters") is preserved unchanged. Explanation header is not shown.
- **Insufficient history (first month, new category)**: explanation header is shown but the prior-comparison line and the rolling-baseline line are conditionally hidden. The header gracefully degrades to just the period summary line.
- **Loading**: existing loading state is unchanged. Explanation header is not rendered until data arrives.
- **Backend response missing `summary` (forward compat)**: explanation header is not rendered. The transaction list and existing filter behavior continue to work.

## Edge Cases

- **First month of any data**: prior period is `null`, rolling average is `null`. Explanation header shows only the period summary line.
- **Single transaction in period**: top transaction line is hidden (`periodCount <= 1` — it would just repeat the only transaction). The period summary line still shows "$X across 1 transaction · avg $X each".
- **Mixed income and expense in a category filter**: the filter `Expenses:*` excludes income postings, so this case mainly arises with custom categories or hierarchical filters that span both. When the filtered transactions contain both positive and negative amounts, omit the "avg X each" clause from the period summary line. The "Biggest" line still shows the largest by absolute value.
- **Very long category names** (e.g., `Expenses:Shopping:Groceries:Bulk Warehouse`): no truncation. Render the full display name in the hero title and let the layout wrap naturally.
- **All-zero prior period**: `priorPeriodTotal === 0` and `priorPeriodCount === 0`. `deltaPercent` is `null` (division by zero). Show "Last month: $0 across 0 transactions" without a percentage. Don't show "↑∞%" or similar.
- **Rolling window with only 1 month of data**: `rollingMonthlyAverage` is `null`, line hidden. Threshold is 2 months minimum.
- **Period preset windows that span calendar boundaries**: e.g., `last-30` evaluated on April 9 covers March 11 → April 9. The bucket-by-calendar-month approach still works because the period-membership check is by date range, while the rolling baseline and prior-period computation use calendar month boundaries.
- **Transaction with zero amount**: included in the transaction count, contributes zero to totals. Cannot be the top transaction (since `abs(0) === 0`). If the period contains only zero-amount transactions, `topTransaction` is `null`.
- **Payee with multibyte characters**: `truncatePayee` slices on character index, which is correct for most European text but could split surrogate pairs. Acceptable for v1 — bank descriptors are ASCII in practice.
- **Category filter that matches no transactions**: empty result state, no explanation header. Existing handling.
- **Month filter for a future month**: empty result state, no explanation header. Existing handling.

## Failure Behavior

- If the activity endpoint returns an error, the existing error state applies. The explanation header has no independent failure mode — it renders from the same response payload.
- If the backend response is well-formed but `summary` is missing or `null`, the frontend simply does not render the explanation header. The transaction list and filters continue to work. This is the forward-compatibility path during deployment.
- If `summary.topTransaction` is malformed (missing fields), the top-transaction line is omitted. The other summary lines are unaffected.
- Backend errors during summary computation must not poison the rest of the response. If the rolling-average computation raises (e.g., on a corrupt date), log the error and return the rest of the summary with `rollingMonthlyAverage: null` and `rollingMonths: 0`. The user still sees period totals and prior comparison.

## Regression Risks

- **Activity endpoint response shape**: the `summary` field is additive. Existing frontend code that reads `transactions`, `totalCount`, `period`, `category`, `month`, or `baseCurrency` is unaffected. Verify by running the activity view with the new backend and confirming filters, presets, and the existing transaction list still render.
- **`build_activity_view` refactor to single-pass bucketing**: the existing transaction filter logic is preserved exactly, just reorganized. Existing tests that verify filter correctness must continue to pass without modification. Add new tests for the summary fields, but don't modify existing tests of filter behavior.
- **Dashboard drilldown links**: the existing `?view=activity&category=...` and `?view=activity&month=...` URLs from `+page.svelte` (dashboard) and the cash-flow drilldown in the same file are unchanged. The activity view reads the same query params and applies the same filters. Verify by clicking through both link types after the change.
- **Filter chip display text**: the category filter chip currently renders `activityResult?.transactions[0]?.category` as fallback display text. This still works — the `transactions` array shape is unchanged.
- **Date grouping in the transaction list**: `activityGroups` groups by date for the existing list. The row template change is inside the per-day group loop, so date grouping is unaffected. Verify the day headers ("Apr 7", "Mar 28", etc.) still render correctly.
- **The existing `.activity-payee` CSS rule**: the selector now applies to a `<span>` instead of a `<p>`. Verify the inherited line-height and weight render correctly. The `text-overflow: ellipsis` rule requires `min-width: 0` on the parent flex container, which is added to `.activity-headline`.
- **Performance**: the single-pass bucketing adds one map insertion per transaction. For typical workspaces (hundreds to low thousands of transactions), the overhead is negligible. No additional I/O.
- **Truncation of payees that contain meaningful suffixes**: e.g., `"COSTCO WHSE #0071 BOISE ID"` (28 chars) is unchanged. `"PURCHASE AUTHORIZED ON 03/19 WINCO FOODS #1 ..."` (truncated) loses information about the merchant number, but the full text is available on hover. For users who need the full text without hovering, the per-account register view (which has different layout) is unchanged.
- **Mobile layout**: the new `.activity-headline` flex container wraps on narrow screens via the existing `@media (max-width: 720px)` breakpoint. Verify rows still render legibly at 400px width.

## Acceptance Criteria

- `GET /api/transactions/activity?category=Expenses:Shopping:Groceries` returns a `summary` block with the period total, prior-period comparison, 6-month rolling average, transaction count, average amount, and top transaction.
- `GET /api/transactions/activity?month=2026-03` returns a summary scoped to March 2026 with February 2026 as the prior period.
- `GET /api/transactions/activity?period=this-month` returns a summary with this-month vs prior-month comparison.
- `GET /api/transactions/activity?period=last-3-months` (default) returns a summary that compares the last 3 months against the preceding 3 months and computes rolling averages from the 6 months before the current window.
- When the prior period has no data, `priorPeriodTotal` is `null` and the prior-comparison line in the explanation header is hidden.
- When fewer than 2 of the 6 preceding months have data, `rollingMonthlyAverage` is `null` and the rolling-baseline line is hidden.
- When the active filter has only one transaction, the top-transaction line is hidden but the period summary line still renders.
- The activity hero title shows the category display name when a category filter is active, the month title when a month filter is active (without category), and "All activity" otherwise.
- The explanation header card appears between the filters card and the transaction list whenever the filtered period has at least one transaction.
- Activity rows show the category as a leading pill before the payee.
- When a category filter is active, the per-row category pill is hidden.
- Payees longer than 50 characters are truncated with `…` and the full text appears on hover via the `title` attribute.
- The meta line in each row is simplified to date + account (category is removed from it).
- The per-account register view (`activityMode === false`) renders identically to before this task.
- Existing dashboard drilldown URLs continue to work without modification.
- `uv run pytest -q` passes in `app/backend`.
- `pnpm check` passes in `app/frontend`.

## Proposed Sequence

1. **Backend: refactor `build_activity_view` to single-pass bucketing.** Walk transactions once. For each transaction that passes the category filter, place it in a `dict[str, list[Transaction]]` keyed by `YYYY-MM`. Preserve the existing filter logic exactly. After the loop, derive the existing `transactions` array from the buckets that fall in the current period date range. Verify all existing activity tests still pass without modification. This step is a behavior-preserving refactor.

2. **Backend: compute `periodTotal`, `periodCount`, `averageAmount`, `topTransaction` from the current-period buckets.** Add to the response payload. Add tests covering: empty period (top is null), single-transaction period (top hidden by frontend), multi-transaction period, mixed-sign period.

3. **Backend: implement prior-period date-range resolution and compute `priorPeriodTotal`, `priorPeriodCount`, `deltaAmount`, `deltaPercent`.** One helper function takes the current period filter state and returns the prior period's date range. Apply the same category filter to the bucketed data within the prior range. Add tests for each filter type (month, this-month, last-30, last-3-months) and the null cases (no prior data, zero prior total → null delta percent).

4. **Backend: implement 6-month rolling average computation.** Iterate the 6 calendar months preceding the current period's start month. For each month, sum the bucket. Average across months that have any matching transactions. Return `null` when fewer than 2 months have data. Set `rollingMonths` to the count of months with data. Add tests for each filter type with sparse history, full history, and exactly-1-month-of-data history.

5. **Backend: assemble the `summary` dict and return it from `build_activity_view`.** Verify the response shape with the FastAPI test client. Confirm the existing fields are unchanged.

6. **Frontend: update the `ActivityResult` TypeScript type with an optional `summary` field.** Add a new `ActivitySummary` type matching the backend shape. Make the field optional so the page degrades gracefully if the backend response lacks it.

7. **Frontend: context-aware activity hero.** Compute the hero title and subtitle from `activityCategory`, `activityMonth`, and `activityPeriod`. Replace the static "All activity" / "Cross-account transactions matching your filters." copy with the conditional copy defined in §2 of Logic. Verify the hero renders correctly for each filter combination.

8. **Frontend: explanation header component.** Add the new `view-card` between the existing `activity-filters-card` and the existing `activity-list-card`. Wire the conditional rendering rules from §3 of Logic. Add the helper functions (`nounForCount`, `truncatePayee` for the top-transaction payee, `priorPeriodLabel`, `deltaArrow`, `deltaClass`). Add the corresponding CSS to the existing `<style>` block.

9. **Frontend: activity row layout change.** Update the row template to extract the category into a leading `.activity-category-pill` and wrap the payee in an inline `<span>` with `title={tx.payee}` and a `truncatePayee(tx.payee)` call. Hide the category pill when `activityCategory` is set. Update the meta line to omit the category. Add the corresponding CSS for `.activity-headline`, `.activity-category-pill`, and the updated `.activity-payee` selector.

10. **Manual verification.** Click through from a dashboard category trend → activity view. Confirm the hero shows the category name, the explanation header shows comparison data, and rows show category pills hidden because the filter is active. Click a cash flow month from the dashboard → confirm the month-titled hero, monthly comparison, and visible category pills (no category filter active). Open the activity view directly with no filters → confirm "All activity" title, period summary, visible category pills. Open the activity view with a deliberately sparse category → confirm graceful degradation when prior or rolling data is unavailable.

11. **Run the full test suite.** `uv run pytest -q` in `app/backend` and `pnpm check` in `app/frontend`. Update `ROADMAP.md` to mark 7a shipped on close.

## Definition of Done

- Every filtered activity view leads with an explanation header that answers "how does this compare?" before showing the transaction list.
- Category is visually primary in activity rows. Raw bank payees are truncated with full text on hover.
- The summary block is computed in a single pass alongside the existing transaction filter — no additional backend queries or file I/O.
- Graceful degradation when history is sparse (first month, new category, single transaction).
- No regressions in the existing activity view behavior, filter chips, period presets, dashboard drilldown links, or the per-account register view.
- All existing tests continue to pass. New tests cover the summary computation for each filter type and edge case.
- The explanation header reads exclusively from the backend `summary` block. The frontend performs no comparison math.

## UX Notes

- The explanation header is read-only context. No buttons, no toggles, no expand/collapse, no interactivity.
- Copy is finance-first: "5 purchases", "avg $360 each", "6-month average". No technical terms, no "transactions" when "purchases" is more accurate.
- The category pill uses a small, neutral, brand-tinted background — visually distinct but not loud. Color-coding by category type (expense vs income) is optional polish for a future task; neutral is fine for v1.
- Payee truncation at 50 chars is the default. On narrow viewports, the CSS `text-overflow: ellipsis` can take over with a smaller effective limit driven by the available column width. JS truncation is the floor, CSS is the ceiling.
- The "Biggest" line is a subtle nudge: it surfaces the one transaction worth investigating. Muted text, no icon, no color. It must not feel like an alert.
- Delta arrows (↑ ↓) follow the existing app convention: spending increases use the negative class (red-tinted), spending decreases use the positive class (green-tinted), income follows the inverse.
- The header lines stack vertically with tight spacing — this is a compact context strip, not a hero.
- When the category filter is active, the redundant per-row category pill is hidden. This is a small but important touch: it removes visual noise that would otherwise repeat the same category 24 times in a 24-row list.

## Out of Scope

- Dashboard "Where should I go next?" panel (Feature 7b).
- Health signal charts: runway gauge, net worth sparkline, recurring vs discretionary bar (Feature 7b).
- Notable-signal generation: largest transaction this week, category spikes, spending streaks (Feature 7b).
- Loose-ends aggregator panel on the dashboard (Feature 7b).
- Sidebar copy rewrites, hero CTA fallthrough, /rules loading-state fix, mobile nav drawer, cash flow zero-row hygiene (Feature 7c).
- Sort toggle (amount vs date) in the activity list — defer to future polish.
- Per-account register changes — this task is scoped to the cross-account activity view only.
- Color-coding category pills by category type — neutral pills for v1.
- Payee alias suggestions or a "clean up this payee" affordance from the activity view.
- Goals, targets, or budgets — deferred per roadmap.
- GenAI trend analysis — deferred.
- Investment tracking (401(k), HSA) — out of scope.
- Bulk-edit or multi-select on the activity list.
- Drilldown from a row in the activity view into a per-transaction detail page.
