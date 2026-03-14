<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';

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

  type ActionLink = {
    href: string;
    label: string;
  };

  type PrimaryTask = ActionLink & {
    note: string;
  };

  type AttentionItem = {
    title: string;
    note: string;
    href: string;
    cta: string;
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
  let error = '';
  let loading = true;

  function formatCurrency(value: number, options?: { signed?: boolean; compact?: boolean }): string {
    const currency = dashboard?.baseCurrency || 'USD';
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

  function titleCase(kind: string): string {
    return kind.charAt(0).toUpperCase() + kind.slice(1);
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

  function reviewAttentionNote(): string {
    const count = reviewQueueCount();
    if (count > 0) {
      return 'Clear uncategorized activity so the dashboard reflects cleaner trends.';
    }
    return 'Finish the remaining review work so the dashboard reflects cleaner trends.';
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
      href: '/import',
      label: 'Import latest statement',
      note: 'Nothing needs review right now.'
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
      actions.push({ href: '/unknowns', label: 'Open review queue' });
    }
    actions.push({ href: '/setup', label: 'Manage accounts' });
    return actions;
  }

  function recentActivityAction(): ActionLink {
    if (hasReviewQueue()) return { href: '/unknowns', label: 'Open review queue' };
    return { href: '/import', label: 'Import more' };
  }

  function attentionItems(): AttentionItem[] {
    if (!state?.initialized) return [];

    const items: AttentionItem[] = [];
    const inboxCount = statementInboxCount();

    if (state.setup?.needsAccounts) {
      items.push({
        title: 'Accounts still need setup',
        note: 'Add the first accounts before the dashboard can stay current.',
        href: '/setup',
        cta: 'Finish setup'
      });
    }

    if (state.setup?.needsFirstImport || !dashboard?.hasData) {
      items.push({
        title: 'No imported activity yet',
        note: 'Bring in one statement so balances and trends can populate.',
        href: '/setup',
        cta: 'Import first statement'
      });
    }

    if (hasReviewQueue()) {
      items.push({
        title: reviewQueueTitle(),
        note: reviewAttentionNote(),
        href: '/unknowns',
        cta: 'Review now'
      });
    }

    if (inboxCount > 0) {
      items.push({
        title: statementInboxTitle(),
        note: 'Import the latest files to keep balances and recent activity accurate.',
        href: '/import',
        cta: 'Open import'
      });
    }

    if (items.length === 0) {
      items.push({
        title: 'Everything looks current',
        note: 'There is nothing urgent to clean up. Import fresh activity when you are ready.',
        href: '/import',
        cta: 'Import latest statement'
      });
    }

    return items.slice(0, 3);
  }

  $: activeTask = primaryTask();
  $: secondary = secondaryActions();
  $: attention = attentionItems();
  $: recentAction = recentActivityAction();
  $: steps = setupSteps();
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
        dashboard = await apiGet<DashboardOverview>('/api/dashboard/overview');
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
        Ledger Flow now centers the daily overview, not the underlying file structure. Start with a workspace,
        import one statement, and the app takes over from there.
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
        The dashboard is in place, but it needs one complete path through setup before it can show balances, cash
        flow, and recent activity.
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
        Updated through {formatDate(dashboard.lastUpdated)}. {dashboard.summary.transactionCount} transactions are
        loaded into the workspace. {activeTask.note}
      </p>
    </div>

    <div class="hero-side hero-side-compact">
      <a class="btn btn-primary" href={activeTask.href}>{activeTask.label}</a>
      {#each secondary as action}
        <a class="text-link" href={action.href}>{action.label}</a>
      {/each}
    </div>
  </section>

  <section class="summary-grid">
    <article class="view-card summary-card">
      <p class="stat-label">Tracked balances</p>
      <p class="stat-value">{formatCurrency(dashboard.summary.trackedBalanceTotal)}</p>
      <p class="stat-note">{dashboard.balances.length} tracked accounts on the overview.</p>
    </article>

    <article class="view-card summary-card">
      <p class="stat-label">Cash flow this month</p>
      <p class:positive={dashboard.summary.savingsThisMonth >= 0} class:negative={dashboard.summary.savingsThisMonth < 0} class="stat-value">
        {formatCurrency(dashboard.summary.savingsThisMonth, { signed: true })}
      </p>
      <p class="stat-note">{monthTitle(dashboard.cashFlow.currentMonth)}</p>
    </article>

    <article class="view-card summary-card">
      <p class="stat-label">Income this month</p>
      <p class="stat-value positive">{formatCurrency(dashboard.summary.incomeThisMonth)}</p>
      <p class="stat-note">Money in across imported activity.</p>
    </article>

    <article class="view-card summary-card">
      <p class="stat-label">Spent this month</p>
      <p class="stat-value negative">{formatCurrency(dashboard.summary.spendingThisMonth)}</p>
      <p class="stat-note">Based on categorized expense postings.</p>
    </article>
  </section>

  <section class="dashboard-main">
    <article class="view-card balances-panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Balances</p>
          <h3>Tracked accounts</h3>
        </div>
        <a class="text-link" href="/setup">Manage accounts</a>
      </div>

      <div class="balance-list">
        {#each dashboard.balances as balance}
          <div class="balance-row">
            <div>
              <p class="balance-name">{balance.displayName}</p>
              <p class="balance-note">
                {titleCase(balance.kind)}{#if balance.last4} •••• {balance.last4}{/if}
              </p>
            </div>
            <p class:negative={balance.balance < 0} class:positive={balance.balance > 0} class="balance-value">
              {formatCurrency(balance.balance)}
            </p>
          </div>
        {/each}
      </div>
    </article>

    <article class="view-card attention-panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Attention</p>
          <h3>What to do next</h3>
        </div>
      </div>

      <div class="attention-list">
        {#each attention as item}
          <a class="attention-item" href={item.href}>
            <div>
              <p class="attention-title">{item.title}</p>
              <p class="attention-note">{item.note}</p>
            </div>
            <span class="attention-cta">{item.cta}</span>
          </a>
        {/each}
      </div>
    </article>
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
  .summary-grid,
  .detail-grid {
    display: grid;
    gap: 1rem;
  }

  .landing-grid,
  .summary-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .progress-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .summary-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .detail-grid {
    grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  }

  .value-card h3,
  .progress-card h3,
  .balances-panel h3,
  .attention-panel h3,
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

  .summary-card {
    padding: 1.1rem 1.15rem;
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
  .attention-note,
  .transaction-meta,
  .empty-copy,
  .category-values,
  .cashflow-meta span {
    margin: 0;
    color: var(--muted-foreground);
  }

  .dashboard-main {
    display: grid;
    grid-template-columns: minmax(0, 1.25fr) minmax(18rem, 0.75fr);
    gap: 1rem;
  }

  .balances-panel,
  .attention-panel,
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
  .attention-list,
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
  .attention-title,
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

  .attention-item {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    border-radius: 1rem;
    background: rgba(244, 249, 255, 0.72);
    border: 1px solid rgba(10, 61, 89, 0.08);
    text-decoration: none;
    color: inherit;
  }

  .attention-item:hover {
    border-color: rgba(15, 95, 136, 0.18);
    transform: translateY(-1px);
  }

  .attention-cta {
    font-weight: 700;
    color: var(--brand-strong);
    white-space: nowrap;
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
    .dashboard-main,
    .detail-grid {
      grid-template-columns: 1fr;
    }

    .landing-grid,
    .summary-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .progress-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 720px) {
    .landing-grid,
    .progress-grid,
    .summary-grid {
      grid-template-columns: 1fr;
    }

    .dashboard-hero {
      padding: 1.2rem;
    }

    .section-head,
    .balance-row,
    .transaction-row,
    .attention-item,
    .cashflow-meta,
    .cashflow-values,
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
