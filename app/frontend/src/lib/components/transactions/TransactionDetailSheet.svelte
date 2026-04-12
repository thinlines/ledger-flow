<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { tick } from 'svelte';
  import XIcon from '@lucide/svelte/icons/x';
  import EllipsisVerticalIcon from '@lucide/svelte/icons/ellipsis-vertical';
  import CheckIcon from '@lucide/svelte/icons/check';
  import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
  import * as Popover from '$lib/components/ui/popover/index.js';
  import * as Command from '$lib/components/ui/command/index.js';
  import type { RegisterEntry, ActivityTransaction } from '$lib/transactions/types';
  import { formatCurrency, shortDate } from '$lib/format';
  import { activityShortDate, canDelete, canRecategorize, canUnmatch } from '$lib/transactions/helpers';
  import { apiPost } from '$lib/api';
  import { cn } from '$lib/utils.js';

  export let entry: RegisterEntry | null = null;
  export let transaction: ActivityTransaction | null = null;
  export let baseCurrency: string;
  export let accounts: string[] = [];
  export let onDelete: (entry: RegisterEntry) => void = () => {};
  export let onResetCategory: (entry: RegisterEntry) => void = () => {};
  export let onRecategorize: (entry: RegisterEntry, newCategory: string) => void = () => {};
  export let onUnmatch: (entry: RegisterEntry) => void = () => {};
  export let onClose: () => void = () => {};

  let menuOpen = false;
  let categoryOpen = false;
  let categoryQuery = '';
  let categoryTriggerRef: HTMLButtonElement | null = null;
  let notesValue = '';
  let notesSaveState: 'idle' | 'saving' | 'saved' | 'error' = 'idle';
  let notesSaveTimer: ReturnType<typeof setTimeout> | null = null;
  let notesErrorMsg = '';
  let lastNotesEntryId = '';

  $: open = entry !== null || transaction !== null;
  $: mode = entry ? 'register' : 'activity';
  $: payee = entry?.payee ?? transaction?.payee ?? '';
  $: amount = entry?.amount ?? transaction?.amount ?? 0;
  $: accountLabel = entry?.summary ?? transaction?.accountLabel ?? '';
  $: isUnknown = entry?.isUnknown ?? transaction?.isUnknown ?? false;
  $: hasActions = entry ? !entry.isOpeningBalance : false;
  $: showDelete = entry ? canDelete(entry) : false;
  $: showResetCategory = entry ? canRecategorize(entry) : false;
  $: showUnmatch = entry ? canUnmatch(entry) : false;

  // Category combobox: show for non-opening-balance, non-transfer, non-split entries in register mode
  $: showCategoryCombobox = entry
    ? !entry.isOpeningBalance && !entry.transferState && entry.detailLines.filter((l) => l.kind !== 'source').length <= 1
    : false;

  // Sync notes value when entry changes
  $: if (entry && entry.id !== lastNotesEntryId) {
    notesValue = entry.notes ?? '';
    lastNotesEntryId = entry.id;
    notesSaveState = 'idle';
    notesErrorMsg = '';
  }

  // Reset category query when popover closes
  $: if (!categoryOpen) categoryQuery = '';

  $: filteredAccounts = filterCategoryAccounts(accounts, categoryQuery);

  function filterCategoryAccounts(items: string[], search: string): string[] {
    const normalized = search.trim().toLowerCase();
    if (!normalized) return items.slice(0, 50);
    return items.filter((account) => account.toLowerCase().includes(normalized)).slice(0, 50);
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      menuOpen = false;
      categoryOpen = false;
      onClose();
    }
  }

  function handleDelete() {
    if (!entry) return;
    menuOpen = false;
    onDelete(entry);
  }

  function handleResetCategory() {
    if (!entry) return;
    menuOpen = false;
    onResetCategory(entry);
  }

  function handleUnmatch() {
    if (!entry) return;
    menuOpen = false;
    onUnmatch(entry);
  }

  async function closeCategoryAndFocus() {
    categoryOpen = false;
    await tick();
    categoryTriggerRef?.focus();
  }

  async function selectCategory(account: string) {
    if (!entry) return;
    onRecategorize(entry, account);
    categoryQuery = '';
    await closeCategoryAndFocus();
  }

  function handleCategoryInputKeydown(event: KeyboardEvent) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    event.stopPropagation();
    const topMatch = filteredAccounts[0];
    if (topMatch) {
      void selectCategory(topMatch);
    }
  }

  async function saveNotes() {
    if (!entry || !entry.journalPath || !entry.headerLine) return;
    const trimmed = notesValue.trim();
    const original = (entry.notes ?? '').trim();
    if (trimmed === original) return;

    notesSaveState = 'saving';
    notesErrorMsg = '';
    if (notesSaveTimer) clearTimeout(notesSaveTimer);

    try {
      await apiPost<{ success: boolean }>('/api/transactions/notes', {
        journalPath: entry.journalPath,
        headerLine: entry.headerLine,
        notes: trimmed
      });
      notesSaveState = 'saved';
      notesSaveTimer = setTimeout(() => {
        notesSaveState = 'idle';
      }, 2000);
    } catch (e) {
      notesSaveState = 'error';
      notesErrorMsg = e instanceof Error ? e.message : 'Failed to save';
      notesSaveTimer = setTimeout(() => {
        notesSaveState = 'idle';
        notesErrorMsg = '';
      }, 4000);
    }
  }
