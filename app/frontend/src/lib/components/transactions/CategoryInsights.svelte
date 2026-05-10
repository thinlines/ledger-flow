<script lang="ts">
  import { goto } from '$app/navigation';
  import type { TransactionRow } from '$lib/transactions/types';
  import { formatCurrency } from '$lib/format';
  import { categoryLeadingSegment, truncatePayee } from '$lib/transactions/helpers';

  // Editorial "dossier" header for category drill-throughs.
  // historyRows is unfiltered for the category (all-time, all accounts) and
  // drives the trend chart + 6-mo baseline. currentRows is the in-view set
  // (after period/account/search filters) and drives the period totals,
  // top merchants, sub-splits, and weekday pulse so the dossier always
  // describes whatever slice the user is currently looking at.
  export let category: string;
  export let month: string | null;
  export let period: string | null;
  export let historyRows: TransactionRow[];
  export let currentRows: TransactionRow[];
  export let baseCurrency: string;

  type DirectionMode = 'expense' | 'income' | 'neutral';

  function directionFor(cat: string): DirectionMode {
    const lead = categoryLeadingSegment(cat);
    if (lead === 'Expenses') return 'expense';
    if (lead === 'Income') return 'income';
    return 'neutral';
  }

  function categoryParts(cat: string): string[] {
    return cat.split(':').filter(Boolean);
  }

  function leafLabel(cat: string): string {
    const parts = categoryParts(cat);
    return parts[parts.length - 1] ?? cat;
  }

  function ancestors(cat: string): string[] {
    const parts = categoryParts(cat);
    return parts.slice(0, -1);
  }

  // Sum the *signed* amount the way the user thinks about this category.
  // For expenses (negative on accounts), we report a positive "spent" number.
  // For income, we report a positive "received" number. For neutral, we keep
  // the signed total so transfers and odd categories don't lie.
  function magnitudeFor(rows: TransactionRow[], dir: DirectionMode): number {
    if (dir === 'neutral') return rows.reduce((s, r) => s + r.amount, 0);
    return rows.reduce((s, r) => s + Math.abs(r.amount), 0);
  }

  function monthKey(dateStr: string): string {
    return dateStr.slice(0, 7);
  }

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
    if (p === '30d') return 'Last 30 days';
    if (p === '90d' || p === '3mo') return 'Last 3 months';
    if (p === '12mo' || p === '1y') return 'Last 12 months';
    if (p === 'ytd') return 'Year to date';
    return 'All time';
  }

  function priorPeriodLabel(m: string | null, p: string | null): string {
    if (m) return monthTitle(previousMonth(m));
    if (p === '30d') return 'Previous 30 days';
    if (p === '90d' || p === '3mo') return 'Previous 3 months';
    if (p === '12mo' || p === '1y') return 'Previous 12 months';
    return 'Earlier';
  }

  // Build a chronological list of the most recent N months keyed off the
  // history rows. We always anchor on "today" so empty trailing months still
  // appear as zero bars — that flat tail is informative.
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
      const v = dir === 'neutral' ? r.amount : Math.abs(r.amount);
      bucket.set(k, (bucket.get(k) ?? 0) + v);
    }
    return months.map((m) => bucket.get(m) ?? 0);
  }

  type MerchantTotal = { payee: string; amount: number; count: number };

  function topMerchants(rows: TransactionRow[], dir: DirectionMode, limit: number): MerchantTotal[] {
    const map = new Map<string, MerchantTotal>();
    for (const r of rows) {
      const v = dir === 'neutral' ? r.amount : Math.abs(r.amount);
      const cur = map.get(r.payee);
      if (cur) {
        cur.amount += v;
        cur.count += 1;
      } else {
        map.set(r.payee, { payee: r.payee, amount: v, count: 1 });
      }
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
      const v = dir === 'neutral' ? r.amount : Math.abs(r.amount);
      const cur = map.get(key);
      if (cur) {
        cur.amount += v;
        cur.count += 1;
      } else {
        map.set(key, { key, label: key, amount: v, count: 1 });
      }
    }
    return Array.from(map.values()).sort((a, b) => b.amount - a.amount);
  }

  function byWeekday(rows: TransactionRow[], dir: DirectionMode): { day: string; amount: number; count: number }[] {
    const labels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const buckets = labels.map((d) => ({ day: d, amount: 0, count: 0 }));
    for (const r of rows) {
      const d = new Date(`${r.date}T00:00:00`);
      const idx = d.getDay();
      const v = dir === 'neutral' ? r.amount : Math.abs(r.amount);
      buckets[idx].amount += v;
      buckets[idx].count += 1;
    }
    return buckets;
  }

  // Compute "what fraction of the current 12-month window this category
  // represents" so the trend has a shape to compare against, not just a
  // single number. Defensive about empty histories.
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

  $: dir = directionFor(category);
  $: leaf = leafLabel(category);
  $: parents = ancestors(category);
  $: trendMonths = lastNMonths(12);
  $: trendValues = bucketByMonth(historyRows, dir, trendMonths);
  $: trendMax = maxOrZero(trendValues);
  $: focusedTrendIndex = month ? trendMonths.indexOf(month) : -1;

  $: currentTotal = magnitudeFor(currentRows, dir);
  $: currentCount = currentRows.length;
  $: currentAvg = currentCount > 0 ? currentTotal / currentCount : 0;

  // Prior period comparison: only well-defined for monthly views right now.
  // Outside that we compare against the 6-month rolling baseline instead.
  $: priorMonth = month ? previousMonth(month) : null;
  $: priorMonthIndex = priorMonth ? trendMonths.indexOf(priorMonth) : -1;
  $: priorMonthValue = priorMonthIndex >= 0 ? trendValues[priorMonthIndex] : null;
  $: deltaVsPrior = priorMonthValue !== null && priorMonthValue !== 0
    ? ((currentTotal - priorMonthValue) / Math.abs(priorMonthValue)) * 100
    : null;

  // Rolling 6-month baseline excluding the focused month so the comparison
  // isn't tautological. If we don't have a focused month, average the last 6
  // completed months.
  $: rollingMonths = month
    ? trendMonths.filter((m) => m !== month).slice(-6)
    : trendMonths.slice(-7, -1);
  $: rollingAvg = rollingMonths.length
    ? rollingMonths.reduce((s, m) => {
        const i = trendMonths.indexOf(m);
        return s + (i >= 0 ? trendValues[i] : 0);
      }, 0) / rollingMonths.length
    : 0;

  $: merchants = topMerchants(currentRows, dir, 6);
  $: merchantMax = maxOrZero(merchants.map((m) => m.amount));

  $: subcats = subcategorySplit(currentRows, category, dir);
  $: subTotal = subcats.reduce((s, c) => s + c.amount, 0);

  $: weekday = byWeekday(currentRows, dir);
  $: weekdayMax = maxOrZero(weekday.map((d) => d.amount));

  // The trailing one-line "gist" sentence is the part that does the work of
  // turning a list of numbers into a story. Build it conditionally based on
  // whether we have enough signal to say something honest.
  // A comparison vs the 6-month per-month average only makes sense when the
  // current period is also "one month" — otherwise we'd be measuring a
  // 12-month total against a monthly baseline. Gate accordingly.
  $: monthScopedView = month !== null || period === '30d';

  $: gist = (() => {
    if (currentCount === 0) return 'No transactions in this slice yet.';
    const verb = dir === 'expense' ? 'spent' : dir === 'income' ? 'received' : 'moved';
    let s = `You ${verb} ${fmt(Math.abs(currentTotal))} across ${currentCount} ${currentCount === 1 ? 'transaction' : 'transactions'}.`;
    if (deltaVsPrior !== null) {
      const dirWord = deltaVsPrior > 0 ? 'up' : 'down';
      const goodNess = dir === 'expense' ? (deltaVsPrior < 0) : (deltaVsPrior > 0);
      const tone = goodNess ? ' ✓' : '';
      s += ` That's ${dirWord} ${Math.abs(deltaVsPrior).toFixed(0)}% from ${monthTitle(priorMonth!)}${tone}.`;
    } else if (monthScopedView && rollingAvg > 0) {
      const ratio = currentTotal / rollingAvg;
      if (ratio > 1.15) s += ` Running ${(((ratio - 1) * 100)).toFixed(0)}% above your 6-month pace.`;
      else if (ratio < 0.85) s += ` Running ${((1 - ratio) * 100).toFixed(0)}% below your 6-month pace.`;
      else s += ` Roughly in line with your 6-month pace.`;
    } else if (!monthScopedView) {
      const months = Math.max(1, trendValues.filter((v) => v > 0).length);
      const perMonth = currentTotal / months;
      s += ` Averaging ${fmt(perMonth)}/mo across ${months} active ${months === 1 ? 'month' : 'months'}.`;
    }
    return s;
  })();

  // Tone class for the delta chip — green = "good direction" for the
  // category type. We render the chip independent of the gist line so the
  // delta is also scannable at a glance.
  $: deltaTone = (() => {
    if (deltaVsPrior === null) return 'neutral';
    if (dir === 'expense') return deltaVsPrior < 0 ? 'good' : 'bad';
    if (dir === 'income') return deltaVsPrior > 0 ? 'good' : 'bad';
    return deltaVsPrior > 0 ? 'good' : 'bad';
  })();

  $: vsAvgPct = monthScopedView && rollingAvg > 0 ? ((currentTotal - rollingAvg) / rollingAvg) * 100 : null;
  $: vsAvgTone = (() => {
    if (vsAvgPct === null) return 'neutral';
    if (Math.abs(vsAvgPct) < 5) return 'neutral';
    if (dir === 'expense') return vsAvgPct < 0 ? 'good' : 'bad';
    if (dir === 'income') return vsAvgPct > 0 ? 'good' : 'bad';
    return vsAvgPct > 0 ? 'good' : 'bad';
  })();

  // Dim non-focused trend bars so the focused month "sings". When no month is
  // focused, treat the most recent month as the implied focus for visual
  // weight — most users came here to look at "now."
  $: trendFocusIndex = focusedTrendIndex >= 0 ? focusedTrendIndex : trendMonths.length - 1;
