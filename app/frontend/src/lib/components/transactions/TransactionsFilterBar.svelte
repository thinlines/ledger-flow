<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { TransactionFilters, TrackedAccount } from '$lib/transactions/types';

  export let filters: TransactionFilters;
  export let trackedAccounts: TrackedAccount[] = [];
  export let onChange: (next: TransactionFilters) => void = () => {};
  export let onOpenFilterDialog: () => void = () => {};

  let searchInput = filters.search;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let helpOpen = false;
  let helpPopoverEl: HTMLDivElement | null = null;
  let helpBtnEl: HTMLButtonElement | null = null;

  onDestroy(() => {
    if (debounceTimer) clearTimeout(debounceTimer);
    removeHelpListeners();
  });

  function toggleHelp() {
    helpOpen = !helpOpen;
    if (helpOpen) {
      // Listen for outside clicks and Escape on next tick.
      setTimeout(() => {
        document.addEventListener('click', handleHelpOutsideClick, true);
        document.addEventListener('keydown', handleHelpEscape, true);
      }, 0);
    } else {
      removeHelpListeners();
    }
  }

  function handleHelpOutsideClick(e: MouseEvent) {
    if (
      helpPopoverEl && !helpPopoverEl.contains(e.target as Node) &&
      helpBtnEl && !helpBtnEl.contains(e.target as Node)
    ) {
      helpOpen = false;
      removeHelpListeners();
    }
  }

  function handleHelpEscape(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      helpOpen = false;
      removeHelpListeners();
    }
  }

  function removeHelpListeners() {
    document.removeEventListener('click', handleHelpOutsideClick, true);
    document.removeEventListener('keydown', handleHelpEscape, true);
  }

  $: if (filters.search !== searchInput && !debounceTimer) {
    searchInput = filters.search;
  }

  function handleSearchInput(event: Event) {
    const value = (event.currentTarget as HTMLInputElement).value;
    searchInput = value;
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      onChange({ ...filters, search: value });
    }, 300);
  }

  function setPeriod(period: string | null) {
    onChange({ ...filters, period, month: null });
  }

  function clearMonth() {
    onChange({ ...filters, month: null });
  }

  function clearCategory() {
    onChange({ ...filters, category: null });
  }

  function clearStatus() {
    onChange({ ...filters, status: null });
  }

  function removeAccount(accountId: string) {
    onChange({ ...filters, accounts: filters.accounts.filter((a) => a !== accountId) });
  }

  function clearSearch() {
    searchInput = '';
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = null;
    onChange({ ...filters, search: '' });
  }

  function accountDisplayName(accountId: string): string {
    const found = trackedAccounts.find((a) => a.id === accountId);
    return found?.displayName ?? accountId;
  }

  function categoryDisplayName(category: string): string {
    const parts = category.split(':');
    if (parts.length <= 1) return category;
    return parts.slice(1).map((s) => s.replace(/_/g, ' ')).join(' / ');
  }

  function monthTitle(month: string): string {
    const parsed = new Date(`${month}-01T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(parsed);
  }

  function statusTitle(status: string): string {
    return status.charAt(0).toUpperCase() + status.slice(1);
  }
</script>

<section class="view-card filter-bar">
  <div class="flex flex-wrap items-center gap-2">
    <div class="filter-search relative">
      <input
        type="search"
        placeholder="Search transactions..."
        value={searchInput}
        on:input={handleSearchInput}
        class="filter-search-input"
      />
      {#if searchInput}
        <button class="filter-clear" type="button" on:click={clearSearch} aria-label="Clear search">&times;</button>
      {/if}
      <button
        bind:this={helpBtnEl}
        class="ml-1 inline-flex items-center justify-center w-5 h-5 rounded-full border border-[rgba(10,61,89,0.15)] bg-white text-[0.7rem] font-semibold text-[var(--muted-foreground)] hover:bg-[rgba(15,95,136,0.08)] hover:text-[var(--foreground)] transition-colors cursor-pointer"
        type="button"
        on:click={toggleHelp}
        aria-label="Search syntax help"
      >?</button>
      {#if helpOpen}
        <div
          bind:this={helpPopoverEl}
          class="absolute top-full left-0 mt-1.5 z-50 w-72 rounded-lg border border-[rgba(10,61,89,0.12)] bg-white shadow-lg p-3"
        >
          <p class="text-[0.78rem] font-semibold text-[var(--foreground)] mb-2">Search syntax</p>
          <table class="w-full text-[0.74rem] leading-snug">
            <tbody>
              <tr><td class="pr-3 py-0.5 font-mono text-[var(--brand-strong)] whitespace-nowrap">amount:&gt;100</td><td class="text-[var(--muted-foreground)]">Over $100</td></tr>
              <tr><td class="pr-3 py-0.5 font-mono text-[var(--brand-strong)] whitespace-nowrap">amount:50..200</td><td class="text-[var(--muted-foreground)]">$50 to $200</td></tr>
              <tr><td class="pr-3 py-0.5 font-mono text-[var(--brand-strong)] whitespace-nowrap">category:food</td><td class="text-[var(--muted-foreground)]">Category contains "food"</td></tr>
              <tr><td class="pr-3 py-0.5 font-mono text-[var(--brand-strong)] whitespace-nowrap">date:this-month</td><td class="text-[var(--muted-foreground)]">Current month</td></tr>
              <tr><td class="pr-3 py-0.5 font-mono text-[var(--brand-strong)] whitespace-nowrap">status:cleared</td><td class="text-[var(--muted-foreground)]">Bank-confirmed only</td></tr>
              <tr><td class="pr-3 py-0.5 font-mono text-[var(--brand-strong)] whitespace-nowrap">account:chase</td><td class="text-[var(--muted-foreground)]">Account name contains "chase"</td></tr>
            </tbody>
          </table>
          <p class="mt-2 text-[0.7rem] text-[var(--muted-foreground)]">Combine terms with spaces. Plain text matches payee.</p>
        </div>
      {/if}
    </div>

    {#if filters.month}
      <span class="filter-chip">
        {monthTitle(filters.month)}
        <button class="filter-clear" type="button" on:click={clearMonth} aria-label="Clear month filter">&times;</button>
      </span>
    {:else}
      <div class="activity-presets">
        <button class:active={filters.period === 'this-month'} on:click={() => setPeriod('this-month')}>This month</button>
        <button class:active={filters.period === 'last-30'} on:click={() => setPeriod('last-30')}>Last 30 days</button>
        <button class:active={filters.period === 'last-3-months'} on:click={() => setPeriod('last-3-months')}>Last 3 months</button>
        <button class:active={!filters.period} on:click={() => setPeriod(null)}>All time</button>
      </div>
    {/if}

    {#each filters.accounts as accountId}
      <span class="filter-chip">
        {accountDisplayName(accountId)}
        <button class="filter-clear" type="button" on:click={() => removeAccount(accountId)} aria-label="Remove account filter">&times;</button>
      </span>
    {/each}

    {#if filters.category}
      <span class="filter-chip">
        {categoryDisplayName(filters.category)}
        <button class="filter-clear" type="button" on:click={clearCategory} aria-label="Clear category filter">&times;</button>
      </span>
    {/if}

    {#if filters.status}
      <span class="filter-chip">
        <span class="sr-only">Status: </span>
        {statusTitle(filters.status)}
        <button class="filter-clear" type="button" on:click={clearStatus} aria-label="Clear status filter">&times;</button>
      </span>
    {/if}

    <button class="btn filter-more-btn" type="button" on:click={onOpenFilterDialog}>+ Filters</button>
  </div>
</section>

<style>
  .filter-bar {
    padding: 0.75rem 1.25rem;
  }

  .filter-search {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    position: relative;
  }

  .filter-search-input {
    width: 12rem;
    padding: 0.35rem 0.65rem;
    border: 1px solid rgba(10, 61, 89, 0.12);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.85);
    font-size: 0.84rem;
    outline: none;
    transition: border-color 0.15s;
  }

  .filter-search-input:focus {
    border-color: var(--brand, rgba(15, 95, 136, 0.4));
  }

  .filter-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    background: rgba(15, 95, 136, 0.08);
    color: var(--brand-strong);
    font-size: 0.82rem;
    font-weight: 600;
    border: 1px solid rgba(15, 95, 136, 0.14);
  }

  .filter-clear {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.1rem;
    height: 1.1rem;
    border: none;
    border-radius: 50%;
    background: rgba(15, 95, 136, 0.12);
    color: var(--brand-strong);
    font-size: 0.85rem;
    line-height: 1;
    cursor: pointer;
    padding: 0;
    transition: background 0.15s;
  }

  .filter-clear:hover {
    background: rgba(15, 95, 136, 0.22);
  }

  .activity-presets {
    display: inline-flex;
    gap: 0.15rem;
    padding: 0.15rem;
    border-radius: 999px;
    background: rgba(10, 61, 89, 0.06);
  }

  .activity-presets button {
    padding: 0.25rem 0.65rem;
    border: none;
    border-radius: 999px;
    background: transparent;
    color: var(--muted-foreground);
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .activity-presets button.active {
    background: #fff;
    color: var(--foreground);
    box-shadow: 0 1px 3px rgba(10, 61, 89, 0.1);
  }

  .activity-presets button:hover:not(.active) {
    color: var(--foreground);
  }

  .filter-more-btn {
    font-size: 0.82rem;
    padding: 0.25rem 0.7rem;
  }
</style>
