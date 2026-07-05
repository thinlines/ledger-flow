<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import {
    canClose,
    canReopen,
    deleteDisabledCopy,
    leafName,
    lifecycleBadges,
    type ManagedAccount
  } from '$lib/account-lifecycle';

  let accounts: ManagedAccount[] = [];
  let loading = true;
  let error = '';
  let busyAccount: string | null = null;
  let showClosed = true;

  export async function reload() {
    try {
      const payload = await apiGet<{ accounts: ManagedAccount[] }>('/api/accounts/manage');
      accounts = payload.accounts;
      error = '';
    } catch (e) {
      error = String(e);
    }
  }

  $: visibleAccounts = showClosed
    ? accounts
    : accounts.filter((account) => !account.closedOn);

  async function run(account: ManagedAccount, action: () => Promise<unknown>) {
    busyAccount = account.name;
    error = '';
    try {
      await action();
      await reload();
    } catch (e) {
      error = String(e);
    } finally {
      busyAccount = null;
    }
  }

  function closeAccount(account: ManagedAccount) {
    void run(account, () => apiPost('/api/accounts/close', { account: account.name }));
  }

  function reopenAccount(account: ManagedAccount) {
    void run(account, () => apiPost('/api/accounts/reopen', { account: account.name }));
  }

  function removeAccount(account: ManagedAccount) {
    const confirmed = window.confirm(
      `Remove the declaration for ${account.name}? The account disappears from pickers; it can be declared again later.`
    );
    if (!confirmed) return;
    void run(account, () => apiPost('/api/accounts/delete', { account: account.name }));
  }

  onMount(async () => {
    loading = true;
    await reload();
    loading = false;
  });
</script>

<article class="view-card grid gap-4">
  <div class="flex items-start justify-between gap-4">
    <div>
      <p class="eyebrow">Ledger accounts</p>
      <h3 class="m-0">Every account in your books</h3>
      <p class="muted">
        Close accounts you no longer use to hide them from entry pickers — history and reports keep them.
        Deleting is only possible when nothing references the account.
      </p>
    </div>
    <label class="flex items-center gap-2 text-sm text-muted-foreground whitespace-nowrap">
      <input type="checkbox" bind:checked={showClosed} />
      <span>Show closed</span>
    </label>
  </div>

  {#if error}
    <p class="error-text m-0">{error}</p>
  {/if}

  {#if loading}
    <p class="muted m-0">Loading ledger accounts…</p>
  {:else if visibleAccounts.length === 0}
    <p class="muted m-0">No accounts projected yet. Add an account or import a statement first.</p>
  {:else}
    <div class="account-tree max-h-[28rem] overflow-y-auto rounded-2xl border border-card-edge">
      {#each visibleAccounts as account (account.name)}
        <div
          class="account-row flex items-center gap-3 px-3.5 py-2"
          class:closed={Boolean(account.closedOn)}
          style={`padding-left: ${0.9 + account.depth * 1.1}rem`}
        >
          <div class="min-w-0 flex-1">
            <div class="flex items-baseline gap-2 min-w-0">
              <span class="font-semibold truncate" title={account.name}>{leafName(account.name)}</span>
              {#each lifecycleBadges(account) as badge (badge.label)}
                <span class={`pill lifecycle-pill ${badge.tone}`}>{badge.label}</span>
              {/each}
            </div>
            {#if account.note}
              <p class="muted m-0 text-sm truncate" title={account.note}>{account.note}</p>
            {/if}
          </div>

          <span class="text-sm text-muted-foreground whitespace-nowrap">
            {account.postingCount === 1 ? '1 posting' : `${account.postingCount} postings`}
          </span>

          <div class="flex items-center gap-2">
            {#if canReopen(account)}
              <button
                class="btn btn-small"
                type="button"
                disabled={busyAccount === account.name}
                on:click={() => reopenAccount(account)}
              >
                Reopen
              </button>
            {:else if canClose(account)}
              <button
                class="btn btn-small"
                type="button"
                disabled={busyAccount === account.name}
                on:click={() => closeAccount(account)}
              >
                Close
              </button>
            {/if}
            <button
              class="btn btn-small danger"
              type="button"
              disabled={!account.deletable || busyAccount === account.name}
              title={deleteDisabledCopy(account) ?? `Remove the declaration for ${account.name}`}
              on:click={() => removeAccount(account)}
            >
              Delete
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</article>

<style>
  /* Row separators inside the tree list — sibling separator case */
  .account-row + .account-row {
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .account-row.closed {
    opacity: 0.62;
  }

  /* Compact action buttons scoped to this dense list */
  .btn.btn-small {
    padding: 0.3rem 0.7rem;
    font-size: 0.82rem;
  }

  .btn.btn-small.danger:not(:disabled) {
    color: #9a2929;
    border-color: rgba(154, 41, 41, 0.28);
  }

  .btn.btn-small:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  /* Lifecycle badge tones — bespoke rgba colors matching subtype pills */
  .lifecycle-pill.closed {
    background: rgba(154, 81, 41, 0.12);
    color: #9a5129;
    border-color: rgba(154, 81, 41, 0.18);
  }

  .lifecycle-pill.subtype {
    background: rgba(15, 95, 136, 0.08);
    color: var(--brand-strong);
    border-color: rgba(15, 95, 136, 0.14);
  }

  .lifecycle-pill.auto {
    background: rgba(10, 61, 89, 0.06);
    color: var(--muted-foreground);
    border-color: rgba(10, 61, 89, 0.1);
  }
</style>
