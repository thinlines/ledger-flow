<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';

  type AppState = {
    initialized: boolean;
    workspaceName: string | null;
  };

  type InstitutionTemplate = {
    id: string;
    displayName: string;
  };

  type CustomImportProfile = {
    displayName?: string | null;
    encoding?: string | null;
    delimiter?: string | null;
    skipRows?: number;
    skipFooterRows?: number;
    reverseOrder?: boolean;
    dateColumn?: string | null;
    dateFormat?: string | null;
    descriptionColumn?: string | null;
    secondaryDescriptionColumn?: string | null;
    amountMode?: 'signed' | 'debit_credit';
    amountColumn?: string | null;
    debitColumn?: string | null;
    creditColumn?: string | null;
    balanceColumn?: string | null;
    codeColumn?: string | null;
    noteColumn?: string | null;
    currency?: string | null;
  };

  type TrackedAccount = {
    id: string;
    displayName: string;
    ledgerAccount: string;
    kind: string;
    institutionId: string | null;
    institutionDisplayName?: string | null;
    last4?: string | null;
    importAccountId?: string | null;
    importConfigured: boolean;
    importMode?: 'institution' | 'custom' | null;
    importProfile?: CustomImportProfile | null;
    openingBalance?: string | null;
    openingBalanceDate?: string | null;
  };

  type DashboardOverview = {
    baseCurrency: string;
    balances: Array<{
      id: string;
      balance: number;
    }>;
  };

  let initialized = false;
  let workspaceName = '';
  let trackedAccounts: TrackedAccount[] = [];
  let institutionTemplates: InstitutionTemplate[] = [];
  let dashboardBalances: Record<string, number> = {};
  let baseCurrency = 'USD';
  let error = '';
  let loading = true;

  function titleCase(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function formatCurrency(value: number | null | undefined): string {
    if (value == null) return 'No balance yet';
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: baseCurrency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  }

  function currentBalance(accountId: string): number | null {
    return dashboardBalances[accountId] ?? null;
  }

  function modeLabel(account: TrackedAccount): string {
    if (!account.importConfigured) return 'Manual';
    return account.importMode === 'custom' ? 'Custom CSV' : 'Import-enabled';
  }

  function customProfileSummary(account: TrackedAccount): string {
    if (account.importMode !== 'custom' || !account.importProfile) return '';
    const amountMode = account.importProfile.amountMode === 'debit_credit' ? 'Debit / credit' : 'Signed amount';
    return `${account.importProfile.displayName || 'Custom profile'} · ${amountMode}`;
  }

  async function load() {
    const state = await apiGet<AppState>('/api/app/state');
    initialized = state.initialized;
    workspaceName = state.workspaceName ?? '';
    if (!initialized) return;

    const [accountsData, dashboardData] = await Promise.all([
      apiGet<{ trackedAccounts: TrackedAccount[]; institutionTemplates: InstitutionTemplate[] }>('/api/tracked-accounts'),
      apiGet<DashboardOverview>('/api/dashboard/overview')
    ]);

    trackedAccounts = accountsData.trackedAccounts;
    institutionTemplates = accountsData.institutionTemplates;
    baseCurrency = dashboardData.baseCurrency;
    dashboardBalances = Object.fromEntries(dashboardData.balances.map((balance) => [balance.id, balance.balance]));
  }

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
  <section class="view-card hero">
    <p class="eyebrow">Accounts</p>
    <h2 class="page-title">Loading account inventory</h2>
    <p class="subtitle">Pulling together tracked accounts, import setup, and current balances.</p>
  </section>
{:else if !initialized}
  <section class="view-card hero">
    <p class="eyebrow">Accounts</p>
    <h2 class="page-title">Create a workspace first</h2>
    <p class="subtitle">Accounts live inside a workspace. Finish setup before adding or configuring them.</p>
    <div class="actions">
      <a class="btn btn-primary" href="/setup">Open setup</a>
    </div>
  </section>
{:else}
  <section class="view-card hero accounts-hero">
    <div>
      <p class="eyebrow">Accounts</p>
      <h2 class="page-title">{workspaceName || 'Workspace'} account inventory</h2>
      <p class="subtitle">
        Review tracked accounts, balances, and import status here. Open the dedicated configuration workspace when you
        want to add accounts or edit import setup.
      </p>
    </div>

    <div class="hero-stats">
      <div>
        <span class="stat-kicker">Tracked</span>
        <strong>{trackedAccounts.length}</strong>
      </div>
      <div>
        <span class="stat-kicker">Import-enabled</span>
        <strong>{trackedAccounts.filter((account) => account.importConfigured).length}</strong>
      </div>
      <div>
        <span class="stat-kicker">Custom CSV</span>
        <strong>{trackedAccounts.filter((account) => account.importMode === 'custom').length}</strong>
      </div>
    </div>
  </section>

  <section class="view-card">
    <div class="section-head">
      <div>
        <p class="eyebrow">Configure</p>
        <h3>Account setup workspace</h3>
      </div>
      <a class="text-link" href="/">Back to overview</a>
    </div>

    <div class="quick-actions">
      <a class="btn btn-primary" href="/accounts/configure?mode=manual">Add manual account</a>
      <a class="btn" href="/accounts/configure?mode=custom">Add custom CSV</a>
      {#each institutionTemplates as template}
        <a class="btn" href={`/accounts/configure?mode=institution&institutionId=${template.id}`}>Add {template.displayName}</a>
      {/each}
    </div>
  </section>

  <section class="view-card">
    <div class="section-head">
      <div>
        <p class="eyebrow">Inventory</p>
        <h3>Tracked accounts</h3>
      </div>
    </div>

    {#if trackedAccounts.length === 0}
      <div class="empty-panel">
        <h4>No accounts yet</h4>
        <p>Start with a supported institution, add a custom CSV import, or track an account manually with an opening balance.</p>
      </div>
    {:else}
      <div class="account-list">
        {#each trackedAccounts as account}
          <article class="account-card">
            <div class="account-card-head">
              <div>
                <h4>{account.displayName}</h4>
                <p class="muted">{account.institutionDisplayName || 'Manual account'}</p>
              </div>
              <a class="inline-link" href={`/accounts/configure?accountId=${account.id}`}>Edit</a>
            </div>

            <div class="pill-row">
              <span class:ok={account.importConfigured} class="pill">{modeLabel(account)}</span>
              <span class="pill">{titleCase(account.kind)}</span>
              {#if account.last4}
                <span class="pill">••{account.last4}</span>
              {/if}
            </div>

            <div class="account-metrics">
              <div>
                <p class="metric-label">Current balance</p>
                <p class="metric-value">{formatCurrency(currentBalance(account.id))}</p>
              </div>
              <div>
                <p class="metric-label">Opening balance</p>
                <p class="metric-value">
                  {account.openingBalance ? `${account.openingBalance} · ${account.openingBalanceDate || 'No date'}` : 'Not set'}
                </p>
              </div>
            </div>

            <details class="advanced-panel">
              <summary>Account details</summary>
              <p class="muted small">Ledger account: {account.ledgerAccount}</p>
              {#if account.importAccountId}
                <p class="muted small">Import configuration: {account.importAccountId}</p>
              {/if}
              {#if account.importMode === 'custom' && account.importProfile}
                <p class="muted small">{customProfileSummary(account)}</p>
                <p class="muted small">Currency symbol: {account.importProfile.currency || '$'}</p>
                <p class="muted small">Date column: {account.importProfile.dateColumn || 'Not set'}</p>
                <p class="muted small">Description column: {account.importProfile.descriptionColumn || 'Not set'}</p>
                <p class="muted small">Code column: {account.importProfile.codeColumn || 'Not set'}</p>
              {/if}
            </details>
          </article>
        {/each}
      </div>
    {/if}
  </section>
{/if}

<style>
  h3,
  h4 {
    margin: 0;
  }

  .accounts-hero {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
  }

  .hero-stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem;
    min-width: min(420px, 100%);
  }

  .hero-stats div {
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1rem;
    padding: 0.8rem 0.9rem;
    background: rgba(255, 255, 255, 0.68);
  }

  .hero-stats strong {
    display: block;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.45rem;
  }

  .stat-kicker {
    display: block;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-foreground);
    margin-bottom: 0.25rem;
  }

  .section-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .quick-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }

  .account-list {
    display: grid;
    gap: 0.8rem;
  }

  .account-card {
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.64);
    padding: 0.9rem;
  }

  .account-card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
  }

  .pill-row {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    margin: 0.8rem 0;
  }

  .pill.ok {
    background: rgba(13, 127, 88, 0.12);
    color: var(--ok);
  }

  .account-metrics {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
    margin-bottom: 0.75rem;
  }

  .metric-label {
    margin: 0 0 0.2rem;
    font-size: 0.8rem;
    color: var(--muted-foreground);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .metric-value {
    margin: 0;
    font-weight: 700;
  }

  .empty-panel {
    border: 1px dashed rgba(10, 61, 89, 0.18);
    border-radius: 1rem;
    padding: 1rem;
    background: rgba(255, 255, 255, 0.52);
  }

  .actions {
    display: flex;
    gap: 0.7rem;
    flex-wrap: wrap;
  }

  .muted {
    color: var(--muted-foreground);
  }

  .small {
    font-size: 0.84rem;
  }

  @media (max-width: 980px) {
    .accounts-hero {
      flex-direction: column;
      align-items: stretch;
    }

    .hero-stats,
    .account-metrics {
      grid-template-columns: 1fr;
    }
  }
</style>
