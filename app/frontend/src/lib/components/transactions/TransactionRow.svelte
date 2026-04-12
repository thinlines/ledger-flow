<script lang="ts">
  import type { RegisterEntry, ActivityTransaction } from '$lib/transactions/types';
  import { formatCurrency, shortDate } from '$lib/format';
  import { truncatePayee, activityShortDate, CLEARING_TOOLTIPS } from '$lib/transactions/helpers';

  export let mode: 'activity' | 'register';

  // Activity mode props
  export let transaction: ActivityTransaction | null = null;
  export let showCategory = true;

  // Register mode props
  export let entry: RegisterEntry | null = null;
  export let onToggleClearing: (entry: RegisterEntry, event: MouseEvent) => void = () => {};

  // Shared
  export let baseCurrency: string;
  export let onRowClick: (() => void) | null = null;
</script>

{#if mode === 'activity' && transaction}
  <button class="activity-row" type="button" on:click={() => onRowClick?.()}>
    <div class="grid gap-0.5 min-w-0">
      <div class="flex items-center gap-2 min-w-0 max-tablet:flex-wrap">
        <span
          class="clearing-indicator clearing-unmarked"
          title="Unmarked"
        ></span>
        {#if showCategory}
          <span class="activity-category-pill">{transaction.category}</span>
        {/if}
        <span class="font-bold truncate min-w-0" title={transaction.payee}>{truncatePayee(transaction.payee)}</span>
      </div>
      <p class="text-muted-foreground text-sm ml-5">
        {activityShortDate(transaction.date)} · {transaction.accountLabel}
      </p>
    </div>
    <div class="grid gap-0.5 justify-items-end shrink-0 max-tablet:justify-items-start">
      <p class:positive={transaction.amount > 0} class:negative={transaction.amount < 0} class="font-bold whitespace-nowrap">
        {formatCurrency(transaction.amount, baseCurrency, { signed: true })}
      </p>
      {#if transaction.isUnknown}
        <a class="pill warn no-underline" href="/unknowns" on:click|stopPropagation>Needs review</a>
      {/if}
    </div>
  </button>
{:else if mode === 'register' && entry}
  <div class:opening-row={entry.isOpeningBalance} class="register-row" role="button" tabindex="0" on:click={() => onRowClick?.()} on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRowClick?.(); } }}>
    <div class="register-summary">
      <button
        class="clearing-indicator clearing-{entry.clearingStatus ?? 'unmarked'}"
        title={CLEARING_TOOLTIPS[entry.clearingStatus ?? 'unmarked']}
        on:click|stopPropagation={(e) => onToggleClearing(entry, e)}
        type="button"
      ></button>
      <div class="register-cell register-date">{shortDate(entry.date)}</div>

      <div class="register-cell min-w-0">
        <p class="font-bold">{entry.payee}</p>
        <div class="flex flex-wrap gap-2 mt-1 text-muted-foreground text-sm">
          <span>{entry.summary}</span>
          {#if entry.isUnknown}
            <span class="pill warn">Needs review</span>
          {/if}
          {#if entry.isOpeningBalance}
            <span class="pill">Starting balance</span>
          {/if}
          {#if entry.transferState === 'settled_grouped'}
            <span class="pill">Grouped transfer</span>
          {/if}
        </div>
      </div>

      <div class="register-cell register-money text-right">
        <p class:positive={entry.amount > 0} class:negative={entry.amount < 0} class="font-bold">
          {formatCurrency(entry.amount, baseCurrency, { signed: true })}
        </p>
      </div>

      <div class="register-cell register-money text-right">
        <p class:positive={entry.runningBalance > 0} class:negative={entry.runningBalance < 0} class="font-bold">
          {formatCurrency(entry.runningBalance, baseCurrency)}
        </p>
      </div>

      <span></span>
    </div>
  </div>
{/if}

<style>
  /* --- Activity row --- */
  .activity-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
    padding: 0.65rem 0;
    border: none;
    border-bottom: 1px solid rgba(10, 61, 89, 0.05);
    background: transparent;
    width: 100%;
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }

  .activity-row:last-child {
    border-bottom: none;
  }

  .activity-row:hover {
    background: rgba(10, 61, 89, 0.03);
  }

  @media (max-width: 720px) {
    .activity-row {
      flex-direction: column;
      gap: 0.3rem;
    }
  }

  /* --- Activity category pill --- */
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

  /* --- Register row states --- */
  .register-row {
    border-bottom: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.35);
    cursor: pointer;
    transition: background 0.12s;
  }

  .register-row:last-child {
    border-bottom: none;
  }

  .register-row:hover {
    background: rgba(244, 249, 255, 0.72);
  }

  .opening-row {
    background: rgba(247, 249, 245, 0.78);
  }

  /* --- Register summary grid layout --- */
  .register-summary {
    display: grid;
    grid-template-columns: 1.5rem minmax(7.5rem, 0.75fr) minmax(0, 2fr) minmax(7.5rem, 0.75fr) minmax(8rem, 0.85fr) 2rem;
    gap: 1rem;
    align-items: center;
    padding: 0.95rem 1rem;
  }

  /* --- State color classes --- */
  .positive {
    color: var(--ok);
  }

  .negative {
    color: var(--bad);
  }

  /* --- Clearing status indicator --- */
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

  /* --- Responsive --- */
  @media (max-width: 820px) {
    .register-summary {
      grid-template-columns: 1.5rem 1fr 2rem;
      gap: 0.45rem;
    }

    .clearing-indicator {
      grid-row: 1;
    }

    .register-date {
      font-size: 0.88rem;
      color: var(--muted-foreground);
    }

    .register-money {
      text-align: left;
    }
  }
</style>
