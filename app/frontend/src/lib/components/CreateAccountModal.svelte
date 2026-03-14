<script lang="ts">
  import { onMount, tick } from 'svelte';

  export let accountName = '';
  export let accountType = 'Expense';
  export let error = '';
  export let loading = false;
  export let onNameInput: () => void = () => {};
  export let onClose: () => void = () => {};
  export let onSubmit: () => void | Promise<void> = () => {};

  let inputEl: HTMLInputElement | null = null;

  onMount(async () => {
    await tick();
    inputEl?.focus();
    inputEl?.select();
  });

  function handleBackdropClick(event: MouseEvent) {
    if (event.target !== event.currentTarget) return;
    onClose();
  }

  function handleBackdropKeydown(event: KeyboardEvent) {
    if (event.key !== 'Escape') return;
    onClose();
  }

  function handleEnterKey(event: KeyboardEvent) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    void onSubmit();
  }

  function handleNameInput() {
    onNameInput();
  }
</script>

<div
  class="modal-backdrop"
  role="button"
  aria-label="Close dialog"
  tabindex="0"
  on:click={handleBackdropClick}
  on:keydown={handleBackdropKeydown}
>
  <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label="Create Account">
    <h3>Create New Account</h3>
    <p class="muted">Enter a fully qualified account name.</p>

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
        <option value="Asset">Asset</option>
        <option value="Cash">Cash</option>
        <option value="Liability">Liability</option>
        <option value="Expense">Expense</option>
        <option value="Revenue">Revenue</option>
        <option value="Equity">Equity</option>
      </select>
    </div>

    {#if error}
      <p class="error-text">{error}</p>
    {/if}

    <div class="modal-actions">
      <button class="btn" on:click={onClose}>Cancel</button>
      <button class="btn btn-primary" disabled={loading || !accountName || !accountType} on:click={() => void onSubmit()}>
        Create Account
      </button>
    </div>
  </div>
</div>

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(10, 20, 30, 0.35);
    display: grid;
    place-items: center;
    padding: 1rem;
    z-index: 30;
  }

  .modal {
    width: min(620px, 100%);
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 1rem;
  }

  .modal-actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }
</style>
