<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';
  import { accountSubtypeLabel } from '$lib/account-subtypes';
  import { normalizeCurrencyCode } from '$lib/currency-format';
  import CashFlowChart from '$lib/components/dashboard/CashFlowChart.svelte';
  import CategoryRibbon from '$lib/components/dashboard/CategoryRibbon.svelte';
  import DashboardDirection from '$lib/components/dashboard/DashboardDirection.svelte';
  import type { DirectionData } from '$lib/components/dashboard/direction-types';
  import type { AccountKind } from '$lib/format';

  type SetupState = {
    needsAccounts: boolean;
    needsFirstImport: boolean;
    needsReview: boolean;
    currentStep: string;
    completedSteps: string[];
  };

  type AppState = {
    initialized: boolean;
    workspaceName: string | null;
    importAccounts?: Array<{ id: string }>;
    csvInbox?: number;
    setup?: SetupState;
  };

  type Summary = {
    netWorth: number;
    trackedBalanceTotal: number;
    incomeThisMonth: number;
    spendingThisMonth: number;
    savingsThisMonth: number;
    transactionCount: number;
    unknownTransactionCount: number;
  };

  type BalanceRow = {
    id: string;
    displayName: string;
    institutionId: string | null;
    kind: string;
    last4?: string | null;
    balance: number;
    importConfigured: boolean;
    hasOpeningBalance: boolean;
    hasTransactionActivity: boolean;
    hasBalanceSource: boolean;
    lastTransactionDate: string | null;
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
    importConfigured: boolean;
    importMode?: 'institution' | 'custom' | null;
    openingBalance?: string | null;
    openingBalanceDate?: string | null;
  };

  type CashFlowRow = {
    month: string;
    label: string;
    income: number;
    spending: number;
    net: number;
  };

  type RecentTransaction = {
    date: string;
    payee: string;
    accountLabel: string;
    importAccountId: string | null;
    category: string;
    amount: number;
    isIncome: boolean;
    isUnknown: boolean;
  };

  type DashboardOverview = {
    baseCurrency: string;
    hasData: boolean;
    lastUpdated: string | null;
    summary: Summary;
    balances: BalanceRow[];
    cashFlow: {
      currentMonth: string;
      previousMonth: string;
      income: number;
      spending: number;
      net: number;
      series: CashFlowRow[];
    };
    recentTransactions: RecentTransaction[];
    cashFlowHistory: CashFlowRow[];
    categoryHistory: Array<{
      month: string;
      category: string;
      categoryLabel: string;
      amount: number;
    }>;
  };

  type OverviewAccount = TrackedAccount & {
    balance: number;
    hasOpeningBalance: boolean;
    hasTransactionActivity: boolean;
    hasBalanceSource: boolean;
    lastTransactionDate: string | null;
  };

  type BalanceGroup = {
    key: string;
    title: string;
    note: string;
    total: number;
    accounts: OverviewAccount[];
  };

  type ActionLink = {
    href: string;
    label: string;
  };

  type PrimaryTask = ActionLink & {
    note: string;
  };

  type SetupStep = {
    id: string;
    label: string;
    note: string;
    complete: boolean;
    current: boolean;
  };

  let state: AppState | null = null;
  let dashboard: DashboardOverview | null = null;
  let direction: DirectionData | null = null;
  let directionLoading = false;
  let trackedAccounts: TrackedAccount[] = [];
  let overviewAccounts: OverviewAccount[] = [];
  let balanceGroups: BalanceGroup[] = [];
  let error = '';
  let loading = true;

  function formatCurrency(value: number, options?: { signed?: boolean; compact?: boolean }): string {
    const currency = normalizeCurrencyCode(dashboard?.baseCurrency);
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      notation: options?.compact ? 'compact' : 'standard',
      minimumFractionDigits: options?.compact ? 0 : 2,
      maximumFractionDigits: options?.compact ? 1 : 2,
      signDisplay: options?.signed ? 'always' : 'auto'
    }).format(value);
  }

  /**
   * Format an amount for the Recent Activity list using the good-change-plus
   * sign convention. Positive changes on asset or liability accounts render as
   * "+$X.XX" (caller shows in green); everything else renders unsigned absolute.
   * Falls through to negative-only when the kind is unknown.
   */
  function formatRecentAmount(value: number, kind: AccountKind | null): string {
    const currency = normalizeCurrencyCode(dashboard?.baseCurrency);
    const absolute = new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
      signDisplay: 'never'
    }).format(Math.abs(value));
    if (kind && value > 0) return `+${absolute}`;
    if (!kind && value < 0) {
      return `-${absolute}`;
    }
    return absolute;
  }

  function recentAccountKind(importAccountId: string | null): AccountKind | null {
    if (!importAccountId) return null;
    const account = trackedAccounts.find((a) => a.id === importAccountId);
    if (!account) return null;
    if (account.kind === 'asset' || account.kind === 'liability') return account.kind;
    return null;
  }

  function formatDate(value: string | null): string {
    if (!value) return 'No activity yet';
    const parsed = new Date(`${value}T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(parsed);
  }

  function monthTitle(month: string): string {
    const parsed = new Date(`${month}-01T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(parsed);
  }

  function shortDate(value: string): string {
    const parsed = new Date(`${value}T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
  }

  function countLabel(count: number, singular: string, plural = `${singular}s`): string {
    return `${count} ${count === 1 ? singular : plural}`;
  }

  function reviewQueueCount(): number {
    return dashboard?.summary.unknownTransactionCount ?? 0;
  }

  function hasReviewQueue(): boolean {
    return reviewQueueCount() > 0 || Boolean(state?.setup?.needsReview);
  }

  function statementInboxCount(): number {
    return state?.csvInbox ?? 0;
  }

  function reviewQueueTitle(): string {
    const count = reviewQueueCount();
    if (count === 1) return '1 transaction needs review';
    if (count > 1) return `${count} transactions need review`;
    return 'Review queue still needs attention';
  }

  function reviewQueueNote(): string {
    const count = reviewQueueCount();
    if (count === 1) return 'Next up: review 1 transaction.';
    if (count > 1) return `Next up: review ${count} transactions.`;
    return 'Next up: review the remaining queue.';
  }

  function statementInboxTitle(): string {
    const count = statementInboxCount();
    return count === 1 ? '1 statement waiting' : `${count} statements waiting`;
  }

  function statementInboxNote(): string {
    const count = statementInboxCount();
    if (count === 1) return 'Next up: import 1 waiting statement.';
    return `Next up: import ${count} waiting statements.`;
  }

  function kindRank(kind: string): number {
    if (kind === 'asset') return 0;
    if (kind === 'liability') return 1;
    return 2;
  }

  function groupTitle(kind: string): string {
    if (kind === 'asset') return 'Assets';
    if (kind === 'liability') return 'Liabilities';
    return 'Other tracked accounts';
  }

  function groupNote(kind: string): string {
    if (kind === 'asset') return 'Cash, investments, and other tracked assets that support your position.';
    if (kind === 'liability') return 'Cards and debt balances that pull against net worth and upcoming decisions.';
    return 'Tracked accounts that sit outside the main balance-sheet groups.';
  }

  function compareOverviewAccounts(left: OverviewAccount, right: OverviewAccount): number {
    const balanceDelta = Math.abs(right.balance) - Math.abs(left.balance);
    if (balanceDelta !== 0) return balanceDelta;
    return left.displayName.localeCompare(right.displayName, undefined, { sensitivity: 'base' });
  }

  function buildOverviewAccounts(..._deps: unknown[]): OverviewAccount[] {
    if (!dashboard) return [];

    const trackedById = new Map(trackedAccounts.map((account) => [account.id, account]));

    return dashboard.balances
      .map((balance) => {
        const tracked = trackedById.get(balance.id);
        return {
          id: balance.id,
          displayName: tracked?.displayName ?? balance.displayName,
          ledgerAccount: tracked?.ledgerAccount ?? '',
          kind: tracked?.kind ?? balance.kind,
          subtype: tracked?.subtype ?? null,
          institutionId: tracked?.institutionId ?? balance.institutionId,
          institutionDisplayName: tracked?.institutionDisplayName ?? null,
          last4: tracked?.last4 ?? balance.last4 ?? null,
          importConfigured: tracked?.importConfigured ?? balance.importConfigured,
          importMode: tracked?.importMode ?? null,
          openingBalance: tracked?.openingBalance ?? null,
          openingBalanceDate: tracked?.openingBalanceDate ?? null,
          balance: balance.balance,
          hasOpeningBalance: balance.hasOpeningBalance,
          hasTransactionActivity: balance.hasTransactionActivity,
          hasBalanceSource: balance.hasBalanceSource,
          lastTransactionDate: balance.lastTransactionDate ?? null,
        } satisfies OverviewAccount;
      })
      .sort((left, right) => {
        const rankDelta = kindRank(left.kind) - kindRank(right.kind);
        return rankDelta !== 0 ? rankDelta : compareOverviewAccounts(left, right);
      });
  }

  function buildBalanceGroups(accounts: OverviewAccount[]): BalanceGroup[] {
    const orderedKinds = ['asset', 'liability'];
    const otherKinds = Array.from(new Set(accounts.map((account) => account.kind))).filter((kind) => !orderedKinds.includes(kind));

    return [...orderedKinds, ...otherKinds]
      .map((kind) => {
        const accountsInGroup = accounts.filter((account) => account.kind === kind);
        if (!accountsInGroup.length) return null;
        return {
          key: kind,
          title: groupTitle(kind),
          note: groupNote(kind),
          total: accountsInGroup.reduce((sum, account) => sum + account.balance, 0),
          accounts: accountsInGroup
        } satisfies BalanceGroup;
      })
      .filter((group): group is BalanceGroup => group !== null);
  }

  const STALE_THRESHOLD_DAYS = 7;

  function isDataStale(): boolean {
    if (!dashboard?.lastUpdated) return false;
    const last = new Date(`${dashboard.lastUpdated}T00:00:00`);
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const diffMs = now.getTime() - last.getTime();
    return diffMs > STALE_THRESHOLD_DAYS * 24 * 60 * 60 * 1000;
  }

  const ACCOUNT_STALE_THRESHOLD_DAYS = 14;

  function isAccountStale(lastTransactionDate: string | null): boolean {
    if (!lastTransactionDate) return true;
    const last = new Date(`${lastTransactionDate}T00:00:00`);
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const diffMs = now.getTime() - last.getTime();
    return diffMs > ACCOUNT_STALE_THRESHOLD_DAYS * 24 * 60 * 60 * 1000;
  }

  function accountStalenessLabel(lastTransactionDate: string | null): string {
    if (!lastTransactionDate) return 'No activity yet';
    return `Last activity ${shortDate(lastTransactionDate)}`;
  }

  function heroRailTitle(): string {
    if (hasReviewQueue()) return reviewQueueTitle();
    if (statementInboxCount() > 0) return statementInboxTitle();
    if (isDataStale()) return `Last activity ${formatDate(dashboard?.lastUpdated ?? null)}`;
    return 'Books look current';
  }

  function setupSteps(..._deps: unknown[]): SetupStep[] {
    const completed = new Set(state?.setup?.completedSteps ?? []);
    const current = state?.setup?.currentStep ?? 'workspace';

    return [
      {
        id: 'workspace',
        label: 'Workspace',
        note: 'Create or connect your books.',
        complete: completed.has('workspace'),
        current: current === 'workspace'
      },
      {
        id: 'accounts',
        label: 'Accounts',
        note: 'Add the accounts you want to track.',
        complete: completed.has('accounts'),
        current: current === 'accounts'
      },
      {
        id: 'import',
        label: 'First import',
        note: 'Bring in the first statement.',
        complete: completed.has('import'),
        current: current === 'import'
      },
      {
        id: 'review',
        label: 'Review',
        note: 'Resolve anything still uncategorized.',
        complete: completed.has('review') || current === 'done',
        current: current === 'review'
      }
    ];
  }

  function primaryTask(..._deps: unknown[]): PrimaryTask {
    if (!state?.initialized) {
      return {
        href: '/setup',
        label: 'Open setup',
        note: 'Open setup to create a workspace or connect an existing one.'
      };
    }
    if (state.setup?.needsAccounts) {
      return {
        href: '/setup',
        label: 'Add accounts',
        note: 'Add the first accounts you want to track.'
      };
    }
    if (state.setup?.needsFirstImport || !dashboard?.hasData) {
      return {
        href: '/setup',
        label: 'Import first statement',
        note: 'Bring in one statement so balances and recent activity can populate.'
      };
    }
    if (hasReviewQueue()) {
      return {
        href: '/unknowns',
        label: 'Review transactions',
        note: reviewQueueNote()
      };
    }
    if (statementInboxCount() > 0) {
      return {
        href: '/import',
        label: 'Import statements',
        note: statementInboxNote()
      };
    }
    if (isDataStale()) {
      return {
        href: '/import',
        label: 'Import a statement',
        note: 'Your most recent activity is over a week old. Import a fresh statement to stay current.'
      };
    }
    return {
      href: '/#direction',
      label: 'Review your direction',
      note: 'No bookkeeping work is waiting. Take a moment to scan your financial direction panel.'
    };
  }

  function secondaryActions(..._deps: unknown[]): ActionLink[] {
    if (!state?.initialized) return [{ href: '/setup#existing', label: 'Use existing workspace' }];
    if (state.setup?.needsAccounts || state.setup?.needsFirstImport || !dashboard?.hasData) {
      return [{ href: '/import', label: 'Open import workspace' }];
    }

    const actions: ActionLink[] = [];
    if (hasReviewQueue()) {
      actions.push({ href: '/rules', label: 'Refine automation' });
    }
    actions.push({ href: '/accounts', label: 'Manage accounts' });
    return actions;
  }

  function recentActivityAction(): ActionLink {
    return { href: '/transactions', label: 'Open transactions' };
  }

  type DateGroup = { header: string; transactions: RecentTransaction[] };

  function groupByDate(transactions: RecentTransaction[]): DateGroup[] {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    const todayStr = today.toISOString().slice(0, 10);
    const yesterdayStr = yesterday.toISOString().slice(0, 10);

    const groups: DateGroup[] = [];
    let currentGroup: DateGroup | null = null;

    for (const tx of transactions.slice(0, 5)) {
      const header = tx.date === todayStr ? 'Today'
        : tx.date === yesterdayStr ? 'Yesterday'
        : shortDate(tx.date);

      if (!currentGroup || currentGroup.header !== header) {
        currentGroup = { header, transactions: [] };
        groups.push(currentGroup);
      }
      currentGroup.transactions.push(tx);
    }
    return groups;
  }

  $: activeTask = primaryTask(state, dashboard);
  $: secondary = secondaryActions(state, dashboard);
  $: recentAction = recentActivityAction();
  $: recentGroups = groupByDate(dashboard?.recentTransactions ?? []);
  $: steps = setupSteps(state);
  $: overviewAccounts = buildOverviewAccounts(dashboard, trackedAccounts);
  $: balanceGroups = buildBalanceGroups(overviewAccounts);

  let focusedPeriod: string | null = null;

  $: focusedMonth = focusedPeriod ?? dashboard?.cashFlow.currentMonth ?? '';
  $: categoryBreakdown = (dashboard?.categoryHistory ?? [])
    .filter(r => r.month === focusedMonth)
    .sort((a, b) => b.amount - a.amount);
  $: sparklineMonths = (dashboard?.cashFlowHistory ?? []).slice(-6).map(r => r.month);
  $: categorySparklineData = (() => {
    const byCategory = new Map<string, number[]>();
    for (const row of dashboard?.categoryHistory ?? []) {
      if (!sparklineMonths.includes(row.month)) continue;
      if (!byCategory.has(row.category)) {
        byCategory.set(row.category, new Array(sparklineMonths.length).fill(0));
      }
      const idx = sparklineMonths.indexOf(row.month);
      byCategory.get(row.category)![idx] = row.amount;
    }
    return byCategory;
  })();
  $: cashFlowFocusedIndex = focusedPeriod
    ? (dashboard?.cashFlowHistory ?? []).findIndex(r => r.month === focusedPeriod)
    : null;
  $: resolvedFocusedIndex = cashFlowFocusedIndex !== null && cashFlowFocusedIndex >= 0 ? cashFlowFocusedIndex : null;

  onMount(async () => {
    loading = true;
    error = '';

    try {
      state = await apiGet<AppState>('/api/app/state');
      if (state.initialized) {
        directionLoading = true;
        const [dashboardData, accountsData] = await Promise.all([
          apiGet<DashboardOverview>('/api/dashboard/overview'),
          apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts')
        ]);
        dashboard = dashboardData;
        trackedAccounts = accountsData.trackedAccounts;

        // Direction is supplementary — failure must not break the dashboard
        apiGet<DirectionData>('/api/dashboard/direction')
          .then((data: DirectionData) => { direction = data; })
          .catch(() => { direction = null; })
          .finally(() => { directionLoading = false; });
      }
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
{:else if loading}
  <section class="view-card p-6">
    <p class="eyebrow">Loading</p>
    <h2 class="page-title">Building your overview</h2>
    <p class="subtitle">Pulling together balances, recent activity, and next actions.</p>
  </section>
{:else if !state?.initialized}
  <section
    class="dashboard-hero view-card grid items-start gap-6 p-6 grid-cols-[minmax(0,1.7fr)_minmax(16rem,0.9fr)] max-desktop:grid-cols-1 max-tablet:p-5"
  >
    <div class="min-w-0">
      <p class="eyebrow">Start here</p>
      <h2 class="page-title m-0 max-w-[12ch] leading-[0.95] text-[clamp(2.3rem,5vw,4.4rem)]">
        See your money at a glance.
      </h2>
      <p class="subtitle mt-3.5 max-w-3xl text-base leading-relaxed">
        Start with a workspace and one statement. From there, Ledger Flow turns the routine work into balances,
        recent activity, and a clear next step.
      </p>
    </div>

    <div class="grid items-start justify-items-start gap-3.5 rounded-lg border border-card-edge bg-white/72 p-4 max-tablet:justify-items-start">
      <a class="btn btn-primary" href={activeTask.href}>{activeTask.label}</a>
      {#each secondary as action}
        <a class="text-link" href={action.href}>{action.label}</a>
      {/each}
    </div>
  </section>

  <section class="grid grid-cols-3 gap-4 max-desktop:grid-cols-2 max-tablet:grid-cols-1">
    <article class="view-card">
      <p class="eyebrow">What matters</p>
      <h3 class="m-0 font-display text-xl">Daily visibility</h3>
      <p class="m-0 text-muted-foreground leading-relaxed">
        The home screen is built to answer three questions quickly: where you stand, what changed, and what needs attention.
      </p>
    </article>

    <article class="view-card">
      <p class="eyebrow">What stays hidden</p>
      <h3 class="m-0 font-display text-xl">Advanced details</h3>
      <p class="m-0 text-muted-foreground leading-relaxed">
        Paths, journal files, and setup internals stay in secondary views unless you explicitly need them.
      </p>
    </article>

    <article class="view-card">
      <p class="eyebrow">What stays strong</p>
      <h3 class="m-0 font-display text-xl">Safe imports</h3>
      <p class="m-0 text-muted-foreground leading-relaxed">
        Preview and apply still work the same way: append new activity, skip duplicates, and surface conflicts instead of rewriting history.
      </p>
    </article>
  </section>
{:else if state.setup?.needsAccounts || state.setup?.needsFirstImport || !dashboard?.hasData}
  <section
    class="dashboard-hero view-card grid items-start gap-6 p-6 grid-cols-[minmax(0,1.7fr)_minmax(16rem,0.9fr)] max-desktop:grid-cols-1 max-tablet:p-5"
  >
    <div class="min-w-0">
      <p class="eyebrow">Finish setup</p>
      <h2 class="page-title m-0 max-w-[12ch] leading-[0.95] text-[clamp(2.3rem,5vw,4.4rem)]">
        {state.workspaceName || 'Your workspace'} is ready for the next step.
      </h2>
      <p class="subtitle mt-3.5 max-w-3xl text-base leading-relaxed">
        Finish one clean pass through setup so the overview can show balances, spending movement, and recent activity.
      </p>
    </div>

    <div class="grid items-start justify-items-start gap-3.5 rounded-lg border border-card-edge bg-white/72 p-4">
      <a class="btn btn-primary" href={activeTask.href}>{activeTask.label}</a>
      {#each secondary as action}
        <a class="text-link" href={action.href}>{action.label}</a>
      {/each}
    </div>
  </section>

  <section class="grid grid-cols-4 gap-4 max-desktop:grid-cols-2 max-tablet:grid-cols-1">
    {#each steps as step}
      <article
        class:step-complete={step.complete}
        class:step-current={step.current}
        class="view-card p-5"
      >
        <p class="m-0 mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
          {step.complete ? 'Done' : step.current ? 'Now' : 'Next'}
        </p>
        <h3 class="m-0 font-display text-xl">{step.label}</h3>
        <p class="m-0 text-muted-foreground leading-relaxed">{step.note}</p>
      </article>
    {/each}
  </section>

  <section class="view-card p-6">
    <p class="eyebrow">Next action</p>
    <h3 class="m-0 font-display text-xl">Keep the first-run path moving.</h3>
    <p class="m-0 text-muted-foreground leading-relaxed">
      Setup is now staged on purpose. Finish one clear step at a time rather than dealing with configuration detail up front.
    </p>
  </section>
{:else}
  <section
    class="dashboard-hero view-card grid items-start gap-6 p-6 grid-cols-[minmax(0,1.7fr)_minmax(16rem,0.9fr)] max-desktop:grid-cols-1 max-tablet:p-5"
  >
    <div class="min-w-0">
      <p class="eyebrow">Overview</p>
      <h2 class="page-title m-0 leading-[0.92] text-[clamp(3rem,6vw,5.2rem)]">
        {formatCurrency(dashboard.summary.netWorth, { compact: true })}
      </h2>
      <p class="m-0 mt-2 text-sm font-bold uppercase tracking-widest text-muted-foreground">Net worth</p>
      <p class="m-0 mt-1 text-base leading-snug text-muted-foreground">
        {#if dashboard.summary.savingsThisMonth > 0}
          You're <span class="positive">{formatCurrency(dashboard.summary.savingsThisMonth, { signed: true, compact: true })}</span> ahead this month
        {:else if dashboard.summary.savingsThisMonth < 0}
          You're <span class="negative">{formatCurrency(Math.abs(dashboard.summary.savingsThisMonth), { compact: true })}</span> behind this month
        {:else}
          Breaking even this month
        {/if}
      </p>
      <div class="mt-3 flex flex-wrap gap-2.5 max-tablet:gap-1.5">
        <span class="inline-flex items-baseline gap-1.5 rounded-full border border-card-edge bg-white/60 px-2.5 py-1 text-sm leading-none">
          <span class="text-[0.68rem] font-bold uppercase tracking-wider text-muted-foreground">Tracked</span>
          <span class="font-display font-semibold">{formatCurrency(dashboard.summary.trackedBalanceTotal, { compact: true })}</span>
        </span>
        <span class="inline-flex items-baseline gap-1.5 rounded-full border border-card-edge bg-white/60 px-2.5 py-1 text-sm leading-none">
          <span class="text-[0.68rem] font-bold uppercase tracking-wider text-muted-foreground">Income</span>
          <span class="positive font-display font-semibold">{formatCurrency(dashboard.summary.incomeThisMonth, { compact: true })}</span>
        </span>
        <span class="inline-flex items-baseline gap-1.5 rounded-full border border-card-edge bg-white/60 px-2.5 py-1 text-sm leading-none">
          <span class="text-[0.68rem] font-bold uppercase tracking-wider text-muted-foreground">Spent</span>
          <span class="negative font-display font-semibold">{formatCurrency(dashboard.summary.spendingThisMonth, { compact: true })}</span>
        </span>
      </div>
      <p class="subtitle mt-3.5 max-w-3xl text-base leading-relaxed">
        Through {formatDate(dashboard.lastUpdated)}, with {countLabel(dashboard.summary.transactionCount, 'transaction')} in view.
      </p>
    </div>

    <div class="grid w-full min-h-full items-start justify-items-start gap-3.5 rounded-lg border border-card-edge bg-white/72 p-4 max-tablet:justify-items-start">
      <p class="m-0 font-display text-lg font-bold leading-tight">{heroRailTitle()}</p>
      <a class="btn btn-primary" href={activeTask.href}>{activeTask.label}</a>
      <div class="flex flex-wrap gap-3.5">
        {#each secondary as action}
          <a class="text-link" href={action.href}>{action.label}</a>
        {/each}
      </div>
    </div>
  </section>

  <section class="view-card p-5">
    <div class="mb-3 flex items-center justify-between gap-4 max-tablet:grid max-tablet:grid-cols-1">
      <div class="min-h-12">
        <p class="eyebrow">Cash flow</p>
        {#if focusedPeriod}
          <div class="flex items-center gap-1.5">
            <button
              class="cursor-pointer border-none bg-transparent p-0 font-semibold text-brand-strong hover:underline text-sm"
              on:click={() => focusedPeriod = null}
            >
              All months
            </button>
            <span class="text-sm text-muted-foreground">&rarr;</span>
            <span class="text-sm font-semibold">{monthTitle(focusedPeriod)}</span>
          </div>
        {:else}
          <h3 class="m-0 font-display text-xl">Monthly income and spending</h3>
        {/if}
      </div>
      <p class="m-0 text-sm text-muted-foreground">{formatCurrency(dashboard.cashFlow.net, { signed: true })} this month</p>
    </div>

    {#if (dashboard.cashFlowHistory ?? []).length > 0}
      <CashFlowChart
        series={dashboard.cashFlowHistory}
        currentMonth={dashboard.cashFlow.currentMonth}
        {formatCurrency}
        onMonthClick={(month) => focusedPeriod = month}
        focusedIndex={resolvedFocusedIndex}
      />
    {:else}
      <p class="m-0 text-sm text-muted-foreground">
        No income or spending recorded yet.
      </p>
    {/if}
  </section>

  <section class="view-card px-5 py-4">
    <div class="mb-2 flex items-baseline justify-between">
      <p class="eyebrow m-0">
        {focusedPeriod ? monthTitle(focusedPeriod) : 'This month'} · spending by category
      </p>
    </div>
    <CategoryRibbon
      categories={categoryBreakdown}
      sparklineData={categorySparklineData}
      {formatCurrency}
    />
  </section>

  <div id="direction" class="scroll-mt-6">
    <DashboardDirection {direction} baseCurrency={dashboard.baseCurrency} loading={directionLoading} />
  </div>

  <section class="grid gap-4 grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] max-desktop:grid-cols-1">
    <article class="view-card p-5">
      <div class="mb-4 flex items-start justify-between gap-4 max-tablet:grid max-tablet:grid-cols-1">
        <div>
          <p class="eyebrow">Recent activity</p>
          <h3 class="m-0 font-display text-xl">Latest transactions</h3>
        </div>
        <a class="text-link" href={recentAction.href}>{recentAction.label}</a>
      </div>

      <div class="grid gap-3.5">
        {#each recentGroups as group}
          <div class="date-group">
            <h4 class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">{group.header}</h4>
            {#each group.transactions as transaction}
              {@const txKind = recentAccountKind(transaction.importAccountId)}
              <div class="transaction-row flex items-center justify-between gap-4 py-3.5 max-tablet:grid max-tablet:grid-cols-1">
                <div class="grid gap-0.5">
                  <p class="m-0 font-bold">{transaction.payee}</p>
                  <p class="m-0 text-sm text-muted-foreground">
                    {shortDate(transaction.date)} · {transaction.accountLabel} · {transaction.category}
                  </p>
                </div>
                <div class="grid gap-0.5 justify-items-end max-tablet:justify-items-start">
                  <p
                    class:positive={txKind && transaction.amount > 0}
                    class="m-0 font-display text-base"
                  >
                    {formatRecentAmount(transaction.amount, txKind)}
                  </p>
                  {#if transaction.isUnknown}
                    <a class="pill warn no-underline" href="/unknowns">Needs review</a>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/each}
      </div>
    </article>

    <article class="view-card p-5">
    <div class="mb-4 flex items-start justify-between gap-4 max-tablet:grid max-tablet:grid-cols-1">
      <div>
        <p class="eyebrow">Balance sheet</p>
        <h3 class="m-0 font-display text-xl">Tracked accounts</h3>
      </div>
      <a class="text-link" href="/accounts">Manage accounts</a>
    </div>

    {#if overviewAccounts.length > 0}
      <div class="grid gap-3">
        {#each balanceGroups as group}
          <section class={`balance-group ${group.key}`}>
            <div class="mb-1 flex items-baseline justify-between gap-4">
              <h4 class="m-0 text-sm font-bold uppercase tracking-wider text-muted-foreground">{group.title}</h4>
              <strong
                class:negative={group.total < 0}
                class:positive={group.total > 0}
                class="font-display text-base"
              >
                {formatCurrency(group.total)}
              </strong>
            </div>

            <table class="w-full border-collapse">
              <tbody>
                {#each group.accounts as account}
                  <tr>
                    <td class="py-1.5 align-baseline border-t border-card-edge first:border-t-0 font-medium">
                      <span>
                        {account.displayName}
                        <span class={`pill subtype-pill ${account.kind} ml-1.5 align-baseline`}>{accountSubtypeLabel(account, 'short')}</span>
                      </span>
                      {#if account.importConfigured && !account.hasOpeningBalance}
                        <a class="text-link block text-xs font-normal" href="/accounts">Needs opening balance</a>
                      {/if}
                    </td>
                    <td
                      class:negative={account.balance < 0}
                      class:positive={account.balance > 0}
                      class="py-1.5 align-baseline border-t border-card-edge first:border-t-0 text-right font-display font-semibold whitespace-nowrap"
                    >
                      <span>{formatCurrency(account.balance)}</span>
                      {#if isAccountStale(account.lastTransactionDate)}
                        <span class="block text-xs font-normal text-muted-foreground">{accountStalenessLabel(account.lastTransactionDate)}</span>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </section>
        {/each}
      </div>
    {:else}
      <p class="m-0 text-sm text-muted-foreground">
        No tracked accounts configured yet. <a class="text-link" href="/accounts">Add accounts</a> to see balances here.
      </p>
    {/if}
    </article>
  </section>
{/if}

<style>
  .dashboard-hero {
    background:
      radial-gradient(circle at top left, rgba(211, 238, 225, 0.9), transparent 34%),
      linear-gradient(155deg, #fbfdf8 0%, #f6fbff 60%, #eef6f3 100%);
  }

  .positive {
    color: var(--ok);
  }

  .negative {
    color: var(--brand-strong);
  }

  .step-complete {
    border-color: rgba(13, 127, 88, 0.25);
    background: linear-gradient(180deg, #ffffff 0%, #f5fbf7 100%);
  }

  .step-current {
    border-color: rgba(15, 95, 136, 0.22);
    box-shadow: 0 16px 30px rgba(8, 45, 68, 0.09);
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

  .drilldown-link:hover {
    background: rgba(10, 61, 89, 0.04);
  }

  .transaction-row + .transaction-row {
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .balance-group + .balance-group {
    margin-top: 0.75rem;
    padding-top: 0.75rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .date-group + .date-group {
    margin-top: 0.65rem;
    padding-top: 0.65rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

</style>
