<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import type { TransactionFilters, TrackedAccount } from '$lib/transactions/types';

  export let open = false;
  export let filters: TransactionFilters;
  export let trackedAccounts: TrackedAccount[] = [];
  export let allAccounts: string[] = [];
  export let onApply: (next: TransactionFilters) => void = () => {};
  export let onClose: () => void = () => {};

  let activeTab: 'accounts' | 'categories' | 'status' = 'accounts';
  let draftAccounts: string[] = [];
  let draftCategory: string | null = null;
  let draftStatus: string | null = null;
  let categorySearch = '';

  // Reset draft state when dialog opens
  $: if (open) {
    draftAccounts = [...filters.accounts];
    draftCategory = filters.category;
    draftStatus = filters.status;
    categorySearch = '';
    activeTab = 'accounts';
  }

  $: filteredCategoryAccounts = allAccounts
    .filter((a) => {
      if (!categorySearch.trim()) return true;
      return a.toLowerCase().includes(categorySearch.trim().toLowerCase());
    })
    .slice(0, 80);

  function toggleAccount(accountId: string) {
    if (draftAccounts.includes(accountId)) {
      draftAccounts = draftAccounts.filter((a) => a !== accountId);
    } else {
      draftAccounts = [...draftAccounts, accountId];
    }
  }

  function selectCategory(account: string) {
    draftCategory = draftCategory === account ? null : account;
  }

  function selectStatus(value: string) {
    draftStatus = draftStatus === value ? null : value;
  }

  function handleApply() {
    onApply({
      ...filters,
      accounts: draftAccounts,
      category: draftCategory,
      status: draftStatus
    });
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) onClose();
  }

  function categoryDisplayName(category: string): string {
    const parts = category.split(':');
    if (parts.length <= 1) return category;
    return parts.slice(1).map((s) => s.replace(/_/g, ' ')).join(' / ');
  }
</script>

<DialogPrimitive.Root {open} onOpenChange={handleOpenChange}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="fixed inset-0 z-30 bg-black/25" />

    <DialogPrimitive.Content
      class="fixed top-1/2 left-1/2 z-40 grid w-[min(36rem,calc(100vw-2rem))] max-h-[calc(100vh-2rem)] -translate-x-1/2 -translate-y-1/2 gap-0 overflow-hidden rounded-2xl border border-line bg-white shadow-card"
      aria-labelledby="filter-dialog-title"
    >
      <div class="border-b border-line/60 px-5 pt-5 pb-3">
        <h3 id="filter-dialog-title" class="m-0 font-display text-lg">Filters</h3>
      </div>

      <!-- Tab bar -->
      <div class="flex border-b border-line/60">
        <button
          class="filter-tab" class:filter-tab-active={activeTab === 'accounts'}
          type="button" on:click={() => (activeTab = 'accounts')}
        >Accounts</button>
        <button
          class="filter-tab" class:filter-tab-active={activeTab === 'categories'}
          type="button" on:click={() => (activeTab = 'categories')}
        >Categories</button>
        <button
          class="filter-tab" class:filter-tab-active={activeTab === 'status'}
          type="button" on:click={() => (activeTab = 'status')}
        >Status</button>
      </div>

      <!-- Tab content -->
      <div class="filter-content overflow-y-auto px-5 py-4">
        {#if activeTab === 'accounts'}
          <div class="grid gap-2">
            {#if trackedAccounts.length === 0}
              <p class="text-sm text-muted-foreground">No tracked accounts found.</p>
            {:else}
              {#each trackedAccounts as account}
                <label class="filter-checkbox-row">
                  <input
                    type="checkbox"
                    checked={draftAccounts.includes(account.id)}
                    on:change={() => toggleAccount(account.id)}
                  />
                  <span class="text-sm font-semibold">{account.displayName}</span>
                  {#if account.institutionDisplayName}
                    <span class="text-xs text-muted-foreground ml-auto">{account.institutionDisplayName}</span>
                  {/if}
                </label>
              {/each}
            {/if}
          </div>

        {:else if activeTab === 'categories'}
          <div class="grid gap-3">
            <input
              type="search"
              class="filter-search-input"
              placeholder="Search categories..."
              bind:value={categorySearch}
            />
            <div class="grid gap-1 max-h-60 overflow-y-auto">
              {#each filteredCategoryAccounts as account}
                <button
                  class="filter-category-item" class:filter-category-selected={draftCategory === account}
                  type="button" on:click={() => selectCategory(account)}
                >
                  {categoryDisplayName(account)}
                </button>
              {/each}
              {#if filteredCategoryAccounts.length === 0}
                <p class="text-sm text-muted-foreground">No matching categories.</p>
              {/if}
            </div>
          </div>

        {:else if activeTab === 'status'}
          <div class="grid gap-2">
            {#each ['cleared', 'pending', 'unmarked'] as statusOption}
              <label class="filter-checkbox-row">
                <input
                  type="radio"
                  name="status"
                  checked={draftStatus === statusOption}
                  on:change={() => selectStatus(statusOption)}
                />
                <span class="text-sm font-semibold capitalize">{statusOption}</span>
              </label>
            {/each}
            <label class="filter-checkbox-row">
              <input
                type="radio"
                name="status"
                checked={draftStatus === null}
                on:change={() => (draftStatus = null)}
              />
              <span class="text-sm font-semibold">Any</span>
            </label>
          </div>
        {/if}
      </div>

      <!-- Footer -->
      <div class="flex items-center justify-end gap-3 border-t border-line/60 px-5 py-3">
        <button class="btn" type="button" on:click={onClose}>Cancel</button>
        <button class="btn btn-primary" type="button" on:click={handleApply}>Apply</button>
      </div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>

<style>
  .filter-tab {
    flex: 1;
    padding: 0.6rem 0.75rem;
    border: none;
    background: transparent;
    color: var(--muted-foreground);
    font-size: 0.84rem;
    font-weight: 600;
    cursor: pointer;
    transition: color 0.15s;
    text-align: center;
  }

  .filter-tab:hover {
    color: var(--foreground);
  }

  .filter-tab-active {
    color: var(--brand-strong);
    box-shadow: inset 0 -2px 0 var(--brand-strong);
  }

  .filter-content {
    min-height: 12rem;
    max-height: 22rem;
  }

  .filter-checkbox-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0.5rem;
    border-radius: 0.5rem;
    cursor: pointer;
    transition: background 0.12s;
  }

  .filter-checkbox-row:hover {
    background: rgba(10, 61, 89, 0.04);
  }

  .filter-search-input {
    width: 100%;
    padding: 0.4rem 0.65rem;
    border: 1px solid rgba(10, 61, 89, 0.12);
    border-radius: 0.5rem;
    background: rgba(255, 255, 255, 0.85);
    font-size: 0.84rem;
    outline: none;
    transition: border-color 0.15s;
  }

  .filter-search-input:focus {
    border-color: var(--brand, rgba(15, 95, 136, 0.4));
  }

  .filter-category-item {
    padding: 0.35rem 0.6rem;
    border: none;
    border-radius: 0.4rem;
    background: transparent;
    color: var(--foreground);
    font-size: 0.84rem;
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }

  .filter-category-item:hover {
    background: rgba(10, 61, 89, 0.04);
  }

  .filter-category-selected {
    background: rgba(15, 95, 136, 0.08);
    color: var(--brand-strong);
    font-weight: 600;
  }
</style>
