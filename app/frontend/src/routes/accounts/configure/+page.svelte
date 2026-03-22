<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import {
    BALANCE_SHEET_KIND_OPTIONS,
    accountKindFromLedger,
    accountSubtypeLabel,
    describeAccountSubtype,
    normalizeBalanceSheetKind,
    subtypeMatchesKind,
    subtypeOptionsForKind,
    suggestedTrackedLedgerAccount
  } from '$lib/account-subtypes';
  import { describeBalanceTrust } from '$lib/account-trust';

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
    subtype?: string | null;
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
      hasOpeningBalance: boolean;
      hasTransactionActivity: boolean;
      hasBalanceSource: boolean;
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
    kind: 'asset' | 'liability';
    displayName: string;
    ledgerAccount: string;
    subtype: string;
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
  let dashboardBalances: Record<string, DashboardOverview['balances'][number]> = {};
  let baseCurrency = 'USD';
  let error = '';
  let loading = true;
  let saving = false;
  let inspecting = false;
  let draftSubtypePreview = 'Asset account';

  let editorMode: 'manual' | 'institution' | 'custom' = 'manual';
  let editingAccountId: string | null = null;
  let draft = newDraft();
  let selectedSampleFile: File | null = null;
  let inspection: CsvInspection | null = null;
  let lastRouteKey = '';
  let needsSetupCount = 0;
  let showAdvancedSettings = false;

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

  function templateKind(institutionId: string): 'asset' | 'liability' {
    const template = templateById(institutionId);
    return normalizeBalanceSheetKind(accountKindFromLedger(template?.suggestedLedgerPrefix));
  }

  function newDraft(institutionId = '', kind: 'asset' | 'liability' = institutionId ? templateKind(institutionId) : 'asset'): AccountDraft {
    const template = templateById(institutionId);
    return {
      kind,
      displayName: template?.displayName ?? '',
      ledgerAccount: '',
      subtype: '',
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

  function suggestedLedgerAccount(nextDraft: AccountDraft): string {
    const template = templateById(nextDraft.institutionId);
    return suggestedTrackedLedgerAccount({
      kind: nextDraft.kind,
      displayName: nextDraft.displayName,
      institutionDisplayName: template?.displayName ?? null,
      templateLedgerPrefix: editorMode === 'institution' ? template?.suggestedLedgerPrefix ?? null : null
    });
  }

  function effectiveLedgerAccount(nextDraft: AccountDraft): string {
    return nextDraft.ledgerAccount.trim() || suggestedLedgerAccount(nextDraft);
  }

  function accountKindHelp(kind: 'asset' | 'liability'): string {
    return kind === 'liability'
      ? 'Track something you owe, such as a credit card, car loan, mortgage, or line of credit.'
      : 'Track something you own or hold, such as checking, savings, cash, investments, or property.';
  }

  function accountNamePlaceholder(): string {
    if (editorMode === 'institution') {
      return draft.kind === 'liability' ? 'Wells Fargo Credit Card' : 'Wells Fargo Checking';
    }
    if (editorMode === 'custom') {
      return draft.kind === 'liability' ? 'Capital One Card' : 'Brokerage Cash';
    }
    return draft.kind === 'liability' ? 'Car loan' : 'House savings';
  }

  function openingBalancePlaceholder(): string {
    return draft.kind === 'liability' ? '-18500.00' : '1250.00';
  }

  function openingBalanceHint(kind: 'asset' | 'liability'): string {
    return kind === 'liability'
      ? 'Enter what you owed on the starting date. Liability opening balances are usually negative.'
      : 'Enter what you owned or held on the starting date. Asset opening balances are usually positive.';
  }

  function subtypeHelperText() {
    const subtypeState = describeAccountSubtype({
      subtype: draft.subtype,
      kind: draft.kind,
      displayName: draft.displayName,
      institutionDisplayName: templateById(draft.institutionId)?.displayName ?? null,
      ledgerAccount: draft.ledgerAccount.trim()
    });

    if (subtypeState.source === 'saved') {
      return `Saved as ${subtypeState.longLabel}. This stays separate from the advanced account name behind the scenes.`;
    }
    if (subtypeState.source === 'suggested') {
      return `Suggested from the account name: ${subtypeState.longLabel}. Select it here if you want that subtype saved on the account.`;
    }
    return `Leave this broad for now, or pick a subtype so Accounts can show exactly what you own or owe.`;
  }

  function subtypeBadgeLabel(account: TrackedAccount): string {
    const subtype = describeAccountSubtype(account);
    if (subtype.source === 'suggested') return `Suggested: ${subtype.shortLabel}`;
    return subtype.shortLabel;
  }

  function subtypeBadgeTone(account: TrackedAccount): string {
    const subtype = describeAccountSubtype(account);
    if (subtype.source === 'saved') return account.kind === 'liability' ? 'liability' : 'asset';
    if (subtype.source === 'suggested') return 'suggested';
    return 'broad';
  }

  function setDraftKind(kind: 'asset' | 'liability') {
    updateDraft({
      kind,
      subtype: subtypeMatchesKind(draft.subtype, kind) ? draft.subtype : ''
    });
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

  function balanceMeta(accountId: string) {
    return dashboardBalances[accountId] ?? null;
  }

  function currentBalance(accountId: string): number | null {
    return balanceMeta(accountId)?.balance ?? null;
  }

  function balanceTrust(account: TrackedAccount) {
    const meta = balanceMeta(account.id);
    return describeBalanceTrust({
      hasOpeningBalance: meta?.hasOpeningBalance ?? Boolean(account.openingBalance),
      hasTransactionActivity: meta?.hasTransactionActivity ?? false,
      hasBalanceSource: meta?.hasBalanceSource ?? Boolean(account.openingBalance),
      importConfigured: account.importConfigured,
      openingBalanceDate: account.openingBalanceDate
    });
  }

  function resetSampleState() {
    inspection = null;
    selectedSampleFile = null;
  }

  function startManualAccount() {
    editorMode = 'manual';
    editingAccountId = null;
    draft = newDraft('', 'asset');
    draft.customProfile.currency = defaultCurrencySymbol(baseCurrency);
    showAdvancedSettings = false;
    resetSampleState();
  }

  function startInstitutionAccount(institutionId = '') {
    editorMode = 'institution';
    editingAccountId = null;
    draft = newDraft(institutionId);
    draft.customProfile.currency = defaultCurrencySymbol(baseCurrency);
    showAdvancedSettings = false;
    resetSampleState();
  }

  function startCustomAccount() {
    editorMode = 'custom';
    editingAccountId = null;
    draft = newDraft('', 'asset');
    draft.customProfile.currency = defaultCurrencySymbol(baseCurrency);
    showAdvancedSettings = false;
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
    const nextTemplateKind = templateKind(institutionId);

    draft = {
      ...draft,
      institutionId,
      kind:
        draft.institutionId && draft.kind !== templateKind(draft.institutionId)
          ? draft.kind
          : nextTemplateKind,
      subtype:
        draft.institutionId && draft.kind !== templateKind(draft.institutionId)
          ? draft.subtype
          : subtypeMatchesKind(draft.subtype, nextTemplateKind)
            ? draft.subtype
            : '',
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
      kind: normalizeBalanceSheetKind(account.kind),
      displayName: account.displayName,
      ledgerAccount: account.ledgerAccount,
      subtype: account.subtype ?? '',
      institutionId: account.institutionId ?? '',
      last4: account.last4 ?? '',
      openingBalance: account.openingBalance ?? '',
      openingBalanceDate: account.openingBalanceDate ?? '',
      customProfile: profileDraftFromAccount(account)
    };
    showAdvancedSettings = false;
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
    dashboardBalances = Object.fromEntries(dashboardData.balances.map((balance) => [balance.id, balance]));
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
      subtype: draft.subtype || null,
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
          ledgerAccount: payload.ledgerAccount,
          subtype: payload.subtype,
          last4: payload.last4,
          openingBalance: payload.openingBalance,
          openingBalanceDate: payload.openingBalanceDate
        });
      } else if (editorMode === 'custom') {
        await apiPost('/api/workspace/custom-import-accounts', {
          accountId: payload.accountId,
          displayName: payload.displayName,
          ledgerAccount: payload.ledgerAccount,
          subtype: payload.subtype,
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
  $: draftSubtypePreview = accountSubtypeLabel({
    subtype: draft.subtype,
    kind: draft.kind,
    displayName: draft.displayName,
    institutionDisplayName: templateById(draft.institutionId)?.displayName ?? null,
    ledgerAccount: effectiveLedgerAccount(draft)
  });
  $: needsSetupCount = trackedAccounts.filter((account) => balanceTrust(account).tone === 'warn').length;

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
        Create and edit the assets and liabilities you want reflected in balances and net worth here. Rules and Review
        stay focused on income and expense categorization.
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
        <span class="stat-kicker">Needs setup</span>
        <strong>{needsSetupCount}</strong>
      </div>
    </div>
  </section>

  <section class="grid-2 accounts-layout">
    <article class="view-card editor-card">
      <div class="section-head editor-head">
        <div>
          <p class="eyebrow">{editingAccountId ? 'Edit tracked account' : 'Create tracked account'}</p>
          <h3>{editorTitle}</h3>
          <p class="muted">
            {#if editorMode === 'institution'}
              Choose the statement source, then say whether this is something you own or something you owe.
            {:else if editorMode === 'custom'}
              Set up a CSV import for an asset or liability, then preview a real file in Import before applying it.
            {:else}
              Add something you own or owe even if you are tracking the balance manually for now.
            {/if}
          </p>
        </div>
        <a class="text-link" href="/accounts">Back to accounts</a>
      </div>

      <div class="mode-switch">
        <button class:active={editorMode === 'manual'} type="button" on:click={startManualAccount}>Manual</button>
        <button class:active={editorMode === 'institution'} type="button" on:click={() => startInstitutionAccount(draft.institutionId)}>
          Supported
        </button>
        <button class:active={editorMode === 'custom'} type="button" on:click={startCustomAccount}>Custom CSV</button>
      </div>

      <section class="kind-panel">
        <p class="selection-label">What are you tracking?</p>
        <div class="kind-choice-grid">
          {#each BALANCE_SHEET_KIND_OPTIONS as kindOption}
            <button
              class:active={draft.kind === kindOption.value}
              class="kind-choice"
              type="button"
              on:click={() => setDraftKind(kindOption.value)}
            >
              <span class="kind-choice-label">{kindOption.label}</span>
              <span class="kind-choice-note">{accountKindHelp(kindOption.value)}</span>
            </button>
          {/each}
        </div>
      </section>

      {#if editorMode === 'institution'}
        <div class="field">
          <label for="institutionId">Institution</label>
          <select id="institutionId" value={draft.institutionId} on:change={(e) => updateInstitution((e.currentTarget as HTMLSelectElement).value)}>
            <option value="">Select...</option>
            {#each institutionTemplates as template}
              <option value={template.id}>{template.displayName}</option>
            {/each}
          </select>
          <p class="muted small">The institution controls the parser. Asset vs liability is set above.</p>
        </div>
      {/if}

      <div class="field grid-2 compact">
        <div class="field">
          <label for="displayName">Account name</label>
          <input
            id="displayName"
            value={draft.displayName}
            placeholder={accountNamePlaceholder()}
            on:input={(e) => updateDraft({ displayName: (e.currentTarget as HTMLInputElement).value })}
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

      <div class="field">
        <label for="subtype">Account subtype</label>
        <select id="subtype" value={draft.subtype} on:change={(e) => updateDraft({ subtype: (e.currentTarget as HTMLSelectElement).value })}>
          <option value="">Keep it broad for now</option>
          {#each subtypeOptionsForKind(draft.kind) as option}
            <option value={option.value}>{option.label}</option>
          {/each}
        </select>
        <p class="muted small">{subtypeHelperText()}</p>
      </div>

      <div class="field grid-2 compact">
        <div class="field">
          <label for="openingBalance">Opening balance</label>
          <input
            id="openingBalance"
            value={draft.openingBalance}
            placeholder={openingBalancePlaceholder()}
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

      <p class="secondary-note">{openingBalanceHint(draft.kind)}</p>

      <details class="advanced-panel" bind:open={showAdvancedSettings}>
        <summary>Advanced account settings</summary>

        <div class="field">
          <label for="ledgerAccount">Advanced account name</label>
          <input
            id="ledgerAccount"
            value={draft.ledgerAccount}
            placeholder={suggestedLedgerAccount(draft) || (draft.kind === 'liability' ? 'Liabilities:Car:Loan' : 'Assets:House:Savings')}
            on:input={(e) => updateDraft({ ledgerAccount: (e.currentTarget as HTMLInputElement).value })}
          />
        </div>

        <div class="selection-summary compact-summary">
          <p class="selection-label">Accounting name in use</p>
          <p class="selection-value">{effectiveLedgerAccount(draft) || 'Choose an account name first'}</p>
          <p class="muted">Leave this blank if the suggested name is good enough. You only need it when you want a custom internal account path.</p>
        </div>
      </details>

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
        <p class="selection-label">What this adds to Accounts</p>
        <p class="selection-value">
          {draft.displayName.trim() || 'Fill in the account details to continue'}
          {#if draft.displayName.trim()}
            {` · ${draftSubtypePreview}`}
          {/if}
        </p>
        <p class="muted">
          {#if editorMode === 'institution'}
            Save this once, then use Import to bring in recent statement activity.
          {:else if editorMode === 'custom'}
            Save the mapping here, then use Import to preview a real statement before applying it.
          {:else}
            This account will show up in balances and net worth even before you attach import automation.
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
    </article>

    <article class="view-card inventory-card">
      <div class="section-head">
        <div>
          <p class="eyebrow">Inventory</p>
          <h3>Tracked accounts</h3>
          <p class="muted">Edit something you already track, or use the shortcuts below to start a new asset or liability.</p>
        </div>
      </div>

      <div class="quick-actions">
        <button class="btn btn-primary" type="button" on:click={startManualAccount}>Add manual account</button>
        <button class="btn" type="button" on:click={() => startInstitutionAccount()}>Add supported account</button>
        <button class="btn" type="button" on:click={startCustomAccount}>Add custom CSV</button>
      </div>

      {#if trackedAccounts.length === 0}
        <div class="empty-panel">
          <h4>No accounts yet</h4>
          <p>Start with something you own or owe, then add a starting balance or import setup so totals are grounded.</p>
        </div>
      {:else}
        <div class="account-list">
          {#each trackedAccounts as account}
            <article class="account-card">
              <div class="account-card-head">
                <div>
                  <h4>{account.displayName}</h4>
                  <p class="muted">{account.institutionDisplayName || 'Tracked manually'}</p>
                </div>
                <button class="inline-link" type="button" on:click={() => editAccount(account)}>Edit</button>
              </div>

              <div class="pill-row">
                <span class={`pill ${balanceTrust(account).tone === 'warn' ? 'warn' : balanceTrust(account).tone === 'ok' ? 'ok' : ''}`}>
                  {balanceTrust(account).shortLabel}
                </span>
                <span class:ok={account.importConfigured} class="pill">{modeLabel(account)}</span>
                <span class={`pill subtype-pill ${subtypeBadgeTone(account)}`}>{subtypeBadgeLabel(account)}</span>
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
                  <p class="metric-label">Balance coverage</p>
                  <p class="metric-value">{balanceTrust(account).label}</p>
                </div>
              </div>

              <p class="muted small account-card-note">{balanceTrust(account).note}</p>
              {#if describeAccountSubtype(account).source === 'suggested'}
                <p class="muted small account-card-note">
                  Subtype is only suggested right now. Save the account if you want that subtype stored explicitly.
                </p>
              {/if}
              <p class="muted small account-card-note">
                Starting balance:
                {#if account.openingBalance}
                  {formatStoredAmount(account.openingBalance)}
                  {#if account.openingBalanceDate}
                    on {shortDate(account.openingBalanceDate)}
                  {/if}
                {:else}
                  Not set
                {/if}
              </p>

              <details class="advanced-panel">
                <summary>Accounting details</summary>
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
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(22rem, 0.88fr);
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

  .editor-head {
    margin-bottom: 0;
  }

  .quick-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-bottom: 1rem;
  }

  .text-link {
    color: var(--brand-strong);
    text-decoration: none;
    font-weight: 700;
  }

  .text-link:hover {
    text-decoration: underline;
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

  .inline-link {
    display: inline-flex;
    align-items: center;
    padding: 0.48rem 0.8rem;
    border-radius: 999px;
    border: 1px solid rgba(10, 61, 89, 0.12);
    background: rgba(255, 255, 255, 0.94);
    color: var(--brand-strong);
    font-weight: 700;
    cursor: pointer;
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

  .account-card-note {
    margin: 0;
    line-height: 1.5;
  }

  .editor-card {
    display: grid;
    gap: 1rem;
    background:
      radial-gradient(circle at top right, rgba(189, 231, 217, 0.28), transparent 34%),
      linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(247, 252, 249, 0.9));
  }

  .inventory-card {
    display: grid;
    gap: 0.95rem;
  }

  .kind-panel {
    display: grid;
    gap: 0.7rem;
  }

  .kind-choice-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
  }

  .kind-choice {
    display: grid;
    gap: 0.28rem;
    padding: 0.95rem 1rem;
    border-radius: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.12);
    background: rgba(255, 255, 255, 0.82);
    color: inherit;
    text-align: left;
    cursor: pointer;
    transition:
      border-color 120ms ease,
      box-shadow 120ms ease,
      transform 120ms ease;
  }

  .kind-choice.active {
    border-color: rgba(12, 103, 138, 0.36);
    box-shadow: 0 14px 28px rgba(12, 103, 138, 0.12);
    transform: translateY(-1px);
  }

  .kind-choice-label {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1rem;
    color: var(--brand-strong);
  }

  .kind-choice-note {
    color: var(--muted-foreground);
    font-size: 0.92rem;
    line-height: 1.5;
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

  .advanced-panel {
    border: 1px solid rgba(10, 61, 89, 0.1);
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.72);
    padding: 0.9rem 1rem;
  }

  .advanced-panel summary {
    cursor: pointer;
    font-weight: 700;
    color: var(--brand-strong);
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

  .selection-summary {
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.72);
    padding: 0.9rem 1rem;
  }

  .compact-summary {
    margin-top: 0.8rem;
    padding: 0.8rem 0.9rem;
  }

  .selection-label {
    margin: 0 0 0.2rem;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .selection-value {
    margin: 0 0 0.25rem;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.1rem;
    color: var(--brand-strong);
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

  .subtype-pill.asset {
    background: rgba(15, 95, 136, 0.08);
    color: var(--brand-strong);
    border-color: rgba(15, 95, 136, 0.14);
  }

  .subtype-pill.liability {
    background: rgba(154, 81, 41, 0.12);
    color: #9a5129;
    border-color: rgba(154, 81, 41, 0.18);
  }

  .subtype-pill.suggested {
    background: rgba(199, 146, 43, 0.12);
    color: #8a5b0f;
    border-color: rgba(199, 146, 43, 0.2);
  }

  .subtype-pill.broad {
    background: rgba(10, 61, 89, 0.06);
    color: var(--muted-foreground);
    border-color: rgba(10, 61, 89, 0.1);
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

    .accounts-layout,
    .kind-choice-grid,
    .hero-stats,
    .account-metrics,
    .mapping-grid,
    .grid-4 {
      grid-template-columns: 1fr;
    }
  }
</style>
