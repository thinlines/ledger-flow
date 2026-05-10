<script lang="ts">
  import { goto } from '$app/navigation';
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

  function clearMonth() {
    const params = new URLSearchParams(window.location.search);
    params.delete('month');
    params.delete('period');
    void goto(`/transactions?${params.toString()}`);
  }
  function focusMonth(m: string) {
    const params = new URLSearchParams(window.location.search);
    params.set('month', m);
    params.delete('period');
    void goto(`/transactions?${params.toString()}`);
  }

  $: subject = pickSubject(filters);
  $: contextChips = pickContextChips(filters);
  $: dir = directionFor(filters);

  // In net mode (no category filter) the dossier reports P&L, so exclude
  // anything that isn't real income/expense activity: transfers between
  // tracked accounts (movement, not flow), opening-balance equity postings
  // (one-time setup events that would dwarf real spending in their month),
  // and balance assertions (no money actually moves). Category-driven
  // views never see these because they don't carry Expenses/Income
  // categories in the first place.
  function netRowsOf(rows: TransactionRow[]): TransactionRow[] {
    if (dir !== 'net') return rows;
    return rows.filter((r) => !r.isTransfer && !r.isOpeningBalance && !r.isAssertion);
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
  $: deltaVsPrior = priorMonthValue !== null && priorMonthValue !== 0
    ? ((currentTotal - priorMonthValue) / Math.abs(priorMonthValue)) * 100
    : null;

  $: rollingMonths = filters.month
    ? trendMonths.filter((m) => m !== filters.month).slice(-6)
    : trendMonths.slice(-7, -1);
  $: rollingAvg = rollingMonths.length
    ? rollingMonths.reduce((s, m) => {
        const i = trendMonths.indexOf(m);
        return s + (i >= 0 ? Math.abs(trendHighlightValues[i]) : 0);
      }, 0) / rollingMonths.length
    : 0;

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
    const verb = dir === 'expense' ? 'spent' : dir === 'income' ? 'received' : (currentTotal >= 0 ? 'netted' : 'spent net');
    const amount = fmt(currentTotalAbs);
    let s = `You ${verb} ${amount} across ${currentCount} ${currentCount === 1 ? 'transaction' : 'transactions'}${excludedTransfers > 0 ? ` (${excludedTransfers} ${excludedTransfers === 1 ? 'transfer' : 'transfers'} excluded)` : ''}.`;
    if (deltaVsPrior !== null) {
      const dirWord = deltaVsPrior > 0 ? 'up' : 'down';
      const goodNess = dir === 'expense' ? deltaVsPrior < 0 : deltaVsPrior > 0;
      const tone = goodNess ? ' ✓' : '';
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
    if (dir === 'expense') return deltaVsPrior < 0 ? 'good' : 'bad';
    if (dir === 'income') return deltaVsPrior > 0 ? 'good' : 'bad';
    return deltaVsPrior > 0 ? 'good' : 'bad';
  })();

  $: vsAvgPct = monthScopedView && rollingAvg > 0 ? ((currentTotalAbs - rollingAvg) / rollingAvg) * 100 : null;
  $: vsAvgTone = (() => {
    if (vsAvgPct === null) return 'neutral';
    if (Math.abs(vsAvgPct) < 5) return 'neutral';
    if (dir === 'expense') return vsAvgPct < 0 ? 'good' : 'bad';
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
        <p class="dossier-fig-amount" class:fig-neg={dir === 'net' && currentTotal < 0}>
          {dir === 'net' ? fmtSigned(currentTotal) : fmt(currentTotal)}
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
          ? fmtSigned(trendHighlightValues.reduce((s, v) => s + v, 0))
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

    {#if trendMax === 0}
      <p class="dossier-empty">No matching activity in the last year.</p>
    {:else}
      <div class="trend-stage">
        {#if rollingAvg > 0}
          <div
            class="trend-baseline"
            style="bottom: calc(1.1rem + (100% - 2.15rem) * {rollingAvg / trendMax})"
            aria-hidden="true"
          >
            <span>6-mo avg · {fmt(rollingAvg)}</span>
          </div>
        {/if}
        <div class="trend-grid">
          {#each trendMonths as m, i}
            {@const v = trendDisplay[i]}
            {@const vh = trendHighlightDisplay[i]}
            {@const h = trendMax > 0 ? Math.max(2, (v / trendMax) * 100) : 2}
            {@const hh = trendMax > 0 && hasHighlight && vh > 0 ? Math.max(2, (vh / trendMax) * 100) : 0}
            {@const isFocus = i === trendFocusIndex}
            {@const isCurrent = i === trendMonths.length - 1}
            {@const labelV = hasHighlight ? vh : v}
            {@const showLabel = (isFocus || (focusedTrendIndex < 0 && isCurrent) || labelV >= trendMax * 0.85) && labelV > 0}
            {@const signedV = trendValues[i]}
            {@const isNeg = dir === 'net' && signedV < 0}
            <button
              type="button"
              class="trend-col"
              class:is-focus={isFocus}
              class:is-current={isCurrent}
              class:is-dimmed={hasHighlight}
              class:is-positive={dir === 'net' && signedV > 0}
              class:is-negative={isNeg}
              on:click={() => focusMonth(m)}
              title={hasHighlight
                ? `${monthTitle(m)} · ${fmt(vh)} matches “${filters.search}” of ${fmt(v)} total`
                : `${monthTitle(m)} · ${dir === 'net' ? fmtSigned(signedV) : fmt(v)}`}
              aria-label={`${monthTitle(m)} ${fmt(labelV)}`}
            >
              <span class="trend-amt">{showLabel ? fmt(labelV).replace(/\.\d+/, '') : ''}</span>
              <span class="trend-bar" style="--h: {h}%">
                {#if hasHighlight}
                  <span class="trend-bar-fill" style="--hh: {h > 0 ? (hh / h) * 100 : 0}%"></span>
                {/if}
              </span>
              <span class="trend-mo">{monthLabel(m)}</span>
            </button>
          {/each}
        </div>
      </div>
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
  .trend-stage { position: relative; height: 11.5rem; margin-top: 0.5rem; }
  .trend-grid {
    position: absolute; inset: 0;
    display: grid;
    grid-template-columns: repeat(12, minmax(0, 1fr));
    gap: 0.45rem;
    align-items: end;
    padding: 0 0.25rem;
    z-index: 1;
  }
  .trend-col {
    background: none; border: none; padding: 0; cursor: pointer;
    display: grid; grid-template-rows: 1.05rem 1fr 1.1rem;
    align-items: end; justify-items: center;
    height: 100%; gap: 0.25rem;
  }
  .trend-amt {
    font-size: 0.62rem; color: rgba(10, 61, 89, 0.4);
    font-variant-numeric: tabular-nums; line-height: 1; align-self: end;
    transition: color 0.18s, transform 0.18s;
  }
  .trend-bar {
    width: 100%; max-width: 38px;
    height: var(--h, 6%);
    border-radius: 6px 6px 0 0;
    background: linear-gradient(180deg, rgba(15, 95, 136, 0.28), rgba(10, 61, 89, 0.45));
    transition: background 0.18s, transform 0.18s, box-shadow 0.18s;
    align-self: end;
    position: relative;
    overflow: hidden;
  }
  /* Inner highlight bar for cross-filter overlay (search narrows totals).
     Sits at the bottom of the outer bar; --hh is its height as % of outer. */
  .trend-bar-fill {
    position: absolute;
    left: 0; right: 0; bottom: 0;
    height: var(--hh, 0%);
    background: linear-gradient(180deg, #0f5f88, #0a3d59);
    border-radius: 6px 6px 0 0;
    transition: height 0.18s;
  }
  /* When a highlight overlay is present, dim the outer bar so the matched
     portion stands out visually without losing the surrounding context. */
  .trend-col.is-dimmed .trend-bar {
    background: linear-gradient(180deg, rgba(15, 95, 136, 0.12), rgba(10, 61, 89, 0.18));
  }
  /* In net mode, only call out *surplus* months in green — they're the
     unusual signal. Deficit months keep the default teal so a credit card
     register doesn't look like a sea of red, since net-negative is the
     normal case there. */
  .trend-col.is-positive:not(.is-focus):not(.is-dimmed) .trend-bar {
    background: linear-gradient(180deg, rgba(13, 127, 88, 0.45), rgba(13, 127, 88, 0.7));
  }
  .trend-mo {
    font-size: 0.7rem; color: rgba(10, 61, 89, 0.55);
    letter-spacing: 0.04em; text-transform: uppercase; font-weight: 600;
  }
  .trend-col.is-focus .trend-bar {
    background: linear-gradient(180deg, #0f5f88, #0a3d59);
    box-shadow: 0 4px 14px rgba(10, 61, 89, 0.3);
  }
  .trend-col.is-focus .trend-amt { color: var(--brand-strong); font-weight: 700; transform: translateY(-2px); }
  .trend-col.is-focus .trend-mo { color: var(--brand-strong); }
  .trend-col.is-current:not(.is-focus) .trend-bar {
    background: linear-gradient(180deg, rgba(173, 106, 0, 0.55), rgba(173, 106, 0, 0.85));
  }
  .trend-col:hover:not(.is-focus) .trend-bar {
    background: linear-gradient(180deg, rgba(15, 95, 136, 0.55), rgba(10, 61, 89, 0.7));
  }
  .trend-baseline {
    position: absolute; left: 0.25rem; right: 0.25rem;
    border-top: 1px dashed rgba(10, 61, 89, 0.4);
    pointer-events: none; z-index: 2;
  }
  .trend-baseline span {
    position: absolute; top: -0.7rem; right: 0;
    background: rgba(255, 255, 255, 0.95);
    padding: 0 0.45rem; font-size: 0.7rem;
    color: rgba(10, 61, 89, 0.65); font-weight: 600;
    border-radius: 4px;
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
