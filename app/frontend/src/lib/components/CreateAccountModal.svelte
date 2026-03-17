<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';

  export let open = false;
  export let accountName = '';
  export let accountType = 'Expense';
  export let accountDescription = '';
  export let error = '';
  export let loading = false;
  export let description = 'Enter a fully qualified account name.';
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
    <DialogPrimitive.Overlay class="create-account-modal-backdrop" />

    <DialogPrimitive.Content
      class="create-account-modal"
      aria-labelledby="create-account-title"
      aria-describedby="create-account-description"
      onOpenAutoFocus={handleOpenAutoFocus}
    >
      <h3 id="create-account-title">Create New Account</h3>
      <p id="create-account-description" class="muted">{description}</p>

      <div class="field">
        <label for="newAccountName">Account Name</label>
        <input
          id="newAccountName"
          bind:this={inputEl}
          bind:value={accountName}
          placeholder="Assets:Transfers"
          on:input={handleNameInput}
          on:keydown={handleEnterKey}
        />
      </div>

      <div class="field">
        <label for="newAccountType">Account Type</label>
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
        <p class="muted small">Optional. Saved to `10-accounts.dat` as `; description: ...`.</p>
      </div>

      {#if error}
        <p class="error-text">{error}</p>
      {/if}

      <div class="modal-actions">
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

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  :global(.create-account-modal-backdrop) {
    position: fixed;
    inset: 0;
    background: rgba(10, 20, 30, 0.35);
    z-index: 30;
  }

  :global(.create-account-modal) {
    width: min(620px, calc(100vw - 2rem));
    max-height: calc(100vh - 2rem);
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 1rem;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    overflow: auto;
    z-index: 31;
  }

  .modal-actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }
</style>
