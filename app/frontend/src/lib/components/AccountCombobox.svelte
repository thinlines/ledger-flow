<script lang="ts">
  import CheckIcon from '@lucide/svelte/icons/check';
  import PlusIcon from '@lucide/svelte/icons/plus';
  import { cn } from '$lib/utils.js';

  export let accounts: string[] = [];
  export let value = '';
  export let placeholder = 'Select account...';
  export let disabled = false;
  export let allowCreate = true;
  export let onChange: (account: string) => void = () => {};
  export let onCreate: (seed: string) => void = () => {};

  let inputEl: HTMLInputElement | null = null;
  let open = false;
  let query = '';
  let highlightedIndex = -1;
  let blurTimer: ReturnType<typeof setTimeout> | null = null;
  let dropY = 0, dropX = 0, dropW = 0;
  const listId = `acct-combo-${Math.random().toString(36).slice(2, 8)}`;

  $: filteredAccounts = filterAccounts(accounts, query, value);
  $: displayValue = open ? query : (value || '');
  $: if (open && highlightedIndex >= filteredAccounts.length) highlightedIndex = filteredAccounts.length - 1;

  function filterAccounts(items: string[], search: string, selected: string): string[] {
    const normalized = search.trim().toLowerCase();
    if (!normalized || normalized === selected.toLowerCase()) return items.slice(0, 50);
    return items.filter((a) => a.toLowerCase().includes(normalized)).slice(0, 50);
  }

  function updatePos() {
    if (!inputEl) return;
    const r = inputEl.getBoundingClientRect();
    dropY = r.bottom + 4;
    dropX = r.left;
    dropW = r.width;
  }

  function selectAccount(account: string) {
    value = account;
    onChange(account);
    query = '';
    open = false;
    highlightedIndex = -1;
  }

  function requestCreate() {
    if (!allowCreate) return;
    const seed = query.trim();
    query = '';
    open = false;
    highlightedIndex = -1;
    onCreate(seed);
  }

  function handleFocus() {
    if (blurTimer) { clearTimeout(blurTimer); blurTimer = null; }
    query = value || '';
    updatePos();
    open = true;
    highlightedIndex = -1;
    requestAnimationFrame(() => inputEl?.select());
  }

  function handleBlur() {
    blurTimer = setTimeout(() => {
      open = false;
      query = '';
      highlightedIndex = -1;
      blurTimer = null;
    }, 150);
  }

  function handleInputKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      open = false;
      query = '';
      highlightedIndex = -1;
      inputEl?.blur();
      return;
    }
    if (event.key === 'Tab') {
      if (open && filteredAccounts.length > 0) {
        selectAccount(filteredAccounts[highlightedIndex >= 0 ? highlightedIndex : 0]);
      }
      return; // don't preventDefault — let Tab move focus naturally
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      event.stopPropagation();
      if (filteredAccounts.length > 0) {
        selectAccount(filteredAccounts[highlightedIndex >= 0 ? highlightedIndex : 0]);
      } else if (allowCreate && query.trim()) {
        requestCreate();
      }
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!open) { updatePos(); open = true; highlightedIndex = 0; return; }
      highlightedIndex = highlightedIndex < filteredAccounts.length - 1 ? highlightedIndex + 1 : 0;
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) { updatePos(); open = true; highlightedIndex = filteredAccounts.length - 1; return; }
      highlightedIndex = highlightedIndex > 0 ? highlightedIndex - 1 : filteredAccounts.length - 1;
      return;
    }
  }

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return {
      destroy() {
        if (node.parentNode) node.parentNode.removeChild(node);
      }
    };
  }
</script>

<div class="relative">
  <input
    bind:this={inputEl}
    type="text"
    role="combobox"
    autocomplete="off"
    aria-expanded={open}
    aria-controls={listId}
    aria-autocomplete="list"
    {disabled}
    class={cn(
      'flex w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-hidden transition-[color,box-shadow] focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
      !value && !open && 'text-muted-foreground'
    )}
    value={displayValue}
    {placeholder}
    on:focus={handleFocus}
    on:blur={handleBlur}
    on:input={(e) => { query = e.currentTarget.value; if (!open) { updatePos(); open = true; } highlightedIndex = -1; }}
    on:keydown={handleInputKeydown}
  />

  {#if open}
    <div
      use:portal
      id={listId}
      role="listbox"
      class="rounded-md border border-border bg-popover py-1 shadow-md"
      style="position: fixed; z-index: 9999; top: {dropY}px; left: {dropX}px; width: {dropW}px; max-height: 300px; overflow-y: auto;"
    >
      {#if filteredAccounts.length === 0}
        {#if allowCreate && query.trim()}
          <button
            type="button"
            class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
            on:pointerdown|preventDefault={() => requestCreate()}
          >
            <PlusIcon class="size-4" />
            Add "{query.trim()}"
          </button>
        {:else}
          <div class="px-2 py-1.5 text-sm text-muted-foreground">No account found.</div>
        {/if}
      {:else}
        {#each filteredAccounts as account, i (account)}
          <button
            type="button"
            role="option"
            aria-selected={i === highlightedIndex}
            class={cn(
              'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-left',
              i === highlightedIndex
                ? 'bg-accent text-accent-foreground'
                : 'hover:bg-accent hover:text-accent-foreground'
            )}
            on:pointerdown|preventDefault={() => selectAccount(account)}
          >
            <CheckIcon class={cn('size-4 shrink-0', value !== account && 'text-transparent')} />
            <span class="truncate">{account}</span>
          </button>
        {/each}
        {#if allowCreate}
          <div class="border-t pt-1">
            <button
              type="button"
              class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
              on:pointerdown|preventDefault={() => requestCreate()}
            >
              <PlusIcon class="size-4" />
              Add account
            </button>
          </div>
        {/if}
      {/if}
    </div>
  {/if}
</div>
