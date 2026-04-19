<script lang="ts">
  import { normalizeCurrencyCode } from '$lib/currency-format';
  import type { DirectionData, NetWorthPoint } from './direction-types';

  export let direction: DirectionData | null = null;
  export let baseCurrency: string = 'USD';
  export let loading: boolean = false;

  function fmt(value: number, opts?: { signed?: boolean; compact?: boolean }): string {
    const currency = normalizeCurrencyCode(baseCurrency);
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      notation: opts?.compact ? 'compact' : 'standard',
      minimumFractionDigits: opts?.compact ? 0 : 2,
      maximumFractionDigits: opts?.compact ? 1 : 2,
      signDisplay: opts?.signed ? 'always' : 'auto'
    }).format(value);
  }

  function shortDate(value: string): string {
    const parsed = new Date(`${value}T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
  }

  function runwayColor(months: number): string {
    if (months >= 6) return 'ok';
    if (months >= 3) return 'caution';
    return 'concern';
  }

  function runwayBarPercent(months: number): number {
    // Cap at 12 months for the bar visual
    return Math.min(100, Math.max(4, (months / 12) * 100));
  }

  // SVG sparkline helpers
  function sparklinePoints(data: NetWorthPoint[], width: number, height: number): string {
    if (data.length < 2) return '';
    const values = data.map((d) => d.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const padding = 4;
    const usableWidth = width - padding * 2;
    const usableHeight = height - padding * 2;

    return data
      .map((d, i) => {
        const x = padding + (i / (data.length - 1)) * usableWidth;
        const y = padding + usableHeight - ((d.value - min) / range) * usableHeight;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }

  function sparklineTrending(data: NetWorthPoint[]): 'up' | 'down' | 'flat' {
    if (data.length < 2) return 'flat';
    const first = data[0].value;
    const last = data[data.length - 1].value;
    if (last > first) return 'up';
    if (last < first) return 'down';
    return 'flat';
  }

  $: hasAnySignal =
    direction &&
    (direction.runway !== null ||
      direction.netWorthTrend !== null ||
      direction.recurringVsDiscretionary.total > 0);

  $: hasAnyNotable =
    direction &&
    (direction.notableSignals.largestThisWeek !== null ||
      direction.notableSignals.categorySpike !== null ||
      direction.notableSignals.spendingStreak !== null);

  $: hasAnyLooseEnd =
    direction &&
    (direction.looseEnds.reviewQueueCount > 0 ||
      direction.looseEnds.statementInboxCount > 0 ||
      direction.looseEnds.staleAccounts.length > 0 ||
      direction.looseEnds.missingOpeningBalances.length > 0);

  $: recurringPercent = (() => {
    if (!direction || direction.recurringVsDiscretionary.total <= 0) return 0;
    return (direction.recurringVsDiscretionary.recurring / direction.recurringVsDiscretionary.total) * 100;
  })();

  $: discretionaryPercent = (() => {
    if (!direction || direction.recurringVsDiscretionary.total <= 0) return 0;
    return (direction.recurringVsDiscretionary.discretionary / direction.recurringVsDiscretionary.total) * 100;
  })();
</script>

{#if loading}
  <section class="view-card p-5">
    <p class="eyebrow">Financial direction</p>
    <h3 class="m-0 font-display text-xl">Where should I go next?</h3>
    <div class="mt-4 grid grid-cols-3 gap-4 max-tablet:grid-cols-1">
      <div class="h-28 animate-pulse rounded-xl bg-card-edge"></div>
      <div class="h-28 animate-pulse rounded-xl bg-card-edge"></div>
      <div class="h-28 animate-pulse rounded-xl bg-card-edge"></div>
    </div>
  </section>
{:else if direction}
  <section class="view-card p-5">
    <div class="mb-4">
      <p class="eyebrow">Financial direction</p>
      <h3 class="m-0 font-display text-xl">Where should I go next?</h3>
    </div>

    {#if !hasAnySignal}
      <p class="m-0 text-sm text-muted-foreground">
        Keep importing activity — signals appear once there's enough history.
      </p>
    {:else}
      {#if hasAnyNotable}
        <div class="mb-5 grid gap-2">
          {#if direction.notableSignals.largestThisWeek}
            {@const sig = direction.notableSignals.largestThisWeek}
            <p class="signal-bullet m-0 text-sm text-muted-foreground">
              Largest this week:
              <span class="font-bold text-foreground">{sig.payee}</span>
              for <span class="font-bold text-brand-strong">{fmt(Math.abs(sig.amount))}</span>
              on {shortDate(sig.date)} ({sig.accountLabel})
            </p>
          {/if}
          {#if direction.notableSignals.categorySpike}
            {@const spike = direction.notableSignals.categorySpike}
            <p class="signal-bullet m-0 text-sm text-muted-foreground">
              <span class="font-bold text-foreground">{spike.category}</span> is at
              <span class="font-bold text-warn">{fmt(spike.current)}</span> this month —
              <span class="font-bold">{spike.ratio}x</span> the usual
              {fmt(spike.average)}/mo
            </p>
          {/if}
          {#if direction.notableSignals.spendingStreak}
            {@const streak = direction.notableSignals.spendingStreak}
            <p class="signal-bullet m-0 text-sm text-muted-foreground">
              Spending has exceeded income for
              <span class="font-bold text-bad">{streak.months} consecutive months</span>
            </p>
          {/if}
        </div>
      {/if}

      <div class="grid grid-cols-3 gap-4 max-tablet:grid-cols-1">
        <!-- Runway gauge -->
        <div class="rounded-xl border border-card-edge bg-white/60 p-4">
          {#if direction.runway}
            {@const rc = runwayColor(direction.runway.months)}
            <p class="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Runway</p>
            <p class="m-0 font-display text-2xl font-bold {rc === 'ok' ? 'text-ok' : rc === 'caution' ? 'text-warn' : 'text-bad'}">
              {direction.runway.months} months
            </p>
            <div class="mt-2 h-2.5 overflow-hidden rounded-full bg-card-edge">
              <div
                class="runway-bar runway-{rc} h-full rounded-full transition-all"
                style="width: {runwayBarPercent(direction.runway.months)}%"
              ></div>
            </div>
            <p class="m-0 mt-1.5 text-xs text-muted-foreground">
              {#if direction.runway.monthlyObligations > 0}
                {fmt(direction.runway.spendableCash, { compact: true })} at {fmt(direction.runway.avgMonthlySpending, { compact: true })} expenses + {fmt(direction.runway.monthlyObligations, { compact: true })} obligations/mo
              {:else}
                {fmt(direction.runway.spendableCash, { compact: true })} at {fmt(direction.runway.avgMonthlySpending, { compact: true })}/mo
              {/if}
            </p>
          {:else}
            <p class="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Runway</p>
            <p class="m-0 text-sm text-muted-foreground">Not enough data</p>
          {/if}
        </div>

        <!-- Net worth sparkline -->
        <div class="rounded-xl border border-card-edge bg-white/60 p-4">
          {#if direction.netWorthTrend && direction.netWorthTrend.length >= 2}
            {@const trend = sparklineTrending(direction.netWorthTrend)}
            {@const lastValue = direction.netWorthTrend[direction.netWorthTrend.length - 1].value}
            {@const values = direction.netWorthTrend.map((d) => d.value)}
            {@const minVal = Math.min(...values)}
            {@const maxVal = Math.max(...values)}
            <p class="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Net worth trend</p>
            <p class="m-0 font-display text-2xl font-bold {trend === 'up' ? 'text-ok' : trend === 'down' ? 'text-bad' : ''}">
              {fmt(lastValue, { compact: true })}
            </p>
            <div class="mt-2 flex items-stretch gap-1">
              <div class="flex flex-col justify-between text-[10px] text-muted-foreground leading-none">
                <span>{fmt(maxVal, { compact: true })}</span>
                <span>{fmt(minVal, { compact: true })}</span>
              </div>
              <svg viewBox="0 0 200 48" class="block h-12 flex-1" preserveAspectRatio="none">
                <polyline
                  points={sparklinePoints(direction.netWorthTrend, 200, 48)}
                  fill="none"
                  stroke={trend === 'up' ? 'var(--ok)' : trend === 'down' ? 'var(--bad)' : 'var(--brand)'}
                  stroke-width="2.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </div>
            <p class="m-0 mt-1 text-xs text-muted-foreground">
              {direction.netWorthTrend.length}-month trend
            </p>
          {:else}
            <p class="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Net worth trend</p>
            <p class="m-0 text-sm text-muted-foreground">Not enough data</p>
          {/if}
        </div>

        <!-- Recurring vs discretionary -->
        <div class="rounded-xl border border-card-edge bg-white/60 p-4">
          {#if direction.recurringVsDiscretionary.total > 0}
            <p class="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Spending split</p>
            <p class="m-0 font-display text-2xl font-bold">
              {fmt(direction.recurringVsDiscretionary.total, { compact: true })}
            </p>
            <div class="mt-2 flex h-2.5 gap-0.5 overflow-hidden rounded-full">
              <div
                class="recurring-bar h-full rounded-l-full"
                style="width: {recurringPercent}%"
              ></div>
              <div
                class="discretionary-bar h-full rounded-r-full"
                style="width: {discretionaryPercent}%"
              ></div>
            </div>
            <div class="mt-1.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>
                <span class="mr-1 inline-block h-2 w-2 rounded-full bg-brand"></span>
                Recurring {fmt(direction.recurringVsDiscretionary.recurring, { compact: true })}
              </span>
              <span>
                <span class="mr-1 inline-block h-2 w-2 rounded-full bg-ok"></span>
                Flex {fmt(direction.recurringVsDiscretionary.discretionary, { compact: true })}
              </span>
            </div>
          {:else}
            <p class="m-0 mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Spending split</p>
            <p class="m-0 text-sm text-muted-foreground">Not enough data</p>
          {/if}
        </div>
      </div>

      {#if hasAnyLooseEnd}
        <div class="mt-5 border-t border-card-edge pt-4">
          <p class="m-0 mb-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">Loose ends</p>
          <ul class="m-0 grid gap-1.5 p-0 list-none">
            {#if direction.looseEnds.reviewQueueCount > 0}
              <li class="m-0 text-sm text-muted-foreground">
                <a class="text-link" href="/unknowns">
                  {direction.looseEnds.reviewQueueCount === 1
                    ? '1 transaction'
                    : `${direction.looseEnds.reviewQueueCount} transactions`} to review
                </a>
              </li>
            {/if}
            {#if direction.looseEnds.statementInboxCount > 0}
              <li class="m-0 text-sm text-muted-foreground">
                <a class="text-link" href="/import">
                  {direction.looseEnds.statementInboxCount === 1
                    ? '1 statement'
                    : `${direction.looseEnds.statementInboxCount} statements`} waiting to import
                </a>
              </li>
            {/if}
            {#each direction.looseEnds.staleAccounts as stale}
              <li class="m-0 text-sm text-muted-foreground">
                <a class="text-link" href="/transactions?accounts={stale.id}">
                  {stale.displayName}
                </a>
                — no activity for {stale.daysSinceActivity} days
              </li>
            {/each}
            {#each direction.looseEnds.missingOpeningBalances as missing}
              <li class="m-0 text-sm text-muted-foreground">
                <a class="text-link" href="/accounts/configure">
                  {missing.displayName}
                </a>
                — needs an opening balance
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    {/if}
  </section>
{/if}

<style>
  .runway-ok {
    background: linear-gradient(90deg, #1d9f6e, #6fd6ae);
  }

  .runway-caution {
    background: linear-gradient(90deg, #ad6a00, #f5c563);
  }

  .runway-concern {
    background: linear-gradient(90deg, #b73a3a, #e87c7c);
  }

  .recurring-bar {
    background: linear-gradient(90deg, #0f5f88, #47a5d8);
  }

  .discretionary-bar {
    background: linear-gradient(90deg, #1d9f6e, #6fd6ae);
  }

  .signal-bullet::before {
    content: '';
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--brand);
    margin-right: 8px;
    vertical-align: middle;
  }
</style>
