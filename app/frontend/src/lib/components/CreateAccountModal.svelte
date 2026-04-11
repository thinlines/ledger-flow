<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';

  export let open = false;
  export let title = 'Create New Account';
  export let accountName = '';
  export let accountType = 'Expense';
  export let accountDescription = '';
  export let error = '';
  export let loading = false;
  export let description = 'Enter a fully qualified account name.';
  export let accountNamePlaceholder = 'Assets:Transfers';
  export let accountTypeLabel = 'Account Type';
  export let submitLabel = 'Create Account';
  export let allowedAccountTypes = ['Asset', 'Cash', 'Liability', 'Expense', 'Revenue', 'Equity'];
  export let onNameInput: () => void = () => {};
  export let onClose: () => void = () => {};
  export let onSubmit: () => void | Promise<void> = () => {};

  let inputEl: HTMLInputElement | null = null;

  function handleEnterKey(event: KeyboardEvent) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    void onSubmit();
  }

  function handleNameInput() {
    onNameInput();
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) onClose();
  }

  function handleOpenAutoFocus(event: Event) {
    event.preventDefault();
    inputEl?.focus();
    inputEl?.select();
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
        <label for="newAccountName">Account Name</label>
        <input
          id="newAccountName"
          bind:this={inputEl}
          bind:value={accountName}
          placeholder={accountNamePlaceholder}
          on:input={handleNameInput}
          on:keydown={handleEnterKey}
        />
      </div>

      <div class="field">
        <label for="newAccountType">{accountTypeLabel}</label>
        <select id="newAccountType" bind:value={accountType}>
          {#each allowedAccountTypes as optionType (optionType)}
            <option value={optionType}>{optionType}</option>
          {/each}
        </select>
      </div>

      <div class="field">
        <label for="newAccountDescription">Description</label>
        <input
          id="newAccountDescription"
          bind:value={accountDescription}
          placeholder="Optional account note"
          on:keydown={handleEnterKey}
        />
        <p class="muted">Optional. Saved to `10-accounts.dat` as `; description: ...`.</p>
      </div>

      {#if error}
        <p class="error-text">{error}</p>
      {/if}

      <div class="flex flex-wrap gap-2.5">
        <button class="btn" type="button" on:click={onClose}>Cancel</button>
        <button
          class="btn btn-primary"
          type="button"
          disabled={loading || !accountName || !accountType}
          on:click={() => void onSubmit()}
        >
          {submitLabel}
        </button>
      </div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>
