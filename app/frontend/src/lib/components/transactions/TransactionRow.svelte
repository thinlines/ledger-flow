<script lang="ts">
  import type { TransactionRow } from '$lib/transactions/types';
  import { formatCurrency } from '$lib/format';
  import { truncatePayee, activityShortDate, CLEARING_TOOLTIPS } from '$lib/transactions/helpers';
  import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';

  export let row: TransactionRow;
  export let baseCurrency: string;
  export let showRunningBalance = false;
  export let showCategory = true;
  export let showAccountLabel = true;
  export let isSingleAccount = false;
  export let onToggleClearing: ((row: TransactionRow, event: MouseEvent) => void) | null = null;
  export let onRowClick: (() => void) | null = null;

  $: clearingStatus = row.status ?? 'unmarked';
  $: clearingInteractive = isSingleAccount && onToggleClearing !== null;
  $: categoryLabel = row.categories.length > 0
    ? row.categories.map((c) => c.label).join(' \u00B7 ')
    : row.isTransfer ? 'Transfer' : '';
  $: secondaryLine = showAccountLabel && !isSingleAccount
    ? `${activityShortDate(row.date)} \u00B7 ${row.account.label}`
    : activityShortDate(row.date);
</script>

<div class="tx-row" class:opening-row={row.isOpeningBalance}>
  <div class="tx-row-inner">
    {#if clearingInteractive}
      <button
        class="clearing-indicator clearing-{clearingStatus}"
        title={CLEARING_TOOLTIPS[clearingStatus]}
        on:click|stopPropagation={(e) => onToggleClearing?.(row, e)}
        type="button"
      ></button>
    {:else}
      <span
        class="clearing-indicator clearing-{clearingStatus}"
        title={CLEARING_TOOLTIPS[clearingStatus]}
      ></span>
    {/if}

    <div class="tx-main min-w-0">
      <div class="flex items-center gap-2 min-w-0 flex-wrap">
        {#if showCategory && categoryLabel}
          <span class="tx-category-pill">{categoryLabel}</span>
        {/if}
        <span class="font-bold truncate min-w-0" title={row.payee}>{truncatePayee(row.payee)}</span>
      </div>
      <p class="text-muted-foreground text-sm mt-0.5">
        {secondaryLine}
        {#if row.isUnknown}
          <a class="pill warn no-underline ml-1" href="/unknowns" on:click|stopPropagation>Needs review</a>
        {/if}
        {#if row.isOpeningBalance}
          <span class="pill ml-1">Starting balance</span>
        {/if}
        {#if row.transferState === 'settled_grouped'}
          <span class="pill ml-1">Grouped transfer</span>
        {/if}
      </p>
    </div>

    <div class="tx-amount shrink-0 text-right">
      <p class:positive={row.amount > 0} class:negative={row.amount < 0} class="font-bold whitespace-nowrap">
        {formatCurrency(row.amount, baseCurrency, { signed: true })}
      </p>
    </div>

    {#if showRunningBalance && row.runningBalance !== null}
      <div class="tx-balance shrink-0 text-right">
        <p class:positive={row.runningBalance > 0} class:negative={row.runningBalance < 0} class="font-bold whitespace-nowrap">
          {formatCurrency(row.runningBalance, baseCurrency)}
        </p>
      </div>
    {/if}

    <button class="row-chevron" type="button" on:click|stopPropagation={() => onRowClick?.()} aria-label="View details">
      <ChevronRightIcon class="size-4" />
    </button>
  </div>
</div>

<style>
  .tx-row {
    border-bottom: 1px solid rgba(10, 61, 89, 0.05);
    background: transparent;
  }

  .tx-row:last-child {
    border-bottom: none;
  }

  .opening-row {
    background: rgba(247, 249, 245, 0.78);
  }

  .tx-row-inner {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.65rem 0.5rem;
  }

  .tx-main {
    flex: 1;
    min-width: 0;
  }

  .tx-amount {
    min-width: 5.5rem;
  }

  .tx-balance {
    min-width: 6rem;
  }

  .tx-category-pill {
    flex-shrink: 0;
    font-size: 0.76rem;
    font-weight: 600;
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    background: rgba(15, 95, 136, 0.08);
    color: var(--brand-strong);
    white-space: nowrap;
  }

  .positive {
    color: var(--ok);
  }

  .negative {
    color: var(--bad);
  }

  .clearing-indicator {
    width: 0.7rem;
    height: 0.7rem;
    padding: 0;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    align-self: center;
    flex-shrink: 0;
    transition: background 0.15s, box-shadow 0.15s;
  }

  span.clearing-indicator {
    cursor: default;
  }

  .clearing-cleared {
    background: var(--ok, #0d7f58);
    box-shadow: none;
  }

  .clearing-pending {
    background: transparent;
    box-shadow: inset 0 0 0 2px var(--warn, #ad6a00);
  }

  .clearing-unmarked {
    background: rgba(10, 61, 89, 0.12);
    box-shadow: none;
  }

  .row-chevron {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    padding: 0;
    border: none;
    border-radius: 0.4rem;
    background: transparent;
    color: var(--muted-foreground);
    cursor: pointer;
    transition: color 0.12s, background 0.12s;
    flex-shrink: 0;
  }

  .row-chevron:hover {
    color: var(--foreground);
    background: rgba(10, 61, 89, 0.06);
  }

  @media (max-width: 720px) {
    .tx-row-inner {
      flex-wrap: wrap;
    }

    .tx-balance {
      display: none;
    }
  }
</style>
