<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { echarts, type EChartsInstance } from '$lib/echarts';
  import type { TrackedAccount, TransactionFilters, TransactionRow } from '$lib/transactions/types';
  import { formatCurrency, type AccountKind } from '$lib/format';
  import { categoryLeadingSegment, truncatePayee } from '$lib/transactions/helpers';

  // Editorial dossier for any slice of transactions. The shape never changes:
  // hero + KPIs, 12-month trend, top merchants, adaptive secondary panel.
  // What changes is which dimension drives the title/direction and what the
  // adaptive panel shows. This keeps the page layout consistent regardless
  // of which filters are active so users get the same scaffolding whether
  // they arrive from the sidebar, an account, a category drill, or any combo.
  export let filters: TransactionFilters;
  // historyRows: rows matching every filter EXCEPT period/month and search.
  // Drives the outer (faded) trend bars and the 6-month baseline so the
  // chart context never shrinks just because the user typed a search query.
  export let historyRows: TransactionRow[];
  // historyRowsHighlight: rows matching every filter EXCEPT period/month
  // (search IS applied). When a search is active and this differs from
  // historyRows, render a Power-BI-style cross-filter highlight on the
  // trend showing the matched portion of each month inside the outer bar.
  // Pass the same array as historyRows when no search is active.
  export let historyRowsHighlight: TransactionRow[];
  export let currentRows: TransactionRow[];
  export let trackedAccounts: TrackedAccount[];
  export let accountKindById: Map<string, AccountKind>;
  export let baseCurrency: string;
  // Callback the page wires to changeFilters({ ...filters, month, period: null })
  // so chart clicks update state directly. Without this, navigation alone
  // wouldn't re-fetch because the page's URL parsing only runs in onMount.
  export let onMonthFocus: (month: string | null) => void = () => {};

  type DirectionMode = 'expense' | 'income' | 'net';

  function categoryParts(cat: string): string[] {
    return cat.split(':').filter(Boolean);
  }
  function leafLabel(cat: string): string {
    const parts = categoryParts(cat);
    return parts[parts.length - 1] ?? cat;
  }
  function categoryAncestors(cat: string): string[] {
    const parts = categoryParts(cat);
    return parts.slice(0, -1);
  }

  function accountName(id: string): string {
    return trackedAccounts.find((a) => a.id === id)?.displayName ?? id;
  }

  // Pick the headline subject of the dossier. Most-specific filter wins so
  // the user immediately sees "what is this page about" without rereading
  // the filter chips. Order: category → single account → search → status →
  // multi-account → period-only → catch-all "Activity."
  function pickSubject(f: TransactionFilters): { eyebrow: string; title: string } {
    if (f.category) {
      const parents = categoryAncestors(f.category);
      const eyebrow = parents.length ? `Category report  ·  ${parents.join(' / ')}` : 'Category report';
      return { eyebrow, title: leafLabel(f.category) };
    }
    if (f.accounts.length === 1) {
      return { eyebrow: 'Account register', title: accountName(f.accounts[0]) };
    }
    if (f.search) {
      return { eyebrow: 'Search results', title: `“${f.search}”` };
    }
    if (f.status) {
      const cap = f.status.charAt(0).toUpperCase() + f.status.slice(1);
      return { eyebrow: 'Status filter', title: `${cap} transactions` };
    }
    if (f.accounts.length > 1) {
      return { eyebrow: 'Activity report', title: `${f.accounts.length} accounts` };
    }
    return { eyebrow: 'Activity report', title: 'All activity' };
  }

  // Other-filter chips shown beside the period chip so the dossier always
  // surfaces the full filter context, not just the headline subject.
  function pickContextChips(f: TransactionFilters): string[] {
    const chips: string[] = [];
    if (f.category && f.accounts.length === 1) chips.push(accountName(f.accounts[0]));
    if (f.category && f.accounts.length > 1) chips.push(`${f.accounts.length} accounts`);
    if (!f.category && f.accounts.length === 1 && f.status) chips.push(f.status);
    if (f.search && (f.category || f.accounts.length > 0)) chips.push(`“${f.search}”`);
    return chips;
  }

  // Single-account direction follows the account kind: assets read inflow as
  // positive (income-like), liabilities read inflow as positive (paydown).
  // For category-driven views we follow the category's leading segment.
  // Otherwise net the signed total — that's the only honest answer when the
  // slice can mix inflows and outflows.
  function directionFor(f: TransactionFilters): DirectionMode {
    if (f.category) {
      const lead = categoryLeadingSegment(f.category);
      if (lead === 'Expenses') return 'expense';
      if (lead === 'Income') return 'income';
    }
    return 'net';
  }

  function magnitudeLabel(dir: DirectionMode): string {
    if (dir === 'expense') return 'Spent';
    if (dir === 'income') return 'Received';
    return 'Net';
  }

  // Sum the way the user thinks about this slice. expense/income flatten to
  // an unsigned magnitude; net keeps the sign so a negative answer is honest.
  function magnitudeFor(rows: TransactionRow[], dir: DirectionMode): number {
    if (dir === 'net') return rows.reduce((s, r) => s + r.amount, 0);
    return rows.reduce((s, r) => s + Math.abs(r.amount), 0);
  }

  function monthKey(d: string): string { return d.slice(0, 7); }
  function previousMonth(m: string): string {
    const [y, mo] = m.split('-').map(Number);
    const d = new Date(y, mo - 1, 1);
    d.setMonth(d.getMonth() - 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  }
  function monthLabel(m: string): string {
    const [y, mo] = m.split('-').map(Number);
    return new Date(y, mo - 1, 1).toLocaleDateString(undefined, { month: 'short' });
  }
  function monthTitle(m: string): string {
    const [y, mo] = m.split('-').map(Number);
    return new Date(y, mo - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  }
  function periodLabel(m: string | null, p: string | null): string {
    if (m) return monthTitle(m);
    if (p === 'this-month') return 'This month';
    if (p === 'last-30') return 'Last 30 days';
    if (p === 'last-3-months') return 'Last 3 months';
    if (p === 'ytd') return 'Year to date';
    return 'All time';
  }

  function lastNMonths(n: number): string[] {
    const months: string[] = [];
    const now = new Date();
    now.setDate(1);
    for (let i = n - 1; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      months.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    }
    return months;
  }

  function bucketByMonth(rows: TransactionRow[], dir: DirectionMode, months: string[]): number[] {
    const bucket = new Map<string, number>();
    for (const r of rows) {
      const k = monthKey(r.date);
      const v = dir === 'net' ? r.amount : Math.abs(r.amount);
      bucket.set(k, (bucket.get(k) ?? 0) + v);
    }
    return months.map((m) => bucket.get(m) ?? 0);
  }

  // Split rows into income vs expense buckets per month for the paired
  // bar chart in net mode. Both arrays return positive magnitudes — the
  // chart series renders them side-by-side, not signed.
  function pairedByMonth(rows: TransactionRow[], months: string[]): { income: number[]; spending: number[] } {
    const incomeBucket = new Map<string, number>();
    const spendBucket = new Map<string, number>();
    for (const r of rows) {
      const acct = r.categories[0]?.account ?? '';
      const lead = categoryLeadingSegment(acct);
      const k = monthKey(r.date);
      if (lead === 'Income') {
        incomeBucket.set(k, (incomeBucket.get(k) ?? 0) + Math.abs(r.amount));
      } else if (lead === 'Expenses') {
        spendBucket.set(k, (spendBucket.get(k) ?? 0) + Math.abs(r.amount));
      }
      // Other categories (transfers, equity) are intentionally dropped — the
      // P&L exclusion logic upstream already filters them in net mode.
    }
    return {
      income: months.map((m) => incomeBucket.get(m) ?? 0),
      spending: months.map((m) => spendBucket.get(m) ?? 0)
    };
  }

  type MerchantTotal = { payee: string; amount: number; count: number };
  function topMerchants(rows: TransactionRow[], dir: DirectionMode, limit: number): MerchantTotal[] {
    const map = new Map<string, MerchantTotal>();
    for (const r of rows) {
      const v = dir === 'net' ? Math.abs(r.amount) : Math.abs(r.amount);
      const cur = map.get(r.payee);
      if (cur) { cur.amount += v; cur.count += 1; }
      else map.set(r.payee, { payee: r.payee, amount: v, count: 1 });
    }
    return Array.from(map.values()).sort((a, b) => b.amount - a.amount).slice(0, limit);
  }

  type CategoryTotal = { account: string; label: string; amount: number; count: number };
  function topCategories(rows: TransactionRow[], limit: number): CategoryTotal[] {
    const map = new Map<string, CategoryTotal>();
    for (const r of rows) {
      const cat = r.categories[0];
      if (!cat) continue;
      const lead = categoryLeadingSegment(cat.account);
      // Skip transfer-y accounts so the breakdown stays focused on income/spending.
      if (lead !== 'Expenses' && lead !== 'Income') continue;
      const v = Math.abs(cat.amount);
      const cur = map.get(cat.account);
      if (cur) { cur.amount += v; cur.count += 1; }
      else map.set(cat.account, { account: cat.account, label: cat.label, amount: v, count: 1 });
    }
    return Array.from(map.values()).sort((a, b) => b.amount - a.amount).slice(0, limit);
  }

  type Subcat = { key: string; label: string; amount: number; count: number };
  function subcategorySplit(rows: TransactionRow[], parent: string, dir: DirectionMode): Subcat[] {
    const prefix = parent + ':';
    const map = new Map<string, Subcat>();
    for (const r of rows) {
      const acct = r.categories[0]?.account ?? '';
      if (acct === parent || !acct.startsWith(prefix)) continue;
      const tail = acct.slice(prefix.length);
      const key = tail.split(':')[0] ?? tail;
      const v = dir === 'net' ? r.amount : Math.abs(r.amount);
      const cur = map.get(key);
      if (cur) { cur.amount += v; cur.count += 1; }
      else map.set(key, { key, label: key, amount: v, count: 1 });
    }
    return Array.from(map.values()).sort((a, b) => b.amount - a.amount);
  }

  function byWeekday(rows: TransactionRow[], dir: DirectionMode) {
    const labels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const buckets = labels.map((d) => ({ day: d, amount: 0, count: 0 }));
    for (const r of rows) {
      const d = new Date(`${r.date}T00:00:00`);
      const idx = d.getDay();
      const v = dir === 'net' ? Math.abs(r.amount) : Math.abs(r.amount);
      buckets[idx].amount += v;
      buckets[idx].count += 1;
    }
    return buckets;
  }

  function maxOrZero(values: number[]): number {
    return values.length ? Math.max(...values) : 0;
  }

  function fmt(amount: number): string {
    return formatCurrency(amount, baseCurrency);
  }
  function fmtSigned(amount: number): string {
    return formatCurrency(amount, baseCurrency, { signMode: 'always' });
  }
  // Unsigned for "bad-direction" changes, "+$X" green for "good-direction"
  // changes — the existing app-wide convention. Used for the big NET amount
  // and the 12-month NET KPI when we know the account kind.
  function fmtKindAware(amount: number, kind: AccountKind | null): string {
    if (kind === null) return fmtSigned(amount);
    return formatCurrency(amount, baseCurrency, { signMode: 'good-change-plus', accountKind: kind });
  }
  // Tone class for kind-aware amounts: matches goodChangeTone() — positive
  // amount on either kind is a "good change" (green), everything else is
  // neutral. We don't paint bad-direction amounts red here; the unsigned
  // rendering itself already encodes "this is the normal/expected direction."
  function kindToneClass(amount: number, kind: AccountKind | null): string {
    if (kind === null) return amount < 0 ? 'fig-neg' : '';
    return amount > 0 ? 'fig-pos' : '';
  }

  function clearMonth() { onMonthFocus(null); }
  function focusMonth(m: string) { onMonthFocus(m); }

  $: subject = pickSubject(filters);
  $: contextChips = pickContextChips(filters);
  $: dir = directionFor(filters);
  // When exactly one account is filtered we know whether "good" means up
  // (asset) or down (liability), which lets us apply the existing
  // unsigned/green-plus convention consistently across the dossier.
  $: filteredAccountKind = filters.accounts.length === 1
    ? (accountKindById.get(filters.accounts[0]) ?? null)
    : null;

  // In net mode (no category filter) the dossier reports P&L. We restrict
  // to rows whose primary category is Income or Expenses — that's the
  // ground-truth filter for "real flow," and it correctly drops transfers
  // (Assets:Transfer-style accounts), opening balances (Equity:Opening),
  // and balance assertions in one rule. Relying on the backend's flags
  // (isOpeningBalance/isTransfer) misses cases where setup transactions
  // weren't tagged. Category-driven views never need this filter because
  // they're already restricted to one category.
  function netRowsOf(rows: TransactionRow[]): TransactionRow[] {
    if (dir !== 'net') return rows;
    return rows.filter((r) => {
      const lead = categoryLeadingSegment(r.categories[0]?.account ?? '');
      return lead === 'Expenses' || lead === 'Income';
    });
  }
  $: visibleHistory = netRowsOf(historyRows);
  $: visibleHistoryHighlight = netRowsOf(historyRowsHighlight);
  $: visibleCurrent = netRowsOf(currentRows);

  $: trendMonths = lastNMonths(12);
  $: trendValues = bucketByMonth(visibleHistory, dir, trendMonths);
  $: trendDisplay = trendValues.map((v) => Math.abs(v));
  $: trendMax = maxOrZero(trendDisplay);
  $: trendHighlightValues = bucketByMonth(visibleHistoryHighlight, dir, trendMonths);
  $: trendHighlightDisplay = trendHighlightValues.map((v) => Math.abs(v));
  // Only render the inner highlight when a search is narrowing the result —
  // identical arrays would draw a redundant bar inside itself.
  $: hasHighlight = !!filters.search && historyRowsHighlight !== historyRows;
  $: focusedTrendIndex = filters.month ? trendMonths.indexOf(filters.month) : -1;
  $: trendFocusIndex = focusedTrendIndex >= 0 ? focusedTrendIndex : trendMonths.length - 1;

  // Paired income/spending breakdown for net-mode chart. Computed from the
  // *un-net-filtered* historyRows so income and spending each isolate their
  // own categorized rows (the netRowsOf filter is for the gist/KPI scalar
  // total, not for the chart breakdown).
  $: paired = pairedByMonth(historyRows, trendMonths);
  $: pairedHighlight = pairedByMonth(historyRowsHighlight, trendMonths);
  $: pairedMax = Math.max(maxOrZero(paired.income), maxOrZero(paired.spending));

  $: currentTotal = magnitudeFor(visibleCurrent, dir);
  $: currentTotalAbs = Math.abs(currentTotal);
  $: currentCount = visibleCurrent.length;
  $: currentAvg = currentCount > 0 ? currentTotalAbs / currentCount : 0;

  // KPIs and gist comparisons follow the *searched* slice so the dossier
  // numbers are internally consistent. The trend chart still shows the
  // unsearched data as outer bars to preserve context — that's the only
  // place the outer/inner distinction surfaces visually.
  $: priorMonth = filters.month ? previousMonth(filters.month) : null;
  $: priorMonthIndex = priorMonth ? trendMonths.indexOf(priorMonth) : -1;
  $: priorMonthValue = priorMonthIndex >= 0 ? trendHighlightValues[priorMonthIndex] : null;

  // "Spending lens": present the slice as "how much was spent" rather than
  // "how much was netted." Expense categories always read this way; net mode
  // on a liability does too (charges are the dominant story); and net mode
  // with no kind context falls into spending lens when the current total is
  // negative (you spent more than you took in). In spending lens, the
  // up/down arrow follows |amount| direction so "down 68%" reads naturally
  // as "spent 68% less" instead of the signed delta which would read "up
  // 68%" because -200 > -600 numerically.
  $: spendingLens = dir === 'expense'
    || (dir === 'net' && filteredAccountKind === 'liability')
    || (dir === 'net' && filteredAccountKind === null && currentTotal < 0);

  // deltaForUser is what the arrow + percentage display: in spending lens,
  // compare magnitudes; otherwise compare signed values.
  $: deltaForUser = (() => {
    if (priorMonthValue === null || priorMonthValue === 0) return null;
    if (spendingLens) {
      const cur = Math.abs(currentTotal);
      const prior = Math.abs(priorMonthValue);
      if (prior === 0) return null;
      return ((cur - prior) / prior) * 100;
    }
    return ((currentTotal - priorMonthValue) / Math.abs(priorMonthValue)) * 100;
  })();
  $: deltaVsPrior = deltaForUser;

  $: rollingMonths = filters.month
    ? trendMonths.filter((m) => m !== filters.month).slice(-6)
    : trendMonths.slice(-7, -1);
  $: rollingAvg = rollingMonths.length
    ? rollingMonths.reduce((s, m) => {
        const i = trendMonths.indexOf(m);
        return s + (i >= 0 ? Math.abs(trendHighlightValues[i]) : 0);
      }, 0) / rollingMonths.length
    : 0;

  // Paired-bar baselines: separate income and spending averages so the
  // reference lines on the net-mode chart aren't ambiguous about which
  // series they measure. Use the *highlight* dataset for parity with the
  // KPI math when a search is active.
  function avgFromBuckets(values: number[], months: string[]): number {
    if (!months.length) return 0;
    let total = 0;
    for (const m of months) {
      const i = trendMonths.indexOf(m);
      if (i >= 0) total += values[i];
    }
    return total / months.length;
  }
  $: rollingIncomeAvg = avgFromBuckets(pairedHighlight.income, rollingMonths);
  $: rollingSpendAvg = avgFromBuckets(pairedHighlight.spending, rollingMonths);

  $: merchants = topMerchants(visibleCurrent, dir, 6);
  $: merchantMax = maxOrZero(merchants.map((m) => m.amount));

  $: subcats = filters.category ? subcategorySplit(visibleCurrent, filters.category, dir) : [];
  $: subTotal = subcats.reduce((s, c) => s + c.amount, 0);

  $: categoryBreakdown = !filters.category ? topCategories(visibleCurrent, 6) : [];
  $: categoryMax = maxOrZero(categoryBreakdown.map((c) => c.amount));

  $: weekday = byWeekday(visibleCurrent, dir);
  $: weekdayMax = maxOrZero(weekday.map((d) => d.amount));

  $: monthScopedView = filters.month !== null || filters.period === 'this-month' || filters.period === 'last-30';

  // Number of rows excluded from the dossier math (transfers in net mode).
  // Surfaced in the gist so users don't notice the discrepancy between the
  // dossier count and the bottom-of-page list count without an explanation.
  $: excludedTransfers = currentRows.length - visibleCurrent.length;

  $: gist = (() => {
    if (currentCount === 0) return 'No transactions match these filters yet.';
    const verb = dir === 'expense' || spendingLens
      ? 'spent'
      : dir === 'income'
        ? 'received'
        : (currentTotal >= 0 ? 'netted' : 'spent net');
    const amount = fmt(currentTotalAbs);
    let s = `You ${verb} ${amount} across ${currentCount} ${currentCount === 1 ? 'transaction' : 'transactions'}${excludedTransfers > 0 ? ` (${excludedTransfers} non-P&L ${excludedTransfers === 1 ? 'entry' : 'entries'} excluded)` : ''}.`;
    if (deltaVsPrior !== null) {
      // Use spending vocabulary when in spending lens, savings/income otherwise.
      const dirWord = spendingLens || dir === 'expense'
        ? (deltaVsPrior > 0 ? 'up' : 'down')
        : (deltaVsPrior > 0 ? 'up' : 'down');
      const tone = deltaTone === 'good' ? ' ✓' : '';
      s += ` That's ${dirWord} ${Math.abs(deltaVsPrior).toFixed(0)}% from ${monthTitle(priorMonth!)}${tone}.`;
    } else if (monthScopedView && rollingAvg > 0) {
      const ratio = currentTotalAbs / rollingAvg;
      if (ratio > 1.15) s += ` Running ${(((ratio - 1) * 100)).toFixed(0)}% above your 6-month pace.`;
      else if (ratio < 0.85) s += ` Running ${((1 - ratio) * 100).toFixed(0)}% below your 6-month pace.`;
      else s += ` Roughly in line with your 6-month pace.`;
    } else if (!monthScopedView) {
      const months = Math.max(1, trendDisplay.filter((v) => v > 0).length);
      const perMonth = currentTotalAbs / months;
      s += ` Averaging ${fmt(perMonth)}/mo across ${months} active ${months === 1 ? 'month' : 'months'}.`;
    }
    return s;
  })();

  $: deltaTone = (() => {
    if (deltaVsPrior === null) return 'neutral';
    // In spending lens, less spending (negative delta) is favorable.
    // Otherwise (income/asset/mixed positive net), more is favorable.
    if (spendingLens) return deltaVsPrior < 0 ? 'good' : 'bad';
    if (dir === 'income') return deltaVsPrior > 0 ? 'good' : 'bad';
    return deltaVsPrior > 0 ? 'good' : 'bad';
  })();

  $: vsAvgPct = monthScopedView && rollingAvg > 0 ? ((currentTotalAbs - rollingAvg) / rollingAvg) * 100 : null;
  $: vsAvgTone = (() => {
    if (vsAvgPct === null) return 'neutral';
    if (Math.abs(vsAvgPct) < 5) return 'neutral';
    // vsAvgPct is computed on absolute values, so it always represents
    // magnitude direction. Spending lens prefers smaller magnitudes.
    if (spendingLens) return vsAvgPct < 0 ? 'good' : 'bad';
    if (dir === 'income') return vsAvgPct > 0 ? 'good' : 'bad';
    return vsAvgPct > 0 ? 'good' : 'bad';
  })();

  // Pick which secondary panel shows on the right. Keeps the layout shape
  // identical across modes — only the *content* of the right cell adapts.
  $: rightPanel = (() => {
    if (subcats.length > 0) return 'subcats';
    if (filters.category) return 'weekday';
    if (categoryBreakdown.length > 0) return 'categories';
    return 'weekday';
  })();

  // ─── ECharts trend ────────────────────────────────────────────────────
  // Matches the dashboard's CashFlowChart aesthetic (paired Income +
  // Spending bars, same colors). When a category narrows the slice we show
  // a single bar series colored to match the direction. Cross-filter
  // overlay (search) is rendered as a dimmed outer + solid inner pair via
  // overlapping ECharts series with barGap '-100%'.
  let chartContainer: HTMLDivElement | null = null;
  let chart: EChartsInstance | null = null;
  let chartObserver: ResizeObserver | null = null;

  const COLOR_INCOME = '#1d9f6e';
  const COLOR_SPENDING = '#0a3d59';
  const COLOR_FOCUS_RING = '#ad6a00';

  function buildChartOption() {
    const xLabels = trendMonths.map((m) => monthLabel(m));
    const focusIdx = focusedTrendIndex >= 0 ? focusedTrendIndex : trendMonths.length - 1;
    const useNet = dir === 'net';

    // Per-bar opacity helper — focused month at full opacity, others slightly
    // dimmed when a focus exists at all.
    const dataWithFocus = (vals: number[], color: string) => vals.map((v, i) => ({
      value: v,
      itemStyle: {
        color,
        borderRadius: [4, 4, 0, 0] as [number, number, number, number],
        opacity: focusedTrendIndex >= 0 && i !== focusIdx ? 0.55 : 1
      }
    }));

    const baseSeries = useNet
      ? [
          {
            name: 'Income',
            type: 'bar' as const,
            cursor: 'pointer',
            data: dataWithFocus(paired.income, COLOR_INCOME),
            ...(hasHighlight ? { itemStyle: { opacity: 0.25 } } : {})
          },
          {
            name: 'Spending',
            type: 'bar' as const,
            cursor: 'pointer',
            data: dataWithFocus(paired.spending, COLOR_SPENDING),
            ...(hasHighlight ? { itemStyle: { opacity: 0.25 } } : {})
          }
        ]
      : [
          {
            name: dir === 'income' ? 'Received' : 'Spent',
            type: 'bar' as const,
            cursor: 'pointer',
            data: dataWithFocus(trendDisplay, dir === 'income' ? COLOR_INCOME : COLOR_SPENDING),
            ...(hasHighlight ? { itemStyle: { opacity: 0.25 } } : {})
          }
        ];

    // When a search narrows the result, overlay solid inner bars showing
    // the matched portion. barGap '-100%' makes them sit on top of the
    // outer bars rather than beside them.
    const highlightSeries = hasHighlight
      ? (useNet
          ? [
              {
                name: 'Income (match)',
                type: 'bar' as const,
                cursor: 'pointer',
                barGap: '-100%',
                z: 3,
                data: dataWithFocus(pairedHighlight.income, COLOR_INCOME)
              },
              {
                name: 'Spending (match)',
                type: 'bar' as const,
                cursor: 'pointer',
                barGap: '-100%',
                z: 3,
                data: dataWithFocus(pairedHighlight.spending, COLOR_SPENDING)
              }
            ]
          : [
              {
                name: 'Match',
                type: 'bar' as const,
                cursor: 'pointer',
                barGap: '-100%',
                z: 3,
                data: dataWithFocus(trendHighlightDisplay, dir === 'income' ? COLOR_INCOME : COLOR_SPENDING)
              }
            ])
      : [];

    // Markline(s) for the 6-month rolling baseline. In net mode we draw
    // two distinct color-matched lines so the user can tell income avg
    // from spending avg at a glance. In single-direction mode one line
    // suffices and matches the bar color.
    const series = [...baseSeries, ...highlightSeries];
    if (series.length > 0) {
      const baseLineStyle = (color: string) => ({
        color, type: 'dashed' as const, width: 1, opacity: 0.7
      });
      const baseLabel = (text: string, color: string) => ({
        formatter: text,
        position: 'insideEndTop' as const,
        color, fontSize: 10, fontWeight: 600,
        backgroundColor: 'rgba(255,255,255,0.92)',
        padding: [2, 4, 2, 4] as [number, number, number, number],
        borderRadius: 3
      });
      const lines: Array<Record<string, unknown>> = [];
      if (useNet) {
        if (rollingIncomeAvg > 0) {
          lines.push({
            name: 'Avg income',
            yAxis: rollingIncomeAvg,
            lineStyle: baseLineStyle(COLOR_INCOME),
            label: baseLabel(`Avg income · ${fmt(rollingIncomeAvg)}`, COLOR_INCOME)
          });
        }
        if (rollingSpendAvg > 0) {
          lines.push({
            name: 'Avg spending',
            yAxis: rollingSpendAvg,
            lineStyle: baseLineStyle(COLOR_SPENDING),
            label: baseLabel(`Avg spending · ${fmt(rollingSpendAvg)}`, COLOR_SPENDING)
          });
        }
      } else if (rollingAvg > 0) {
        const c = dir === 'income' ? COLOR_INCOME : COLOR_SPENDING;
        lines.push({
          name: '6-mo avg',
          yAxis: rollingAvg,
          lineStyle: baseLineStyle(c),
          label: baseLabel(`6-mo avg · ${fmt(rollingAvg)}`, c)
        });
      }
      if (lines.length) {
        (series[0] as Record<string, unknown>).markLine = {
          symbol: 'none', silent: true, animation: false, data: lines
        };
      }
    }

    return {
      animationDuration: 350,
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: 'rgba(10,61,89,0.12)',
        borderWidth: 1,
        textStyle: { color: '#0a3d59', fontSize: 12 },
        formatter: (params: Array<{ axisValue: string; seriesName: string; value: number; color: string }>) => {
          if (!params.length) return '';
          const idx = trendMonths.findIndex((m) => monthLabel(m) === params[0].axisValue);
          const month = idx >= 0 ? monthTitle(trendMonths[idx]) : params[0].axisValue;
          const lines = params
            .filter((p) => p.value > 0)
            .map((p) => `<div style="display:flex;gap:8px;align-items:center;margin-top:2px"><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color}"></span><span style="flex:1">${p.seriesName}</span><span style="font-variant-numeric:tabular-nums;font-weight:600">${fmt(p.value)}</span></div>`)
            .join('');
          return `<div style="font-weight:700;margin-bottom:2px">${month}</div>${lines || '<div style="color:rgba(10,61,89,0.5)">No activity</div>'}`;
        }
      },
      legend: useNet
        ? {
            data: ['Income', 'Spending'],
            bottom: 0,
            textStyle: { fontSize: 11, color: 'rgba(10,61,89,0.7)' },
            itemWidth: 10,
            itemHeight: 10
          }
        : { show: false },
      grid: { top: 20, right: 8, bottom: useNet ? 28 : 20, left: 8, containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: xLabels,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: 'rgba(10,61,89,0.12)' } },
        axisLabel: {
          color: (_v: string, idx: number) => idx === focusIdx ? '#0a3d59' : 'rgba(10,61,89,0.55)',
          fontWeight: (_v: string, idx: number) => idx === focusIdx ? 700 : 500,
          fontSize: 11,
          letterSpacing: 0.5
        }
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { show: false },
        splitLine: { lineStyle: { type: 'dashed' as const, color: 'rgba(10,61,89,0.06)' } }
      },
      series
    };
  }

  function mountChart() {
    if (!chartContainer) return;
    chart = echarts.init(chartContainer);
    chart.setOption(buildChartOption());
    chart.on('click', (params: { dataIndex: number }) => {
      if (typeof params.dataIndex === 'number' && trendMonths[params.dataIndex]) {
        focusMonth(trendMonths[params.dataIndex]);
      }
    });
    chartObserver = new ResizeObserver(() => chart?.resize());
    chartObserver.observe(chartContainer);
  }

  // Re-render whenever any input the chart depends on changes. ECharts'
  // setOption is idempotent + diff-aware, so this is cheap.
  $: if (chart && trendMonths) {
    chart.setOption(buildChartOption(), { notMerge: true });
  }

  onMount(() => mountChart());
  onDestroy(() => {
    chartObserver?.disconnect();
    chart?.dispose();
    chart = null;
  });
