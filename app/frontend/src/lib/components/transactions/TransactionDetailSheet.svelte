<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import XIcon from '@lucide/svelte/icons/x';
  import EllipsisVerticalIcon from '@lucide/svelte/icons/ellipsis-vertical';
  import * as Popover from '$lib/components/ui/popover/index.js';
  import type { RegisterEntry, ActivityTransaction } from '$lib/transactions/types';
  import { formatCurrency, shortDate } from '$lib/format';
  import { activityShortDate, canDelete, canRecategorize, canUnmatch } from '$lib/transactions/helpers';

  export let entry: RegisterEntry | null = null;
  export let transaction: ActivityTransaction | null = null;
  export let baseCurrency: string;
  export let onDelete: (entry: RegisterEntry) => void = () => {};
  export let onRecategorize: (entry: RegisterEntry) => void = () => {};
  export let onUnmatch: (entry: RegisterEntry) => void = () => {};
  export let onClose: () => void = () => {};

  let menuOpen = false;

  $: open = entry !== null || transaction !== null;
  $: mode = entry ? 'register' : 'activity';
  $: payee = entry?.payee ?? transaction?.payee ?? '';
  $: amount = entry?.amount ?? transaction?.amount ?? 0;
  $: accountLabel = transaction?.accountLabel ?? entry?.summary ?? '';
  $: hasActions = entry ? !entry.isOpeningBalance : false;
  $: showDelete = entry ? canDelete(entry) : false;
  $: showRecategorize = entry ? canRecategorize(entry) : false;
  $: showUnmatch = entry ? canUnmatch(entry) : false;

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      menuOpen = false;
      onClose();
    }
  }

  function handleDelete() {
    if (!entry) return;
    menuOpen = false;
    onDelete(entry);
  }

  function handleRecategorize() {
    if (!entry) return;
    menuOpen = false;
    onRecategorize(entry);
  }

  function handleUnmatch() {
    if (!entry) return;
    menuOpen = false;
    onUnmatch(entry);
  }
</script>

