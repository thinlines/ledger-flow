<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';
  import { validateNewAccount } from '$lib/account-create';

  export let open = false;
  export let title = 'Create New Account';
  export let parentAccounts: string[] = [];
  export let parent = '';
  export let leaf = '';
  export let accountDescription = '';
  export let error = '';
  export let loading = false;
  export let description = 'Pick where the account belongs, then name it.';
  export let parentLabel = 'Parent account';
  export let leafLabel = 'New account name';
  export let leafPlaceholder = 'e.g. Dining';
  export let submitLabel = 'Create Account';
  export let onClose: () => void = () => {};
  export let onSubmit: () => void | Promise<void> = () => {};

  let leafEl: HTMLInputElement | null = null;

  $: validationError = validateNewAccount(parent, leaf);
  $: showLeafHint = leaf.includes(':');

  function handleEnterKey(event: KeyboardEvent) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    if (!validationError) void onSubmit();
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) onClose();
  }

  function handleOpenAutoFocus(event: Event) {
    event.preventDefault();
    leafEl?.focus();
    leafEl?.select();
  }
</script>

<DialogPrimitive.Root bind:open onOpenChange={handleOpenChange}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="fixed inset-0 z-30 bg-black/35" />

    <DialogPrimitive.Content
      class="fixed top-1/2 left-1/2 z-40 w-[620px] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border border-line bg-white p-4 shadow-card"
      aria-labelledby="create-account-title"
      aria-describedby="create-account-description"
      onOpenAutoFocus={handleOpenAutoFocus}
    >
      <h3 id="create-account-title" class="mx-0 mt-0.5 mb-3">{title}</h3>
      <p id="create-account-description" class="muted">{description}</p>

      <div class="field">
        <label for="newAccountParent">{parentLabel}</label>
        <AccountCombobox
          accounts={parentAccounts}
          bind:value={parent}
          placeholder="Select parent account..."
          allowCreate={false}
        />
      </div>

      <div class="field">
        <label for="newAccountLeaf">{leafLabel}</label>
        <input
          id="newAccountLeaf"
          bind:this={leafEl}
          bind:value={leaf}
          placeholder={leafPlaceholder}
          on:keydown={handleEnterKey}
        />
        {#if showLeafHint}
          <p class="error-text">{validateNewAccount(parent || 'x', leaf)}</p>
        {/if}
      </div>

      <div class="field">
        <label for="newAccountDescription">Description</label>
        <input
          id="newAccountDescription"
          bind:value={accountDescription}
          placeholder="Optional note about what this account is for"
          on:keydown={handleEnterKey}
        />
      </div>

      {#if error}
        <p class="error-text">{error}</p>
      {/if}

      <div class="flex flex-wrap gap-2.5">
        <button class="btn" type="button" on:click={onClose}>Cancel</button>
        <button
          class="btn btn-primary"
          type="button"
          disabled={loading || validationError !== null}
          on:click={() => void onSubmit()}
        >
          {submitLabel}
        </button>
      </div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>
