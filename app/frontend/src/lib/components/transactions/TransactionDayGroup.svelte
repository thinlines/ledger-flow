<script lang="ts">
  import { formatCurrency } from '$lib/format';

  export let header: string;
  export let isFirst = false;
  export let dailySum: number | null = null;
  export let baseCurrency = 'USD';
</script>

<div class="date-group" class:date-group-first={isFirst}>
  <div class="date-header-row">
    <h4 class="date-header">{header}</h4>
    {#if dailySum !== null}
      <span class="daily-sum" class:positive={dailySum > 0} class:negative={dailySum < 0}>
        {formatCurrency(dailySum, baseCurrency, { signed: true })}
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
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.25rem;
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

  .negative {
    color: var(--bad);
  }
</style>
