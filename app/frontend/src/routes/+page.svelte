<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';
  import { accountSubtypeLabel } from '$lib/account-subtypes';
  import { normalizeCurrencyCode } from '$lib/currency-format';

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

  type CategoryTrend = {
    category: string;
    current: number;
    previous: number;
    delta: number;
    direction: 'up' | 'down' | 'flat';
  };

  type RecentTransaction = {
    date: string;
    payee: string;
    accountLabel: string;
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
    categoryTrends: CategoryTrend[];
    recentTransactions: RecentTransaction[];
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

  function barWidth(value: number, max: number): string {
    if (max <= 0 || value <= 0) return '0%';
    return `${Math.max(8, (value / max) * 100)}%`;
  }

  function formatTrend(delta: number): string {
    if (delta === 0) return 'Flat vs last month';
    return `${delta > 0 ? '+' : ''}${formatCurrency(delta)} vs last month`;
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
      href: '/transactions',
      label: 'Open transactions',
      note: 'Scan the latest activity or drill into an account register.'
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
    } else {
      actions.push({ href: '/transactions', label: 'Open transactions' });
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

  let cashFlowPreset: 'month' | 'last3' | 'last6' = 'last3';
  $: visibleCashFlow = (() => {
    const reversed = [...(dashboard?.cashFlow.series ?? [])].reverse();
    if (cashFlowPreset === 'month') return reversed.slice(0, 1);
    if (cashFlowPreset === 'last6') return reversed;
    return reversed.slice(0, 3);
  })();
  $: cashFlowMax = Math.max(...visibleCashFlow.map((row) => Math.max(row.income, row.spending)), 0);
  $: categoryMax = Math.max(
    ...(dashboard?.categoryTrends.flatMap((row) => [row.current, row.previous]) ?? [0])
  );

  onMount(async () => {
    loading = true;
    error = '';

    try {
      state = await apiGet<AppState>('/api/app/state');
      if (state.initialized) {
        const [dashboardData, accountsData] = await Promise.all([
          apiGet<DashboardOverview>('/api/dashboard/overview'),
          apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts')
        ]);
        dashboard = dashboardData;
        trackedAccounts = accountsData.trackedAccounts;
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
  <section class="view-card dashboard-loading">
    <p class="eyebrow">Loading</p>
    <h2 class="page-title">Building your overview</h2>
    <p class="subtitle">Pulling together balances, recent activity, and next actions.</p>
  </section>
{:else if !state?.initialized}
  <section class="view-card dashboard-hero landing-hero">
    <div class="hero-copy">
      <p class="eyebrow">Start here</p>
      <h2 class="page-title page-title-xl">See your money at a glance.</h2>
      <p class="subtitle hero-subtitle">
        Start with a workspace and one statement. From there, Ledger Flow turns the routine work into balances,
        recent activity, and a clear next step.
      </p>
    </div>

    <div class="hero-side">
      <a class="btn btn-primary" href={activeTask.href}>{activeTask.label}</a>
      {#each secondary as action}
        <a class="text-link" href={action.href}>{action.label}</a>
      {/each}
    </div>
  </section>

  <section class="landing-grid">
    <article class="view-card value-card">
      <p class="eyebrow">What matters</p>
      <h3>Daily visibility</h3>
      <p>The home screen is built to answer three questions quickly: where you stand, what changed, and what needs attention.</p>
    </article>

    <article class="view-card value-card">
      <p class="eyebrow">What stays hidden</p>
      <h3>Advanced details</h3>
      <p>Paths, journal files, and setup internals stay in secondary views unless you explicitly need them.</p>
    </article>

    <article class="view-card value-card">
      <p class="eyebrow">What stays strong</p>
      <h3>Safe imports</h3>
      <p>Preview and apply still work the same way: append new activity, skip duplicates, and surface conflicts instead of rewriting history.</p>
    </article>
  </section>
{:else if state.setup?.needsAccounts || state.setup?.needsFirstImport || !dashboard?.hasData}
  <section class="view-card dashboard-hero onboarding-hero">
    <div class="hero-copy">
      <p class="eyebrow">Finish setup</p>
      <h2 class="page-title page-title-xl">{state.workspaceName || 'Your workspace'} is ready for the next step.</h2>
      <p class="subtitle hero-subtitle">
        Finish one clean pass through setup so the overview can show balances, spending movement, and recent activity.
      </p>
    </div>

    <div class="hero-side">
      <a class="btn btn-primary" href={activeTask.href}>{activeTask.label}</a>
      {#each secondary as action}
        <a class="text-link" href={action.href}>{action.label}</a>
      {/each}
    </div>
  </section>

  <section class="progress-grid">
    {#each steps as step}
      <article class:step-complete={step.complete} class:step-current={step.current} class="view-card progress-card">
        <p class="progress-kicker">{step.complete ? 'Done' : step.current ? 'Now' : 'Next'}</p>
        <h3>{step.label}</h3>
        <p>{step.note}</p>
      </article>
    {/each}
  </section>

  <section class="view-card next-action-card">
    <p class="eyebrow">Next action</p>
    <h3>Keep the first-run path moving.</h3>
    <p>Setup is now staged on purpose. Finish one clear step at a time rather than dealing with configuration detail up front.</p>
  </section>
{:else}
  <section class="view-card dashboard-hero overview-hero">
    <div class="hero-copy">
      <p class="eyebrow">Overview</p>
      <h2 class="page-title hero-worth">{formatCurrency(dashboard.summary.netWorth, { compact: true })}</h2>
      <p class="hero-label">Net worth</p>
      <p class="hero-momentum">
        {#if dashboard.summary.savingsThisMonth > 0}
          You're <span class="positive">{formatCurrency(dashboard.summary.savingsThisMonth, { signed: true, compact: true })}</span> ahead this month
        {:else if dashboard.summary.savingsThisMonth < 0}
          You're <span class="negative">{formatCurrency(Math.abs(dashboard.summary.savingsThisMonth), { compact: true })}</span> behind this month
        {:else}
          Breaking even this month
        {/if}
      </p>
      <div class="hero-stats">
        <span class="hero-chip">
          <span class="hero-chip-label">Tracked</span>
          <span class="hero-chip-value">{formatCurrency(dashboard.summary.trackedBalanceTotal, { compact: true })}</span>
        </span>
        <span class="hero-chip">
          <span class="hero-chip-label">Income</span>
          <span class="hero-chip-value positive">{formatCurrency(dashboard.summary.incomeThisMonth, { compact: true })}</span>
        </span>
        <span class="hero-chip">
          <span class="hero-chip-label">Spent</span>
          <span class="hero-chip-value negative">{formatCurrency(dashboard.summary.spendingThisMonth, { compact: true })}</span>
        </span>
      </div>
      <p class="subtitle hero-subtitle">
        Through {formatDate(dashboard.lastUpdated)}, with {countLabel(dashboard.summary.transactionCount, 'transaction')} in view.
      </p>
    </div>

    <div class="hero-side hero-side-compact today-rail">
      <p class="today-status">{heroRailTitle()}</p>
      <a class="btn btn-primary" href={activeTask.href}>{activeTask.label}</a>
      <div class="hero-links">
        {#each secondary as action}
          <a class="text-link" href={action.href}>{action.label}</a>
        {/each}
      </div>
    </div>
  </section>

  <section class="detail-grid">
    <article class="view-card recent-panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Recent activity</p>
          <h3>Latest transactions</h3>
        </div>
        <a class="text-link" href={recentAction.href}>{recentAction.label}</a>
      </div>

      <div class="transaction-list">
        {#each recentGroups as group, gi}
          <div class="date-group" class:date-group-first={gi === 0}>
            <h4 class="date-header">{group.header}</h4>
            {#each group.transactions as transaction}
              <div class="transaction-row">
                <div class="transaction-main">
                  <p class="transaction-payee">{transaction.payee}</p>
                  <p class="transaction-meta">
                    {shortDate(transaction.date)} · {transaction.accountLabel} · {transaction.category}
                  </p>
                </div>
                <div class="transaction-side">
                  <p class:positive={transaction.amount > 0} class:negative={transaction.amount < 0} class="transaction-amount">
                    {formatCurrency(transaction.amount, { signed: true })}
                  </p>
                  {#if transaction.isUnknown}
                    <a class="pill warn" href="/unknowns">Needs review</a>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/each}
      </div>
    </article>

    <article class="view-card categories-panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Category trends</p>
          <h3>Where spending moved the most</h3>
        </div>
        <p class="section-note">{monthTitle(dashboard.cashFlow.currentMonth)} vs {monthTitle(dashboard.cashFlow.previousMonth)}</p>
      </div>

      {#if dashboard.categoryTrends.length > 0}
        <div class="category-list">
          {#each dashboard.categoryTrends as row}
            <div class="category-row">
              <div class="category-head">
                <p>{row.category}</p>
                <span class:negative={row.delta > 0} class:positive={row.delta < 0}>{formatTrend(row.delta)}</span>
              </div>
              <div class="category-bars">
                <div class="category-meter current">
                  <span style={`width: ${barWidth(row.current, categoryMax)}`}></span>
                </div>
                <div class="category-meter previous">
                  <span style={`width: ${barWidth(row.previous, categoryMax)}`}></span>
                </div>
              </div>
              <div class="category-values">
                <span>Now {formatCurrency(row.current)}</span>
                <span>Prev {formatCurrency(row.previous)}</span>
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <p class="empty-copy">Once expenses land in at least two months of activity, category movement will show up here.</p>
      {/if}
    </article>
  </section>

  <section class="view-card cashflow-panel">
    <div class="section-head">
      <div>
        <p class="eyebrow">Cash flow</p>
        <h3>Monthly income and spending</h3>
      </div>
      <div class="cashflow-controls">
        <p class="section-note">{formatCurrency(dashboard.cashFlow.net, { signed: true })} this month</p>
        <div class="cashflow-presets">
          <button class:active={cashFlowPreset === 'month'} on:click={() => cashFlowPreset = 'month'}>This month</button>
          <button class:active={cashFlowPreset === 'last3'} on:click={() => cashFlowPreset = 'last3'}>Last 3</button>
          <button class:active={cashFlowPreset === 'last6'} on:click={() => cashFlowPreset = 'last6'}>Last 6</button>
        </div>
      </div>
    </div>

    <div class="cashflow-list">
      {#each visibleCashFlow as row}
        <div class="cashflow-row-compact">
          <div class="cashflow-meta">
            <p>{row.label}</p>
            <span class:positive={row.net >= 0} class:negative={row.net < 0}>{formatCurrency(row.net, { signed: true, compact: true })}</span>
          </div>
          <div class="cashflow-bar-pair">
            <span class="bar-income" style={`width: ${barWidth(row.income, cashFlowMax)}`}></span>
            <span class="bar-spending" style={`width: ${barWidth(row.spending, cashFlowMax)}`}></span>
          </div>
        </div>
      {/each}
    </div>

  </section>

  <section class="view-card balances-panel balance-sheet-panel">
    <div class="section-head">
      <div>
        <p class="eyebrow">Balance sheet</p>
        <h3>Tracked accounts</h3>
      </div>
      <a class="text-link" href="/accounts">Manage accounts</a>
    </div>

    {#if overviewAccounts.length > 0}
      <div class="balance-group-list">
        {#each balanceGroups as group}
          <section class={`balance-group ${group.key}`}>
            <div class="balance-group-head-compact">
              <h4>{group.title}</h4>
              <strong class:negative={group.total < 0} class:positive={group.total > 0}>{formatCurrency(group.total)}</strong>
            </div>

            <table class="balance-table">
              <tbody>
                {#each group.accounts as account}
                  <tr>
                    <td class="balance-table-name">
                      <span>
                        {account.displayName}
                        <span class={`pill subtype-pill ${account.kind}`}>{accountSubtypeLabel(account, 'short')}</span>
                      </span>
                      {#if account.importConfigured && !account.hasOpeningBalance}
                        <a class="account-note text-link" href="/accounts">Needs opening balance</a>
                      {/if}
                    </td>
                    <td class:negative={account.balance < 0} class:positive={account.balance > 0} class="balance-table-value">
                      <span>{formatCurrency(account.balance)}</span>
                      {#if isAccountStale(account.lastTransactionDate)}
                        <span class="staleness-note">{accountStalenessLabel(account.lastTransactionDate)}</span>
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
      <p class="empty-copy">No tracked accounts configured yet. <a class="text-link" href="/accounts">Add accounts</a> to see balances here.</p>
    {/if}
  </section>
{/if}

<style>
  .dashboard-loading,
  .dashboard-hero,
  .next-action-card {
    padding: 1.5rem;
  }

  .dashboard-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.7fr) minmax(16rem, 0.9fr);
    gap: 1.5rem;
    align-items: start;
    background:
      radial-gradient(circle at top left, rgba(211, 238, 225, 0.9), transparent 34%),
      linear-gradient(155deg, #fbfdf8 0%, #f6fbff 60%, #eef6f3 100%);
  }

  .hero-copy {
    min-width: 0;
  }

  .page-title-xl {
    font-size: clamp(2.3rem, 5vw, 4.4rem);
    line-height: 0.95;
    max-width: 12ch;
  }

  .hero-worth {
    font-size: clamp(3rem, 6vw, 5.2rem);
    line-height: 0.92;
  }

  .hero-label {
    margin: 0.45rem 0 0;
    font-size: 0.92rem;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .hero-momentum {
    margin: 0.3rem 0 0;
    font-size: 1rem;
    color: var(--muted-foreground);
    line-height: 1.4;
  }

  .hero-subtitle {
    max-width: 48rem;
    margin-top: 0.85rem;
    line-height: 1.65;
    font-size: 1rem;
  }

  .hero-side {
    display: grid;
    gap: 0.85rem;
    align-content: start;
    justify-items: start;
    padding: 1rem;
    border-radius: calc(var(--radius) - 0.15rem);
    background: rgba(255, 255, 255, 0.72);
    border: 1px solid rgba(10, 61, 89, 0.08);
  }

  .hero-side-compact {
    min-height: 100%;
  }

  .text-link {
    color: var(--brand-strong);
    text-decoration: none;
    font-weight: 700;
  }

  .text-link:hover {
    text-decoration: underline;
  }

  .landing-grid,
  .progress-grid,
  .detail-grid {
    display: grid;
    gap: 1rem;
  }

  .landing-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .progress-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .detail-grid {
    grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  }

  h3,
  h4 {
    margin: 0;
  }

  .today-rail {
    gap: 0.85rem;
    width: 100%;
  }

  .today-status {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.1rem;
    font-weight: 700;
    line-height: 1.2;
  }

  .hero-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-top: 0.7rem;
  }

  .hero-chip {
    display: inline-flex;
    align-items: baseline;
    gap: 0.35rem;
    padding: 0.3rem 0.65rem;
    border-radius: 999px;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.6);
    font-size: 0.82rem;
    line-height: 1;
  }

  .hero-chip-label {
    color: var(--muted-foreground);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.68rem;
  }

  .hero-chip-value {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
  }

  .hero-links {
    display: flex;
    flex-wrap: wrap;
    gap: 0.85rem;
  }

  .value-card h3,
  .progress-card h3,
  .balances-panel h3,
  .cashflow-panel h3,
  .categories-panel h3,
  .recent-panel h3,
  .next-action-card h3 {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.2rem;
  }

  .value-card p:last-child,
  .progress-card p:last-child,
  .next-action-card p:last-child {
    margin-bottom: 0;
    color: var(--muted-foreground);
    line-height: 1.65;
  }

  .progress-card {
    padding: 1.2rem;
  }

  .progress-kicker {
    margin: 0 0 0.4rem;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
    color: var(--muted-foreground);
  }

  .step-complete {
    border-color: rgba(13, 127, 88, 0.25);
    background: linear-gradient(180deg, #ffffff 0%, #f5fbf7 100%);
  }

  .step-current {
    border-color: rgba(15, 95, 136, 0.22);
    box-shadow: 0 16px 30px rgba(8, 45, 68, 0.09);
  }

  .section-note,
  .transaction-meta,
  .empty-copy,
  .category-values,
  .cashflow-meta span {
    margin: 0;
    color: var(--muted-foreground);
  }

  .balances-panel,
  .cashflow-panel,
  .categories-panel,
  .recent-panel {
    padding: 1.25rem;
  }

  .section-head {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
  }

  .cashflow-list,
  .category-list,
  .transaction-list {
    display: grid;
    gap: 0.85rem;
  }

  .transaction-row {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: center;
    padding: 0.95rem 0;
  }

  .transaction-row + .transaction-row {
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .transaction-payee,
  .category-head p,
  .cashflow-meta p {
    margin: 0;
    font-weight: 700;
  }

  .transaction-amount {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.1rem;
  }

  .balance-group-list {
    display: grid;
    gap: 0.75rem;
  }

  .balance-group + .balance-group {
    padding-top: 0.75rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .balance-group-head-compact {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.25rem;
  }

  .balance-group-head-compact h4 {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .balance-group-head-compact strong {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1rem;
  }

  .balance-table {
    width: 100%;
    border-collapse: collapse;
  }

  .balance-table td {
    padding: 0.4rem 0;
    border-top: 1px solid rgba(10, 61, 89, 0.06);
    vertical-align: baseline;
  }

  .balance-table tr:first-child td {
    border-top: none;
  }

  .balance-table-name {
    font-weight: 500;
  }

  .balance-table-name .subtype-pill {
    margin-left: 0.4rem;
    vertical-align: baseline;
  }

  .balance-table-value {
    text-align: right;
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    white-space: nowrap;
  }

  .account-note {
    display: block;
    font-size: 0.75rem;
    font-weight: 400;
    color: var(--muted-foreground);
  }

  .staleness-note {
    display: block;
    font-size: 0.75rem;
    font-weight: 400;
    color: var(--muted-foreground);
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

  .cashflow-row-compact,
  .category-row {
    display: grid;
    gap: 0.45rem;
  }

  .cashflow-row-compact + .cashflow-row-compact,
  .category-row + .category-row {
    padding-top: 0.65rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .cashflow-meta,
  .category-head,
  .category-values {
    display: flex;
    gap: 0.75rem;
    justify-content: space-between;
    align-items: center;
  }

  .cashflow-bar-pair {
    display: flex;
    gap: 0.25rem;
    height: 0.7rem;
  }

  .cashflow-bar-pair .bar-income,
  .cashflow-bar-pair .bar-spending {
    height: 100%;
    border-radius: 999px;
    min-width: 2px;
  }

  .cashflow-controls {
    display: grid;
    gap: 0.4rem;
    justify-items: end;
    text-align: right;
  }

  .cashflow-presets {
    display: inline-flex;
    gap: 0.15rem;
    padding: 0.15rem;
    border-radius: 999px;
    background: rgba(10, 61, 89, 0.06);
  }

  .cashflow-presets button {
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

  .cashflow-presets button.active {
    background: #fff;
    color: var(--foreground);
    box-shadow: 0 1px 3px rgba(10, 61, 89, 0.1);
  }

  .cashflow-presets button:hover:not(.active) {
    color: var(--foreground);
  }

  .category-bars {
    display: grid;
    gap: 0.4rem;
  }

  .category-meter {
    height: 0.7rem;
    border-radius: 999px;
    background: rgba(10, 61, 89, 0.08);
    overflow: hidden;
  }

  .bar-income,
  .bar-spending,
  .category-meter span {
    display: block;
    height: 100%;
    border-radius: inherit;
  }

  .bar-income {
    background: linear-gradient(90deg, #1d9f6e, #6fd6ae);
  }

  .bar-spending {
    background: linear-gradient(90deg, #0a3d59, #2f88b7);
  }

  .category-meter.current span {
    background: linear-gradient(90deg, #0f5f88, #47a5d8);
  }

  .category-meter.previous span {
    background: linear-gradient(90deg, #d5dee8, #b7c9da);
  }

  .transaction-main,
  .transaction-side {
    display: grid;
    gap: 0.2rem;
  }

  .transaction-side {
    justify-items: end;
  }

  .date-header {
    margin: 0;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .date-group + .date-group {
    margin-top: 0.65rem;
    padding-top: 0.65rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  a.pill.warn {
    text-decoration: none;
  }

  .positive {
    color: var(--ok);
  }

  .negative {
    color: var(--brand-strong);
  }

  @media (max-width: 1100px) {
    .dashboard-hero,
    .detail-grid {
      grid-template-columns: 1fr;
    }

    .categories-panel {
      order: -1;
    }

    .landing-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .progress-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 720px) {
    .landing-grid,
    .progress-grid {
      grid-template-columns: 1fr;
    }

    .dashboard-hero {
      padding: 1.2rem;
    }

    .hero-stats {
      gap: 0.4rem;
    }

    .section-head,
    .transaction-row,
    .cashflow-meta,
    .category-head,
    .category-values {
      grid-template-columns: 1fr;
      display: grid;
    }

    .transaction-side,
    .hero-side {
      justify-items: start;
    }
  }
</style>
