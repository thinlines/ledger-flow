<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import { splitAccountSeed } from '$lib/account-create';
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';
  import CreateAccountModal from '$lib/components/CreateAccountModal.svelte';

  export let selectedAccountId: string;
  export let allAccounts: string[];
  export let onCancel: () => void = () => {};
  export let onSuccess: (result: {
    payee: string;
    date: string;
    eventId: string | null;
  }) => void = () => {};
  export let onAccountsChanged: (accounts: string[]) => void = () => {};

  let addDate = '';
  let addPayee = '';
  let addAmount = '';
  let addDestination = '';
  let addError = '';
  let addSubmitting = false;
  let addDateEl: HTMLInputElement | null = null;

  /* ── Create-account modal state ── */
  let showCreateModal = false;
  let newAccountParent = '';
  let newAccountLeaf = '';
  let newAccountDescription = '';
  let createError = '';
  let createLoading = false;

  function openCreateModal(seed: string) {
    ({ parent: newAccountParent, leaf: newAccountLeaf } = splitAccountSeed(seed));
    newAccountDescription = '';
    createError = '';
    showCreateModal = true;
  }

  function closeCreateModal() {
    createError = '';
    showCreateModal = false;
  }

  async function createAccountAndSelect() {
    createLoading = true;
    createError = '';
    try {
      const result = await apiPost<{ added: boolean; warning: string | null; account: string }>(
        '/api/accounts',
        {
          parent: newAccountParent,
          leaf: newAccountLeaf,
          description: newAccountDescription
        }
      );
      if (result.warning) {
        createError = result.warning;
        return;
      }
      const refreshed = await apiGet<{ allAccounts: string[] }>('/api/accounts');
      allAccounts = refreshed.allAccounts;
      onAccountsChanged(allAccounts);
      addDestination = result.account;
      showCreateModal = false;
    } catch (e) {
      createError = String(e);
    } finally {
      createLoading = false;
    }
  }

  function todayISO(): string {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }

  onMount(() => {
    addDate = todayISO();
    setTimeout(() => addDateEl?.focus(), 50);
  });

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onCancel();
    }
  }

  async function submit() {
    if (!selectedAccountId || !addDate || !addPayee.trim() || !addAmount.trim() || !addDestination.trim()) {
      addError = 'All fields are required.';
      return;
    }
    addError = '';
    addSubmitting = true;
    try {
      const result = await apiPost<{ created: boolean; eventId?: string | null }>(
        '/api/transactions/create',
        {
          trackedAccountId: selectedAccountId,
          date: addDate,
          payee: addPayee.trim(),
          amount: addAmount.trim(),
          destinationAccount: addDestination.trim()
        }
      );
      onSuccess({
        payee: addPayee.trim(),
        date: addDate,
        eventId: result.eventId ?? null
      });
    } catch (e) {
      addError = String(e);
    } finally {
      addSubmitting = false;
    }
  }
</script>

<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
<section class="view-card add-txn-card" role="form" on:keydown={handleKeydown}>
  <div class="section-head">
    <div>
      <p class="eyebrow">New Transaction</p>
      <h3>Add a manual entry</h3>
    </div>
    <button class="btn" type="button" on:click={onCancel}>Cancel</button>
  </div>

  <div class="add-txn-fields">
    <div class="field">
      <label for="add-date">Date</label>
      <input
        id="add-date"
        type="date"
        bind:this={addDateEl}
        bind:value={addDate}
      />
    </div>

    <div class="field">
      <label for="add-payee">Payee</label>
      <input
        id="add-payee"
        type="text"
        bind:value={addPayee}
        placeholder="e.g. Coffee Shop"
      />
    </div>

    <div class="field">
      <label for="add-amount">Amount</label>
      <input
        id="add-amount"
        type="text"
        inputmode="decimal"
        bind:value={addAmount}
        placeholder="e.g. 45.95"
      />
    </div>

    <div class="field">
      <label for="add-destination">Destination account</label>
      <AccountCombobox
        accounts={allAccounts}
        value={addDestination}
        placeholder="e.g. Expenses:Food"
        onChange={(account) => (addDestination = account)}
        onCreate={(seed) => openCreateModal(seed)}
      />
    </div>
  </div>

  {#if addError}
    <p class="error-text">{addError}</p>
  {/if}

  <div class="add-txn-actions">
    <button
      class="btn btn-primary"
      type="button"
      disabled={addSubmitting}
      on:click={() => void submit()}
    >
      {addSubmitting ? 'Saving...' : 'Save transaction'}
    </button>
  </div>
</section>

<CreateAccountModal
  bind:open={showCreateModal}
  bind:parent={newAccountParent}
  bind:leaf={newAccountLeaf}
  bind:accountDescription={newAccountDescription}
  parentAccounts={allAccounts}
  error={createError}
  loading={createLoading}
  onClose={closeCreateModal}
  onSubmit={createAccountAndSelect}
/>

<style>
  .add-txn-card {
    display: grid;
    gap: 1rem;
  }

  .add-txn-fields {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
    gap: 0.85rem;
  }

  .add-txn-actions {
    display: flex;
    gap: 0.7rem;
    justify-content: flex-end;
  }
</style>
