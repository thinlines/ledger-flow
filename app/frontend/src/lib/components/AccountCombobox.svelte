<script lang="ts">
  import CheckIcon from '@lucide/svelte/icons/check';
  import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
  import PlusIcon from '@lucide/svelte/icons/plus';
  import { tick } from 'svelte';
  import * as Command from '$lib/components/ui/command/index.js';
  import * as Popover from '$lib/components/ui/popover/index.js';
  import { cn } from '$lib/utils.js';

  export let accounts: string[] = [];
  export let value = '';
  export let placeholder = 'Select account...';
  export let disabled = false;
  export let onChange: (account: string) => void = () => {};
  export let onCreate: (seed: string) => void = () => {};

  let open = false;
  let query = '';
  let triggerRef: HTMLButtonElement | null = null;

  $: filteredAccounts = filterAccounts(query);
  $: selectedValue = value || '';
  $: if (!open) query = '';

  function filterAccounts(search: string): string[] {
    const normalized = search.trim().toLowerCase();
    if (!normalized) return accounts.slice(0, 50);
    return accounts.filter((account) => account.toLowerCase().includes(normalized)).slice(0, 50);
  }

  async function closeAndFocusTrigger() {
    open = false;
    await tick();
    triggerRef?.focus();
  }

  async function selectAccount(account: string) {
    value = account;
    onChange(account);
    query = '';
    await closeAndFocusTrigger();
  }

  async function requestCreate() {
    onCreate(query.trim());
    query = '';
    await closeAndFocusTrigger();
  }

  function handleInputKeydown(event: KeyboardEvent) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    event.stopPropagation();
    const topMatch = filteredAccounts[0];
    if (topMatch) {
      void selectAccount(topMatch);
      return;
    }
    void requestCreate();
  }

  function handleCreateButtonKeydown(event: KeyboardEvent) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    event.stopPropagation();
    void requestCreate();
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger
    bind:ref={triggerRef}
    disabled={disabled}
    class={cn(
      'flex w-full min-w-68 items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-left text-sm shadow-xs outline-hidden transition-[color,box-shadow] hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
      !selectedValue && 'text-muted-foreground'
    )}
    role="combobox"
    aria-expanded={open}
  >
    <span class="truncate">{selectedValue || placeholder}</span>
    <ChevronsUpDownIcon class="size-4 shrink-0 opacity-50" />
  </Popover.Trigger>

  <Popover.Content class="w-[22rem] p-0" align="start">
    <Command.Root shouldFilter={false}>
      <div role="presentation" on:keydown={handleInputKeydown}>
        <Command.Input bind:value={query} placeholder="Search account..." />
      </div>
      <Command.List>
        {#if filteredAccounts.length === 0}
          <Command.Empty>No account found.</Command.Empty>
        {:else}
          <Command.Group value="accounts">
            {#each filteredAccounts as account (account)}
              <Command.Item value={account} onSelect={() => void selectAccount(account)}>
                <CheckIcon class={cn('size-4', value !== account && 'text-transparent')} />
                <span class="truncate">{account}</span>
              </Command.Item>
            {/each}
          </Command.Group>
        {/if}

        <div class="border-t p-1">
          <button
            type="button"
            class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
            on:click={() => void requestCreate()}
            on:keydown={handleCreateButtonKeydown}
          >
            <PlusIcon class="size-4" />
            Add account
          </button>
        </div>
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