</script>

<DialogPrimitive.Root {open} onOpenChange={handleOpenChange}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="fixed inset-0 z-30 bg-black/25 max-desktop:bg-black/35" />

    <DialogPrimitive.Content
      class="fixed top-0 right-0 z-40 flex h-full w-[min(26rem,100vw)] flex-col border-l border-line bg-white shadow-card animate-[sheet-slide-in_0.2s_ease-out]"
      aria-labelledby="sheet-title"
    >
      <!-- Header bar -->
      <div class="flex items-start justify-between gap-3 border-b border-line/60 px-5 pt-5 pb-4">
        <h3 id="sheet-title" class="m-0 min-w-0 truncate font-display text-lg" title={payee}>{payee}</h3>

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
                {#if showResetCategory}
                  <button class="sheet-menu-item" type="button" on:click={handleResetCategory}>
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
        <div class="grid gap-5">
          <!-- Amount + account label -->
          <div>
            <p class:sheet-positive={amount > 0} class:sheet-negative={amount < 0} class="m-0 font-display text-2xl leading-none">
              {formatCurrency(amount, baseCurrency, { signed: true })}
            </p>
            <p class="mt-1 text-sm text-muted-foreground">{accountLabel}</p>
          </div>

          <!-- Needs review badge -->
          {#if isUnknown}
            <a class="pill warn no-underline inline-block w-fit" href="/unknowns">Needs review</a>
          {/if}

          <!-- Fields section -->
          <div class="grid gap-4">
            {#if mode === 'register' && entry}
              <!-- Date -->
              <div>
                <p class="eyebrow">Date</p>
                <p class="mt-0.5 text-sm">{shortDate(entry.date)}</p>
              </div>

              <!-- Category — combobox or read-only -->
              <div>
                <p class="eyebrow">Category</p>
                {#if showCategoryCombobox}
                  <Popover.Root bind:open={categoryOpen}>
                    <Popover.Trigger
                      bind:ref={categoryTriggerRef}
                      class={cn(
                        'mt-1 flex w-full min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-left text-sm shadow-xs outline-hidden transition-[color,box-shadow] hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring'
                      )}
                      role="combobox"
                      aria-expanded={categoryOpen}
                    >
                      <span class="truncate">{entry.summary}</span>
                      <ChevronsUpDownIcon class="size-4 shrink-0 opacity-50" />
                    </Popover.Trigger>

                    <Popover.Content class="w-72 max-w-[calc(100vw-2rem)] p-0" align="start">
                      <Command.Root shouldFilter={false}>
                        <div role="presentation" on:keydown={handleCategoryInputKeydown}>
                          <Command.Input bind:value={categoryQuery} placeholder="Search category..." />
                        </div>
                        <Command.List>
                          {#if filteredAccounts.length === 0}
                            <Command.Empty>No account found.</Command.Empty>
                          {:else}
                            <Command.Group value="categories">
                              {#each filteredAccounts as account (account)}
                                <Command.Item value={account} onSelect={() => void selectCategory(account)}>
                                  <CheckIcon class={cn('size-4', entry.summary !== account && 'text-transparent')} />
                                  <span class="truncate">{account}</span>
                                </Command.Item>
                              {/each}
                            </Command.Group>
                          {/if}
                        </Command.List>
                      </Command.Root>
                    </Popover.Content>
                  </Popover.Root>
                {:else}
                  <p class="mt-0.5 text-sm">{entry.summary}</p>
                {/if}
              </div>

              <!-- Running balance -->
              <div>
                <p class="eyebrow">Running balance</p>
                <p class:sheet-positive={entry.runningBalance > 0} class:sheet-negative={entry.runningBalance < 0} class="mt-0.5 text-sm font-bold">
                  {formatCurrency(entry.runningBalance, baseCurrency)}
                </p>
              </div>
            {:else if mode === 'activity' && transaction}
              <!-- Date -->
              <div>
                <p class="eyebrow">Date</p>
                <p class="mt-0.5 text-sm">{activityShortDate(transaction.date)}</p>
              </div>

              <!-- Category — read-only in activity mode -->
              <div>
                <p class="eyebrow">Category</p>
                <p class="mt-0.5 text-sm">{transaction.category}</p>
              </div>

              <!-- Account — activity mode only -->
              <div>
                <p class="eyebrow">Account</p>
                <p class="mt-0.5 text-sm">{transaction.accountLabel}</p>
              </div>
            {/if}
          </div>

          <!-- Notes field (register mode only) -->
          {#if mode === 'register' && entry}
            <div>
              <div class="flex items-center gap-2">
                <p class="eyebrow">Notes</p>
                {#if notesSaveState === 'saved'}
                  <span class="text-xs text-ok">Saved</span>
                {:else if notesSaveState === 'saving'}
                  <span class="text-xs text-muted-foreground">Saving...</span>
                {:else if notesSaveState === 'error'}
                  <span class="text-xs text-bad">{notesErrorMsg}</span>
                {/if}
              </div>
              <textarea
                class="mt-1 w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-hidden placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                rows="3"
                placeholder="Add a note..."
                bind:value={notesValue}
                on:blur={saveNotes}
              ></textarea>
            </div>
          {/if}

          <!-- Info cards -->
          {#if mode === 'register' && entry}
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
          {/if}

          <!-- Detail lines (register mode only) -->
          {#if mode === 'register' && entry && entry.detailLines.length > 0}
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
