<script lang="ts">
  import type { RegisterEntry, ActivityTransaction } from '$lib/transactions/types';
  import { formatCurrency, shortDate } from '$lib/format';
  import {
    truncatePayee,
    activityShortDate,
    entryHasActions,
    canDelete,
    canRecategorize,
    canUnmatch,
    CLEARING_TOOLTIPS
  } from '$lib/transactions/helpers';

  export let mode: 'activity' | 'register';

  // Activity mode props
  export let transaction: ActivityTransaction | null = null;
  export let showCategory = true;

  // Register mode props
  export let entry: RegisterEntry | null = null;
  export let activeMenuEntry: RegisterEntry | null = null;
  export let onToggleClearing: (entry: RegisterEntry, event: MouseEvent) => void = () => {};
  export let onOpenActionMenu: (entry: RegisterEntry, event: MouseEvent) => void = () => {};
  export let onConfirmDelete: (entry: RegisterEntry) => void = () => {};
  export let onRecategorize: (entry: RegisterEntry) => void = () => {};
  export let onConfirmUnmatch: (entry: RegisterEntry) => void = () => {};

  // Shared
  export let baseCurrency: string;
</script>

{#if mode === 'activity' && transaction}
  <div class="activity-row">
    <div class="grid gap-0.5 min-w-0">
      <div class="flex items-center gap-2 min-w-0 max-tablet:flex-wrap">
        <button
          class="clearing-indicator clearing-unmarked"
          title="Unmarked"
          type="button"
        ></button>
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
        <a class="pill warn no-underline" href="/unknowns">Needs review</a>
      {/if}
    </div>
  </div>
{:else if mode === 'register' && entry}
  <details class:opening-row={entry.isOpeningBalance} class="register-row">
    <summary class="register-summary">
      <button
        class="clearing-indicator clearing-{entry.clearingStatus ?? 'unmarked'}"
        title={CLEARING_TOOLTIPS[entry.clearingStatus ?? 'unmarked']}
        on:click={(e) => onToggleClearing(entry, e)}
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

      {#if entryHasActions(entry)}
        <div class="register-cell relative">
          <button
            class="action-menu-btn"
            title="Actions"
            type="button"
            on:click={(e) => onOpenActionMenu(entry, e)}
          >⋮</button>
          {#if activeMenuEntry === entry}
            <div class="action-menu-popover">
              {#if canDelete(entry)}
                <button class="action-menu-item danger" type="button" on:click={(e) => { e.stopPropagation(); onConfirmDelete(entry); }}>
                  Remove transaction
                </button>
              {/if}
              {#if canRecategorize(entry)}
                <button class="action-menu-item" type="button" on:click={(e) => { e.stopPropagation(); onRecategorize(entry); }}>
                  Reset category
                </button>
              {/if}
              {#if canUnmatch(entry)}
                <button class="action-menu-item" type="button" on:click={(e) => { e.stopPropagation(); onConfirmUnmatch(entry); }}>
                  Undo match
                </button>
              {/if}
            </div>
          {/if}
        </div>
      {:else}
        <span></span>
      {/if}
    </summary>

    <div class="px-4 pb-4 grid gap-3">
      {#if entry.isOpeningBalance}
        <p class="text-muted-foreground text-sm">This entry anchors running balances for the account until more history is backfilled.</p>
      {/if}

      {#if entry.transferState === 'settled_grouped'}
        <p class="text-muted-foreground text-sm">This imported row settled as part of a grouped transfer, so it no longer counts as pending.</p>
      {/if}

      {#if entry.manualResolutionNote}
        <p class="text-sm manual-resolution-note">{entry.manualResolutionNote}</p>
      {/if}

      {#if entry.detailLines.length > 0}
        <div class="grid gap-2.5 grid-cols-[repeat(auto-fit,minmax(14rem,1fr))]">
          {#each entry.detailLines as line}
            <div class="detail-line">
              <p>{line.label}</p>
              <p class="muted text-sm">{line.account}</p>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </details>
{/if}

<style>
  /* --- Activity row separator --- */
  .activity-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
    padding: 0.65rem 0;
    border-bottom: 1px solid rgba(10, 61, 89, 0.05);
  }

  .activity-row:last-child {
    border-bottom: none;
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
  }

  .register-row:last-child {
    border-bottom: none;
  }

  .register-row[open] {
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
    cursor: pointer;
    list-style: none;
  }

  .register-summary::-webkit-details-marker {
    display: none;
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

  /* --- Detail note colors --- */
  .manual-resolution-note {
    color: var(--brand-strong);
  }

  /* --- Detail line card --- */
  .detail-line {
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 0.9rem;
    padding: 0.7rem 0.8rem;
    background: rgba(255, 255, 255, 0.62);
  }

  /* --- Action menu --- */
  .action-menu-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.6rem;
    height: 1.6rem;
    padding: 0;
    border: none;
    border-radius: 0.4rem;
    background: transparent;
    color: var(--muted-foreground);
    font-size: 1.1rem;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }

  .action-menu-btn:hover {
    background: rgba(10, 61, 89, 0.08);
    color: var(--foreground);
  }

  .action-menu-popover {
    position: absolute;
    right: 0;
    top: 100%;
    z-index: 20;
    min-width: 11rem;
    background: #fff;
    border: 1px solid rgba(10, 61, 89, 0.12);
    border-radius: 0.7rem;
    box-shadow: 0 4px 16px rgba(10, 20, 30, 0.12);
    padding: 0.3rem;
    display: grid;
    gap: 0.1rem;
  }

  .action-menu-item {
    display: block;
    width: 100%;
    padding: 0.55rem 0.75rem;
    border: none;
    border-radius: 0.45rem;
    background: transparent;
    color: var(--foreground);
    font-size: 0.88rem;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }

  .action-menu-item:hover {
    background: rgba(10, 61, 89, 0.06);
  }

  .action-menu-item.danger {
    color: var(--error, #c53030);
  }

  .action-menu-item.danger:hover {
    background: rgba(197, 48, 48, 0.08);
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
