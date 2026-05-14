<script lang="ts">
  import CheckIcon from '@lucide/svelte/icons/check';
  import PlusIcon from '@lucide/svelte/icons/plus';
  import * as Command from '$lib/components/ui/command/index.js';
  import * as Popover from '$lib/components/ui/popover/index.js';
  import { cn } from '$lib/utils.js';

  export let accounts: string[] = [];
  export let value = '';
  export let placeholder = 'Select account...';
  export let disabled = false;
  export let allowCreate = true;
  export let onChange: (account: string) => void = () => {};
  export let onCreate: (seed: string) => void = () => {};

  let open = false;
  let query = '';
  let inputEl: HTMLInputElement | null = null;
  let blurTimer: ReturnType<typeof setTimeout> | null = null;
  const listId = `acct-combo-${Math.random().toString(36).slice(2, 8)}`;

  $: filteredAccounts = filterAccounts(accounts, query, value);
  $: displayValue = open ? query : (value || '');

  function filterAccounts(items: string[], search: string, selected: string): string[] {
    const normalized = search.trim().toLowerCase();
    if (!normalized || normalized === selected.toLowerCase()) return items.slice(0, 50);
    return items.filter((account) => account.toLowerCase().includes(normalized)).slice(0, 50);
  }

  function selectAccount(account: string) {
    value = account;
    onChange(account);
    query = '';
    open = false;
  }

  function requestCreate() {
    if (!allowCreate) return;
    const seed = query.trim();
    query = '';
    open = false;
    onCreate(seed);
  }

  function selectHighlightedOrFirst() {
    if (filteredAccounts.length === 0) return;
    const popoverEl = document.getElementById(listId);
    const selectedEl = popoverEl?.querySelector('[aria-selected="true"]');
    const selectedValue = selectedEl?.getAttribute('data-value');
    if (selectedValue && accounts.includes(selectedValue)) {
      selectAccount(selectedValue);
    } else {
      selectAccount(filteredAccounts[0]);
    }
  }

  function handleFocus() {
    if (blurTimer) { clearTimeout(blurTimer); blurTimer = null; }
    query = value || '';
    open = true;
    requestAnimationFrame(() => inputEl?.select());
  }

  function handleBlur() {
    blurTimer = setTimeout(() => {
      open = false;
      query = '';
      blurTimer = null;
    }, 200);
  }

  function handleOpenChange(isOpen: boolean) {
    if (!isOpen) { open = false; query = ''; }
  }

  function handleInputKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      open = false;
      query = '';
      inputEl?.blur();
      return;
    }
    if (event.key === 'Tab') {
      if (open && filteredAccounts.length > 0) {
        selectHighlightedOrFirst();
      }
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      event.stopPropagation();
      if (filteredAccounts.length > 0) {
        selectHighlightedOrFirst();
      } else if (allowCreate && query.trim()) {
        requestCreate();
      }
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) { open = true; return; }
      const popoverEl = document.getElementById(listId);
      const items = popoverEl ? Array.from(popoverEl.querySelectorAll('[data-slot="command-item"]')) : [];
      if (items.length === 0) return;
      const current = items.findIndex((el) => el.getAttribute('aria-selected') === 'true');
      let next: number;
      if (event.key === 'ArrowDown') {
        next = current < items.length - 1 ? current + 1 : 0;
      } else {
        next = current > 0 ? current - 1 : items.length - 1;
      }
      items.forEach((el, i) => el.setAttribute('aria-selected', i === next ? 'true' : 'false'));
      items[next]?.scrollIntoView({ block: 'nearest' });
    }
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
    on:input={(e) => { query = e.currentTarget.value; if (!open) open = true; }}
    on:keydown={handleInputKeydown}
  />

  <Popover.Root bind:open onOpenChange={handleOpenChange}>
    <Popover.Trigger class="absolute inset-0 -z-10" tabindex={-1} aria-hidden="true">
      <span class="sr-only">anchor</span>
    </Popover.Trigger>
    <Popover.Content
      id={listId}
      class="w-(--bits-popover-anchor-width) max-w-[calc(100vw-2rem)] p-0"
      align="start"
      sideOffset={4}
    >
      <Command.Root shouldFilter={false}>
        <Command.List>
          {#if filteredAccounts.length === 0 && !allowCreate}
            <Command.Empty>No account found.</Command.Empty>
          {:else if filteredAccounts.length === 0 && allowCreate && query.trim()}
            <div class="p-1">
              <button
                type="button"
                class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
                on:pointerdown|preventDefault={() => requestCreate()}
              >
                <PlusIcon class="size-4" />
                Add "{query.trim()}"
              </button>
            </div>
          {:else}
            <Command.Group>
              {#each filteredAccounts as account (account)}
                <Command.Item
                  value={account}
                  onSelect={() => selectAccount(account)}
                >
                  <CheckIcon class={cn('size-4', value !== account && 'text-transparent')} />
                  <span class="truncate">{account}</span>
                </Command.Item>
              {/each}
            </Command.Group>
            {#if allowCreate}
              <div class="border-t p-1">
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
        </Command.List>
      </Command.Root>
    </Popover.Content>
  </Popover.Root>
</div>