</script>

<section class="dossier">
  <!-- HERO -->
  <div class="dossier-hero" data-direction={dir}>
    <div class="dossier-hero-band" aria-hidden="true"></div>
    <div class="dossier-hero-grid">
      <div class="dossier-hero-text">
        <p class="dossier-eyebrow">
          <span>Category report</span>
          {#if parents.length}<span class="dossier-eyebrow-sep">/</span><span class="dossier-eyebrow-path">{parents.join(' / ')}</span>{/if}
        </p>
        <h1 class="dossier-title">{leaf}</h1>
        <div class="dossier-period">
          <span class="dossier-period-chip">{periodLabel(month, period)}</span>
          {#if month}
            <button class="dossier-period-clear" type="button" on:click={clearMonth} aria-label="Clear month filter">Clear month</button>
          {/if}
        </div>
        <p class="dossier-gist">{gist}</p>
      </div>

      <div class="dossier-hero-figure">
        <p class="dossier-fig-eyebrow">{dir === 'income' ? 'Received' : dir === 'expense' ? 'Spent' : 'Net'}</p>
        <p class="dossier-fig-amount" class:fig-neg={dir === 'neutral' && currentTotal < 0}>
          {dir === 'neutral' ? fmtSigned(currentTotal) : fmt(currentTotal)}
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

    <!-- KPI strip -->
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
        <p class="kpi-label">12-month total</p>
        <p class="kpi-value">{fmt(trendValues.reduce((s, v) => s + v, 0))}</p>
      </div>
    </div>
  </div>

  <!-- TREND -->
  <div class="dossier-card dossier-trend">
    <div class="dossier-card-head">
      <div>
        <p class="eyebrow">Trend</p>
        <h2 class="dossier-card-title">12-month shape</h2>
      </div>
      <p class="dossier-card-aux">Click a month to focus it</p>
    </div>

    {#if trendMax === 0}
      <p class="dossier-empty">No history for this category in the last year.</p>
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
            {@const v = trendValues[i]}
            {@const h = trendMax > 0 ? Math.max(2, (v / trendMax) * 100) : 2}
            {@const isFocus = i === trendFocusIndex}
            {@const isCurrent = i === trendMonths.length - 1}
            {@const showLabel = (isFocus || (focusedTrendIndex < 0 && isCurrent) || v >= trendMax * 0.85) && v > 0}
            <button
              type="button"
              class="trend-col"
              class:is-focus={isFocus}
              class:is-current={isCurrent}
              on:click={() => focusMonth(m)}
              title={`${monthTitle(m)} · ${fmt(v)}`}
              aria-label={`${monthTitle(m)} ${fmt(v)}`}
            >
              <span class="trend-amt">{showLabel ? fmt(v).replace(/\.\d+/, '') : ''}</span>
              <span class="trend-bar" style="--h: {h}%"></span>
              <span class="trend-mo">{monthLabel(m)}</span>
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </div>

  <!-- BREAKDOWN GRID -->
  <div class="dossier-grid">
    <!-- Top merchants -->
    <div class="dossier-card">
      <div class="dossier-card-head">
        <div>
          <p class="eyebrow">Where it went</p>
          <h2 class="dossier-card-title">Top {dir === 'income' ? 'sources' : 'merchants'}</h2>
        </div>
        <p class="dossier-card-aux">In {periodLabel(month, period).toLowerCase()}</p>
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

    <!-- Subcategory split OR weekday pulse -->
    {#if subcats.length > 0}
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
  .dossier {
    display: grid;
    gap: 1rem;
  }

  /* ─── HERO ──────────────────────────────────────────── */
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

  .dossier-hero-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
    gap: 2rem;
    align-items: end;
  }

  @media (max-width: 720px) {
    .dossier-hero-grid {
      grid-template-columns: 1fr;
      gap: 1.25rem;
    }
  }

  .dossier-eyebrow {
    margin: 0 0 0.6rem;
    display: flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: rgba(10, 61, 89, 0.62);
  }
  .dossier-eyebrow-sep {
    opacity: 0.4;
  }
  .dossier-eyebrow-path {
    color: rgba(10, 61, 89, 0.85);
    text-transform: none;
    letter-spacing: 0.04em;
    font-weight: 600;
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
  .dossier-period-clear {
    background: none;
    border: none;
    padding: 0;
    color: rgba(10, 61, 89, 0.55);
    font-size: 0.78rem;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .dossier-period-clear:hover {
    color: var(--brand);
  }

  .dossier-gist {
    margin: 0.95rem 0 0;
    color: rgba(10, 61, 89, 0.75);
    font-size: 0.98rem;
    max-width: 52ch;
    line-height: 1.45;
  }

  .dossier-hero-figure {
    text-align: right;
    padding-left: 1rem;
    border-left: 1px solid rgba(10, 61, 89, 0.08);
  }
  @media (max-width: 720px) {
    .dossier-hero-figure {
      text-align: left;
      padding-left: 0;
      border-left: 0;
      border-top: 1px solid rgba(10, 61, 89, 0.08);
      padding-top: 1rem;
    }
  }
  .dossier-fig-eyebrow {
    margin: 0;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: rgba(10, 61, 89, 0.55);
  }
  .dossier-fig-amount {
    margin: 0.2rem 0 0;
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: clamp(2.6rem, 5.5vw, 3.8rem);
    line-height: 1;
    letter-spacing: -0.025em;
    color: #0a3d59;
    font-variant-numeric: tabular-nums;
  }
  .fig-neg {
    color: var(--bad);
  }
  .dossier-fig-delta {
    margin: 0.55rem 0 0;
    font-size: 0.95rem;
    font-weight: 600;
    color: rgba(10, 61, 89, 0.7);
  }
  .dossier-fig-delta[data-tone='good'] { color: var(--ok); }
  .dossier-fig-delta[data-tone='bad'] { color: var(--bad); }
  .delta-arrow { display: inline-block; transform: translateY(-1px); margin-right: 0.15rem; }

  /* KPI strip */
  .dossier-kpis {
    margin-top: 1.5rem;
    padding-top: 1.25rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 1.25rem;
  }
  @media (max-width: 720px) {
    .dossier-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  .kpi { display: grid; gap: 0.2rem; }
  .kpi-label {
    margin: 0;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
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
    font-size: 0.78rem;
    color: rgba(10, 61, 89, 0.5);
    margin-left: 0.15rem;
    font-weight: 500;
  }

  /* ─── CARDS ─────────────────────────────────────────── */
  .dossier-card {
    background: rgba(255, 255, 255, 0.78);
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1.15rem;
    padding: 1.25rem 1.35rem;
    box-shadow: 0 8px 22px -16px rgba(10, 61, 89, 0.3);
  }
  .dossier-card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
  }
  .dossier-card-title {
    margin: 0;
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: 1.15rem;
    color: var(--brand-strong);
    letter-spacing: -0.005em;
  }
  .dossier-card-aux {
    margin: 0;
    font-size: 0.78rem;
    color: rgba(10, 61, 89, 0.5);
    text-align: right;
  }
  .dossier-empty {
    margin: 0.5rem 0;
    color: rgba(10, 61, 89, 0.5);
    font-size: 0.9rem;
  }

  /* ─── TREND ─────────────────────────────────────────── */
  .dossier-trend { position: relative; }
  .trend-stage {
    position: relative;
    height: 11.5rem;
    margin-top: 0.5rem;
  }
  .trend-grid {
    position: absolute;
    inset: 0;
    display: grid;
    grid-template-columns: repeat(12, minmax(0, 1fr));
    gap: 0.45rem;
    align-items: end;
    padding: 0 0.25rem;
    z-index: 1;
  }
  .trend-col {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    display: grid;
    grid-template-rows: 1.05rem 1fr 1.1rem;
    align-items: end;
    justify-items: center;
    height: 100%;
    gap: 0.25rem;
  }
  .trend-amt {
    font-size: 0.62rem;
    color: rgba(10, 61, 89, 0.4);
    font-variant-numeric: tabular-nums;
    line-height: 1;
    align-self: end;
    transition: color 0.18s, transform 0.18s;
  }
  .trend-bar {
    width: 100%;
    max-width: 38px;
    height: var(--h, 6%);
    border-radius: 6px 6px 0 0;
    background: linear-gradient(180deg, rgba(15, 95, 136, 0.28), rgba(10, 61, 89, 0.45));
    transition: background 0.18s, transform 0.18s, box-shadow 0.18s;
    align-self: end;
  }
  .trend-mo {
    font-size: 0.7rem;
    color: rgba(10, 61, 89, 0.55);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-weight: 600;
  }
  .trend-col.is-focus .trend-bar {
    background: linear-gradient(180deg, #0f5f88, #0a3d59);
    box-shadow: 0 4px 14px rgba(10, 61, 89, 0.3);
  }
  .trend-col.is-focus .trend-amt {
    color: var(--brand-strong);
    font-weight: 700;
    transform: translateY(-2px);
  }
  .trend-col.is-focus .trend-mo {
    color: var(--brand-strong);
  }
  .trend-col.is-current:not(.is-focus) .trend-bar {
    background: linear-gradient(180deg, rgba(173, 106, 0, 0.55), rgba(173, 106, 0, 0.85));
  }
  .trend-col:hover:not(.is-focus) .trend-bar {
    background: linear-gradient(180deg, rgba(15, 95, 136, 0.55), rgba(10, 61, 89, 0.7));
  }

  .trend-baseline {
    position: absolute;
    left: 0.25rem;
    right: 0.25rem;
    border-top: 1px dashed rgba(10, 61, 89, 0.4);
    pointer-events: none;
    z-index: 2;
  }
  .trend-baseline span {
    position: absolute;
    top: -0.7rem;
    right: 0;
    background: rgba(255, 255, 255, 0.95);
    padding: 0 0.45rem;
    font-size: 0.7rem;
    color: rgba(10, 61, 89, 0.65);
    font-weight: 600;
    border-radius: 4px;
  }

  /* ─── GRID ──────────────────────────────────────────── */
  .dossier-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
    gap: 1rem;
  }
  @media (max-width: 980px) {
    .dossier-grid { grid-template-columns: 1fr; }
  }

  /* Top merchants */
  .merchant-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.95rem;
  }
  .merchant-row {
    display: grid;
    grid-template-columns: 1.6rem 1fr;
    gap: 0.6rem;
    align-items: start;
  }
  .merchant-rank {
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: 0.85rem;
    color: rgba(10, 61, 89, 0.35);
    font-variant-numeric: tabular-nums;
    line-height: 1.4;
  }
  .merchant-body { display: grid; gap: 0.25rem; min-width: 0; }
  .merchant-line {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    align-items: baseline;
    min-width: 0;
  }
  .merchant-name {
    font-weight: 600;
    color: var(--brand-strong);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .merchant-amount {
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    color: var(--brand-strong);
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
  }
  .merchant-bar {
    height: 5px;
    background: rgba(10, 61, 89, 0.06);
    border-radius: 999px;
    overflow: hidden;
  }
  .merchant-bar span {
    display: block;
    width: var(--w, 0%);
    height: 100%;
    background: linear-gradient(90deg, #0f5f88, #0a3d59);
    border-radius: 999px;
  }
  .merchant-meta {
    margin: 0;
    font-size: 0.74rem;
    color: rgba(10, 61, 89, 0.5);
  }

  /* Subcategory split */
  .split-stack {
    display: flex;
    height: 14px;
    border-radius: 999px;
    overflow: hidden;
    background: rgba(10, 61, 89, 0.05);
    margin-bottom: 0.85rem;
  }
  .split-seg {
    display: block;
    width: var(--pct, 0%);
    transition: filter 0.15s;
  }
  .split-seg[data-idx='0'] { background: #0a3d59; }
  .split-seg[data-idx='1'] { background: #0f5f88; }
  .split-seg[data-idx='2'] { background: #0d7f58; }
  .split-seg[data-idx='3'] { background: #1d9f6e; }
  .split-seg[data-idx='4'] { background: #ad6a00; }
  .split-seg[data-idx='5'] { background: rgba(10, 61, 89, 0.4); }

  .split-legend {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.55rem;
  }
  .split-legend li {
    display: grid;
    grid-template-columns: 0.7rem 1fr auto auto;
    align-items: center;
    gap: 0.6rem;
    font-size: 0.88rem;
  }
  .split-dot {
    width: 0.65rem;
    height: 0.65rem;
    border-radius: 2px;
  }
  .split-dot[data-idx='0'] { background: #0a3d59; }
  .split-dot[data-idx='1'] { background: #0f5f88; }
  .split-dot[data-idx='2'] { background: #0d7f58; }
  .split-dot[data-idx='3'] { background: #1d9f6e; }
  .split-dot[data-idx='4'] { background: #ad6a00; }
  .split-dot[data-idx='5'] { background: rgba(10, 61, 89, 0.4); }
  .split-label { color: var(--brand-strong); font-weight: 600; }
  .split-pct { color: rgba(10, 61, 89, 0.5); font-size: 0.78rem; font-variant-numeric: tabular-nums; }
  .split-amt { font-family: var(--font-display, 'Space Grotesk', sans-serif); color: var(--brand-strong); font-variant-numeric: tabular-nums; }

  /* Weekday */
  .weekday-grid {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 0.4rem;
    align-items: end;
    height: 9.5rem;
  }
  .weekday-col {
    display: grid;
    grid-template-rows: 1rem 1fr 1.1rem 1rem;
    gap: 0.2rem;
    justify-items: center;
    align-items: end;
    height: 100%;
  }
  .weekday-amt {
    font-size: 0.62rem;
    color: rgba(10, 61, 89, 0.4);
    font-variant-numeric: tabular-nums;
    align-self: end;
    line-height: 1;
  }
  .weekday-bar {
    width: 100%;
    max-width: 32px;
    height: var(--h, 4%);
    border-radius: 5px 5px 0 0;
    background: linear-gradient(180deg, rgba(15, 95, 136, 0.35), rgba(10, 61, 89, 0.55));
    align-self: end;
  }
  .weekday-day {
    font-size: 0.7rem;
    color: rgba(10, 61, 89, 0.6);
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .weekday-count {
    font-size: 0.68rem;
    color: rgba(10, 61, 89, 0.4);
    font-variant-numeric: tabular-nums;
  }
</style>
