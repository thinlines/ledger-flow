<script lang="ts">
  import type { ActivitySummary, ActivityTransaction } from '$lib/transactions/types';
  import { formatCurrency } from '$lib/format';

  export let summary: ActivitySummary | null;
  export let category: string | null;
  export let month: string | null;
  export let transactions: ActivityTransaction[];
  export let baseCurrency: string;

  // Helpers below are duplicated from +page.svelte; Phase 2 of the
  // transactions rethink will consolidate them once the row template also
  // lives in a component.
  function activityShortDate(value: string): string {
    const parsed = new Date(`${value}T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
  }

  function truncatePayee(payee: string, max = 50): string {
    if (payee.length <= max) return payee;
    return payee.slice(0, max - 1) + '…';
  }

  function categoryLeadingSegment(cat: string | null): string {
    if (!cat) return '';
    return cat.split(':')[0] ?? '';
  }

  function nounForCategory(cat: string | null, count: number): string {
    const plural = count !== 1;
    const leading = categoryLeadingSegment(cat);
    if (leading === 'Expenses') return plural ? 'purchases' : 'purchase';
    if (leading === 'Income') return plural ? 'deposits' : 'deposit';
    return plural ? 'transactions' : 'transaction';
  }

  function mixedSigns(txs: ActivityTransaction[]): boolean {
    let hasPositive = false;
    let hasNegative = false;
    for (const tx of txs) {
      if (tx.amount > 0) hasPositive = true;
      else if (tx.amount < 0) hasNegative = true;
      if (hasPositive && hasNegative) return true;
    }
    return false;
  }

  function isCurrentPeriodSingleMonth(m: string | null): boolean {
    return m !== null;
  }

  function priorComparisonLabel(m: string | null): string {
    return isCurrentPeriodSingleMonth(m) ? 'Last month' : 'Prior period';
  }

  type DeltaPresentation = {
    arrow: string;
    className: string;
    displayPercent: number;
  };

  function presentDelta(
    periodTotal: number,
    priorTotal: number | null,
    cat: string | null
  ): DeltaPresentation | null {
    if (priorTotal === null) return null;

    const leading = categoryLeadingSegment(cat);

    // Mixed/all-activity views sum income and outflows together. A percentage
    // change on that net total is mathematically defined but hard to read —
    // the sign can flip with small swings and the base can be near zero. Skip
    // the delta entirely; the prior total itself is the comparison line.
    if (leading !== 'Expenses' && leading !== 'Income') return null;

    // For expenses, the user thinks in absolute-spending terms. Normalize to
    // positive "how much was spent" values before computing the percent change
    // so that `periodTotal` going from -$2,917 to -$2,817 reads as spending
    // dropping 3% (↓3% green), not the signed delta flipping 3% in the other
    // direction (↑3% red).
    const useAbs = leading === 'Expenses';
    const current = useAbs ? Math.abs(periodTotal) : periodTotal;
    const prior = useAbs ? Math.abs(priorTotal) : priorTotal;

    if (prior === 0) return null; // can't compute percent change from zero

    const signedPercent = ((current - prior) / Math.abs(prior)) * 100;
    if (signedPercent === 0) return null;

    const increasing = signedPercent > 0;
    const favorable = leading === 'Expenses' ? !increasing : increasing;

    return {
      arrow: increasing ? '↑' : '↓',
      className: favorable ? 'positive' : 'negative',
      displayPercent: Math.abs(signedPercent)
    };
  }

  $: periodIsMixed = mixedSigns(transactions);
  $: deltaPresentation = summary
    ? presentDelta(summary.periodTotal, summary.priorPeriodTotal, category)
    : null;
  $: priorLabel = priorComparisonLabel(month);
  $: periodNoun = nounForCategory(category, summary?.periodCount ?? 0);
</script>

{#if summary}
  <section class="view-card explanation-header-card">
    <p class="explanation-period">
      {formatCurrency(summary.periodTotal, baseCurrency)} across {summary.periodCount} {periodNoun}{#if !periodIsMixed && summary.periodCount > 0} · avg {formatCurrency(summary.averageAmount, baseCurrency)} each{/if}
    </p>

    {#if summary.priorPeriodTotal !== null && summary.priorPeriodCount !== null}
      <p class="explanation-prior">
        {priorLabel}: {formatCurrency(summary.priorPeriodTotal, baseCurrency)} across {summary.priorPeriodCount} {nounForCategory(category, summary.priorPeriodCount)}{#if deltaPresentation} — <span class={deltaPresentation.className}>{deltaPresentation.arrow}{deltaPresentation.displayPercent.toFixed(0)}%</span>{/if}
      </p>
    {/if}

    {#if summary.rollingMonthlyAverage !== null}
      <p class="explanation-baseline">
        6-month average: {formatCurrency(summary.rollingMonthlyAverage, baseCurrency)}/mo
      </p>
    {/if}

    {#if summary.topTransaction && summary.periodCount > 1}
      <p class="explanation-top">
        Biggest: {formatCurrency(Math.abs(summary.topTransaction.amount), baseCurrency)} at {truncatePayee(summary.topTransaction.payee, 30)} on {activityShortDate(summary.topTransaction.date)}
      </p>
    {/if}
  </section>
{/if}

<style>
  .explanation-header-card {
    display: grid;
    gap: 0.4rem;
    padding: 1rem 1.15rem;
  }

  .explanation-period {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0;
  }

  .explanation-prior {
    font-size: 0.95rem;
    margin: 0;
  }

  .explanation-baseline,
  .explanation-top {
    color: var(--muted-foreground);
    font-size: 0.88rem;
    margin: 0;
  }

  .positive {
    color: var(--ok);
  }

  .negative {
    color: var(--bad);
  }
</style>