<DialogPrimitive.Root {open} onOpenChange={handleOpenChange}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="fixed inset-0 z-30 bg-black/25 max-desktop:bg-black/35" />

    <DialogPrimitive.Content
      class="fixed top-0 right-0 z-40 flex h-full w-[min(26rem,100vw)] flex-col border-l border-line bg-white shadow-card animate-[sheet-slide-in_0.2s_ease-out]"
      aria-labelledby="sheet-title"
    >
      <!-- Header -->
      <div class="flex items-start justify-between gap-3 border-b border-line/60 px-5 pt-5 pb-4">
        <div class="min-w-0">
          <h3 id="sheet-title" class="m-0 truncate font-display text-lg" title={payee}>{payee}</h3>
          <p class="mt-1 text-sm text-muted-foreground">{accountLabel}</p>
        </div>

        <div class="flex shrink-0 items-center gap-1">
          {#if hasActions}
            <Popover.Root bind:open={menuOpen}>
              <Popover.Trigger
                class="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label="Actions"
              >
                <EllipsisVerticalIcon class="size-4" />
              </Popover.Trigger>

              <Popover.Content class="w-48 p-1" align="end">
                {#if showDelete}
                  <button class="sheet-menu-item sheet-menu-danger" type="button" on:click={handleDelete}>
                    Remove transaction
                  </button>
                {/if}
                {#if showRecategorize}
                  <button class="sheet-menu-item" type="button" on:click={handleRecategorize}>
                    Reset category
                  </button>
                {/if}
                {#if showUnmatch}
                  <button class="sheet-menu-item" type="button" on:click={handleUnmatch}>
                    Undo match
                  </button>
                {/if}
              </Popover.Content>
            </Popover.Root>
          {/if}

          <button
            class="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            type="button"
            on:click={onClose}
            aria-label="Close"
          >
            <XIcon class="size-4" />
          </button>
        </div>
      </div>

      <!-- Body -->
      <div class="flex-1 overflow-y-auto px-5 py-4">
        <div class="grid gap-4">
          <!-- Amount -->
          <div>
            <p class="eyebrow">Amount</p>
            <p class:sheet-positive={amount > 0} class:sheet-negative={amount < 0} class="mt-0.5 font-display text-2xl leading-none">
              {formatCurrency(amount, baseCurrency, { signed: true })}
            </p>
          </div>

          {#if mode === 'register' && entry}
            <!-- Register mode fields -->
            <div class="grid gap-4">
              <div>
                <p class="eyebrow">Date</p>
                <p class="mt-0.5 text-sm">{shortDate(entry.date)}</p>
              </div>

              <div>
                <p class="eyebrow">Category</p>
                <p class="mt-0.5 text-sm">{entry.summary}</p>
              </div>

              <div>
                <p class="eyebrow">Running balance</p>
                <p class:sheet-positive={entry.runningBalance > 0} class:sheet-negative={entry.runningBalance < 0} class="mt-0.5 text-sm font-bold">
                  {formatCurrency(entry.runningBalance, baseCurrency)}
                </p>
              </div>

              {#if entry.isOpeningBalance}
                <p class="rounded-xl border border-line/60 bg-white/60 px-3 py-2.5 text-sm text-muted-foreground">
                  This entry anchors running balances for the account until more history is backfilled.
                </p>
              {/if}

              {#if entry.transferState === 'settled_grouped'}
                <p class="rounded-xl border border-line/60 bg-white/60 px-3 py-2.5 text-sm text-muted-foreground">
                  This imported row settled as part of a grouped transfer, so it no longer counts as pending.
                </p>
              {/if}

              {#if entry.manualResolutionNote}
                <p class="rounded-xl border border-brand/15 bg-brand/4 px-3 py-2.5 text-sm text-brand-strong">
                  {entry.manualResolutionNote}
                </p>
              {/if}

              {#if entry.detailLines.length > 0}
                <div>
                  <p class="eyebrow">Detail lines</p>
                  <div class="mt-2 grid gap-2">
                    {#each entry.detailLines as line}
                      <div class="rounded-xl border border-line/60 bg-white/60 px-3 py-2.5">
                        <p class="text-sm font-semibold">{line.label}</p>
                        <p class="mt-0.5 text-sm text-muted-foreground">{line.account}</p>
                      </div>
                    {/each}
                  </div>
                </div>
              {/if}
            </div>
          {:else if mode === 'activity' && transaction}
            <!-- Activity mode fields -->
            <div class="grid gap-4">
              <div>
                <p class="eyebrow">Date</p>
                <p class="mt-0.5 text-sm">{activityShortDate(transaction.date)}</p>
              </div>

              <div>
                <p class="eyebrow">Account</p>
                <p class="mt-0.5 text-sm">{transaction.accountLabel}</p>
              </div>

              <div>
                <p class="eyebrow">Category</p>
                <p class="mt-0.5 text-sm">{transaction.category}</p>
              </div>

              {#if transaction.isUnknown}
                <a class="pill warn no-underline inline-block w-fit" href="/unknowns">Needs review</a>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>

<style>
  /* Amount color classes */
  .sheet-positive {
    color: var(--ok);
  }

  .sheet-negative {
    color: var(--bad);
  }

  /* Overflow menu items */
  .sheet-menu-item {
    display: block;
    width: 100%;
    padding: 0.5rem 0.65rem;
    border: none;
    border-radius: 0.4rem;
    background: transparent;
    color: var(--foreground);
    font-size: 0.88rem;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }

  .sheet-menu-item:hover {
    background: rgba(10, 61, 89, 0.06);
  }

  .sheet-menu-danger {
    color: var(--error, #c53030);
  }

  .sheet-menu-danger:hover {
    background: rgba(197, 48, 48, 0.08);
  }
</style>
