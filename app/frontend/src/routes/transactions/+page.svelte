<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import { showUndoToast } from '$lib/undo-toast';
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';
  import { describeBalanceTrust } from '$lib/account-trust';
  import { normalizeCurrencyCode } from '$lib/currency-format';

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
    manualResolutionToken?: string | null;
    manualResolutionNote?: string | null;
    clearingStatus?: 'unmarked' | 'pending' | 'cleared';
    headerLine?: string;
    journalPath?: string;
    matchId?: string | null;
  };

  type AccountRegister = {
    baseCurrency: string;
    accountId: string;
    currentBalance: number;
    entryCount: number;
    transactionCount: number;
    latestTransactionDate: string | null;
    latestActivityDate: string | null;
    hasOpeningBalance: boolean;
    hasTransactionActivity: boolean;
    hasBalanceSource: boolean;
    entries: RegisterEntry[];
  };

  type ActivityTransaction = {
    date: string;
    payee: string;
    accountLabel: string;
    importAccountId: string | null;
    category: string;
    categoryAccount: string;
    amount: number;
    isIncome: boolean;
    isUnknown: boolean;
  };

  type ActivityTopTransaction = {
    date: string;
    payee: string;
    amount: number;
    accountLabel: string;
  };

  type ActivitySummary = {
    periodTotal: number;
    periodCount: number;
    averageAmount: number;
    priorPeriodTotal: number | null;
    priorPeriodCount: number | null;
    deltaAmount: number | null;
    deltaPercent: number | null;
    rollingMonthlyAverage: number | null;
    rollingMonths: number;
    topTransaction: ActivityTopTransaction | null;
  };

  type ActivityResult = {
    baseCurrency: string;
    period: string | null;
    category: string | null;
    month: string | null;
    transactions: ActivityTransaction[];
    totalCount: number;
    summary?: ActivitySummary | null;
  };

  type ActivityDateGroup = {
    header: string;
    transactions: ActivityTransaction[];
  };

  type ActionLink = {
    href: string;
    label: string;
  };

  type RegisterAction = ActionLink & {
    note: string;
  };

  type ManualResolutionPreview = {
    resolutionToken: string;
    date: string;
    payee: string;
    amount: number;
    baseCurrency: string;
    sourceAccountId: string;
    sourceAccountName: string;
    destinationAccountId: string;
    destinationAccountName: string;
    fromAccountId: string;
    fromAccountName: string;
    toAccountId: string;
    toAccountName: string;
    warning: string;
  };

  type ManualResolutionApplyResult = {
    applied: boolean;
    backupPath: string;
    journalPath: string;
    date: string;
    payee: string;
    amount: number;
    sourceAccountId: string;
    sourceAccountName: string;
    destinationAccountId: string;
    destinationAccountName: string;
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

  // Activity view state
  let activityMode = false;
  let activityResult: ActivityResult | null = null;
  let activityLoading = false;
  let activityError = '';
  let activityPeriod: 'this-month' | 'last-30' | 'last-3-months' = 'last-3-months';
  let activityCategory: string | null = null;
  let activityMonth: string | null = null;
  let postedEntries: RegisterEntry[] = [];
  let pendingEntries: RegisterEntry[] = [];
  let pendingTransferCount = 0;
  let pendingTransferTotal = 0;
  let balanceWithPending: number | null = null;
  let latestPostedActivityDate: string | null = null;
  let registerUnknownCount = 0;
  let primaryAction: RegisterAction | null = null;
  let secondaryActions: ActionLink[] = [];
  let manualResolutionOpen = false;
  let manualResolutionEntry: RegisterEntry | null = null;
  let manualResolutionPreview: ManualResolutionPreview | null = null;
  let manualResolutionError = '';
  let manualResolutionSuccess = '';
  let manualResolutionLoading: 'preview' | 'apply' | null = null;

  // Transaction actions menu state
  let actionMenuEntry: RegisterEntry | null = null;
  let confirmDeleteEntry: RegisterEntry | null = null;
  let confirmUnmatchEntry: RegisterEntry | null = null;
  let actionError = '';
  let actionBusy = false;

  function entryHasActions(entry: RegisterEntry): boolean {
    return !entry.isOpeningBalance;
  }

  function canDelete(entry: RegisterEntry): boolean {
    return !entry.isOpeningBalance;
  }

  function canRecategorize(entry: RegisterEntry): boolean {
    if (entry.isOpeningBalance || entry.isUnknown) return false;
    if (entry.transferState) return false;
    // Split transactions: more than 1 non-source detail line means split
    const categoryLines = entry.detailLines.filter((l) => l.kind !== 'source');
    if (categoryLines.length > 1) return false;
    return true;
  }

  function canUnmatch(entry: RegisterEntry): boolean {
    return !!entry.matchId;
  }

  function openActionMenu(entry: RegisterEntry, event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation();
    if (actionMenuEntry === entry) {
      actionMenuEntry = null;
    } else {
      actionMenuEntry = entry;
    }
  }

  function closeActionMenu() {
    actionMenuEntry = null;
  }

  async function executeDelete(entry: RegisterEntry) {
    if (!entry.headerLine || !entry.journalPath) return;
    actionBusy = true;
    actionError = '';
    try {
      const res = await apiPost<{ success: boolean; eventId: string | null }>('/api/transactions/delete', {
        journalPath: entry.journalPath,
        headerLine: entry.headerLine,
      });
      confirmDeleteEntry = null;
      closeActionMenu();
      const reloadRegister = () => loadRegister(selectedAccountId);
      if (res.eventId) showUndoToast(res.eventId, `Removed ${entry.payee} on ${entry.date}`, reloadRegister);
      await reloadRegister();
    } catch (e) {
      actionError = String(e);
    } finally {
      actionBusy = false;
    }
  }

  async function executeRecategorize(entry: RegisterEntry) {
    if (!entry.headerLine || !entry.journalPath) return;
    actionBusy = true;
    actionError = '';
    try {
      const res = await apiPost<{ success: boolean; eventId: string | null }>('/api/transactions/recategorize', {
        journalPath: entry.journalPath,
        headerLine: entry.headerLine,
      });
      closeActionMenu();
      const reloadRegister = () => loadRegister(selectedAccountId);
      if (res.eventId) showUndoToast(res.eventId, `Reset category on ${entry.payee}`, reloadRegister);
      await reloadRegister();
    } catch (e) {
      actionError = String(e);
    } finally {
      actionBusy = false;
    }
  }

  async function executeUnmatch(entry: RegisterEntry) {
    if (!entry.headerLine || !entry.journalPath || !entry.matchId) return;
    actionBusy = true;
    actionError = '';
    try {
      const res = await apiPost<{ success: boolean; eventId: string | null }>('/api/transactions/unmatch', {
        journalPath: entry.journalPath,
        headerLine: entry.headerLine,
        matchId: entry.matchId,
      });
      confirmUnmatchEntry = null;
      closeActionMenu();
      const reloadRegister = () => loadRegister(selectedAccountId);
      if (res.eventId) showUndoToast(res.eventId, `Undid match for ${entry.payee}`, reloadRegister);
      await reloadRegister();
    } catch (e) {
      actionError = String(e);
    } finally {
      actionBusy = false;
    }
  }

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
      currency: normalizeCurrencyCode(baseCurrency),
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

  function resetManualResolutionDialog() {
    manualResolutionOpen = false;
    manualResolutionEntry = null;
    manualResolutionPreview = null;
    manualResolutionError = '';
    manualResolutionLoading = null;
  }

  function handleManualResolutionOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      resetManualResolutionDialog();
    }
  }

  function selectedAccountTrust() {
    if (!selectedAccount) return null;
    return describeBalanceTrust({
      hasOpeningBalance: register?.hasOpeningBalance ?? Boolean(selectedAccount.openingBalance),
      hasTransactionActivity: register?.hasTransactionActivity ?? Boolean(register?.transactionCount ?? 0),
      hasBalanceSource:
        register?.hasBalanceSource ?? (Boolean(selectedAccount.openingBalance) || Boolean(register?.transactionCount ?? 0)),
      importConfigured: selectedAccount.importConfigured,
      openingBalanceDate: selectedAccount.openingBalanceDate,
      latestActivityDate: latestPostedActivityDate
    });
  }

  function registerPrimaryAction(account: TrackedAccount | null, unknownCount: number): RegisterAction | null {
    if (!account) return null;

    if (unknownCount > 0) {
      return {
        href: '/unknowns',
        label: unknownCount === 1 ? 'Review 1 transaction' : `Review ${unknownCount} transactions`,
        note: 'Some imported activity still needs a category before this register is fully clean.'
      };
    }

    if (account.importConfigured) {
      return {
        href: '/import',
        label: latestPostedActivityDate ? 'Import latest statement' : 'Import first statement',
        note: latestPostedActivityDate
          ? 'Bring in the newest statement to keep this register current.'
          : 'Bring in the first statement so this register has full transaction history instead of only a starting balance.'
      };
    }

    if (!account.openingBalance) {
      return {
        href: `/accounts/configure?accountId=${account.id}`,
        label: 'Set starting balance',
        note: 'Add a starting balance before relying on this manually tracked account in totals.'
      };
    }

    return {
      href: `/accounts/configure?accountId=${account.id}`,
      label: 'Edit account setup',
      note: 'Update this account when you want to change the starting balance or add import automation later.'
    };
  }

  function registerSecondaryActions(account: TrackedAccount | null): ActionLink[] {
    if (!account) return [];

    const actions: ActionLink[] = [{ href: '/accounts', label: 'Back to accounts' }];
    if (account.importConfigured) {
      actions.push({ href: `/accounts/configure?accountId=${account.id}`, label: 'Edit account' });
    } else {
      actions.push({ href: '/accounts/configure?mode=institution', label: 'Add import-ready account' });
    }
    return actions;
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

  function monthTitle(month: string): string {
    const parsed = new Date(`${month}-01T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(parsed);
  }

  function activityShortDate(value: string): string {
    const parsed = new Date(`${value}T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
  }

  function truncatePayee(payee: string, max = 50): string {
    if (payee.length <= max) return payee;
    return payee.slice(0, max - 1) + '…';
  }

  function categoryDisplayName(category: string | null): string {
    if (!category) return '';
    const parts = category.split(':');
    if (parts.length <= 1) return category;
    return parts
      .slice(1)
      .map((segment) => segment.replace(/_/g, ' '))
      .join(' / ');
  }

  function categoryLeadingSegment(category: string | null): string {
    if (!category) return '';
    return category.split(':')[0] ?? '';
  }

  function periodPresetLabel(period: 'this-month' | 'last-30' | 'last-3-months'): string {
    if (period === 'this-month') return 'This month';
    if (period === 'last-30') return 'Last 30 days';
    return 'Last 3 months';
  }

  type ActivityHeroCopy = {
    eyebrow: string;
    title: string;
    subtitle: string;
  };

  function buildActivityHero(
    category: string | null,
    month: string | null,
    period: 'this-month' | 'last-30' | 'last-3-months'
  ): ActivityHeroCopy {
    if (category) {
      const leading = categoryLeadingSegment(category);
      const eyebrow = leading === 'Expenses'
        ? 'Spending category'
        : leading === 'Income'
        ? 'Income category'
        : 'Activity';
      const title = categoryDisplayName(category) || category;
      const subtitle = month ? monthTitle(month) : periodPresetLabel(period);
      return { eyebrow, title, subtitle };
    }
    if (month) {
      return {
        eyebrow: 'Activity',
        title: monthTitle(month),
        subtitle: 'All cross-account spending and income'
      };
    }
    return {
      eyebrow: 'Transactions',
      title: 'All activity',
      subtitle: periodPresetLabel(period)
    };
  }

  function isCurrentPeriodSingleMonth(month: string | null): boolean {
    return month !== null;
  }

  function nounForCategory(category: string | null, count: number): string {
    const plural = count !== 1;
    const leading = categoryLeadingSegment(category);
    if (leading === 'Expenses') return plural ? 'purchases' : 'purchase';
    if (leading === 'Income') return plural ? 'deposits' : 'deposit';
    return plural ? 'transactions' : 'transaction';
  }

  function mixedSigns(transactions: ActivityTransaction[]): boolean {
    let hasPositive = false;
    let hasNegative = false;
    for (const tx of transactions) {
      if (tx.amount > 0) hasPositive = true;
      else if (tx.amount < 0) hasNegative = true;
      if (hasPositive && hasNegative) return true;
    }
    return false;
  }

  function priorComparisonLabel(month: string | null): string {
    return isCurrentPeriodSingleMonth(month) ? 'Last month' : 'Prior period';
  }

  type DeltaPresentation = {
    arrow: string;
    className: string;
    displayPercent: number;
  };

  function presentDelta(
    periodTotal: number,
    priorTotal: number | null,
    category: string | null
  ): DeltaPresentation | null {
    if (priorTotal === null) return null;

    const leading = categoryLeadingSegment(category);

    // Mixed/all-activity views sum income and outflows together. A percentage
    // change on that net total is mathematically defined but hard to read —
    // the sign can flip with small swings and the base can be near zero. Skip
    // the delta entirely; the prior total itself is the comparison line.
    if (leading !== 'Expenses' && leading !== 'Income') return null;

    // For expenses, the user thinks in absolute-spending terms. Normalize to
    // positive "how much was spent" values before computing the percent change
    // so that `periodTotal` going from -$2,917 to -$2,817 reads as spending
    // dropping 3% (↓3% green), not the signed delta flipping 3% in the other
    // direction (↑3% red).
    //
    // For income categories, signed totals already match intuition
    // (positive totals, positive delta = more income).
    const useAbs = leading === 'Expenses';
    const current = useAbs ? Math.abs(periodTotal) : periodTotal;
    const prior = useAbs ? Math.abs(priorTotal) : priorTotal;

    if (prior === 0) return null; // can't compute percent change from zero

    const signedPercent = ((current - prior) / Math.abs(prior)) * 100;
    if (signedPercent === 0) return null;

    const increasing = signedPercent > 0;
    const favorable = leading === 'Expenses' ? !increasing : increasing;

    return {
      arrow: increasing ? '↑' : '↓',
      className: favorable ? 'positive' : 'negative',
      displayPercent: Math.abs(signedPercent)
    };
  }

  function groupActivityByDate(transactions: ActivityTransaction[]): ActivityDateGroup[] {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    const todayStr = today.toISOString().slice(0, 10);
    const yesterdayStr = yesterday.toISOString().slice(0, 10);

    const groups: ActivityDateGroup[] = [];
    let currentGroup: ActivityDateGroup | null = null;

    for (const tx of transactions) {
      const header = tx.date === todayStr ? 'Today'
        : tx.date === yesterdayStr ? 'Yesterday'
        : activityShortDate(tx.date);

      if (!currentGroup || currentGroup.header !== header) {
        currentGroup = { header, transactions: [] };
        groups.push(currentGroup);
      }
      currentGroup.transactions.push(tx);
    }
    return groups;
  }

  async function loadActivity() {
    activityLoading = true;
    activityError = '';

    const params = new URLSearchParams();
    if (activityMonth) {
      params.set('month', activityMonth);
    } else {
      params.set('period', activityPeriod);
    }
    if (activityCategory) {
      params.set('category', activityCategory);
    }

    try {
      activityResult = await apiGet<ActivityResult>(`/api/transactions/activity?${params.toString()}`);
      baseCurrency = activityResult.baseCurrency;
    } catch (e) {
      activityError = String(e);
      activityResult = null;
    } finally {
      activityLoading = false;
    }
  }

  function updateActivityUrl(replaceState = false) {
    const params = new URLSearchParams();
    params.set('view', 'activity');
    if (activityMonth) {
      params.set('month', activityMonth);
    } else if (activityPeriod !== 'last-3-months') {
      params.set('period', activityPeriod);
    }
    if (activityCategory) {
      params.set('category', activityCategory);
    }
    void goto(`/transactions?${params.toString()}`, {
      replaceState,
      noScroll: true,
      keepFocus: true
    });
  }

  function setActivityPeriod(preset: 'this-month' | 'last-30' | 'last-3-months') {
    activityPeriod = preset;
    activityMonth = null;
    updateActivityUrl(true);
    void loadActivity();
  }

  function clearActivityMonth() {
    activityMonth = null;
    updateActivityUrl(true);
    void loadActivity();
  }

  function clearActivityCategory() {
    activityCategory = null;
    updateActivityUrl(true);
    void loadActivity();
  }

  function switchToActivity() {
    activityMode = true;
    updateActivityUrl();
    void loadActivity();
  }

  function switchToRegister() {
    activityMode = false;
    const accountId = selectedAccountId || (trackedAccounts[0]?.id ?? '');
    if (accountId) {
      void syncSelection(accountId);
    } else {
      void goto('/transactions', { replaceState: true, noScroll: true, keepFocus: true });
    }
  }

  async function syncSelection(accountId: string, replaceState = false) {
    if (!accountId) return;
    if (accountId === selectedAccountId && register?.accountId === accountId) return;

    manualResolutionSuccess = '';
    resetManualResolutionDialog();
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

    const [accountsData] = await Promise.all([
      apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts'),
      loadAllAccounts()
    ]);
    trackedAccounts = accountsData.trackedAccounts;

    // Check for activity view mode
    const viewParam = $page.url.searchParams.get('view');
    if (viewParam === 'activity') {
      activityMode = true;
      activityCategory = $page.url.searchParams.get('category') || null;
      activityMonth = $page.url.searchParams.get('month') || null;
      const periodParam = $page.url.searchParams.get('period');
      if (periodParam === 'this-month' || periodParam === 'last-30' || periodParam === 'last-3-months') {
        activityPeriod = periodParam;
      }
      await loadActivity();
      return;
    }

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

  async function openManualResolution(entry: RegisterEntry) {
    if (!entry.manualResolutionToken) return;

    manualResolutionSuccess = '';
    manualResolutionEntry = entry;
    manualResolutionPreview = null;
    manualResolutionError = '';
    manualResolutionOpen = true;
    manualResolutionLoading = 'preview';

    try {
      manualResolutionPreview = await apiPost<ManualResolutionPreview>(
        '/api/transactions/manual-transfer-resolution/preview',
        {
          resolutionToken: entry.manualResolutionToken
        }
      );
      baseCurrency = manualResolutionPreview.baseCurrency;
    } catch (e) {
      manualResolutionError = String(e);
    } finally {
      manualResolutionLoading = null;
    }
  }

  async function confirmManualResolution() {
    const resolutionToken =
      manualResolutionPreview?.resolutionToken ?? manualResolutionEntry?.manualResolutionToken ?? null;
    if (!resolutionToken) return;

    manualResolutionError = '';
    manualResolutionLoading = 'apply';

    try {
      const result = await apiPost<ManualResolutionApplyResult>(
        '/api/transactions/manual-transfer-resolution/apply',
        {
          resolutionToken
        }
      );
      await loadRegister(selectedAccountId);
      manualResolutionSuccess = `Resolved manually: ${result.sourceAccountName} to ${result.destinationAccountName}.`;
      resetManualResolutionDialog();
    } catch (e) {
      manualResolutionError = String(e);
    } finally {
      manualResolutionLoading = null;
    }
  }

  // --- Clearing Status Toggle ---
  const CLEARING_TOOLTIPS: Record<string, string> = {
    cleared: 'Bank-confirmed',
    pending: 'Flagged',
    unmarked: 'Manual entry'
  };

  const CLEARING_CYCLE: Record<string, string> = {
    unmarked: 'pending',
    pending: 'cleared',
    cleared: 'unmarked'
  };

  async function toggleClearingStatus(entry: RegisterEntry, event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation();

    if (!entry.headerLine || !entry.journalPath) return;

    const previousStatus = entry.clearingStatus ?? 'unmarked';
    const nextStatus = CLEARING_CYCLE[previousStatus] as 'unmarked' | 'pending' | 'cleared';

    entry.clearingStatus = nextStatus;
    postedEntries = [...postedEntries];
    pendingEntries = [...pendingEntries];

    try {
      const result = await apiPost<{ newStatus: string; newHeaderLine: string }>(
        '/api/transactions/toggle-status',
        { journalPath: entry.journalPath, headerLine: entry.headerLine }
      );
      entry.clearingStatus = result.newStatus as 'unmarked' | 'pending' | 'cleared';
      entry.headerLine = result.newHeaderLine;
      postedEntries = [...postedEntries];
      pendingEntries = [...pendingEntries];
    } catch {
      entry.clearingStatus = previousStatus;
      postedEntries = [...postedEntries];
      pendingEntries = [...pendingEntries];
    }
  }

  // --- Add Transaction Form ---
  let showAddForm = false;
  let addDate = '';
  let addPayee = '';
  let addAmount = '';
  let addDestination = '';
  let addError = '';
  let addSubmitting = false;
  let addSuccess = '';
  let addDateEl: HTMLInputElement | null = null;
  let allAccounts: string[] = [];

  function todayISO(): string {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }

  function openAddForm() {
    addDate = todayISO();
    addPayee = '';
    addAmount = '';
    addDestination = '';
    addError = '';
    addSuccess = '';
    showAddForm = true;
    setTimeout(() => addDateEl?.focus(), 50);
  }

  function closeAddForm() {
    showAddForm = false;
    addError = '';
  }

  function handleAddFormKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeAddForm();
    }
  }

  async function submitAddTransaction() {
    if (!selectedAccountId || !addDate || !addPayee.trim() || !addAmount.trim() || !addDestination.trim()) {
      addError = 'All fields are required.';
      return;
    }
    addError = '';
    addSubmitting = true;
    try {
      const result = await apiPost<{ created: boolean; warning?: string | null; eventId?: string | null }>('/api/transactions/create', {
        trackedAccountId: selectedAccountId,
        date: addDate,
        payee: addPayee.trim(),
        amount: addAmount.trim(),
        destinationAccount: addDestination.trim()
      });
      addSuccess = `Added: ${addPayee.trim()} on ${addDate}${result.warning ? ` (${result.warning})` : ''}`;
      const reloadRegister = () => loadRegister(selectedAccountId);
      if (result.eventId) showUndoToast(result.eventId, `Added ${addPayee.trim()}`, reloadRegister);
      showAddForm = false;
      await reloadRegister();
    } catch (e) {
      addError = String(e);
    } finally {
      addSubmitting = false;
    }
  }

  async function loadAllAccounts() {
    try {
      const data = await apiGet<{ accounts: string[] }>('/api/accounts');
      allAccounts = data.accounts;
    } catch {
      // Non-critical, combobox will work without pre-loaded accounts
    }
  }

  $: selectedAccount = trackedAccounts.find((account) => account.id === selectedAccountId) ?? null;
  $: postedEntries = register?.entries.filter((entry) => entry.transferState !== 'pending') ?? [];
  $: pendingEntries = register?.entries.filter((entry) => entry.transferState === 'pending') ?? [];
  $: pendingTransferCount = pendingEntries.length;
  $: pendingTransferTotal = pendingEntries.reduce((sum, entry) => sum + entry.amount, 0);
  $: balanceWithPending = register ? register.currentBalance + pendingTransferTotal : null;
  $: latestPostedActivityDate = register?.latestTransactionDate ?? null;
  $: registerUnknownCount = postedEntries.filter((entry) => entry.isUnknown).length;
  $: primaryAction = registerPrimaryAction(selectedAccount, registerUnknownCount);
  $: secondaryActions = registerSecondaryActions(selectedAccount);
  $: activityGroups = groupActivityByDate(activityResult?.transactions ?? []);
  $: activityHero = buildActivityHero(activityCategory, activityMonth, activityPeriod);
  $: activitySummary = activityResult?.summary ?? null;
  $: activityPeriodIsMixed = mixedSigns(activityResult?.transactions ?? []);
  $: activityDeltaPresentation = presentDelta(
    activitySummary?.periodTotal ?? 0,
    activitySummary?.priorPeriodTotal ?? null,
    activityCategory
  );
  $: activityPriorLabel = priorComparisonLabel(activityMonth);
  $: activityPeriodNoun = nounForCategory(
    activityCategory,
    activitySummary?.periodCount ?? 0
  );

  onMount(async () => {
    loading = true;
    error = '';
    try {
      await Promise.all([load(), loadAllAccounts()]);
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

<svelte:window on:click={() => { if (actionMenuEntry) actionMenuEntry = null; }} />

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
{:else if !activityMode && trackedAccounts.length === 0}
  <section class="view-card transactions-hero">
    <p class="eyebrow">Transactions</p>
    <h2 class="page-title">{workspaceName || 'Workspace'} does not have any accounts yet</h2>
    <p class="subtitle">Add at least one tracked account before reviewing its transaction register.</p>
    <div class="actions">
      <a class="btn btn-primary" href="/accounts/configure?mode=manual">Add first account</a>
      <a class="text-link" href="/accounts">Open accounts</a>
    </div>
  </section>
{:else if activityMode}
  <section class="view-card transactions-hero activity-hero">
    <div class="hero-copy">
      <p class="eyebrow">{activityHero.eyebrow}</p>
      <h2 class="page-title">{activityHero.title}</h2>
      <p class="subtitle">{activityHero.subtitle}</p>
    </div>

    <div class="hero-side">
      <div class="view-toggle">
        <button class="view-toggle-btn active" type="button">All activity</button>
        <button class="view-toggle-btn" type="button" on:click={switchToRegister}>Account view</button>
      </div>
    </div>
  </section>

  <section class="view-card activity-filters-card">
    <div class="activity-filter-bar">
      {#if activityMonth}
        <div class="filter-chip-group">
          <span class="filter-label">Month</span>
          <span class="filter-chip">
            {monthTitle(activityMonth)}
            <button class="filter-clear" type="button" on:click={clearActivityMonth} aria-label="Clear month filter">&times;</button>
          </span>
        </div>
      {:else}
        <div class="activity-presets">
          <button class:active={activityPeriod === 'this-month'} on:click={() => setActivityPeriod('this-month')}>This month</button>
          <button class:active={activityPeriod === 'last-30'} on:click={() => setActivityPeriod('last-30')}>Last 30 days</button>
          <button class:active={activityPeriod === 'last-3-months'} on:click={() => setActivityPeriod('last-3-months')}>Last 3 months</button>
        </div>
      {/if}

      {#if activityCategory}
        <div class="filter-chip-group">
          <span class="filter-label">Category</span>
          <span class="filter-chip">
            {activityResult?.transactions[0]?.category || activityCategory.split(':').slice(1).join(' / ')}
            <button class="filter-clear" type="button" on:click={clearActivityCategory} aria-label="Clear category filter">&times;</button>
          </span>
        </div>
      {/if}
    </div>
  </section>

  {#if activityError}
    <section class="view-card">
      <p class="error-text">{activityError}</p>
    </section>
  {:else if activityLoading}
    <section class="view-card">
      <div class="empty-panel">
        <h4>Loading transactions</h4>
        <p>Fetching cross-account activity.</p>
      </div>
    </section>
  {:else if !activityResult || activityResult.transactions.length === 0}
    <section class="view-card">
      <div class="empty-panel">
        <h4>No transactions match these filters</h4>
        <p>Try a different time range or clear the category filter to see more.</p>
        <div class="actions" style="margin-top: 0.75rem;">
          {#if activityCategory || activityMonth}
            <button class="btn" type="button" on:click={() => { activityCategory = null; activityMonth = null; activityPeriod = 'last-3-months'; updateActivityUrl(true); void loadActivity(); }}>Clear all filters</button>
          {/if}
        </div>
      </div>
    </section>
  {:else}
    {#if activitySummary}
      <section class="view-card explanation-header-card">
        <p class="explanation-period">
          {formatCurrency(activitySummary.periodTotal)} across {activitySummary.periodCount} {activityPeriodNoun}{#if !activityPeriodIsMixed && activitySummary.periodCount > 0} · avg {formatCurrency(activitySummary.averageAmount)} each{/if}
        </p>

        {#if activitySummary.priorPeriodTotal !== null && activitySummary.priorPeriodCount !== null}
          <p class="explanation-prior">
            {activityPriorLabel}: {formatCurrency(activitySummary.priorPeriodTotal)} across {activitySummary.priorPeriodCount} {nounForCategory(activityCategory, activitySummary.priorPeriodCount)}{#if activityDeltaPresentation} — <span class={activityDeltaPresentation.className}>{activityDeltaPresentation.arrow}{activityDeltaPresentation.displayPercent.toFixed(0)}%</span>{/if}
          </p>
        {/if}

        {#if activitySummary.rollingMonthlyAverage !== null}
          <p class="explanation-baseline">
            6-month average: {formatCurrency(activitySummary.rollingMonthlyAverage)}/mo
          </p>
        {/if}

        {#if activitySummary.topTransaction && activitySummary.periodCount > 1}
          <p class="explanation-top">
            Biggest: {formatCurrency(Math.abs(activitySummary.topTransaction.amount))} at {truncatePayee(activitySummary.topTransaction.payee, 30)} on {activityShortDate(activitySummary.topTransaction.date)}
          </p>
        {/if}
      </section>
    {/if}

    <section class="view-card activity-list-card">
      <div class="section-head">
        <div>
          <p class="eyebrow">Results</p>
          <h3>{activityResult.totalCount} {activityResult.totalCount === 1 ? 'transaction' : 'transactions'}</h3>
        </div>
      </div>

      <div class="activity-list">
        {#each activityGroups as group, gi}
          <div class="date-group" class:date-group-first={gi === 0}>
            <h4 class="date-header">{group.header}</h4>
            {#each group.transactions as tx}
              <div class="activity-row">
                <div class="activity-main">
                  <div class="activity-headline">
                    {#if !activityCategory}
                      <span class="activity-category-pill">{tx.category}</span>
                    {/if}
                    <span class="activity-payee" title={tx.payee}>{truncatePayee(tx.payee)}</span>
                  </div>
                  <p class="activity-meta">
                    {activityShortDate(tx.date)} · {tx.accountLabel}
                  </p>
                </div>
                <div class="activity-side">
                  <p class:positive={tx.amount > 0} class:negative={tx.amount < 0} class="activity-amount">
                    {formatCurrency(tx.amount, { signed: true })}
                  </p>
                  {#if tx.isUnknown}
                    <a class="pill warn" href="/unknowns">Needs review</a>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/each}
      </div>
    </section>
  {/if}
{:else}
  <section class="view-card transactions-hero">
    <div class="hero-copy">
      <p class="eyebrow">Transactions</p>
      <h2 class="page-title">{selectedAccount?.displayName || 'Account register'}</h2>
      <p class="subtitle">{selectedAccountTrust()?.note || 'Review recent activity and running balances for this account.'}</p>
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
      <div class="view-toggle">
        <button class="view-toggle-btn" type="button" on:click={switchToActivity}>All activity</button>
        <button class="view-toggle-btn active" type="button">Account view</button>
      </div>

      <div class="field">
        <label for="account-select">Account</label>
        <select id="account-select" bind:value={selectedAccountId} on:change={handleAccountChange}>
          {#each trackedAccounts as account}
            <option value={account.id}>{account.displayName}</option>
          {/each}
        </select>
      </div>

      <div class="hero-actions">
        <button class="btn" type="button" on:click={openAddForm}>Add transaction</button>
        {#if primaryAction}
          <a class="btn btn-primary" href={primaryAction.href}>{primaryAction.label}</a>
        {/if}
        {#each secondaryActions as action}
          <a class="text-link" href={action.href}>{action.label}</a>
        {/each}
      </div>

      {#if primaryAction}
        <p class="supporting-note">{primaryAction.note}</p>
      {/if}
    </div>
  </section>

  {#if manualResolutionSuccess}
    <section class="view-card result-card">
      <p class="eyebrow">Resolved</p>
      <h3>Transfer resolved manually</h3>
      <p class="section-note">{manualResolutionSuccess} The missing side was added because no imported counterpart was expected.</p>
    </section>
  {/if}

  {#if addSuccess}
    <section class="view-card result-card">
      <p class="eyebrow">Transaction Added</p>
      <h3>Manual entry created</h3>
      <p class="section-note">{addSuccess}</p>
    </section>
  {/if}

  {#if showAddForm}
    <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
    <section class="view-card add-txn-card" role="form" on:keydown={handleAddFormKeydown}>
      <div class="section-head">
        <div>
          <p class="eyebrow">New Transaction</p>
          <h3>Add a manual entry</h3>
        </div>
        <button class="btn" type="button" on:click={closeAddForm}>Cancel</button>
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
            allowCreate={false}
            onChange={(account) => (addDestination = account)}
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
          on:click={() => void submitAddTransaction()}
        >
          {addSubmitting ? 'Saving...' : 'Save transaction'}
        </button>
      </div>
    </section>
  {/if}

  <section class="summary-grid">
    <article class="view-card summary-card">
      <p class="stat-label">Balance coverage</p>
      <p class="stat-value">{selectedAccountTrust()?.label || 'No balance yet'}</p>
      <p class="stat-note">{selectedAccountTrust()?.note || 'Add activity or a starting balance to build this register.'}</p>
    </article>

    <article class="view-card summary-card summary-balance-card">
      <p class="stat-label">Current balance</p>
      <p class:positive={(register?.currentBalance ?? 0) > 0} class:negative={(register?.currentBalance ?? 0) < 0} class="stat-value">
        {formatCurrency(register?.currentBalance ?? null)}
      </p>
      <p class="stat-note">
        {selectedAccount?.institutionDisplayName || 'Tracked account'}{#if selectedAccount?.last4} •••• {selectedAccount.last4}{/if}
      </p>
    </article>

    <article class="view-card summary-card summary-balance-card summary-balance-pending">
      <p class="stat-label">Balance with pending</p>
      <p class:positive={(balanceWithPending ?? 0) > 0} class:negative={(balanceWithPending ?? 0) < 0} class="stat-value">
        {formatCurrency(balanceWithPending)}
      </p>
      <p class="stat-note">
        {#if pendingTransferCount > 0}
          {countLabel(pendingTransferCount, 'pending transfer')} worth {formatCurrency(pendingTransferTotal, { signed: true })} still waiting to settle.
        {:else}
          Matches current balance when nothing is pending.
        {/if}
      </p>
    </article>

    <article class="view-card summary-card">
      <p class="stat-label">Latest activity</p>
      <p class="stat-value">{latestPostedActivityDate ? shortDate(latestPostedActivityDate) : 'No activity yet'}</p>
      <p class="stat-note">
        {#if latestPostedActivityDate}
          Posted to this {selectedAccount?.kind || 'account'} register.
        {:else if pendingTransferCount > 0}
          Pending transfers are above while posted activity is still empty.
        {:else}
          Posted activity will appear here after the first statement import.
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
        <p class="pending-banner-note">
          Current balance remains {formatCurrency(register?.currentBalance ?? null)} until the missing side is imported or resolved.
        </p>
      </div>

      <div class="pending-header" aria-hidden="true">
        <span></span>
        <span>Date</span>
        <span>Description</span>
        <span class="align-right">Amount</span>
        <span>Status</span>
        <span></span>
      </div>

      <div class="pending-list">
        {#each pendingEntries as entry}
          <details class="pending-row">
            <summary class="pending-summary">
              <button
                class="clearing-indicator clearing-{entry.clearingStatus ?? 'unmarked'}"
                title={CLEARING_TOOLTIPS[entry.clearingStatus ?? 'unmarked']}
                on:click={(e) => toggleClearingStatus(entry, e)}
                type="button"
              ></button>
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
                {#if entry.manualResolutionToken}
                  This transfer stays pending until the matching import arrives. Resolve it manually only when no imported counterpart is expected.
                {:else}
                  This transfer stays in the pending section until the imported transaction lands and replaces it in the register.
                {/if}
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

              {#if entry.manualResolutionToken}
                <div class="pending-actions">
                  <button class="btn pending-secondary-action" type="button" on:click={() => void openManualResolution(entry)}>
                    Resolve manually
                  </button>
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
        <p class="eyebrow">Posted</p>
        <h3>Posted register</h3>
      </div>
      <p class="section-note">Imported activity, manual transfer resolutions, and opening balances change this running balance.</p>
    </div>

    {#if registerLoading}
      <div class="empty-panel">
        <h4>Loading transactions</h4>
        <p>Refreshing this account’s register.</p>
      </div>
    {:else if !register || postedEntries.length === 0}
      <div class="empty-panel">
        <h4>No posted activity yet</h4>
        <p>
          {#if pendingTransferCount > 0}
            Pending transfers are listed above. Posted transactions and opening-balance history will appear here after import or manual resolution.
          {:else}
            Once this account has posted transactions or an opening balance, the register will appear here.
          {/if}
        </p>
      </div>
    {:else}
      <div class="register-header" aria-hidden="true">
        <span></span>
        <span>Date</span>
        <span>Description</span>
        <span class="align-right">Amount</span>
        <span class="align-right">Balance</span>
        <span></span>
      </div>

      <div class="register-list">
        {#each postedEntries as entry}
          <details class:opening-row={entry.isOpeningBalance} class="register-row">
            <summary class="register-summary">
              <button
                class="clearing-indicator clearing-{entry.clearingStatus ?? 'unmarked'}"
                title={CLEARING_TOOLTIPS[entry.clearingStatus ?? 'unmarked']}
                on:click={(e) => toggleClearingStatus(entry, e)}
                type="button"
              ></button>
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
                  {#if entry.transferState === 'settled_grouped'}
                    <span class="pill">Grouped transfer</span>
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

              {#if entryHasActions(entry)}
                <div class="register-cell register-actions">
                  <button
                    class="action-menu-btn"
                    title="Actions"
                    type="button"
                    on:click={(e) => openActionMenu(entry, e)}
                  >⋮</button>
                  {#if actionMenuEntry === entry}
                    <div class="action-menu-popover">
                      {#if canDelete(entry)}
                        <button class="action-menu-item danger" type="button" on:click={(e) => { e.stopPropagation(); closeActionMenu(); confirmDeleteEntry = entry; }}>
                          Remove transaction
                        </button>
                      {/if}
                      {#if canRecategorize(entry)}
                        <button class="action-menu-item" type="button" on:click={(e) => { e.stopPropagation(); closeActionMenu(); void executeRecategorize(entry); }}>
                          Reset category
                        </button>
                      {/if}
                      {#if canUnmatch(entry)}
                        <button class="action-menu-item" type="button" on:click={(e) => { e.stopPropagation(); closeActionMenu(); confirmUnmatchEntry = entry; }}>
                          Undo match
                        </button>
                      {/if}
                    </div>
                  {/if}
                </div>
              {:else}
                <span></span>
              {/if}
            </summary>

            <div class="register-details">
              {#if entry.isOpeningBalance}
                <p class="details-note">This entry anchors running balances for the account until more history is backfilled.</p>
              {/if}

              {#if entry.transferState === 'settled_grouped'}
                <p class="details-note">This imported row settled as part of a grouped transfer, so it no longer counts as pending.</p>
              {/if}

              {#if entry.manualResolutionNote}
                <p class="details-note manual-resolution-note">{entry.manualResolutionNote}</p>
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

<DialogPrimitive.Root bind:open={manualResolutionOpen} onOpenChange={handleManualResolutionOpenChange}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="manual-resolution-backdrop" />

    <DialogPrimitive.Content
      class="manual-resolution-modal"
      aria-labelledby="manual-resolution-title"
      aria-describedby="manual-resolution-description"
    >
      <h3 id="manual-resolution-title">Resolve manually</h3>
      <p id="manual-resolution-description" class="muted">
        Add the missing side of this transfer only when no imported counterpart is expected.
      </p>

      {#if manualResolutionLoading === 'preview'}
        <div class="empty-panel">
          <h4>Loading preview</h4>
          <p>Validating the pending transfer and building the missing side.</p>
        </div>
      {:else if manualResolutionPreview}
        <div class="manual-resolution-preview">
          <div class="manual-resolution-grid">
            <div>
              <p class="stat-label">From</p>
              <p>{manualResolutionPreview.fromAccountName}</p>
            </div>
            <div>
              <p class="stat-label">To</p>
              <p>{manualResolutionPreview.toAccountName}</p>
            </div>
            <div>
              <p class="stat-label">Date</p>
              <p>{shortDate(manualResolutionPreview.date)}</p>
            </div>
            <div>
              <p class="stat-label">Amount</p>
              <p>{formatCurrency(manualResolutionPreview.amount)}</p>
            </div>
          </div>

          <div class="detail-line preview-payee">
            <p>{manualResolutionPreview.payee}</p>
            <p class="muted small">The imported side stays in place. The missing destination-side transaction will be added and marked matched.</p>
          </div>

          <p class="details-note pending-details-note">{manualResolutionPreview.warning}</p>
        </div>
      {/if}

      {#if manualResolutionError}
        <p class="error-text">{manualResolutionError}</p>
      {/if}

      <div class="modal-actions">
        <button class="btn" type="button" on:click={resetManualResolutionDialog}>Cancel</button>
        <button
          class="btn btn-primary"
          type="button"
          disabled={!manualResolutionPreview || manualResolutionLoading === 'apply'}
          on:click={() => void confirmManualResolution()}
        >
          {manualResolutionLoading === 'apply' ? 'Applying...' : 'Confirm resolution'}
        </button>
      </div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>

<!-- Delete confirmation dialog -->
{#if confirmDeleteEntry}
  <div class="confirm-backdrop" on:click={() => { confirmDeleteEntry = null; actionError = ''; }} role="presentation">
    <div class="confirm-modal" on:click|stopPropagation on:keydown={(e) => { if (e.key === 'Escape') { confirmDeleteEntry = null; actionError = ''; } }} role="dialog" tabindex="-1" aria-labelledby="confirm-delete-title">
      <h3 id="confirm-delete-title">Remove transaction</h3>
      <p>Remove <strong>{confirmDeleteEntry.payee}</strong> on {confirmDeleteEntry.date}?</p>
      <p class="muted small">This removes the transaction from your records. You'll be able to undo this soon.</p>
      {#if actionError}
        <p class="action-error">{actionError}</p>
      {/if}
      <div class="modal-actions">
        <button class="btn" type="button" on:click={() => { confirmDeleteEntry = null; actionError = ''; }}>Cancel</button>
        <button class="btn btn-danger" type="button" disabled={actionBusy} on:click={() => confirmDeleteEntry && void executeDelete(confirmDeleteEntry)}>
          {actionBusy ? 'Removing…' : 'Remove'}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- Unmatch confirmation dialog -->
{#if confirmUnmatchEntry}
  <div class="confirm-backdrop" on:click={() => { confirmUnmatchEntry = null; actionError = ''; }} role="presentation">
    <div class="confirm-modal" on:click|stopPropagation on:keydown={(e) => { if (e.key === 'Escape') { confirmUnmatchEntry = null; actionError = ''; } }} role="dialog" tabindex="-1" aria-labelledby="confirm-unmatch-title">
      <h3 id="confirm-unmatch-title">Undo match</h3>
      <p>Undo the match for <strong>{confirmUnmatchEntry.payee}</strong> on {confirmUnmatchEntry.date}?</p>
      <p class="muted small">This will restore the original manual entry and move the imported transaction back to the review queue.</p>
      {#if actionError}
        <p class="action-error">{actionError}</p>
      {/if}
      <div class="modal-actions">
        <button class="btn" type="button" on:click={() => { confirmUnmatchEntry = null; actionError = ''; }}>Cancel</button>
        <button class="btn btn-danger" type="button" disabled={actionBusy} on:click={() => confirmUnmatchEntry && void executeUnmatch(confirmUnmatchEntry)}>
          {actionBusy ? 'Undoing…' : 'Undo match'}
        </button>
      </div>
    </div>
  </div>
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
    grid-template-columns: 1.5rem minmax(7.5rem, 0.75fr) minmax(0, 2fr) minmax(7.5rem, 0.75fr) minmax(8rem, 0.85fr) 2rem;
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

  .clearing-indicator {
    width: 0.7rem;
    height: 0.7rem;
    padding: 0;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    align-self: center;
    flex-shrink: 0;
    transition: background 0.15s, box-shadow 0.15s;
  }

  .clearing-cleared {
    background: var(--ok, #0d7f58);
    box-shadow: none;
  }

  .clearing-pending {
    background: transparent;
    box-shadow: inset 0 0 0 2px var(--warn, #ad6a00);
  }

  .clearing-unmarked {
    background: rgba(10, 61, 89, 0.12);
    box-shadow: none;
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

  .manual-resolution-note {
    color: var(--brand-strong);
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

  .result-card {
    display: grid;
    gap: 0.45rem;
    background:
      radial-gradient(circle at top right, rgba(214, 235, 220, 0.62), transparent 44%),
      linear-gradient(155deg, rgba(248, 252, 246, 0.98), rgba(242, 248, 255, 0.96));
  }

  .pending-actions,
  .modal-actions {
    display: flex;
    gap: 0.7rem;
    flex-wrap: wrap;
  }

  .pending-secondary-action {
    background: rgba(255, 255, 255, 0.85);
  }

  .manual-resolution-preview {
    display: grid;
    gap: 0.9rem;
  }

  .manual-resolution-grid {
    display: grid;
    gap: 0.8rem;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  }

  .preview-payee {
    background: rgba(255, 255, 255, 0.72);
  }

  :global(.manual-resolution-backdrop) {
    position: fixed;
    inset: 0;
    background: rgba(10, 20, 30, 0.35);
    z-index: 30;
  }

  :global(.manual-resolution-modal) {
    width: min(640px, calc(100vw - 2rem));
    max-height: calc(100vh - 2rem);
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 1rem;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    overflow: auto;
    z-index: 31;
    display: grid;
    gap: 1rem;
  }

  /* --- Transaction Actions Menu --- */

  .register-actions {
    position: relative;
  }

  .action-menu-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.6rem;
    height: 1.6rem;
    padding: 0;
    border: none;
    border-radius: 0.4rem;
    background: transparent;
    color: var(--muted-foreground);
    font-size: 1.1rem;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }

  .action-menu-btn:hover {
    background: rgba(10, 61, 89, 0.08);
    color: var(--foreground);
  }

  .action-menu-popover {
    position: absolute;
    right: 0;
    top: 100%;
    z-index: 20;
    min-width: 11rem;
    background: #fff;
    border: 1px solid rgba(10, 61, 89, 0.12);
    border-radius: 0.7rem;
    box-shadow: 0 4px 16px rgba(10, 20, 30, 0.12);
    padding: 0.3rem;
    display: grid;
    gap: 0.1rem;
  }

  .action-menu-item {
    display: block;
    width: 100%;
    padding: 0.55rem 0.75rem;
    border: none;
    border-radius: 0.45rem;
    background: transparent;
    color: var(--foreground);
    font-size: 0.88rem;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }

  .action-menu-item:hover {
    background: rgba(10, 61, 89, 0.06);
  }

  .action-menu-item.danger {
    color: var(--error, #c53030);
  }

  .action-menu-item.danger:hover {
    background: rgba(197, 48, 48, 0.08);
  }

  /* --- Confirmation dialogs --- */

  .confirm-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(10, 20, 30, 0.35);
    z-index: 30;
  }

  .confirm-modal {
    width: min(480px, calc(100vw - 2rem));
    max-height: calc(100vh - 2rem);
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 1.25rem;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    overflow: auto;
    z-index: 31;
    display: grid;
    gap: 0.75rem;
  }

  .action-error {
    color: var(--error, #c53030);
    font-size: 0.88rem;
  }

  .btn-danger {
    background: var(--error, #c53030);
    color: #fff;
    border-color: var(--error, #c53030);
  }

  .btn-danger:hover {
    opacity: 0.9;
  }

  .btn-danger:disabled {
    opacity: 0.6;
    cursor: not-allowed;
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
      grid-template-columns: 1.5rem 1fr 2rem;
      gap: 0.45rem;
    }

    .clearing-indicator {
      grid-row: 1;
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

  /* --- View Toggle --- */
  .view-toggle {
    display: inline-flex;
    gap: 0.15rem;
    padding: 0.15rem;
    border-radius: 999px;
    background: rgba(10, 61, 89, 0.06);
  }

  .view-toggle-btn {
    padding: 0.3rem 0.75rem;
    border: none;
    border-radius: 999px;
    background: transparent;
    color: var(--muted-foreground);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .view-toggle-btn.active {
    background: #fff;
    color: var(--foreground);
    box-shadow: 0 1px 3px rgba(10, 61, 89, 0.1);
  }

  .view-toggle-btn:hover:not(.active) {
    color: var(--foreground);
  }

  /* --- Activity View --- */
  .activity-hero {
    background:
      radial-gradient(circle at top left, rgba(214, 235, 220, 0.86), transparent 34%),
      linear-gradient(155deg, #fbfdf8 0%, #f6fbff 60%, #eef6f3 100%);
  }

  .activity-filters-card {
    padding: 1rem 1.5rem;
  }

  .activity-filter-bar {
    display: flex;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
  }

  .activity-presets {
    display: inline-flex;
    gap: 0.15rem;
    padding: 0.15rem;
    border-radius: 999px;
    background: rgba(10, 61, 89, 0.06);
  }

  .activity-presets button {
    padding: 0.25rem 0.65rem;
    border: none;
    border-radius: 999px;
    background: transparent;
    color: var(--muted-foreground);
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .activity-presets button.active {
    background: #fff;
    color: var(--foreground);
    box-shadow: 0 1px 3px rgba(10, 61, 89, 0.1);
  }

  .activity-presets button:hover:not(.active) {
    color: var(--foreground);
  }

  .filter-chip-group {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .filter-label {
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-foreground);
  }

  .filter-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    background: rgba(15, 95, 136, 0.08);
    color: var(--brand-strong);
    font-size: 0.82rem;
    font-weight: 600;
    border: 1px solid rgba(15, 95, 136, 0.14);
  }

  .filter-clear {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.1rem;
    height: 1.1rem;
    border: none;
    border-radius: 50%;
    background: rgba(15, 95, 136, 0.12);
    color: var(--brand-strong);
    font-size: 0.85rem;
    line-height: 1;
    cursor: pointer;
    padding: 0;
    transition: background 0.15s;
  }

  .filter-clear:hover {
    background: rgba(15, 95, 136, 0.22);
  }

  .activity-list-card {
    overflow: hidden;
  }

  .activity-list {
    display: grid;
  }

  .date-group + .date-group {
    margin-top: 0.65rem;
    padding-top: 0.65rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .date-header {
    margin: 0;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .activity-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
    padding: 0.65rem 0;
    border-bottom: 1px solid rgba(10, 61, 89, 0.05);
  }

  .activity-row:last-child {
    border-bottom: none;
  }

  .activity-main {
    display: grid;
    gap: 0.2rem;
    min-width: 0;
  }

  .activity-headline {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    min-width: 0;
  }

  .activity-category-pill {
    flex-shrink: 0;
    font-size: 0.76rem;
    font-weight: 600;
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    background: rgba(15, 95, 136, 0.08);
    color: var(--brand-strong);
    white-space: nowrap;
  }

  .activity-payee {
    font-weight: 700;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .activity-meta {
    color: var(--muted-foreground);
    font-size: 0.88rem;
  }

  .explanation-header-card {
    display: grid;
    gap: 0.4rem;
    padding: 1rem 1.15rem;
  }

  .explanation-period {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0;
  }

  .explanation-prior {
    font-size: 0.95rem;
    margin: 0;
  }

  .explanation-baseline,
  .explanation-top {
    color: var(--muted-foreground);
    font-size: 0.88rem;
    margin: 0;
  }

  .activity-side {
    display: grid;
    gap: 0.2rem;
    justify-items: end;
    flex-shrink: 0;
  }

  .activity-amount {
    font-weight: 700;
    white-space: nowrap;
  }

  a.pill.warn {
    text-decoration: none;
  }

  @media (max-width: 980px) {
    .activity-hero {
      grid-template-columns: 1fr;
    }

    .activity-filter-bar {
      flex-direction: column;
      align-items: flex-start;
    }
  }

  @media (max-width: 720px) {
    .activity-row {
      flex-direction: column;
      gap: 0.3rem;
    }

    .activity-side {
      justify-items: start;
    }

    .activity-headline {
      flex-wrap: wrap;
    }
  }
</style>
