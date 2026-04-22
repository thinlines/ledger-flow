<script lang="ts">
  import { formatCurrency, goodChangeTone, type AccountKind } from '$lib/format';

  export let header: string;
  export let isFirst = false;
  export let dailySum: number | null = null;
  export let baseCurrency = 'USD';
  /**
   * Account kind of the currently-filtered account in single-account view.
   * Null/undefined in cross-account views — the day sum renders unsigned
   * neutral because a mixed-account sum has no meaningful "good" direction.
   */
  export let accountKind: AccountKind | null = null;

  $: dailyTone = accountKind && dailySum !== null ? goodChangeTone(dailySum, accountKind) : 'neutral';
  $: dailyFormatted = dailySum === null
    ? ''
    : accountKind
      ? formatCurrency(dailySum, baseCurrency, { signMode: 'good-change-plus', accountKind })
      : formatCurrency(Math.abs(dailySum), baseCurrency, { signMode: 'negative-only' });
</script>

<div class="date-group" class:date-group-first={isFirst}>
  <div class="date-header-row">
    <h4 class="date-header">{header}</h4>
    {#if dailySum !== null}
      <span class="daily-sum" class:positive={dailyTone === 'positive'}>
        {dailyFormatted}
      </span>
    {/if}
  </div>
  <slot />
</div>

<style>
  .date-group + :global(.date-group) {
    margin-top: 0.65rem;
    padding-top: 0.65rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .date-header-row {
    position: sticky;
    top: var(--filter-bar-height, 0px);
    z-index: 5;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.35rem 0.5rem;
    margin: 0 -0.5rem 0.25rem;
    background: rgba(255, 255, 255, 0.97);
    backdrop-filter: saturate(1.2);
  }

  .date-header {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .daily-sum {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--muted-foreground);
    white-space: nowrap;
  }

  .positive {
    color: var(--ok);
  }
</style>
