<script lang="ts">
  import { goto } from '$app/navigation';
  import type { AccountMeta, TrackedAccount } from '$lib/transactions/types';
  import { describeBalanceTrust } from '$lib/account-trust';
  import { formatCurrency, countLabel, shortDate } from '$lib/format';

  // Single-account-only supplementary strip. Renders below the unified
  // dossier when exactly one account is filtered. Owns the data the dossier
  // doesn't (balance, coverage trust, latest activity, reconcile entry-point)
  // so the dossier shape stays the same regardless of mode.
  export let account: TrackedAccount;
  export let meta: AccountMeta;
  export let baseCurrency: string;
  export let pendingCount: number;
  export let pendingTotal: number;
  export let onAddTransaction: () => void;

  function trustNote() {
    return describeBalanceTrust({
      hasOpeningBalance: meta.hasOpeningBalance,
      hasTransactionActivity: meta.hasTransactionActivity,
      hasBalanceSource: meta.hasBalanceSource,
      importConfigured: account.importConfigured,
      openingBalanceDate: account.openingBalanceDate,
      latestActivityDate: meta.latestActivityDate,
    });
  }

  $: curBal = meta.currentBalance ?? null;
  $: balPending = curBal !== null ? curBal + pendingTotal : null;
  $: trust = trustNote();

  function openReconcile() {
    void goto(`/accounts/${encodeURIComponent(account.id)}/reconcile`);
  }
</script>

<section class="account-strip">
  <div class="strip-grid">
    <article class="strip-card">
      <p class="strip-eyebrow">Current balance</p>
      <p class="strip-amount" class:positive={(curBal ?? 0) > 0} class:negative={(curBal ?? 0) < 0}>
        {formatCurrency(curBal, baseCurrency)}
      </p>
      <p class="strip-meta">
        {account.institutionDisplayName || 'Tracked account'}{#if account.last4} · {account.last4}{/if}
      </p>
    </article>

    <article class="strip-card">
      <p class="strip-eyebrow">With pending</p>
      <p class="strip-amount" class:positive={(balPending ?? 0) > 0} class:negative={(balPending ?? 0) < 0}>
        {formatCurrency(balPending, baseCurrency)}
      </p>
      <p class="strip-meta">
        {#if pendingCount > 0}{countLabel(pendingCount, 'pending transfer')} worth {formatCurrency(pendingTotal, baseCurrency, { signed: true })}{:else}Matches current balance{/if}
      </p>
    </article>

    <article class="strip-card">
      <p class="strip-eyebrow">Balance coverage</p>
      <p class="strip-status">{trust?.label || 'No balance yet'}</p>
      <p class="strip-meta">{trust?.note || 'Add activity or a starting balance.'}</p>
    </article>

    <article class="strip-card">
      <p class="strip-eyebrow">Latest activity</p>
      <p class="strip-status">{meta.latestTransactionDate ? shortDate(meta.latestTransactionDate) : 'No activity yet'}</p>
      <p class="strip-meta">
        {meta.latestTransactionDate ? `${meta.transactionCount} posted ${meta.transactionCount === 1 ? 'entry' : 'entries'}` : 'Posted activity will appear after first import.'}
      </p>
    </article>

    <article class="strip-card strip-actions">
      <button class="btn btn-primary strip-btn" type="button" on:click={openReconcile}>Reconcile</button>
      <button class="btn strip-btn" type="button" on:click={onAddTransaction}>Add transaction</button>
      <a class="text-link strip-link" href="/accounts">Manage accounts</a>
    </article>
  </div>
</section>

<style>
  .account-strip {
    border-radius: 1.15rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.62);
    padding: 0.85rem;
    box-shadow: 0 8px 22px -16px rgba(10, 61, 89, 0.25);
  }
  .strip-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr)) auto;
    gap: 0.85rem;
    align-items: stretch;
  }
  @media (max-width: 1100px) {
    .strip-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .strip-actions { grid-column: 1 / -1; }
  }
  @media (max-width: 540px) {
    .strip-grid { grid-template-columns: 1fr; }
  }

  .strip-card {
    display: grid;
    gap: 0.2rem;
    padding: 0.75rem 0.95rem;
    border-radius: 0.85rem;
    background: rgba(255, 255, 255, 0.85);
    border: 1px solid rgba(10, 61, 89, 0.06);
  }
  .strip-eyebrow {
    margin: 0;
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: rgba(10, 61, 89, 0.55);
  }
  .strip-amount {
    margin: 0;
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: 1.4rem;
    line-height: 1.05;
    color: var(--brand-strong);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
  }
  .strip-status {
    margin: 0;
    font-family: var(--font-display, 'Space Grotesk', sans-serif);
    font-size: 1rem;
    color: var(--brand-strong);
  }
  .strip-meta {
    margin: 0;
    font-size: 0.74rem;
    color: rgba(10, 61, 89, 0.55);
    line-height: 1.3;
  }
  .positive { color: var(--ok); }
  .negative { color: var(--bad); }

  .strip-actions {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 0.4rem;
    background: linear-gradient(165deg, rgba(255, 255, 255, 0.95), rgba(243, 248, 251, 0.95));
  }
  .strip-btn {
    width: 100%;
    padding: 0.45rem 0.85rem;
    font-size: 0.84rem;
    text-align: center;
  }
  .strip-link {
    text-align: center;
    font-size: 0.78rem;
  }
</style>