</script>

<section class="dossier">
  <div class="dossier-hero" data-direction={dir}>
    <div class="dossier-hero-band" aria-hidden="true"></div>
    <div class="dossier-hero-grid">
      <div class="dossier-hero-text">
        <p class="dossier-eyebrow">{subject.eyebrow}</p>
        <h1 class="dossier-title">{subject.title}</h1>
        <div class="dossier-period">
          <span class="dossier-period-chip">{periodLabel(filters.month, filters.period)}</span>
          {#if filters.month}
            <button class="dossier-period-clear" type="button" on:click={clearMonth}>Clear month</button>
          {/if}
          {#each contextChips as chip}
            <span class="dossier-context-chip">{chip}</span>
          {/each}
        </div>
        <p class="dossier-gist">{gist}</p>
      </div>

      <div class="dossier-hero-figure">
        <p class="dossier-fig-eyebrow">{magnitudeLabel(dir)}</p>
        <p class="dossier-fig-amount {dir === 'net' ? kindToneClass(currentTotal, filteredAccountKind) : ''}">
          {dir === 'net' ? fmtKindAware(currentTotal, filteredAccountKind) : fmt(currentTotal)}
        </p>
        {#if deltaVsPrior !== null}
          <p class="dossier-fig-delta" data-tone={deltaTone}>
            <span class="delta-arrow">{deltaVsPrior > 0 ? '▲' : '▼'}</span>
            {Math.abs(deltaVsPrior).toFixed(0)}% vs {monthLabel(priorMonth!)}
          </p>
        {:else if vsAvgPct !== null}
          <p class="dossier-fig-delta" data-tone={vsAvgTone}>
            {vsAvgPct > 0 ? '▲' : '▼'} {Math.abs(vsAvgPct).toFixed(0)}% vs 6-mo avg
          </p>
        {/if}
      </div>
    </div>

    <div class="dossier-kpis">
      <div class="kpi">
        <p class="kpi-label">Transactions</p>
        <p class="kpi-value">{currentCount}</p>
      </div>
      <div class="kpi">
        <p class="kpi-label">Avg per transaction</p>
        <p class="kpi-value">{fmt(currentAvg)}</p>
      </div>
      <div class="kpi">
        <p class="kpi-label">6-month average</p>
        <p class="kpi-value">{fmt(rollingAvg)}<span class="kpi-unit">/mo</span></p>
      </div>
      <div class="kpi">
        <p class="kpi-label">12-month {dir === 'net' ? 'net' : 'total'}</p>
        <p class="kpi-value">{dir === 'net'
          ? fmtKindAware(trendHighlightValues.reduce((s, v) => s + v, 0), filteredAccountKind)
          : fmt(trendHighlightDisplay.reduce((s, v) => s + v, 0))}</p>
      </div>
    </div>
  </div>

  <div class="dossier-card dossier-trend">
    <div class="dossier-card-head">
      <div>
        <p class="eyebrow">Trend</p>
        <h2 class="dossier-card-title">12-month shape</h2>
      </div>
      <p class="dossier-card-aux">Click a month to focus it</p>
    </div>

    {#if trendMax === 0 && (dir !== 'net' || pairedMax === 0)}
      <p class="dossier-empty">No matching activity in the last year.</p>
    {:else}
      <div bind:this={chartContainer} class="trend-chart" aria-label="12-month trend chart"></div>
    {/if}
  </div>

  <div class="dossier-grid">
    <div class="dossier-card">
      <div class="dossier-card-head">
        <div>
          <p class="eyebrow">Where it went</p>
          <h2 class="dossier-card-title">Top {dir === 'income' ? 'sources' : 'merchants'}</h2>
        </div>
        <p class="dossier-card-aux">In {periodLabel(filters.month, filters.period).toLowerCase()}</p>
      </div>
      {#if merchants.length === 0}
        <p class="dossier-empty">No transactions in this slice.</p>
      {:else}
        <ul class="merchant-list">
          {#each merchants as m, i}
            {@const pct = merchantMax > 0 ? (m.amount / merchantMax) * 100 : 0}
            <li class="merchant-row">
              <span class="merchant-rank">{String(i + 1).padStart(2, '0')}</span>
              <div class="merchant-body">
                <div class="merchant-line">
                  <span class="merchant-name" title={m.payee}>{truncatePayee(m.payee, 28)}</span>
                  <span class="merchant-amount">{fmt(m.amount)}</span>
                </div>
                <div class="merchant-bar"><span style="--w: {pct}%"></span></div>
                <p class="merchant-meta">{m.count} {m.count === 1 ? 'visit' : 'visits'} · avg {fmt(m.amount / m.count)}</p>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    {#if rightPanel === 'subcats'}
      <div class="dossier-card">
        <div class="dossier-card-head">
          <div>
            <p class="eyebrow">Composition</p>
            <h2 class="dossier-card-title">Subcategory split</h2>
          </div>
          <p class="dossier-card-aux">{subcats.length} {subcats.length === 1 ? 'subcategory' : 'subcategories'}</p>
        </div>
        <div class="split-stack" aria-hidden="true">
          {#each subcats as s, i}
            {@const pct = subTotal > 0 ? (s.amount / subTotal) * 100 : 0}
            <span class="split-seg" data-idx={i % 6} style="--pct: {pct}%" title={`${s.label}: ${fmt(s.amount)} (${pct.toFixed(0)}%)`}></span>
          {/each}
        </div>
        <ul class="split-legend">
          {#each subcats as s, i}
            {@const pct = subTotal > 0 ? (s.amount / subTotal) * 100 : 0}
            <li>
              <span class="split-dot" data-idx={i % 6}></span>
              <span class="split-label">{s.label}</span>
              <span class="split-pct">{pct.toFixed(0)}%</span>
              <span class="split-amt">{fmt(s.amount)}</span>
            </li>
          {/each}
        </ul>
      </div>
    {:else if rightPanel === 'categories'}
      <div class="dossier-card">
        <div class="dossier-card-head">
          <div>
            <p class="eyebrow">Composition</p>
            <h2 class="dossier-card-title">Top categories</h2>
          </div>
          <p class="dossier-card-aux">{categoryBreakdown.length} shown</p>
        </div>
        <ul class="merchant-list">
          {#each categoryBreakdown as c, i}
            {@const pct = categoryMax > 0 ? (c.amount / categoryMax) * 100 : 0}
            <li class="merchant-row">
              <span class="merchant-rank">{String(i + 1).padStart(2, '0')}</span>
              <div class="merchant-body">
                <div class="merchant-line">
                  <a class="merchant-name merchant-link" href={`/transactions?category=${encodeURIComponent(c.account)}${filters.month ? `&month=${filters.month}` : filters.period ? `&period=${filters.period}` : ''}`}>{c.label}</a>
                  <span class="merchant-amount">{fmt(c.amount)}</span>
                </div>
                <div class="merchant-bar"><span style="--w: {pct}%"></span></div>
                <p class="merchant-meta">{c.count} {c.count === 1 ? 'transaction' : 'transactions'}</p>
              </div>
            </li>
          {/each}
        </ul>
      </div>
    {:else}
      <div class="dossier-card">
        <div class="dossier-card-head">
          <div>
            <p class="eyebrow">Cadence</p>
            <h2 class="dossier-card-title">By day of week</h2>
          </div>
          <p class="dossier-card-aux">When it happens</p>
        </div>
        {#if weekdayMax === 0}
          <p class="dossier-empty">No transactions in this slice.</p>
        {:else}
          <div class="weekday-grid">
            {#each weekday as d}
              {@const h = weekdayMax > 0 ? Math.max(4, (d.amount / weekdayMax) * 100) : 4}
              <div class="weekday-col" title={`${d.day}: ${fmt(d.amount)} (${d.count})`}>
                <span class="weekday-amt">{d.count > 0 ? fmt(d.amount).replace(/\.\d+/, '') : ''}</span>
                <span class="weekday-bar" style="--h: {h}%"></span>
                <span class="weekday-day">{d.day}</span>
                <span class="weekday-count">{d.count}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</section>

<style>
  .dossier { display: grid; gap: 1rem; }

  /* HERO */
  .dossier-hero {
    position: relative;
    overflow: hidden;
    border-radius: 1.5rem;
    border: 1px solid rgba(10, 61, 89, 0.1);
    background:
      radial-gradient(circle at 0% 0%, rgba(214, 235, 220, 0.55), transparent 38%),
      radial-gradient(circle at 100% 0%, rgba(210, 230, 248, 0.55), transparent 42%),
      linear-gradient(160deg, #fdfcf6 0%, #f3f8fb 100%);
    padding: 1.75rem 1.85rem 1.4rem;
    box-shadow: 0 24px 50px -28px rgba(10, 61, 89, 0.35);
  }
  .dossier-hero-band {
    position: absolute;
    inset: 0 0 auto 0;
    height: 4px;
    background: linear-gradient(90deg, #0a3d59, #0f5f88 35%, #0d7f58 70%, #ad6a00);
    opacity: 0.85;
  }
  .dossier-hero[data-direction='income'] .dossier-hero-band {
    background: linear-gradient(90deg, #0d7f58, #1d9f6e 50%, #b8d96a);
  }
  .dossier-hero[data-direction='net'] .dossier-hero-band {
    background: linear-gradient(90deg, #0a3d59, #0f5f88 60%, #0d7f58);
  }
  .dossier-hero-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
    gap: 2rem;
    align-items: end;
  }
  @media (max-width: 720px) { .dossier-hero-grid { grid-template-columns: 1fr; gap: 1.25rem; } }

  .dossier-eyebrow {
    margin: 0 0 0.6rem;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: rgba(10, 61, 89, 0.62);
  }
  .dossier-title {
    margin: 0;
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: clamp(2.4rem, 5vw, 3.5rem);
    line-height: 0.95;
    letter-spacing: -0.02em;
    color: var(--brand-strong);
  }
  .dossier-period {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-top: 0.85rem;
    flex-wrap: wrap;
  }
  .dossier-period-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.3rem 0.75rem;
    border-radius: 999px;
    background: rgba(10, 61, 89, 0.06);
    color: var(--brand-strong);
    font-size: 0.84rem;
    font-weight: 600;
    border: 1px solid rgba(10, 61, 89, 0.1);
  }
  .dossier-context-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.3rem 0.75rem;
    border-radius: 999px;
    background: rgba(15, 95, 136, 0.05);
    color: rgba(10, 61, 89, 0.78);
    font-size: 0.78rem;
    font-weight: 500;
    border: 1px dashed rgba(15, 95, 136, 0.2);
  }
  .dossier-period-clear {
    background: none; border: none; padding: 0;
    color: rgba(10, 61, 89, 0.55);
    font-size: 0.78rem;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .dossier-period-clear:hover { color: var(--brand); }

  .dossier-gist {
    margin: 0.95rem 0 0;
    color: rgba(10, 61, 89, 0.75);
    font-size: 0.98rem;
    max-width: 60ch;
    line-height: 1.45;
  }

  .dossier-hero-figure {
    text-align: right;
    padding-left: 1rem;
    border-left: 1px solid rgba(10, 61, 89, 0.08);
  }
  @media (max-width: 720px) {
    .dossier-hero-figure {
      text-align: left; padding-left: 0; border-left: 0;
      border-top: 1px solid rgba(10, 61, 89, 0.08);
      padding-top: 1rem;
    }
  }
  .dossier-fig-eyebrow {
    margin: 0;
    font-size: 0.72rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.14em;
    color: rgba(10, 61, 89, 0.55);
  }
  .dossier-fig-amount {
    margin: 0.2rem 0 0;
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: clamp(2.6rem, 5.5vw, 3.8rem);
    line-height: 1; letter-spacing: -0.025em;
    color: #0a3d59; font-variant-numeric: tabular-nums;
  }
  .fig-neg { color: var(--bad); }
  .fig-pos { color: var(--ok); }
  .dossier-fig-delta {
    margin: 0.55rem 0 0;
    font-size: 0.95rem; font-weight: 600;
    color: rgba(10, 61, 89, 0.7);
  }
  .dossier-fig-delta[data-tone='good'] { color: var(--ok); }
  .dossier-fig-delta[data-tone='bad'] { color: var(--bad); }
  .delta-arrow { display: inline-block; transform: translateY(-1px); margin-right: 0.15rem; }

  .dossier-kpis {
    margin-top: 1.5rem;
    padding-top: 1.25rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 1.25rem;
  }
  @media (max-width: 720px) { .dossier-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  .kpi { display: grid; gap: 0.2rem; }
  .kpi-label {
    margin: 0;
    font-size: 0.7rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.12em;
    color: rgba(10, 61, 89, 0.55);
  }
  .kpi-value {
    margin: 0;
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: 1.35rem;
    color: var(--brand-strong);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
  }
  .kpi-unit {
    font-size: 0.78rem; color: rgba(10, 61, 89, 0.5);
    margin-left: 0.15rem; font-weight: 500;
  }

  /* CARDS */
  .dossier-card {
    background: rgba(255, 255, 255, 0.78);
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1.15rem;
    padding: 1.25rem 1.35rem;
    box-shadow: 0 8px 22px -16px rgba(10, 61, 89, 0.3);
  }
  .dossier-card-head {
    display: flex; align-items: flex-start; justify-content: space-between;
    gap: 1rem; margin-bottom: 1rem;
  }
  .dossier-card-title {
    margin: 0;
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: 1.15rem; color: var(--brand-strong);
    letter-spacing: -0.005em;
  }
  .dossier-card-aux {
    margin: 0; font-size: 0.78rem;
    color: rgba(10, 61, 89, 0.5); text-align: right;
  }
  .dossier-empty {
    margin: 0.5rem 0; color: rgba(10, 61, 89, 0.5); font-size: 0.9rem;
  }

  /* TREND */
  .dossier-trend { position: relative; }
  .trend-chart {
    width: 100%;
    height: 13.5rem;
    margin-top: 0.5rem;
  }

  /* GRID */
  .dossier-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
    gap: 1rem;
  }
  @media (max-width: 980px) { .dossier-grid { grid-template-columns: 1fr; } }

  /* MERCHANTS / CATEGORIES */
  .merchant-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.95rem; }
  .merchant-row {
    display: grid; grid-template-columns: 1.6rem 1fr;
    gap: 0.6rem; align-items: start;
  }
  .merchant-rank {
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: 0.85rem; color: rgba(10, 61, 89, 0.35);
    font-variant-numeric: tabular-nums; line-height: 1.4;
  }
  .merchant-body { display: grid; gap: 0.25rem; min-width: 0; }
  .merchant-line {
    display: flex; justify-content: space-between;
    gap: 0.75rem; align-items: baseline; min-width: 0;
  }
  .merchant-name {
    font-weight: 600; color: var(--brand-strong);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;
  }
  .merchant-link {
    text-decoration: none;
    transition: color 0.15s;
  }
  .merchant-link:hover {
    color: var(--brand);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .merchant-amount {
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    color: var(--brand-strong);
    font-variant-numeric: tabular-nums; flex-shrink: 0;
  }
  .merchant-bar {
    height: 5px; background: rgba(10, 61, 89, 0.06);
    border-radius: 999px; overflow: hidden;
  }
  .merchant-bar span {
    display: block; width: var(--w, 0%); height: 100%;
    background: linear-gradient(90deg, #0f5f88, #0a3d59);
    border-radius: 999px;
  }
  .merchant-meta { margin: 0; font-size: 0.74rem; color: rgba(10, 61, 89, 0.5); }

  /* SPLIT */
  .split-stack {
    display: flex; height: 14px;
    border-radius: 999px; overflow: hidden;
    background: rgba(10, 61, 89, 0.05);
    margin-bottom: 0.85rem;
  }
  .split-seg { display: block; width: var(--pct, 0%); transition: filter 0.15s; }
  .split-seg[data-idx='0'] { background: #0a3d59; }
  .split-seg[data-idx='1'] { background: #0f5f88; }
  .split-seg[data-idx='2'] { background: #0d7f58; }
  .split-seg[data-idx='3'] { background: #1d9f6e; }
  .split-seg[data-idx='4'] { background: #ad6a00; }
  .split-seg[data-idx='5'] { background: rgba(10, 61, 89, 0.4); }

  .split-legend { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.55rem; }
  .split-legend li {
    display: grid; grid-template-columns: 0.7rem 1fr auto auto;
    align-items: center; gap: 0.6rem; font-size: 0.88rem;
  }
  .split-dot { width: 0.65rem; height: 0.65rem; border-radius: 2px; }
  .split-dot[data-idx='0'] { background: #0a3d59; }
  .split-dot[data-idx='1'] { background: #0f5f88; }
  .split-dot[data-idx='2'] { background: #0d7f58; }
  .split-dot[data-idx='3'] { background: #1d9f6e; }
  .split-dot[data-idx='4'] { background: #ad6a00; }
  .split-dot[data-idx='5'] { background: rgba(10, 61, 89, 0.4); }
  .split-label { color: var(--brand-strong); font-weight: 600; }
  .split-pct { color: rgba(10, 61, 89, 0.5); font-size: 0.78rem; font-variant-numeric: tabular-nums; }
  .split-amt {
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    color: var(--brand-strong); font-variant-numeric: tabular-nums;
  }

  /* WEEKDAY */
  .weekday-grid {
    display: grid; grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 0.4rem; align-items: end; height: 9.5rem;
  }
  .weekday-col {
    display: grid; grid-template-rows: 1rem 1fr 1.1rem 1rem;
    gap: 0.2rem; justify-items: center; align-items: end; height: 100%;
  }
  .weekday-amt {
    font-size: 0.62rem; color: rgba(10, 61, 89, 0.4);
    font-variant-numeric: tabular-nums; align-self: end; line-height: 1;
  }
  .weekday-bar {
    width: 100%; max-width: 32px; height: var(--h, 4%);
    border-radius: 5px 5px 0 0;
    background: linear-gradient(180deg, rgba(15, 95, 136, 0.35), rgba(10, 61, 89, 0.55));
    align-self: end;
  }
  .weekday-day {
    font-size: 0.7rem; color: rgba(10, 61, 89, 0.6); font-weight: 600;
    letter-spacing: 0.04em; text-transform: uppercase;
  }
  .weekday-count { font-size: 0.68rem; color: rgba(10, 61, 89, 0.4); font-variant-numeric: tabular-nums; }
</style>
