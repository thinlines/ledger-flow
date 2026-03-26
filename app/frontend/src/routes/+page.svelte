<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';
  import { accountSubtypeLabel } from '$lib/account-subtypes';
  import { describeBalanceTrust } from '$lib/account-trust';
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

  type CoverageItem = {
    label: string;
    value: string;
    note: string;
    tone?: 'ok' | 'warn' | 'neutral';
  };

  type HeroSignal = {
    label: string;
    value: string;
    note: string;
    tone?: 'ok' | 'warn' | 'neutral';
  };

  type OverviewAccount = TrackedAccount & {
    balance: number;
    hasOpeningBalance: boolean;
    hasTransactionActivity: boolean;
    hasBalanceSource: boolean;
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
  let coverage: CoverageItem[] = [];
  let todaySignals: HeroSignal[] = [];
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

  function accountIdentity(account: OverviewAccount): string {
    const parts = [account.institutionDisplayName || 'Manual account'];
    if (account.last4) parts.push(`•••• ${account.last4}`);
    return parts.join(' · ');
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

  function accountCoverageLabel(account: OverviewAccount): string {
    return describeBalanceTrust({
      hasOpeningBalance: account.hasOpeningBalance,
      hasTransactionActivity: account.hasTransactionActivity,
      hasBalanceSource: account.hasBalanceSource,
      importConfigured: account.importConfigured,
      openingBalanceDate: account.openingBalanceDate
    }).shortLabel;
  }

  function accountCoverageTone(account: OverviewAccount): 'ok' | 'warn' | 'neutral' {
    return describeBalanceTrust({
      hasOpeningBalance: account.hasOpeningBalance,
      hasTransactionActivity: account.hasTransactionActivity,
      hasBalanceSource: account.hasBalanceSource,
      importConfigured: account.importConfigured,
      openingBalanceDate: account.openingBalanceDate
    }).tone;
  }

  function accountCoverageNote(account: OverviewAccount): string {
    return describeBalanceTrust({
      hasOpeningBalance: account.hasOpeningBalance,
      hasTransactionActivity: account.hasTransactionActivity,
      hasBalanceSource: account.hasBalanceSource,
      importConfigured: account.importConfigured,
      openingBalanceDate: account.openingBalanceDate
    }).note;
  }

  function compareOverviewAccounts(left: OverviewAccount, right: OverviewAccount): number {
    const balanceDelta = Math.abs(right.balance) - Math.abs(left.balance);
    if (balanceDelta !== 0) return balanceDelta;
    return left.displayName.localeCompare(right.displayName, undefined, { sensitivity: 'base' });
  }

  function buildOverviewAccounts(): OverviewAccount[] {
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
          hasBalanceSource: balance.hasBalanceSource
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

  function coverageItems(accounts: OverviewAccount[]): CoverageItem[] {
    if (!accounts.length) return [];

    const coveredCount = accounts.filter((account) => account.hasBalanceSource).length;
    const missingCount = accounts.length - coveredCount;
    const importReadyCount = accounts.filter((account) => account.importConfigured).length;
    const manualCount = accounts.length - importReadyCount;

    return [
      {
        label: 'Coverage',
        value: `${coveredCount} of ${accounts.length}`,
        note: 'Balances backed by history or a starting balance.',
        tone: coveredCount === accounts.length ? 'ok' : 'neutral'
      },
      {
        label: 'Needs a start',
        value: String(missingCount),
        note:
          missingCount > 0
            ? `${countLabel(missingCount, 'account')} still need imported history or a starting balance.`
            : 'Every tracked account has history or a starting balance.',
        tone: missingCount > 0 ? 'warn' : 'ok'
      },
      {
        label: 'Import ready',
        value: `${importReadyCount} of ${accounts.length}`,
        note:
          manualCount > 0
            ? `${countLabel(manualCount, 'account')} ${manualCount === 1 ? 'is' : 'are'} tracked manually.`
            : 'Every tracked account can import fresh activity.',
        tone: importReadyCount > 0 ? 'neutral' : 'ok'
      }
    ];
  }

  function caughtUpInsight(): HeroSignal | null {
    if (dashboard?.categoryTrends.length) {
      const trend = dashboard.categoryTrends[0];
      return {
        label: 'Watch item',
        value: trend.category,
        note: formatTrend(trend.delta),
        tone: trend.delta > 0 ? 'warn' : trend.delta < 0 ? 'ok' : 'neutral'
      };
    }

    const latest = dashboard?.recentTransactions[0];
    if (!latest) return null;
    return {
      label: 'Latest activity',
      value: latest.payee,
      note: `${shortDate(latest.date)} · ${formatCurrency(latest.amount, { signed: true })}`,
      tone: latest.isUnknown ? 'warn' : 'neutral'
    };
  }

  function heroRailTitle(): string {
    if (hasReviewQueue()) return reviewQueueTitle();
    if (statementInboxCount() > 0) return statementInboxTitle();
    return 'Books look current';
  }

  function heroRailNote(): string {
    if (hasReviewQueue()) return 'Resolve uncategorized activity so the overview stays clean and trustworthy.';
    if (statementInboxCount() > 0) return 'Bring in the latest files to keep balances and recent activity current.';
    if (dashboard?.categoryTrends.length) {
      return `${dashboard.categoryTrends[0].category} is the biggest spending move versus last month.`;
    }
    return 'No review or import backlog right now.';
  }

  function heroSignals(): HeroSignal[] {
    if (!dashboard) return [];

    const reviewCount = reviewQueueCount();
    const inboxCount = statementInboxCount();
    const monthSignal: HeroSignal = {
      label: 'This month',
      value: formatCurrency(dashboard.summary.savingsThisMonth, { signed: true }),
      note: `Net cash flow for ${monthTitle(dashboard.cashFlow.currentMonth)}.`,
      tone: dashboard.summary.savingsThisMonth < 0 ? 'warn' : dashboard.summary.savingsThisMonth > 0 ? 'ok' : 'neutral'
    };

    const reviewSignal: HeroSignal = {
      label: 'Review',
      value: reviewCount > 0 ? `${reviewCount} waiting` : 'Clear',
      note: reviewCount > 0 ? 'Uncategorized activity still needs attention.' : 'No uncategorized transactions right now.',
      tone: reviewCount > 0 ? 'warn' : 'ok'
    };

    const inboxSignal: HeroSignal = {
      label: 'Statements',
      value: inboxCount > 0 ? `${inboxCount} waiting` : 'Inbox empty',
      note: inboxCount > 0 ? 'New files are ready to import.' : 'No queued statement files right now.',
      tone: inboxCount > 0 ? 'neutral' : 'ok'
    };

    if (reviewCount > 0) return [reviewSignal, inboxSignal, monthSignal];
    if (inboxCount > 0) return [inboxSignal, reviewSignal, monthSignal];

    const insight = caughtUpInsight();
    const signals: HeroSignal[] = [
      {
        label: 'Status',
        value: 'Up to date',
        note: 'Review and import queues are both clear.',
        tone: 'ok'
      },
      monthSignal
    ];
    if (insight) signals.splice(1, 0, insight);
    return signals;
  }

  function setupSteps(): SetupStep[] {
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

  function primaryTask(): PrimaryTask {
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
    return {
      href: '/transactions',
      label: 'Open transactions',
      note: 'Scan the latest activity or drill into an account register.'
    };
  }

  function secondaryActions(): ActionLink[] {
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

  $: activeTask = primaryTask();
  $: secondary = secondaryActions();
  $: recentAction = recentActivityAction();
  $: steps = setupSteps();
  $: overviewAccounts = buildOverviewAccounts();
  $: balanceGroups = buildBalanceGroups(overviewAccounts);
  $: coverage = coverageItems(overviewAccounts);
  $: todaySignals = heroSignals();
  $: cashFlowMax = Math.max(...(dashboard?.cashFlow.series.map((row) => Math.max(row.income, row.spending)) ?? [0]));
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
      <p class="subtitle hero-subtitle">
        Through {formatDate(dashboard.lastUpdated)}, with {countLabel(dashboard.summary.transactionCount, 'transaction')} in view.
        {activeTask.note}
      </p>
    </div>

    <div class="hero-side hero-side-compact today-rail">
      <div class="today-head">
        <p class="eyebrow">Today</p>
        <h3>{heroRailTitle()}</h3>
        <p class="section-note today-note">{heroRailNote()}</p>
      </div>

      <div class="today-signal-list">
        {#each todaySignals as signal}
          <article class={`today-signal ${signal.tone ?? 'neutral'}`}>
            <span class="today-signal-label">{signal.label}</span>
            <strong>{signal.value}</strong>
            <p>{signal.note}</p>
          </article>
        {/each}
      </div>

      <a class="btn btn-primary" href={activeTask.href}>{activeTask.label}</a>
      <div class="hero-links">
        {#each secondary as action}
          <a class="text-link" href={action.href}>{action.label}</a>
        {/each}
      </div>
    </div>

    <div class="coverage-strip">
      {#each coverage as item}
        <article class={`coverage-item ${item.tone ?? 'neutral'}`}>
          <span class="coverage-label">{item.label}</span>
          <strong>{item.value}</strong>
          <p>{item.note}</p>
        </article>
      {/each}
    </div>
  </section>

  <section class="view-card snapshot-band">
    <article class="snapshot-metric">
      <p class="stat-label">Tracked balances</p>
      <p class="stat-value">{formatCurrency(dashboard.summary.trackedBalanceTotal)}</p>
      <p class="stat-note">Across {countLabel(overviewAccounts.length, 'tracked account')}.</p>
    </article>

    <article class="snapshot-metric">
      <p class="stat-label">Income this month</p>
      <p class="stat-value positive">{formatCurrency(dashboard.summary.incomeThisMonth)}</p>
      <p class="stat-note">Money in for {monthTitle(dashboard.cashFlow.currentMonth)}.</p>
    </article>

    <article class="snapshot-metric">
      <p class="stat-label">Spent this month</p>
      <p class="stat-value negative">{formatCurrency(dashboard.summary.spendingThisMonth)}</p>
      <p class="stat-note">Categorized outflow this month.</p>
    </article>

    <article class="snapshot-metric">
      <p class="stat-label">Net this month</p>
      <p class:positive={dashboard.summary.savingsThisMonth >= 0} class:negative={dashboard.summary.savingsThisMonth < 0} class="stat-value">
        {formatCurrency(dashboard.summary.savingsThisMonth, { signed: true })}
      </p>
      <p class="stat-note">Current month cash flow.</p>
    </article>
  </section>

  <section class="view-card balances-panel balance-sheet-panel">
    <div class="section-head">
      <div>
        <p class="eyebrow">Balance sheet</p>
        <h3>Tracked accounts</h3>
      </div>
      <a class="text-link" href="/accounts">Manage accounts</a>
    </div>

    <div class="balance-group-list">
      {#each balanceGroups as group}
        <section class={`balance-group ${group.key}`}>
          <div class="balance-group-head">
            <div>
              <h4>{group.title}</h4>
              <p class="balance-group-note">{group.note}</p>
            </div>
            <div class="balance-group-summary">
              <span>{countLabel(group.accounts.length, 'account')}</span>
              <strong class:negative={group.total < 0} class:positive={group.total > 0}>{formatCurrency(group.total)}</strong>
            </div>
          </div>

          <div class="balance-list grouped-balance-list">
            {#each group.accounts as account}
              <div class="balance-row grouped-balance-row">
                <div class="grouped-balance-main">
                  <div class="grouped-balance-head">
                    <p class="balance-name">{account.displayName}</p>
                    <div class="pill-row">
                      <span class={`pill subtype-pill ${account.kind}`}>{accountSubtypeLabel(account, 'short')}</span>
                      <span class={`pill coverage-pill ${accountCoverageTone(account)}`}>{accountCoverageLabel(account)}</span>
                    </div>
                  </div>
                  <p class="balance-note">{accountIdentity(account)}</p>
                  <p class="balance-subnote">{accountCoverageNote(account)}</p>
                </div>
                <p class:negative={account.balance < 0} class:positive={account.balance > 0} class="balance-value">
                  {formatCurrency(account.balance)}
                </p>
              </div>
            {/each}
          </div>
        </section>
      {/each}
    </div>
  </section>

  <section class="view-card cashflow-panel">
    <div class="section-head">
      <div>
        <p class="eyebrow">Cash flow</p>
        <h3>Income and spending over the last six months</h3>
      </div>
      <p class="section-note">{formatCurrency(dashboard.cashFlow.net, { signed: true })} this month</p>
    </div>

    <div class="cashflow-list">
      {#each dashboard.cashFlow.series as row}
        <div class="cashflow-row">
          <div class="cashflow-meta">
            <p>{row.label}</p>
            <span>{formatCurrency(row.net, { signed: true, compact: true })}</span>
          </div>

          <div class="cashflow-bars">
            <div class="bar-track">
              <span class="bar-income" style={`width: ${barWidth(row.income, cashFlowMax)}`}></span>
            </div>
            <div class="bar-track">
              <span class="bar-spending" style={`width: ${barWidth(row.spending, cashFlowMax)}`}></span>
            </div>
          </div>

          <div class="cashflow-values">
            <span class="positive">{formatCurrency(row.income)}</span>
            <span class="negative">{formatCurrency(row.spending)}</span>
          </div>
        </div>
      {/each}
    </div>
  </section>

  <section class="detail-grid">
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

    <article class="view-card recent-panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Recent activity</p>
          <h3>Latest transactions</h3>
        </div>
        <a class="text-link" href={recentAction.href}>{recentAction.label}</a>
      </div>

      <div class="transaction-list">
        {#each dashboard.recentTransactions as transaction}
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
                <span class="pill warn">Needs review</span>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    </article>
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
    gap: 1rem;
    width: 100%;
  }

  .today-head {
    display: grid;
    gap: 0.35rem;
    width: 100%;
  }

  .today-head h3 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.25rem;
    line-height: 1.08;
  }

  .today-note {
    line-height: 1.55;
  }

  .today-signal-list {
    width: 100%;
    display: grid;
    gap: 0.7rem;
  }

  .today-signal {
    display: grid;
    gap: 0.18rem;
    width: 100%;
    padding: 0.85rem 0.9rem;
    border-radius: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.86);
  }

  .today-signal.ok {
    border-color: rgba(13, 127, 88, 0.16);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(242, 250, 246, 0.92));
  }

  .today-signal.warn {
    border-color: rgba(173, 106, 0, 0.2);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(255, 248, 236, 0.94));
  }

  .today-signal-label,
  .coverage-label {
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .today-signal strong,
  .coverage-item strong,
  .balance-group-summary strong {
    display: block;
    font-family: 'Space Grotesk', sans-serif;
  }

  .today-signal strong {
    font-size: 1.12rem;
  }

  .today-signal p,
  .coverage-item p {
    margin: 0;
    color: var(--muted-foreground);
    line-height: 1.45;
  }

  .hero-links {
    display: flex;
    flex-wrap: wrap;
    gap: 0.85rem;
  }

  .coverage-strip {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.85rem;
    padding-top: 0.2rem;
  }

  .coverage-item {
    display: grid;
    gap: 0.3rem;
    padding: 0.95rem 1rem;
    border-radius: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.72);
  }

  .coverage-item.ok {
    border-color: rgba(13, 127, 88, 0.16);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(242, 250, 246, 0.9));
  }

  .coverage-item.warn {
    border-color: rgba(173, 106, 0, 0.2);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(255, 248, 236, 0.94));
  }

  .coverage-item strong {
    font-size: 1.28rem;
  }

  .snapshot-band {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0;
    padding: 0;
    overflow: hidden;
  }

  .snapshot-metric {
    padding: 1.1rem 1.15rem;
  }

  .snapshot-metric + .snapshot-metric {
    border-left: 1px solid rgba(10, 61, 89, 0.08);
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

  .stat-label {
    margin: 0;
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .stat-value {
    margin: 0.6rem 0 0.25rem;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 2rem;
    line-height: 1;
  }

  .stat-note,
  .section-note,
  .balance-note,
  .balance-subnote,
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

  .balance-list,
  .cashflow-list,
  .category-list,
  .transaction-list {
    display: grid;
    gap: 0.85rem;
  }

  .balance-row,
  .transaction-row {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: center;
    padding: 0.95rem 0;
  }

  .balance-row + .balance-row,
  .transaction-row + .transaction-row {
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .balance-name,
  .transaction-payee,
  .category-head p,
  .cashflow-meta p {
    margin: 0;
    font-weight: 700;
  }

  .balance-value,
  .transaction-amount {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.1rem;
  }

  .balance-group-list {
    display: grid;
    gap: 1.1rem;
  }

  .balance-group {
    display: grid;
    gap: 0.85rem;
  }

  .balance-group + .balance-group {
    padding-top: 1rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .balance-group-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .balance-group-note {
    margin: 0.35rem 0 0;
    color: var(--muted-foreground);
    max-width: 58ch;
  }

  .balance-group-summary {
    min-width: 12rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1rem;
    padding: 0.8rem 0.9rem;
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.92), rgba(243, 249, 255, 0.88));
  }

  .balance-group-summary span {
    display: block;
    margin-bottom: 0.2rem;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .balance-group-summary strong {
    font-size: 1.35rem;
  }

  .grouped-balance-list {
    gap: 0;
  }

  .grouped-balance-row {
    align-items: flex-start;
  }

  .grouped-balance-main {
    min-width: 0;
    display: grid;
    gap: 0.3rem;
  }

  .grouped-balance-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .balance-subnote {
    font-size: 0.9rem;
    line-height: 1.5;
  }

  .pill-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
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

  .coverage-pill.ok {
    background: rgba(13, 127, 88, 0.12);
    color: var(--ok);
    border-color: rgba(13, 127, 88, 0.16);
  }

  .coverage-pill.warn {
    background: rgba(173, 106, 0, 0.12);
    color: var(--warn);
    border-color: rgba(173, 106, 0, 0.18);
  }

  .coverage-pill.neutral {
    background: rgba(10, 61, 89, 0.06);
    color: var(--brand-strong);
    border-color: rgba(10, 61, 89, 0.12);
  }

  .cashflow-row,
  .category-row {
    display: grid;
    gap: 0.7rem;
  }

  .cashflow-row + .cashflow-row,
  .category-row + .category-row {
    padding-top: 0.85rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .cashflow-meta,
  .category-head,
  .cashflow-values,
  .category-values {
    display: flex;
    gap: 0.75rem;
    justify-content: space-between;
    align-items: center;
  }

  .cashflow-bars,
  .category-bars {
    display: grid;
    gap: 0.4rem;
  }

  .bar-track,
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

    .landing-grid,
    .coverage-strip,
    .snapshot-band {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .progress-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 720px) {
    .landing-grid,
    .progress-grid,
    .coverage-strip,
    .snapshot-band {
      grid-template-columns: 1fr;
    }

    .dashboard-hero {
      padding: 1.2rem;
    }

    .section-head,
    .balance-row,
    .transaction-row,
    .cashflow-meta,
    .cashflow-values,
    .category-head,
    .category-values {
      grid-template-columns: 1fr;
      display: grid;
    }

    .grouped-balance-head,
    .balance-group-head {
      align-items: stretch;
    }

    .grouped-balance-head {
      flex-direction: column;
    }

    .transaction-side,
    .hero-side {
      justify-items: start;
    }

    .snapshot-metric + .snapshot-metric {
      border-left: 0;
      border-top: 1px solid rgba(10, 61, 89, 0.08);
    }
  }
</style>
