<script lang="ts">
  import { page } from '$app/stores';
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
    importProfileId?: string | null;
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

  type CsvInspection = {
    encoding: string;
    delimiter: string;
    headers: string[];
    sampleRows: Array<Record<string, string>>;
  };

  type CustomProfileDraft = {
    encoding: string;
    delimiter: string;
    skipRows: string;
    skipFooterRows: string;
    reverseOrder: boolean;
    dateColumn: string;
    dateFormat: string;
    descriptionColumn: string;
    secondaryDescriptionColumn: string;
    amountMode: 'signed' | 'debit_credit';
    amountColumn: string;
    debitColumn: string;
    creditColumn: string;
    balanceColumn: string;
    codeColumn: string;
    noteColumn: string;
    currency: string;
  };

  type AccountDraft = {
    displayName: string;
    ledgerAccount: string;
    institutionId: string;
    last4: string;
    openingBalance: string;
    openingBalanceDate: string;
    customProfile: CustomProfileDraft;
  };

  type HeaderGuessPatch = Partial<{
    dateColumn: string;
    descriptionColumn: string;
    secondaryDescriptionColumn: string;
    amountMode: 'signed' | 'debit_credit';
    amountColumn: string;
    debitColumn: string;
    creditColumn: string;
    balanceColumn: string;
    codeColumn: string;
    noteColumn: string;
  }>;

  const DELIMITER_OPTIONS = [
    { value: '', label: 'Auto-detect' },
    { value: ',', label: 'Comma' },
    { value: ';', label: 'Semicolon' },
    { value: '\t', label: 'Tab' },
    { value: '|', label: 'Pipe' }
  ];
  const ENCODING_OPTIONS = [
    { value: '', label: 'Auto-detect' },
    { value: 'utf-8', label: 'UTF-8' },
    { value: 'utf-8-sig', label: 'UTF-8 with BOM' },
    { value: 'cp1252', label: 'Windows-1252' },
    { value: 'latin-1', label: 'Latin-1' },
    { value: 'gb18030', label: 'GB18030' }
  ];
  const CURRENCY_OPTIONS = [
    { value: '$', label: '$ USD' },
    { value: '€', label: '€ EUR' },
    { value: '£', label: '£ GBP' },
    { value: '¥', label: '¥ CNY / JPY' }
  ];

  let initialized = false;
  let workspaceName = '';
  let trackedAccounts: TrackedAccount[] = [];
  let institutionTemplates: InstitutionTemplate[] = [];
  let dashboardBalances: Record<string, number> = {};
  let baseCurrency = 'USD';
  let error = '';
  let loading = true;
  let saving = false;
  let inspecting = false;

  let editorMode: 'manual' | 'institution' | 'custom' = 'manual';
  let editingAccountId: string | null = null;
  let draft = newDraft();
  let selectedSampleFile: File | null = null;
  let inspection: CsvInspection | null = null;
  let lastRouteKey = '';

  function defaultCurrencySymbol(value: string): string {
    switch (value.toUpperCase()) {
      case 'USD':
      case 'CAD':
      case 'AUD':
        return '$';
      case 'EUR':
        return '€';
      case 'GBP':
        return '£';
      case 'CNY':
      case 'JPY':
        return '¥';
      default:
        return '$';
    }
  }

  function normalizeStoredCurrency(value: string | null | undefined): string {
    if (!value) return defaultCurrencySymbol(baseCurrency);
    if (['$', '€', '£', '¥'].includes(value)) return value;
    return defaultCurrencySymbol(value);
  }

  function newCustomProfileDraft(currency = baseCurrency): CustomProfileDraft {
    return {
      encoding: '',
      delimiter: '',
      skipRows: '0',
      skipFooterRows: '0',
      reverseOrder: true,
      dateColumn: '',
      dateFormat: '',
      descriptionColumn: '',
      secondaryDescriptionColumn: '',
      amountMode: 'signed',
      amountColumn: '',
      debitColumn: '',
      creditColumn: '',
      balanceColumn: '',
      codeColumn: '',
      noteColumn: '',
      currency: normalizeStoredCurrency(currency)
    };
  }

  function newDraft(institutionId = ''): AccountDraft {
    const template = templateById(institutionId);
    return {
      displayName: template?.displayName ?? '',
      ledgerAccount: '',
      institutionId,
      last4: '',
      openingBalance: '',
      openingBalanceDate: '',
      customProfile: newCustomProfileDraft()
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
    if (editorMode === 'institution') {
      return nextDraft.ledgerAccount.trim() || suggestedLedgerAccount(nextDraft);
    }
    return nextDraft.ledgerAccount.trim();
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

  function resetSampleState() {
    inspection = null;
    selectedSampleFile = null;
  }

  function startManualAccount() {
    editorMode = 'manual';
    editingAccountId = null;
    draft = newDraft();
    draft.customProfile.currency = defaultCurrencySymbol(baseCurrency);
    resetSampleState();
  }

  function startInstitutionAccount(institutionId = '') {
    editorMode = 'institution';
    editingAccountId = null;
    draft = newDraft(institutionId);
    draft.customProfile.currency = defaultCurrencySymbol(baseCurrency);
    resetSampleState();
  }

  function startCustomAccount() {
    editorMode = 'custom';
    editingAccountId = null;
    draft = newDraft();
    draft.customProfile.currency = defaultCurrencySymbol(baseCurrency);
    resetSampleState();
  }

  function updateDraft(patch: Partial<AccountDraft>) {
    draft = { ...draft, ...patch };
  }

  function updateCustomProfile(patch: Partial<CustomProfileDraft>) {
    draft = {
      ...draft,
      customProfile: {
        ...draft.customProfile,
        ...patch
      }
    };
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

  function profileDraftFromAccount(account: TrackedAccount): CustomProfileDraft {
    return {
      encoding: account.importProfile?.encoding ?? '',
      delimiter: account.importProfile?.delimiter ?? '',
      skipRows: String(account.importProfile?.skipRows ?? 0),
      skipFooterRows: String(account.importProfile?.skipFooterRows ?? 0),
      reverseOrder: account.importProfile?.reverseOrder ?? true,
      dateColumn: account.importProfile?.dateColumn ?? '',
      dateFormat: account.importProfile?.dateFormat ?? '',
      descriptionColumn: account.importProfile?.descriptionColumn ?? '',
      secondaryDescriptionColumn: account.importProfile?.secondaryDescriptionColumn ?? '',
      amountMode: account.importProfile?.amountMode ?? 'signed',
      amountColumn: account.importProfile?.amountColumn ?? '',
      debitColumn: account.importProfile?.debitColumn ?? '',
      creditColumn: account.importProfile?.creditColumn ?? '',
      balanceColumn: account.importProfile?.balanceColumn ?? '',
      codeColumn: account.importProfile?.codeColumn ?? '',
      noteColumn: account.importProfile?.noteColumn ?? '',
      currency: normalizeStoredCurrency(account.importProfile?.currency)
    };
  }

  function editAccount(account: TrackedAccount) {
    editorMode = account.importConfigured
      ? account.importMode === 'custom'
        ? 'custom'
        : 'institution'
      : 'manual';
    editingAccountId = account.id;
    draft = {
      displayName: account.displayName,
      ledgerAccount: account.ledgerAccount,
      institutionId: account.institutionId ?? '',
      last4: account.last4 ?? '',
      openingBalance: account.openingBalance ?? '',
      openingBalanceDate: account.openingBalanceDate ?? '',
      customProfile: profileDraftFromAccount(account)
    };
    inspection = null;
    selectedSampleFile = null;
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
    if (!draft.customProfile.currency) {
      updateCustomProfile({ currency: defaultCurrencySymbol(baseCurrency) });
    }
  }

  function syncFromRoute(routeKey: string) {
    if (!initialized || routeKey === lastRouteKey) return;
    lastRouteKey = routeKey;

    const accountId = $page.url.searchParams.get('accountId');
    if (accountId) {
      const account = trackedAccounts.find((row) => row.id === accountId);
      if (account) {
        editAccount(account);
        return;
      }
    }

    const mode = $page.url.searchParams.get('mode');
    if (mode === 'institution') {
      startInstitutionAccount($page.url.searchParams.get('institutionId') ?? '');
    } else if (mode === 'custom') {
      startCustomAccount();
    } else if (mode === 'manual') {
      startManualAccount();
    }
  }

  function normalizeDelimiterLabel(value: string): string {
    if (value === '\t') return 'Tab';
    const option = DELIMITER_OPTIONS.find((entry) => entry.value === value);
    return option?.label ?? value;
  }

  function headerMatches(header: string, terms: string[]): boolean {
    const value = header.trim().toLowerCase();
    return terms.some((term) => value.includes(term));
  }

  function firstHeader(headers: string[], terms: string[]): string {
    return headers.find((header) => headerMatches(header, terms)) ?? '';
  }

  function guessProfileFromHeaders(headers: string[]): HeaderGuessPatch {
    const debit = firstHeader(headers, ['debit', 'withdraw', 'outflow', 'charge', 'spent']);
    const credit = firstHeader(headers, ['credit', 'deposit', 'payment', 'refund', 'inflow']);
    const signedAmount = firstHeader(headers, ['amount', 'amt']) || firstHeader(headers, ['transaction amount']);

    return {
      dateColumn: firstHeader(headers, ['date', 'posted']),
      descriptionColumn: firstHeader(headers, ['description', 'merchant', 'details', 'payee', 'name']),
      secondaryDescriptionColumn: firstHeader(headers, ['memo', 'details', 'notes', 'category']),
      amountMode: debit || credit ? 'debit_credit' : 'signed',
      amountColumn: signedAmount,
      debitColumn: debit,
      creditColumn: credit,
      balanceColumn: firstHeader(headers, ['balance']),
      codeColumn: firstHeader(headers, ['reference', 'ref', 'code', 'id']),
      noteColumn: firstHeader(headers, ['note', 'memo'])
    };
  }

  function applyHeaderGuesses(headers: string[]) {
    const guess = guessProfileFromHeaders(headers);
    updateCustomProfile({
      dateColumn: draft.customProfile.dateColumn || guess.dateColumn || '',
      descriptionColumn: draft.customProfile.descriptionColumn || guess.descriptionColumn || '',
      secondaryDescriptionColumn:
        draft.customProfile.secondaryDescriptionColumn || guess.secondaryDescriptionColumn || '',
      amountMode:
        draft.customProfile.debitColumn || draft.customProfile.creditColumn
          ? draft.customProfile.amountMode
          : guess.amountMode ?? draft.customProfile.amountMode,
      amountColumn: draft.customProfile.amountColumn || guess.amountColumn || '',
      debitColumn: draft.customProfile.debitColumn || guess.debitColumn || '',
      creditColumn: draft.customProfile.creditColumn || guess.creditColumn || '',
      balanceColumn: draft.customProfile.balanceColumn || guess.balanceColumn || '',
      codeColumn: draft.customProfile.codeColumn || guess.codeColumn || '',
      noteColumn: draft.customProfile.noteColumn || guess.noteColumn || ''
    });
  }

  async function inspectSample() {
    if (!selectedSampleFile) return;
    inspecting = true;
    error = '';
    try {
      const form = new FormData();
      form.append('file', selectedSampleFile);
      if (draft.customProfile.encoding) form.append('encoding', draft.customProfile.encoding);
      if (draft.customProfile.delimiter) form.append('delimiter', draft.customProfile.delimiter);
      form.append('skipRows', draft.customProfile.skipRows || '0');
      form.append('skipFooterRows', draft.customProfile.skipFooterRows || '0');

      const res = await fetch('/api/import/custom-profile/inspect', { method: 'POST', body: form });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || 'Sample inspection failed');
      }
      inspection = (await res.json()) as CsvInspection;
      updateCustomProfile({
        encoding: draft.customProfile.encoding || inspection.encoding,
        delimiter: draft.customProfile.delimiter || inspection.delimiter
      });
      applyHeaderGuesses(inspection.headers);
    } catch (e) {
      error = String(e);
    } finally {
      inspecting = false;
    }
  }

  function customProfilePayload(): CustomImportProfile {
    return {
      displayName: `${draft.displayName.trim() || 'Account'} CSV`,
      encoding: draft.customProfile.encoding || '',
      delimiter: draft.customProfile.delimiter || '',
      skipRows: Number(draft.customProfile.skipRows || '0'),
      skipFooterRows: Number(draft.customProfile.skipFooterRows || '0'),
      reverseOrder: draft.customProfile.reverseOrder,
      dateColumn: draft.customProfile.dateColumn.trim(),
      dateFormat: draft.customProfile.dateFormat.trim() || null,
      descriptionColumn: draft.customProfile.descriptionColumn.trim(),
      secondaryDescriptionColumn: draft.customProfile.secondaryDescriptionColumn.trim() || null,
      amountMode: draft.customProfile.amountMode,
      amountColumn: draft.customProfile.amountMode === 'signed' ? draft.customProfile.amountColumn.trim() : null,
      debitColumn: draft.customProfile.amountMode === 'debit_credit' ? draft.customProfile.debitColumn.trim() : null,
      creditColumn: draft.customProfile.amountMode === 'debit_credit' ? draft.customProfile.creditColumn.trim() : null,
      balanceColumn: draft.customProfile.balanceColumn.trim() || null,
      codeColumn: draft.customProfile.codeColumn.trim() || null,
      noteColumn: draft.customProfile.noteColumn.trim() || null,
      currency: draft.customProfile.currency.trim() || defaultCurrencySymbol(baseCurrency)
    };
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
      if (editorMode === 'institution') {
        await apiPost('/api/workspace/import-accounts', {
          accountId: payload.accountId,
          institutionId: payload.institutionId,
          displayName: payload.displayName,
          ledgerAccount: draft.ledgerAccount.trim() || null,
          last4: payload.last4,
          openingBalance: payload.openingBalance,
          openingBalanceDate: payload.openingBalanceDate
        });
      } else if (editorMode === 'custom') {
        await apiPost('/api/workspace/custom-import-accounts', {
          accountId: payload.accountId,
          displayName: payload.displayName,
          ledgerAccount: payload.ledgerAccount,
          last4: payload.last4,
          openingBalance: payload.openingBalance,
          openingBalanceDate: payload.openingBalanceDate,
          customProfile: customProfilePayload()
        });
      } else {
        await apiPost('/api/tracked-accounts', payload);
      }

      await load();
      lastRouteKey = '';
      if (editorMode === 'institution') {
        startInstitutionAccount();
      } else if (editorMode === 'custom') {
        startCustomAccount();
      } else {
        startManualAccount();
      }
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }

  function modeLabel(account: TrackedAccount): string {
    if (!account.importConfigured) return 'Manual';
    return account.importMode === 'custom' ? 'Custom CSV' : 'Import-enabled';
  }

  function amountConfigInvalid(): boolean {
    if (draft.customProfile.amountMode === 'signed') {
      return !draft.customProfile.amountColumn.trim();
    }
    return !draft.customProfile.debitColumn.trim() && !draft.customProfile.creditColumn.trim();
  }

  $: customDraftInvalid =
    !draft.displayName.trim() ||
    !effectiveLedgerAccount(draft) ||
    !draft.customProfile.dateColumn.trim() ||
    !draft.customProfile.descriptionColumn.trim() ||
    amountConfigInvalid();
  $: draftInvalid =
    editorMode === 'institution'
      ? !draft.displayName.trim() || !draft.institutionId
      : editorMode === 'custom'
        ? customDraftInvalid
        : !draft.displayName.trim() || !effectiveLedgerAccount(draft);
  $: editorTitle =
    editingAccountId == null
      ? editorMode === 'institution'
        ? 'Add supported import account'
        : editorMode === 'custom'
          ? 'Add custom CSV import account'
          : 'Add manual account'
      : `Edit ${
          editorMode === 'institution'
            ? 'supported import'
            : editorMode === 'custom'
              ? 'custom CSV'
              : 'manual'
        } account`;

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

  $: if (!loading && initialized) {
    syncFromRoute($page.url.searchParams.toString());
  }
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
      <p class="eyebrow">Account Setup</p>
      <h2 class="page-title">{workspaceName || 'Workspace'} configuration workspace</h2>
      <p class="subtitle">
        Configure manual accounts, supported institution imports, or custom CSV mappings without squeezing the form into
        the account inventory view.
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

  <section class="grid-2 accounts-layout">
    <article class="view-card">
      <div class="section-head">
        <div>
          <p class="eyebrow">Inventory</p>
          <h3>Tracked accounts</h3>
        </div>
        <a class="text-link" href="/accounts">Back to accounts</a>
      </div>

      <div class="quick-actions">
        <button class="btn btn-primary" type="button" on:click={startManualAccount}>Add manual account</button>
        <button class="btn" type="button" on:click={startCustomAccount}>Add custom CSV</button>
        {#each institutionTemplates as template}
          <button class="btn" type="button" on:click={() => startInstitutionAccount(template.id)}>
            Add {template.displayName}
          </button>
        {/each}
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
                <button class="inline-link" type="button" on:click={() => editAccount(account)}>Edit</button>
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
                  <p class="muted small">
                    Custom CSV: {account.importProfile.displayName || 'Custom profile'} · {account.importProfile.currency || baseCurrency}
                  </p>
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
        {#if editorMode === 'institution'}
          Use this for supported institutions that already have a built-in parser.
        {:else if editorMode === 'custom'}
          Use this when you have a normal transaction CSV and want to manage the mapping yourself.
        {:else}
          Use this for unsupported institutions, manual balances, or accounts you want in the overview before import automation exists.
        {/if}
      </p>

      <div class="mode-switch">
        <button class:active={editorMode === 'manual'} type="button" on:click={startManualAccount}>Manual</button>
        <button class:active={editorMode === 'institution'} type="button" on:click={() => startInstitutionAccount(draft.institutionId)}>
          Supported
        </button>
        <button class:active={editorMode === 'custom'} type="button" on:click={startCustomAccount}>Custom CSV</button>
      </div>

      {#if editorMode === 'institution'}
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
          placeholder={editorMode === 'institution' ? 'Wells Fargo Checking' : editorMode === 'custom' ? 'Capital One Card' : 'Brokerage Cash'}
          on:input={(e) => updateDraft({ displayName: (e.currentTarget as HTMLInputElement).value })}
        />
      </div>

      <div class="field grid-2 compact">
        <div class="field">
          <label for="ledgerAccount">Ledger account</label>
          <input
            id="ledgerAccount"
            value={draft.ledgerAccount}
            placeholder={
              editorMode === 'institution'
                ? suggestedLedgerAccount(draft) || 'Assets:Bank:Institution:Account'
                : editorMode === 'custom'
                  ? 'Liabilities:Cards:Capital One'
                  : 'Assets:Investments:Brokerage'
            }
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

      {#if editorMode === 'custom'}
        <section class="custom-profile-panel">
          <div class="section-head compact-head">
            <div>
              <p class="eyebrow">CSV setup</p>
              <h4>Inspect a sample file</h4>
            </div>
          </div>

          <div class="field grid-2 compact">
            <div class="field">
              <label for="sampleFile">Sample CSV</label>
              <input
                id="sampleFile"
                type="file"
                accept=".csv,text/csv"
                on:change={(e) => (selectedSampleFile = (e.currentTarget as HTMLInputElement).files?.[0] ?? null)}
              />
            </div>
            <div class="field">
              <label for="currency">Currency symbol</label>
              <select id="currency" value={draft.customProfile.currency} on:change={(e) => updateCustomProfile({ currency: (e.currentTarget as HTMLSelectElement).value })}>
                {#each CURRENCY_OPTIONS as option}
                  <option value={option.value}>{option.label}</option>
                {/each}
              </select>
            </div>
          </div>

          <div class="field grid-4 compact">
            <div class="field">
              <label for="encoding">Encoding</label>
              <select id="encoding" value={draft.customProfile.encoding} on:change={(e) => updateCustomProfile({ encoding: (e.currentTarget as HTMLSelectElement).value })}>
                {#each ENCODING_OPTIONS as option}
                  <option value={option.value}>{option.label}</option>
                {/each}
              </select>
            </div>
            <div class="field">
              <label for="delimiter">Delimiter</label>
              <select id="delimiter" value={draft.customProfile.delimiter} on:change={(e) => updateCustomProfile({ delimiter: (e.currentTarget as HTMLSelectElement).value })}>
                {#each DELIMITER_OPTIONS as option}
                  <option value={option.value}>{option.label}</option>
                {/each}
              </select>
            </div>
            <div class="field">
              <label for="skipRows">Skip top rows</label>
              <input
                id="skipRows"
                type="number"
                min="0"
                value={draft.customProfile.skipRows}
                on:input={(e) => updateCustomProfile({ skipRows: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="skipFooterRows">Skip bottom rows</label>
              <input
                id="skipFooterRows"
                type="number"
                min="0"
                value={draft.customProfile.skipFooterRows}
                on:input={(e) => updateCustomProfile({ skipFooterRows: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
          </div>

          <div class="actions">
            <button class="btn" disabled={inspecting || !selectedSampleFile} type="button" on:click={inspectSample}>
              {inspecting ? 'Inspecting...' : 'Inspect sample'}
            </button>
          </div>

          {#if inspection}
            <div class="selection-summary">
              <p class="selection-label">Detected format</p>
              <p class="selection-value">
                {inspection.headers.length} columns · {normalizeDelimiterLabel(inspection.delimiter)} · {inspection.encoding}
              </p>
              <p class="muted">Column names from the sample file are available below. You can still type your own column names if needed.</p>
            </div>
          {/if}

          <datalist id="custom-csv-headers">
            {#if inspection}
              {#each inspection.headers as header}
                <option value={header}></option>
              {/each}
            {/if}
          </datalist>

          <div class="mapping-grid">
            <div class="field">
              <label for="dateColumn">Date column</label>
              <input
                id="dateColumn"
                list="custom-csv-headers"
                value={draft.customProfile.dateColumn}
                on:input={(e) => updateCustomProfile({ dateColumn: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="dateFormat">Date format</label>
              <input
                id="dateFormat"
                value={draft.customProfile.dateFormat}
                placeholder="Leave blank to auto-detect"
                on:input={(e) => updateCustomProfile({ dateFormat: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="descriptionColumn">Description column</label>
              <input
                id="descriptionColumn"
                list="custom-csv-headers"
                value={draft.customProfile.descriptionColumn}
                on:input={(e) => updateCustomProfile({ descriptionColumn: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="secondaryDescriptionColumn">Extra description</label>
              <input
                id="secondaryDescriptionColumn"
                list="custom-csv-headers"
                value={draft.customProfile.secondaryDescriptionColumn}
                on:input={(e) => updateCustomProfile({ secondaryDescriptionColumn: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="amountMode">Amount mode</label>
              <select
                id="amountMode"
                value={draft.customProfile.amountMode}
                on:change={(e) => updateCustomProfile({ amountMode: (e.currentTarget as HTMLSelectElement).value as 'signed' | 'debit_credit' })}
              >
                <option value="signed">Signed amount column</option>
                <option value="debit_credit">Separate debit / credit columns</option>
              </select>
            </div>
            {#if draft.customProfile.amountMode === 'signed'}
              <div class="field">
                <label for="amountColumn">Amount column</label>
                <input
                  id="amountColumn"
                  list="custom-csv-headers"
                  value={draft.customProfile.amountColumn}
                  on:input={(e) => updateCustomProfile({ amountColumn: (e.currentTarget as HTMLInputElement).value })}
                />
              </div>
            {:else}
              <div class="field">
                <label for="debitColumn">Debit column</label>
                <input
                  id="debitColumn"
                  list="custom-csv-headers"
                  value={draft.customProfile.debitColumn}
                  on:input={(e) => updateCustomProfile({ debitColumn: (e.currentTarget as HTMLInputElement).value })}
                />
              </div>
              <div class="field">
                <label for="creditColumn">Credit column</label>
                <input
                  id="creditColumn"
                  list="custom-csv-headers"
                  value={draft.customProfile.creditColumn}
                  on:input={(e) => updateCustomProfile({ creditColumn: (e.currentTarget as HTMLInputElement).value })}
                />
              </div>
            {/if}
            <div class="field">
              <label for="balanceColumn">Balance column</label>
              <input
                id="balanceColumn"
                list="custom-csv-headers"
                value={draft.customProfile.balanceColumn}
                on:input={(e) => updateCustomProfile({ balanceColumn: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="codeColumn">Code column</label>
              <input
                id="codeColumn"
                list="custom-csv-headers"
                value={draft.customProfile.codeColumn}
                on:input={(e) => updateCustomProfile({ codeColumn: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
            <div class="field">
              <label for="noteColumn">Note column</label>
              <input
                id="noteColumn"
                list="custom-csv-headers"
                value={draft.customProfile.noteColumn}
                on:input={(e) => updateCustomProfile({ noteColumn: (e.currentTarget as HTMLInputElement).value })}
              />
            </div>
          </div>

          <label class="checkbox-row">
            <input
              type="checkbox"
              checked={draft.customProfile.reverseOrder}
              on:change={(e) => updateCustomProfile({ reverseOrder: (e.currentTarget as HTMLInputElement).checked })}
            />
            <span>The file is newest first, so reverse it during import.</span>
          </label>

          {#if inspection?.sampleRows.length}
            <div class="sample-table-wrap">
              <table class="sample-table">
                <thead>
                  <tr>
                    {#each inspection.headers as header}
                      <th>{header}</th>
                    {/each}
                  </tr>
                </thead>
                <tbody>
                  {#each inspection.sampleRows as row}
                    <tr>
                      {#each inspection.headers as header}
                        <td>{row[header] || ''}</td>
                      {/each}
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </section>
      {/if}

      <div class="selection-summary">
        <p class="selection-label">Account target</p>
        <p class="selection-value">{effectiveLedgerAccount(draft) || 'Fill in the account details to continue'}</p>
        <p class="muted">
          {#if editorMode === 'institution'}
            Leave the ledger account blank to use the suggested destination automatically.
          {:else if editorMode === 'custom'}
            Save the profile here, then use the Import screen to preview a real statement before applying it.
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
          <button
            class="btn"
            type="button"
            on:click={editorMode === 'institution' ? () => startInstitutionAccount() : editorMode === 'custom' ? startCustomAccount : startManualAccount}
          >
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

  .compact-head {
    margin-bottom: 0.8rem;
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
    flex-wrap: wrap;
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

  .grid-4 {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .mapping-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
  }

  .custom-profile-panel {
    border: 1px solid rgba(10, 61, 89, 0.1);
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.56);
    padding: 1rem;
    display: grid;
    gap: 0.9rem;
  }

  .sample-table-wrap {
    overflow: auto;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 0.9rem;
    background: rgba(255, 255, 255, 0.82);
  }

  .sample-table {
    width: 100%;
    border-collapse: collapse;
    min-width: 34rem;
  }

  .sample-table th,
  .sample-table td {
    text-align: left;
    padding: 0.55rem 0.7rem;
    border-bottom: 1px solid rgba(10, 61, 89, 0.08);
    font-size: 0.9rem;
    vertical-align: top;
  }

  .sample-table th {
    background: rgba(12, 61, 92, 0.06);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground);
  }

  .checkbox-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    color: var(--muted-foreground);
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

  @media (max-width: 1200px) {
    .grid-4 {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 980px) {
    .accounts-hero {
      flex-direction: column;
      align-items: stretch;
    }

    .hero-stats,
    .account-metrics,
    .mapping-grid,
    .grid-4 {
      grid-template-columns: 1fr;
    }
  }
</style>
