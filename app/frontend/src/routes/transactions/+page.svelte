<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';

  type AppState = {
    initialized: boolean;
    workspaceName: string | null;
  };

  type TrackedAccount = {
    id: string;
    displayName: string;
    ledgerAccount: string;
    kind: string;
    institutionId: string | null;
    institutionDisplayName?: string | null;
    last4?: string | null;
    importConfigured: boolean;
    openingBalance?: string | null;
    openingBalanceDate?: string | null;
  };

  type RegisterEntry = {
    id: string;
    date: string;
    payee: string;
    summary: string;
    amount: number;
    runningBalance: number;
    isUnknown: boolean;
    isOpeningBalance: boolean;
    transferState?: string | null;
    detailLines: Array<{
      label: string;
      account: string;
      kind: string;
    }>;
  };

  type AccountRegister = {
    baseCurrency: string;
    accountId: string;
    currentBalance: number;
    entryCount: number;
    transactionCount: number;
    latestActivityDate: string | null;
    entries: RegisterEntry[];
  };

  let initialized = false;
  let workspaceName = '';
  let trackedAccounts: TrackedAccount[] = [];
  let selectedAccountId = '';
  let register: AccountRegister | null = null;
  let baseCurrency = 'USD';
  let error = '';
  let loading = true;
  let registerLoading = false;
  let postedEntries: RegisterEntry[] = [];
  let pendingEntries: RegisterEntry[] = [];
  let pendingTransferCount = 0;
  let pendingTransferTotal = 0;
  let balanceWithPending: number | null = null;
  let latestPostedActivityDate: string | null = null;

  function titleCase(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function countLabel(count: number, singular: string, plural = `${singular}s`): string {
    return `${count} ${count === 1 ? singular : plural}`;
  }

  function formatCurrency(
    value: number | null | undefined,
    options: { signed?: boolean } = {}
  ): string {
    if (value == null) return 'No balance yet';

    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: baseCurrency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
      signDisplay: options.signed ? 'always' : 'auto'
    }).format(value);
  }

  function formatStoredAmount(value: string | null | undefined): string {
    if (!value) return 'Not set';
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) return formatCurrency(parsed);
    return value;
  }

  function shortDate(value: string | null | undefined): string {
    if (!value) return 'No activity yet';
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    }).format(new Date(`${value}T00:00:00`));
  }

  async function loadRegister(accountId: string) {
    registerLoading = true;
    error = '';

    try {
      register = await apiGet<AccountRegister>(`/api/transactions/register?accountId=${encodeURIComponent(accountId)}`);
      baseCurrency = register.baseCurrency;
    } catch (e) {
      error = String(e);
      register = null;
    } finally {
      registerLoading = false;
    }
  }

  async function syncSelection(accountId: string, replaceState = false) {
    if (!accountId) return;
    if (accountId === selectedAccountId && register?.accountId === accountId) return;

    selectedAccountId = accountId;
    const params = new URLSearchParams($page.url.searchParams);
    params.set('accountId', accountId);
    await goto(`/transactions?${params.toString()}`, {
      replaceState,
      noScroll: true,
      keepFocus: true
    });
    await loadRegister(accountId);
  }

  async function load() {
    const state = await apiGet<AppState>('/api/app/state');
    initialized = state.initialized;
    workspaceName = state.workspaceName ?? '';
    if (!initialized) return;

    const accountsData = await apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts');
    trackedAccounts = accountsData.trackedAccounts;
    if (trackedAccounts.length === 0) return;

    const requestedAccountId = $page.url.searchParams.get('accountId') ?? '';
    const initialAccountId = trackedAccounts.some((account) => account.id === requestedAccountId)
      ? requestedAccountId
      : trackedAccounts[0].id;

    if (requestedAccountId !== initialAccountId) {
      await syncSelection(initialAccountId, true);
      return;
    }

    selectedAccountId = initialAccountId;
    await loadRegister(initialAccountId);
  }

  function handleAccountChange(event: Event) {
    const nextAccountId = (event.currentTarget as HTMLSelectElement).value;
    void syncSelection(nextAccountId);
  }

  $: selectedAccount = trackedAccounts.find((account) => account.id === selectedAccountId) ?? null;
  $: postedEntries = register?.entries.filter((entry) => entry.transferState !== 'pending') ?? [];
  $: pendingEntries = register?.entries.filter((entry) => entry.transferState === 'pending') ?? [];
  $: pendingTransferCount = pendingEntries.length;
  $: pendingTransferTotal = pendingEntries.reduce((sum, entry) => sum + entry.amount, 0);
  $: balanceWithPending = register ? register.currentBalance + pendingTransferTotal : null;
  $: latestPostedActivityDate = postedEntries[0]?.date ?? null;

  onMount(async () => {
    loading = true;
    error = '';
    try {
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  });
</script>

{#if error}
  <section class="view-card">
    <p class="error-text">{error}</p>
  </section>
{/if}

{#if loading}
  <section class="view-card transactions-hero">
    <p class="eyebrow">Transactions</p>
    <h2 class="page-title">Loading account register</h2>
    <p class="subtitle">Pulling together the latest account activity and running balances.</p>
  </section>
{:else if !initialized}
  <section class="view-card transactions-hero">
    <p class="eyebrow">Transactions</p>
    <h2 class="page-title">Create a workspace first</h2>
    <p class="subtitle">Transaction registers live inside a workspace. Finish setup before reviewing account activity.</p>
    <div class="actions">
      <a class="btn btn-primary" href="/setup">Open setup</a>
    </div>
  </section>
{:else if trackedAccounts.length === 0}
  <section class="view-card transactions-hero">
    <p class="eyebrow">Transactions</p>
    <h2 class="page-title">{workspaceName || 'Workspace'} does not have any accounts yet</h2>
    <p class="subtitle">Add at least one tracked account before reviewing its transaction register.</p>
    <div class="actions">
      <a class="btn btn-primary" href="/accounts/configure?mode=manual">Add first account</a>
      <a class="text-link" href="/accounts">Open accounts</a>
    </div>
  </section>
{:else}
  <section class="view-card transactions-hero">
    <div class="hero-copy">
      <p class="eyebrow">Transactions</p>
      <h2 class="page-title">{selectedAccount?.displayName || 'Account register'}</h2>
      <p class="subtitle">
        Reverse-chronological activity for this account. Running balances reflect each row in posted-date order and
        keep detail tucked behind expansion when you need it.
      </p>
      {#if selectedAccount?.openingBalance}
        <p class="supporting-note">
          Starting balance {formatStoredAmount(selectedAccount.openingBalance)}
          {#if selectedAccount.openingBalanceDate}
            on {shortDate(selectedAccount.openingBalanceDate)}
          {/if}
        </p>
      {/if}
    </div>

    <div class="hero-side">
      <div class="field">
        <label for="account-select">Account</label>
        <select id="account-select" bind:value={selectedAccountId} on:change={handleAccountChange}>
          {#each trackedAccounts as account}
            <option value={account.id}>{account.displayName}</option>
          {/each}
        </select>
      </div>

      <div class="hero-actions">
        <a class="text-link" href="/accounts">Back to accounts</a>
        {#if selectedAccount}
          <a class="text-link" href={`/accounts/configure?accountId=${selectedAccount.id}`}>Edit account</a>
        {/if}
      </div>
    </div>
  </section>

  <section class="summary-grid">
    <article class="view-card summary-card summary-balance-card">
      <p class="stat-label">Imported balance</p>
      <p class:positive={(register?.currentBalance ?? 0) > 0} class:negative={(register?.currentBalance ?? 0) < 0} class="stat-value">
        {formatCurrency(register?.currentBalance ?? null)}
      </p>
      <p class="stat-note">{selectedAccount?.institutionDisplayName || 'Tracked account'}{#if selectedAccount?.last4} •••• {selectedAccount.last4}{/if}</p>
    </article>

    <article class="view-card summary-card summary-balance-card summary-balance-pending">
      <p class="stat-label">Balance with pending</p>
      <p class:positive={(balanceWithPending ?? 0) > 0} class:negative={(balanceWithPending ?? 0) < 0} class="stat-value">
        {formatCurrency(balanceWithPending)}
      </p>
      <p class="stat-note">
        {#if pendingTransferCount > 0}
          {countLabel(pendingTransferCount, 'pending transfer')} worth {formatCurrency(pendingTransferTotal, { signed: true })} waiting to import.
        {:else}
          Matches imported balance when nothing is pending.
        {/if}
      </p>
    </article>

    <article class="view-card summary-card">
      <p class="stat-label">Pending transfers</p>
      <p class:positive={pendingTransferTotal > 0} class:negative={pendingTransferTotal < 0} class="stat-value">
        {pendingTransferCount > 0 ? formatCurrency(pendingTransferTotal, { signed: true }) : 'None'}
      </p>
      <p class="stat-note">
        {#if pendingTransferCount > 0}
          {countLabel(pendingTransferCount, 'transfer')} waiting to move into the imported register.
        {:else}
          No pending transfers for this account.
        {/if}
      </p>
    </article>

    <article class="view-card summary-card">
      <p class="stat-label">Latest imported</p>
      <p class="stat-value">{latestPostedActivityDate ? shortDate(latestPostedActivityDate) : 'No imports yet'}</p>
      <p class="stat-note">
        {#if latestPostedActivityDate}
          {titleCase(selectedAccount?.kind || 'account')} register.
        {:else if pendingTransferCount > 0}
          Pending transfers are above while imported activity is still empty.
        {:else}
          Imported activity will appear here after the first statement import.
        {/if}
      </p>
    </article>
  </section>

  {#if pendingTransferCount > 0}
    <section class="view-card pending-card">
      <div class="section-head">
        <div>
          <p class="eyebrow">Pending</p>
          <h3>Pending transfers</h3>
        </div>
        <p class="section-note">
          These affect <strong>Balance with pending</strong> above, but they do not change imported running balances
          until the matching transactions are imported.
        </p>
      </div>

      <div class="pending-balance-banner">
        <div>
          <p class="pending-banner-label">Balance with pending</p>
          <p class:positive={(balanceWithPending ?? 0) > 0} class:negative={(balanceWithPending ?? 0) < 0} class="pending-banner-value">
            {formatCurrency(balanceWithPending)}
          </p>
        </div>
        <p class="pending-banner-note">Imported balance remains {formatCurrency(register?.currentBalance ?? null)} until import completes.</p>
      </div>

      <div class="pending-header" aria-hidden="true">
        <span>Date</span>
        <span>Description</span>
        <span class="align-right">Amount</span>
        <span>Status</span>
      </div>

      <div class="pending-list">
        {#each pendingEntries as entry}
          <details class="pending-row">
            <summary class="pending-summary">
              <div class="register-cell register-date">{shortDate(entry.date)}</div>

              <div class="register-cell register-description">
                <p class="register-payee">{entry.payee}</p>
                <div class="register-meta">
                  <span>{entry.summary}</span>
                  {#if entry.isUnknown}
                    <span class="pill warn">Needs review</span>
                  {/if}
                  <span class="pill pending-pill">Pending</span>
                </div>
              </div>

              <div class="register-cell register-money align-right">
                <p class:positive={entry.amount > 0} class:negative={entry.amount < 0} class="money-value">
                  {formatCurrency(entry.amount, { signed: true })}
                </p>
              </div>

              <div class="register-cell pending-status">
                <p class="pending-status-title">Included in balance with pending</p>
                <p class="muted small">Waiting for import</p>
              </div>
            </summary>

            <div class="register-details">
              <p class="details-note pending-details-note">
                This transfer stays in the pending section until the imported transaction lands and replaces it in the
                register.
              </p>

              {#if entry.detailLines.length > 0}
                <div class="detail-lines">
                  {#each entry.detailLines as line}
                    <div class="detail-line">
                      <p>{line.label}</p>
                      <p class="muted small">{line.account}</p>
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          </details>
        {/each}
      </div>
    </section>
  {/if}

  <section class="view-card register-card">
    <div class="section-head">
      <div>
        <p class="eyebrow">Imported</p>
        <h3>Imported register</h3>
      </div>
      <p class="section-note">Only imported activity changes this running balance.</p>
    </div>

    {#if registerLoading}
      <div class="empty-panel">
        <h4>Loading transactions</h4>
        <p>Refreshing this account’s register.</p>
      </div>
    {:else if !register || postedEntries.length === 0}
      <div class="empty-panel">
        <h4>No imported activity yet</h4>
        <p>
          {#if pendingTransferCount > 0}
            Pending transfers are listed above. Imported transactions and opening-balance history will appear here after import.
          {:else}
            Once this account has imported transactions or an opening balance, the register will appear here.
          {/if}
        </p>
      </div>
    {:else}
      <div class="register-header" aria-hidden="true">
        <span>Date</span>
        <span>Description</span>
        <span class="align-right">Amount</span>
        <span class="align-right">Balance</span>
      </div>

      <div class="register-list">
        {#each postedEntries as entry}
          <details class:opening-row={entry.isOpeningBalance} class="register-row">
            <summary class="register-summary">
              <div class="register-cell register-date">{shortDate(entry.date)}</div>

              <div class="register-cell register-description">
                <p class="register-payee">{entry.payee}</p>
                <div class="register-meta">
                  <span>{entry.summary}</span>
                  {#if entry.isUnknown}
                    <span class="pill warn">Needs review</span>
                  {/if}
                  {#if entry.isOpeningBalance}
                    <span class="pill">Starting balance</span>
                  {/if}
                </div>
              </div>

              <div class="register-cell register-money align-right">
                <p class:positive={entry.amount > 0} class:negative={entry.amount < 0} class="money-value">
                  {formatCurrency(entry.amount, { signed: true })}
                </p>
              </div>

              <div class="register-cell register-money align-right">
                <p class:positive={entry.runningBalance > 0} class:negative={entry.runningBalance < 0} class="money-value">
                  {formatCurrency(entry.runningBalance)}
                </p>
              </div>
            </summary>

            <div class="register-details">
              {#if entry.isOpeningBalance}
                <p class="details-note">This entry anchors running balances for the account until more history is backfilled.</p>
              {/if}

              {#if entry.detailLines.length > 0}
                <div class="detail-lines">
                  {#each entry.detailLines as line}
                    <div class="detail-line">
                      <p>{line.label}</p>
                      <p class="muted small">{line.account}</p>
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          </details>
        {/each}
      </div>
    {/if}
  </section>
{/if}

<style>
  h3,
  h4,
  p {
    margin: 0;
  }

  .transactions-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.5fr) minmax(18rem, 0.9fr);
    gap: 1.2rem;
    align-items: start;
    background:
      radial-gradient(circle at top left, rgba(214, 235, 220, 0.86), transparent 34%),
      linear-gradient(155deg, #fbfdf8 0%, #f6fbff 60%, #eef6f3 100%);
  }

  .hero-copy {
    display: grid;
    gap: 0.7rem;
  }

  .supporting-note {
    color: var(--muted-foreground);
    font-size: 0.92rem;
  }

  .hero-side {
    display: grid;
    gap: 0.85rem;
    padding: 1rem;
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.72);
    border: 1px solid rgba(10, 61, 89, 0.08);
  }

  .hero-actions,
  .actions {
    display: flex;
    gap: 0.7rem;
    flex-wrap: wrap;
  }

  .text-link {
    color: var(--brand-strong);
    text-decoration: none;
    font-weight: 700;
  }

  .text-link:hover {
    text-decoration: underline;
  }

  .summary-grid {
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  }

  .summary-card {
    display: grid;
    gap: 0.35rem;
  }

  .summary-balance-card {
    background:
      linear-gradient(160deg, rgba(250, 252, 255, 0.95), rgba(243, 248, 252, 0.9)),
      rgba(255, 255, 255, 0.86);
  }

  .summary-balance-pending {
    border-color: rgba(15, 95, 136, 0.18);
    background:
      radial-gradient(circle at top right, rgba(214, 235, 220, 0.78), transparent 42%),
      linear-gradient(155deg, rgba(250, 253, 248, 0.98), rgba(241, 247, 255, 0.96));
  }

  .stat-label {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .stat-value {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.55rem;
    line-height: 1;
  }

  .stat-note,
  .section-note {
    color: var(--muted-foreground);
    font-size: 0.9rem;
  }

  .positive {
    color: var(--ok);
  }

  .negative {
    color: var(--bad);
  }

  .section-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .pending-card {
    background:
      radial-gradient(circle at top right, rgba(214, 235, 220, 0.68), transparent 36%),
      linear-gradient(155deg, rgba(252, 252, 247, 0.98), rgba(247, 250, 255, 0.96));
  }

  .pending-balance-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
    padding: 0.95rem 1rem;
    border-radius: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.72);
  }

  .pending-banner-label {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .pending-banner-value {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.5rem;
    line-height: 1.05;
    margin-top: 0.2rem;
  }

  .pending-banner-note {
    max-width: 26rem;
    color: var(--muted-foreground);
    font-size: 0.9rem;
  }

  .register-card {
    overflow: hidden;
  }

  .register-header,
  .register-summary,
  .pending-header,
  .pending-summary {
    display: grid;
    grid-template-columns: minmax(7.5rem, 0.75fr) minmax(0, 2fr) minmax(7.5rem, 0.75fr) minmax(8rem, 0.85fr);
    gap: 1rem;
    align-items: center;
  }

  .register-header,
  .pending-header {
    padding: 0 1rem 0.75rem;
    border-bottom: 1px solid rgba(10, 61, 89, 0.08);
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted-foreground);
  }

  .register-list {
    display: grid;
  }

  .pending-list {
    display: grid;
    gap: 0.8rem;
  }

  .register-row {
    border-bottom: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.35);
  }

  .pending-row {
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.62);
    overflow: hidden;
  }

  .register-row:last-child {
    border-bottom: none;
  }

  .register-row[open] {
    background: rgba(244, 249, 255, 0.72);
  }

  .opening-row {
    background: rgba(247, 249, 245, 0.78);
  }

  .register-summary,
  .pending-summary {
    padding: 0.95rem 1rem;
    cursor: pointer;
    list-style: none;
  }

  .register-summary::-webkit-details-marker,
  .pending-summary::-webkit-details-marker {
    display: none;
  }

  .register-description {
    min-width: 0;
  }

  .register-payee {
    font-weight: 700;
  }

  .register-meta {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-top: 0.3rem;
    color: var(--muted-foreground);
    font-size: 0.92rem;
  }

  .pending-pill {
    color: var(--warn);
    border-color: #f3cf96;
    background: #fff7ea;
  }

  .money-value {
    font-weight: 700;
  }

  .align-right {
    text-align: right;
  }

  .pending-status {
    display: grid;
    gap: 0.15rem;
  }

  .pending-status-title {
    font-size: 0.84rem;
    font-weight: 700;
    color: var(--brand-strong);
  }

  .register-details {
    padding: 0 1rem 1rem;
    display: grid;
    gap: 0.75rem;
  }

  .details-note {
    color: var(--muted-foreground);
    font-size: 0.92rem;
  }

  .pending-details-note {
    color: #7d5200;
  }

  .detail-lines {
    display: grid;
    gap: 0.6rem;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  }

  .detail-line {
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 0.9rem;
    padding: 0.7rem 0.8rem;
    background: rgba(255, 255, 255, 0.62);
  }

  .small {
    font-size: 0.84rem;
  }

  .empty-panel {
    border: 1px dashed rgba(10, 61, 89, 0.18);
    border-radius: 1rem;
    padding: 1rem;
    background: rgba(255, 255, 255, 0.52);
  }

  @media (max-width: 980px) {
    .transactions-hero,
    .summary-grid {
      grid-template-columns: 1fr;
    }

    .section-head {
      flex-direction: column;
    }

    .pending-balance-banner {
      flex-direction: column;
      align-items: flex-start;
    }
  }

  @media (max-width: 820px) {
    .register-header,
    .pending-header {
      display: none;
    }

    .register-summary,
    .pending-summary {
      grid-template-columns: 1fr;
      gap: 0.45rem;
    }

    .register-date {
      font-size: 0.88rem;
      color: var(--muted-foreground);
    }

    .register-money {
      text-align: left;
    }

    .pending-status {
      text-align: left;
    }

    .align-right {
      text-align: left;
    }
  }
</style>
