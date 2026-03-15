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

  function formatStoredAmount(value: string | null | undefined): string {
    if (!value) return 'Not set';
    const numeric = Number(value);
    if (Number.isNaN(numeric)) return value;
    return formatCurrency(numeric);
  }

  function shortDate(value: string | null | undefined): string {
    if (!value) return 'No date';
    const parsed = new Date(`${value}T12:00:00`);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    }).format(parsed);
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

  function importSetupTitle(account: TrackedAccount): string {
    if (!account.importConfigured) return 'Manual tracking';
    if (account.importMode === 'custom') return account.importProfile?.displayName || 'Custom CSV';
    return 'Institution import';
  }

  function importSetupNote(account: TrackedAccount): string {
    if (!account.importConfigured) return 'No automated import attached.';
    if (account.importMode === 'custom') {
      const amountMode = account.importProfile?.amountMode === 'debit_credit' ? 'Debit / credit mapping' : 'Signed amount mapping';
      return account.importAccountId ? `${account.importAccountId} · ${amountMode}` : amountMode;
    }
    return account.importAccountId || 'Connected through a supported institution.';
  }

  function hasAdvancedDetails(account: TrackedAccount): boolean {
    return account.importMode === 'custom' && Boolean(account.importProfile);
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
            <div class="account-card-main">
              <div class="account-balance-panel">
                <p class="metric-label">Current balance</p>
                <p
                  class:positive={(currentBalance(account.id) ?? 0) > 0}
                  class:negative={(currentBalance(account.id) ?? 0) < 0}
                  class="account-balance-value"
                >
                  {formatCurrency(currentBalance(account.id))}
                </p>
                <p class="account-balance-note">
                  {#if account.openingBalance}
                    Started at {formatStoredAmount(account.openingBalance)}
                    {#if account.openingBalanceDate}
                      on {shortDate(account.openingBalanceDate)}
                    {/if}
                  {:else}
                    Opening balance not set yet.
                  {/if}
                </p>
              </div>

              <div class="account-card-content">
                <div class="account-card-head">
                  <div class="account-title-group">
                    <h4>{account.displayName}</h4>
                    <p class="muted">{account.institutionDisplayName || 'Manual account'}</p>
                  </div>
                  <div class="account-card-actions">
                    <a class="inline-link" href={`/transactions?accountId=${account.id}`}>Transactions</a>
                    <a class="inline-link" href={`/accounts/configure?accountId=${account.id}`}>Edit</a>
                  </div>
                </div>

                <div class="pill-row">
                  <span class:ok={account.importConfigured} class="pill">{modeLabel(account)}</span>
                  <span class="pill">{titleCase(account.kind)}</span>
                  {#if account.last4}
                    <span class="pill">••{account.last4}</span>
                  {/if}
                </div>

                <dl class="account-meta-grid">
                  <div class="account-meta-item">
                    <dt>Opening balance</dt>
                    <dd>{account.openingBalance ? formatStoredAmount(account.openingBalance) : 'Not set'}</dd>
                    <span class="account-meta-note">
                      {account.openingBalanceDate ? shortDate(account.openingBalanceDate) : 'Add a starting date in setup.'}
                    </span>
                  </div>

                  <div class="account-meta-item">
                    <dt>Ledger account</dt>
                    <dd>{account.ledgerAccount}</dd>
                    <span class="account-meta-note">
                      {account.importConfigured ? 'Ready for imported activity.' : 'Used for manual balance tracking.'}
                    </span>
                  </div>

                  <div class="account-meta-item">
                    <dt>Import setup</dt>
                    <dd>{importSetupTitle(account)}</dd>
                    <span class="account-meta-note">{importSetupNote(account)}</span>
                  </div>
                </dl>
              </div>
            </div>

            {#if hasAdvancedDetails(account)}
              <details class="advanced-panel">
                <summary>Import mapping details</summary>
                <p class="muted small">{customProfileSummary(account)}</p>
                <p class="muted small">Currency symbol: {account.importProfile?.currency || '$'}</p>
                <p class="muted small">Date column: {account.importProfile?.dateColumn || 'Not set'}</p>
                <p class="muted small">Description column: {account.importProfile?.descriptionColumn || 'Not set'}</p>
                <p class="muted small">Code column: {account.importProfile?.codeColumn || 'Not set'}</p>
              </details>
            {/if}
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
    padding: 1rem;
    display: grid;
    gap: 0.95rem;
  }

  .account-card-main {
    display: grid;
    grid-template-columns: minmax(17rem, 20rem) minmax(0, 1fr);
    gap: 1rem;
    align-items: start;
  }

  .account-balance-panel {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 0.4rem;
    min-height: 100%;
    padding: 1rem;
    border-radius: 1rem;
    border: 1px solid rgba(15, 95, 136, 0.12);
    background: linear-gradient(160deg, rgba(244, 249, 255, 0.96), rgba(239, 248, 244, 0.9));
  }

  .account-balance-value {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(2rem, 3vw, 2.7rem);
    line-height: 0.96;
  }

  .account-balance-note {
    margin: 0;
    max-width: 28ch;
    color: var(--muted-foreground);
    font-size: 0.92rem;
  }

  .account-card-content {
    display: grid;
    gap: 0.9rem;
    min-width: 0;
  }

  .account-card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.9rem;
  }

  .account-title-group {
    min-width: 0;
  }

  .account-title-group p {
    margin: 0.3rem 0 0;
  }

  .account-card-actions {
    display: flex;
    gap: 0.55rem;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .pill-row {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    margin: 0;
  }

  .pill.ok {
    background: rgba(13, 127, 88, 0.12);
    color: var(--ok);
  }

  .account-meta-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem;
    margin: 0;
  }

  .account-meta-item {
    margin: 0;
    padding: 0.85rem 0.9rem;
    border-radius: 0.95rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.7);
  }

  .account-meta-item dt {
    margin: 0 0 0.35rem;
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .account-meta-item dd {
    margin: 0;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .account-meta-note {
    display: block;
    margin-top: 0.3rem;
    color: var(--muted-foreground);
    font-size: 0.86rem;
    overflow-wrap: anywhere;
  }

  .metric-label {
    margin: 0;
    font-size: 0.8rem;
    color: var(--muted-foreground);
    text-transform: uppercase;
    letter-spacing: 0.08em;
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
    margin: 0;
  }

  .small {
    font-size: 0.84rem;
  }

  .text-link {
    color: var(--brand-strong);
    text-decoration: none;
    font-weight: 700;
  }

  .inline-link {
    display: inline-flex;
    align-items: center;
    padding: 0.48rem 0.8rem;
    border-radius: 999px;
    border: 1px solid rgba(10, 61, 89, 0.12);
    background: rgba(255, 255, 255, 0.94);
    color: var(--brand-strong);
    text-decoration: none;
    font-weight: 700;
    box-shadow: 0 8px 18px rgba(17, 35, 52, 0.04);
  }

  .inline-link:hover,
  .text-link:hover {
    text-decoration: underline;
  }

  .inline-link:hover {
    text-decoration: none;
    background: #f7fbff;
    border-color: rgba(15, 95, 136, 0.18);
  }

  .advanced-panel {
    border-top: 1px solid rgba(10, 61, 89, 0.08);
    padding-top: 0.9rem;
  }

  .advanced-panel summary {
    cursor: pointer;
    font-weight: 700;
    color: var(--brand-strong);
  }

  .advanced-panel p + p {
    margin-top: 0.35rem;
  }

  .positive {
    color: var(--ok);
  }

  .negative {
    color: var(--bad);
  }

  @media (max-width: 980px) {
    .accounts-hero {
      flex-direction: column;
      align-items: stretch;
    }

    .hero-stats,
    .account-meta-grid,
    .account-card-main {
      grid-template-columns: 1fr;
    }

    .account-card-head {
      flex-direction: column;
    }

    .account-card-actions {
      justify-content: flex-start;
    }

    .account-balance-note {
      max-width: none;
    }
  }
</style>
