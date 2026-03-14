<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';

  type AppState = {
    initialized: boolean;
    workspaceName: string | null;
  };

  type InstitutionTemplate = {
    id: string;
    displayName: string;
    suggestedLedgerPrefix?: string;
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

  type AccountDraft = {
    displayName: string;
    ledgerAccount: string;
    institutionId: string;
    last4: string;
    openingBalance: string;
    openingBalanceDate: string;
  };

  let initialized = false;
  let workspaceName = '';
  let trackedAccounts: TrackedAccount[] = [];
  let institutionTemplates: InstitutionTemplate[] = [];
  let dashboardBalances: Record<string, number> = {};
  let baseCurrency = 'USD';
  let error = '';
  let loading = true;
  let saving = false;

  let editorMode: 'manual' | 'import' = 'manual';
  let editingAccountId: string | null = null;
  let draft = newDraft();

  function newDraft(institutionId = ''): AccountDraft {
    const template = templateById(institutionId);
    return {
      displayName: template?.displayName ?? '',
      ledgerAccount: '',
      institutionId,
      last4: '',
      openingBalance: '',
      openingBalanceDate: ''
    };
  }

  function templateById(id: string): InstitutionTemplate | undefined {
    return institutionTemplates.find((template) => template.id === id);
  }

  function titleCase(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function ledgerSuffix(templateDisplayName: string, displayName: string): string {
    let candidate = displayName.trim();
    if (templateDisplayName && candidate.toLowerCase().startsWith(templateDisplayName.toLowerCase())) {
      const remainder = candidate.slice(templateDisplayName.length).replace(/^[\s:._-]+/, '').trim();
      if (remainder) candidate = remainder;
    }
    const parts = candidate
      .split(/[^A-Za-z0-9]+/)
      .filter(Boolean)
      .map((part) => part[0].toUpperCase() + part.slice(1).toLowerCase());
    return parts.join(':') || 'Account';
  }

  function suggestedLedgerAccount(nextDraft: AccountDraft): string {
    const template = templateById(nextDraft.institutionId);
    if (!template?.suggestedLedgerPrefix || !nextDraft.displayName.trim()) return '';
    return `${template.suggestedLedgerPrefix}:${ledgerSuffix(template.displayName, nextDraft.displayName)}`;
  }

  function effectiveLedgerAccount(nextDraft: AccountDraft): string {
    if (editorMode === 'manual') return nextDraft.ledgerAccount.trim();
    return nextDraft.ledgerAccount.trim() || suggestedLedgerAccount(nextDraft);
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

  function startManualAccount() {
    editorMode = 'manual';
    editingAccountId = null;
    draft = newDraft();
  }

  function startImportAccount(institutionId = '') {
    editorMode = 'import';
    editingAccountId = null;
    draft = newDraft(institutionId);
  }

  function updateDraft(patch: Partial<AccountDraft>) {
    draft = { ...draft, ...patch };
  }

  function updateInstitution(institutionId: string) {
    const nextTemplate = templateById(institutionId);
    const previousTemplate = templateById(draft.institutionId);
    const previousSuggested = suggestedLedgerAccount(draft);

    draft = {
      ...draft,
      institutionId,
      displayName:
        !draft.displayName.trim() || draft.displayName === previousTemplate?.displayName
          ? nextTemplate?.displayName ?? ''
          : draft.displayName,
      ledgerAccount:
        !draft.ledgerAccount.trim() || draft.ledgerAccount === previousSuggested
          ? ''
          : draft.ledgerAccount
    };
  }

  function editAccount(account: TrackedAccount) {
    editorMode = account.importConfigured ? 'import' : 'manual';
    editingAccountId = account.id;
    draft = {
      displayName: account.displayName,
      ledgerAccount: account.ledgerAccount,
      institutionId: account.institutionId ?? '',
      last4: account.last4 ?? '',
      openingBalance: account.openingBalance ?? '',
      openingBalanceDate: account.openingBalanceDate ?? ''
    };
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

  async function saveAccount() {
    const payload = {
      accountId: editingAccountId,
      displayName: draft.displayName.trim(),
      ledgerAccount: effectiveLedgerAccount(draft) || null,
      institutionId: draft.institutionId || null,
      last4: draft.last4.trim() || null,
      openingBalance: draft.openingBalance,
      openingBalanceDate: draft.openingBalanceDate || null
    };

    saving = true;
    error = '';
    try {
      if (editorMode === 'import') {
        await apiPost('/api/workspace/import-accounts', {
          accountId: payload.accountId,
          institutionId: payload.institutionId,
          displayName: payload.displayName,
          ledgerAccount: draft.ledgerAccount.trim() || null,
          last4: payload.last4,
          openingBalance: payload.openingBalance,
          openingBalanceDate: payload.openingBalanceDate
        });
      } else {
        await apiPost('/api/tracked-accounts', payload);
      }
      await load();
      if (editorMode === 'import') {
        startImportAccount();
      } else {
        startManualAccount();
      }
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }

  $: draftInvalid =
    editorMode === 'import'
      ? !draft.displayName.trim() || !draft.institutionId
      : !draft.displayName.trim() || !effectiveLedgerAccount(draft);
  $: editorTitle =
    editingAccountId == null
      ? editorMode === 'import'
        ? 'Add import-enabled account'
        : 'Add manual account'
      : `Edit ${editorMode === 'import' ? 'import-enabled' : 'manual'} account`;

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
    <p class="subtitle">Pulling together tracked accounts, opening balances, and current balances.</p>
  </section>
{:else if !initialized}
  <section class="view-card hero">
    <p class="eyebrow">Accounts</p>
    <h2 class="page-title">Create a workspace first</h2>
    <p class="subtitle">Accounts live inside a workspace. Finish setup before adding manual or import-enabled accounts.</p>
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
        Add manual accounts, connect supported institutions, and set opening balances so the overview has a trustworthy
        balance picture.
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
        <span class="stat-kicker">Manual</span>
        <strong>{trackedAccounts.filter((account) => !account.importConfigured).length}</strong>
      </div>
    </div>
  </section>

  <section class="grid-2 accounts-layout">
    <article class="view-card">
      <div class="section-head">
        <div>
          <p class="eyebrow">Inventory</p>
          <h3>Tracked accounts</h3>
        </div>
        <a class="text-link" href="/">Back to overview</a>
      </div>

      <div class="quick-actions">
        <button class="btn btn-primary" type="button" on:click={startManualAccount}>Add manual account</button>
        {#each institutionTemplates as template}
          <button class="btn" type="button" on:click={() => startImportAccount(template.id)}>
            Add {template.displayName}
          </button>
        {/each}
      </div>

      {#if trackedAccounts.length === 0}
        <div class="empty-panel">
          <h4>No accounts yet</h4>
          <p>Start with a supported institution or add a manual account with an opening balance.</p>
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
                <button class="inline-link" type="button" on:click={() => editAccount(account)}>Edit</button>
              </div>

              <div class="pill-row">
                <span class:ok={account.importConfigured} class="pill">{account.importConfigured ? 'Import-enabled' : 'Manual'}</span>
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
              </details>
            </article>
          {/each}
        </div>
      {/if}
    </article>

    <article class="view-card editor-card">
      <p class="eyebrow">{editingAccountId ? 'Edit account' : 'New account'}</p>
      <h3>{editorTitle}</h3>
      <p class="muted">
        {#if editorMode === 'import'}
          Use this for supported institutions you want to import from.
        {:else}
          Use this for unsupported institutions, manual balances, or accounts you want in the overview before import automation exists.
        {/if}
      </p>

      <div class="mode-switch">
        <button class:active={editorMode === 'manual'} type="button" on:click={startManualAccount}>Manual</button>
        <button class:active={editorMode === 'import'} type="button" on:click={() => startImportAccount(draft.institutionId)}>
          Import-enabled
        </button>
      </div>

      {#if editorMode === 'import'}
        <div class="field">
          <label for="institutionId">Institution</label>
          <select id="institutionId" value={draft.institutionId} on:change={(e) => updateInstitution((e.currentTarget as HTMLSelectElement).value)}>
            <option value="">Select...</option>
            {#each institutionTemplates as template}
              <option value={template.id}>{template.displayName}</option>
            {/each}
          </select>
        </div>
      {/if}

      <div class="field">
        <label for="displayName">Account name</label>
        <input
          id="displayName"
          value={draft.displayName}
          placeholder={editorMode === 'import' ? 'Wells Fargo Checking' : 'Brokerage Cash'}
          on:input={(e) => updateDraft({ displayName: (e.currentTarget as HTMLInputElement).value })}
        />
      </div>

      <div class="field grid-2 compact">
        <div class="field">
          <label for="ledgerAccount">Ledger account</label>
          <input
            id="ledgerAccount"
            value={draft.ledgerAccount}
            placeholder={editorMode === 'import' ? suggestedLedgerAccount(draft) || 'Assets:Bank:Institution:Account' : 'Assets:Investments:Brokerage'}
            on:input={(e) => updateDraft({ ledgerAccount: (e.currentTarget as HTMLInputElement).value })}
          />
        </div>
        <div class="field">
          <label for="last4">Last 4</label>
          <input
            id="last4"
            value={draft.last4}
            placeholder="1234"
            on:input={(e) => updateDraft({ last4: (e.currentTarget as HTMLInputElement).value })}
          />
        </div>
      </div>

      <div class="field grid-2 compact">
        <div class="field">
          <label for="openingBalance">Opening balance</label>
          <input
            id="openingBalance"
            value={draft.openingBalance}
            placeholder="1250.00 or -850.00"
            on:input={(e) => updateDraft({ openingBalance: (e.currentTarget as HTMLInputElement).value })}
          />
        </div>
        <div class="field">
          <label for="openingBalanceDate">Opening date</label>
          <input
            id="openingBalanceDate"
            type="date"
            value={draft.openingBalanceDate}
            on:input={(e) => updateDraft({ openingBalanceDate: (e.currentTarget as HTMLInputElement).value })}
          />
        </div>
      </div>

      <div class="selection-summary">
        <p class="selection-label">Account target</p>
        <p class="selection-value">{effectiveLedgerAccount(draft) || 'Fill in the account details to continue'}</p>
        <p class="muted">
          {#if editorMode === 'import'}
            Leave the ledger account blank to use the suggested destination automatically.
          {:else}
            Manual accounts appear in the overview even without import automation.
          {/if}
        </p>
      </div>

      <div class="actions">
        <button class="btn btn-primary" disabled={saving || draftInvalid} type="button" on:click={saveAccount}>
          {saving ? 'Saving...' : editingAccountId ? 'Save changes' : 'Add account'}
        </button>
        {#if editingAccountId}
          <button class="btn" type="button" on:click={editorMode === 'import' ? () => startImportAccount() : startManualAccount}>
            Cancel
          </button>
        {/if}
      </div>

      <p class="secondary-note">
        Use signed opening balances. Assets are usually positive; liabilities such as credit-card debt should usually be negative.
      </p>
    </article>
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

  .accounts-layout {
    align-items: start;
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
    margin-bottom: 1rem;
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

  .editor-card {
    display: grid;
    gap: 0.9rem;
  }

  .mode-switch {
    display: inline-flex;
    gap: 0.35rem;
    padding: 0.35rem;
    border-radius: 999px;
    background: rgba(10, 61, 89, 0.06);
    width: fit-content;
  }

  .mode-switch button {
    border: 0;
    background: transparent;
    color: var(--brand-strong);
    padding: 0.55rem 0.9rem;
    border-radius: 999px;
    font: inherit;
    font-weight: 700;
    cursor: pointer;
  }

  .mode-switch button.active {
    background: #fff;
    box-shadow: 0 8px 20px rgba(17, 35, 52, 0.08);
  }

  .compact {
    gap: 0.8rem;
  }

  .empty-panel {
    border: 1px dashed rgba(10, 61, 89, 0.18);
    border-radius: 1rem;
    padding: 1rem;
    background: rgba(255, 255, 255, 0.52);
  }

  .secondary-note {
    margin: 0;
    color: var(--muted-foreground);
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
