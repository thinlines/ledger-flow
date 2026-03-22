<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';
  import { describeAccountSubtype } from '$lib/account-subtypes';
  import { describeBalanceTrust } from '$lib/account-trust';

  type AppState = {
    initialized: boolean;
    workspaceName: string | null;
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

  type AccountGroup = {
    kind: string;
    title: string;
    note: string;
    balanceTotal: number | null;
    accounts: TrackedAccount[];
  };

  type DashboardBalance = DashboardOverview['balances'][number];

  type ActionLink = {
    href: string;
    label: string;
  };

  type NextStepAction = ActionLink & {
    title: string;
    note: string;
  };

  let initialized = false;
  let workspaceName = '';
  let trackedAccounts: TrackedAccount[] = [];
  let dashboardBalances: Record<string, DashboardBalance> = {};
  let baseCurrency = 'USD';
  let error = '';
  let loading = true;
  let accountQuery = '';
  let normalizedAccountQuery = '';
  let filteredTrackedAccounts: TrackedAccount[] = [];
  let accountGroups: AccountGroup[] = [];
  let missingSourceAccounts: TrackedAccount[] = [];
  let startingBalanceOnlyAccounts: TrackedAccount[] = [];
  let balanceReadyCount = 0;
  let balanceNeedsSetupCount = 0;
  let openingBalanceOnlyCount = 0;
  let primaryAction: NextStepAction | null = null;
  let secondaryActions: ActionLink[] = [];

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

  function balanceMeta(accountId: string): DashboardBalance | null {
    return dashboardBalances[accountId] ?? null;
  }

  function currentBalance(accountId: string): number | null {
    return balanceMeta(accountId)?.balance ?? null;
  }

  function kindRank(kind: string): number {
    if (kind === 'asset') return 0;
    if (kind === 'liability') return 1;
    return 2;
  }

  function kindLabel(kind: string): string {
    if (kind === 'asset') return 'Asset';
    if (kind === 'liability') return 'Liability';
    return titleCase(kind);
  }

  function groupTitle(kind: string): string {
    if (kind === 'asset') return 'Assets';
    if (kind === 'liability') return 'Liabilities';
    return 'Other tracked accounts';
  }

  function groupNote(kind: string): string {
    if (kind === 'asset') return 'Cash, bank, and investment accounts that support your current position.';
    if (kind === 'liability') return 'Credit cards and debt balances that affect net worth and upcoming decisions.';
    return 'Tracked accounts that fall outside the main balance-sheet groups.';
  }

  function groupBalanceTotal(accounts: TrackedAccount[]): number | null {
    const balances = accounts
      .map((account) => currentBalance(account.id))
      .filter((balance): balance is number => balance != null);
    if (!balances.length) return null;
    return balances.reduce((sum, balance) => sum + balance, 0);
  }

  function groupBalanceLabel(value: number | null): string {
    return value == null ? 'No balances yet' : formatCurrency(value);
  }

  function accountIdentity(account: TrackedAccount): string {
    const parts = [account.institutionDisplayName || 'Tracked manually'];
    if (account.last4) parts.push(`•••• ${account.last4}`);
    return parts.join(' · ');
  }

  function accountSubtypeLine(account: TrackedAccount): string {
    const subtype = describeAccountSubtype(account);
    if (subtype.source === 'suggested') return `Suggested ${subtype.longLabel.toLowerCase()}`;
    return subtype.longLabel;
  }

  function accountSubtypePillLabel(account: TrackedAccount): string {
    const subtype = describeAccountSubtype(account);
    if (subtype.source === 'suggested') return `Suggested: ${subtype.shortLabel}`;
    return subtype.shortLabel;
  }

  function accountSubtypePillTone(account: TrackedAccount): string {
    const subtype = describeAccountSubtype(account);
    if (subtype.source === 'saved') return account.kind;
    if (subtype.source === 'suggested') return 'suggested';
    return 'broad';
  }

  function subtypeStateNote(account: TrackedAccount): string {
    const subtype = describeAccountSubtype(account);
    if (subtype.source === 'suggested') {
      return 'Subtype is suggested from the account name. Save the account in Accounts if you want it stored explicitly.';
    }
    if (subtype.source === 'broad') {
      return 'No narrower subtype is saved yet.';
    }
    return `Saved as ${subtype.longLabel}.`;
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

  function accountStatusLabel(account: TrackedAccount): string {
    return balanceTrust(account).shortLabel;
  }

  function accountStatusNote(account: TrackedAccount): string {
    return balanceTrust(account).note;
  }

  function accountStatusTone(account: TrackedAccount): string {
    const trust = balanceTrust(account).tone;
    if (trust === 'warn') return 'attention';
    if (trust === 'ok') return 'ok';
    return 'manual';
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
    return 'Supported institution';
  }

  function importSetupNote(account: TrackedAccount): string {
    if (!account.importConfigured) return 'No automated import attached.';
    if (account.importMode === 'custom') {
      return 'Custom CSV mapping is ready for the next statement.';
    }
    return 'Ready to bring in new statement activity.';
  }

  function hasAdvancedDetails(account: TrackedAccount): boolean {
    return Boolean(account.ledgerAccount) || (account.importMode === 'custom' && Boolean(account.importProfile));
  }

  function matchesAccountQuery(account: TrackedAccount, query: string): boolean {
    if (!query) return true;
    const haystack = [
      account.displayName,
      account.institutionDisplayName,
      account.last4,
      account.subtype,
      account.ledgerAccount,
      account.importAccountId,
      accountSubtypePillLabel(account),
      accountSubtypeLine(account),
      kindLabel(account.kind),
      importSetupTitle(account),
      importSetupNote(account)
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    return haystack.includes(query);
  }

  function compareAccounts(left: TrackedAccount, right: TrackedAccount): number {
    const nameDelta = left.displayName.localeCompare(right.displayName, undefined, { sensitivity: 'base' });
    if (nameDelta !== 0) return nameDelta;
    return accountIdentity(left).localeCompare(accountIdentity(right), undefined, { sensitivity: 'base' });
  }

  function buildAccountGroups(accounts: TrackedAccount[]): AccountGroup[] {
    const orderedKinds = ['asset', 'liability'];
    const otherKinds = Array.from(new Set(accounts.map((account) => account.kind))).filter((kind) => !orderedKinds.includes(kind));
    const groups: AccountGroup[] = [];

    for (const kind of [...orderedKinds, ...otherKinds]) {
      const items = accounts.filter((account) => account.kind === kind);
      if (!items.length) continue;
      groups.push({
        kind,
        title: groupTitle(kind),
        note: groupNote(kind),
        balanceTotal: groupBalanceTotal(items),
        accounts: items
      });
    }

    return groups;
  }

  function accountsMissingSource(accounts: TrackedAccount[]): TrackedAccount[] {
    return accounts.filter((account) => balanceTrust(account).tone === 'warn');
  }

  function accountsUsingOnlyStartingBalance(accounts: TrackedAccount[]): TrackedAccount[] {
    return accounts.filter((account) => balanceTrust(account).shortLabel === 'Starting balance');
  }

  function nextStepAction(accounts: TrackedAccount[], missingAccounts: TrackedAccount[]): NextStepAction {
    if (accounts.length === 0) {
      return {
        href: '/accounts/configure?mode=manual',
        label: 'Add first account',
        title: 'Add the first account you want to track',
        note: 'Start with one real account and either a starting balance or import setup. You can add the rest later.'
      };
    }

    const firstMissing = missingAccounts[0];
    if (firstMissing) {
      return {
        href: `/accounts/configure?accountId=${firstMissing.id}`,
        label: 'Finish balance setup',
        title: 'Fill in the missing starting points',
        note: `${firstMissing.displayName} still needs a starting balance or imported history before it belongs in totals with confidence.`
      };
    }

    if (accounts.some((account) => account.importConfigured)) {
      return {
        href: '/import',
        label: 'Import latest statements',
        title: 'Bring in the latest activity',
        note: 'Balances are in place. Import new statements to keep recent activity and account totals current.'
      };
    }

    return {
      href: '/transactions',
      label: 'Open transactions',
      title: 'Review the balances already on file',
      note: 'These accounts are being tracked manually. Use transactions to inspect the current picture, or add import-ready accounts later.'
    };
  }

  function nextStepSecondaryActions(accounts: TrackedAccount[]): ActionLink[] {
    if (accounts.length === 0) {
      return [{ href: '/setup', label: 'Open setup' }];
    }

    const actions: ActionLink[] = [];
    if (accounts.some((account) => account.importConfigured)) {
      actions.push({ href: '/transactions', label: 'Open transactions' });
    } else {
      actions.push({ href: '/accounts/configure?mode=institution', label: 'Add supported account' });
    }
    actions.push({ href: '/accounts/configure?mode=manual', label: 'Add manual account' });
    return actions;
  }

  async function load() {
    const state = await apiGet<AppState>('/api/app/state');
    initialized = state.initialized;
    workspaceName = state.workspaceName ?? '';
    if (!initialized) return;

    const [accountsData, dashboardData] = await Promise.all([
      apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts'),
      apiGet<DashboardOverview>('/api/dashboard/overview')
    ]);

    trackedAccounts = accountsData.trackedAccounts;
    baseCurrency = dashboardData.baseCurrency;
    dashboardBalances = Object.fromEntries(dashboardData.balances.map((balance) => [balance.id, balance]));
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

  $: normalizedAccountQuery = accountQuery.trim().toLowerCase();
  $: filteredTrackedAccounts = [...trackedAccounts]
    .sort((left, right) => {
      const rankDelta = kindRank(left.kind) - kindRank(right.kind);
      return rankDelta !== 0 ? rankDelta : compareAccounts(left, right);
    })
    .filter((account) => matchesAccountQuery(account, normalizedAccountQuery));
  $: accountGroups = buildAccountGroups(filteredTrackedAccounts);
  $: missingSourceAccounts = accountsMissingSource(trackedAccounts);
  $: startingBalanceOnlyAccounts = accountsUsingOnlyStartingBalance(trackedAccounts);
  $: balanceReadyCount = trackedAccounts.length - missingSourceAccounts.length;
  $: balanceNeedsSetupCount = missingSourceAccounts.length;
  $: openingBalanceOnlyCount = startingBalanceOnlyAccounts.length;
  $: primaryAction = nextStepAction(trackedAccounts, missingSourceAccounts);
  $: secondaryActions = nextStepSecondaryActions(trackedAccounts);
</script>

{#if error}
  <section class="view-card hero">
    <p class="eyebrow">Accounts</p>
    <h2 class="page-title">Could not load account inventory</h2>
    <p class="subtitle">{error}</p>
    <div class="actions">
      <button class="btn btn-primary" type="button" on:click={() => window.location.reload()}>Reload page</button>
      <a class="btn" href="/">Back to overview</a>
    </div>
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
        Review the assets and liabilities you track here. Open the configuration workspace when you want to add
        accounts, save a subtype explicitly, or edit import setup.
      </p>
    </div>

    <div class="hero-stats">
      <div>
        <span class="stat-kicker">Tracked</span>
        <strong>{trackedAccounts.length}</strong>
      </div>
      <div>
        <span class="stat-kicker">Balance ready</span>
        <strong>{balanceReadyCount}</strong>
      </div>
      <div>
        <span class="stat-kicker">Needs setup</span>
        <strong>{balanceNeedsSetupCount}</strong>
      </div>
    </div>
  </section>

  <section class="view-card">
    <div class="section-head">
      <div>
        <p class="eyebrow">Next step</p>
        <h3>{primaryAction?.title}</h3>
        <p class="muted">
          {primaryAction?.note}
          {#if openingBalanceOnlyCount > 0}
            {` ${openingBalanceOnlyCount} account${openingBalanceOnlyCount === 1 ? '' : 's'} still rely on a starting balance only.`}
          {/if}
        </p>
      </div>
      <a class="text-link" href="/">Back to overview</a>
    </div>

    <div class="quick-actions">
      {#if primaryAction}
        <a class="btn btn-primary" href={primaryAction.href}>{primaryAction.label}</a>
      {/if}
      {#each secondaryActions as action}
        <a class="btn" href={action.href}>{action.label}</a>
      {/each}
      <a class="text-link" href="/accounts/configure">Open configuration workspace</a>
    </div>
  </section>

  <section class="view-card">
    <div class="section-head">
      <div>
        <p class="eyebrow">Inventory</p>
        <h3>Tracked accounts</h3>
      </div>
    </div>

    {#if trackedAccounts.length > 0}
      <div class="inventory-toolbar">
        <label class="search-field" for="account-search">
          <span>Find an account</span>
          <input
            id="account-search"
            bind:value={accountQuery}
            type="search"
            placeholder="Search by name, institution, or last four"
          />
        </label>
        <p aria-live="polite" class="inventory-results">
          {#if normalizedAccountQuery}
            Showing {filteredTrackedAccounts.length} of {trackedAccounts.length} accounts
          {:else}
            {trackedAccounts.length} tracked account{trackedAccounts.length === 1 ? '' : 's'}
          {/if}
        </p>
      </div>
    {/if}

    {#if trackedAccounts.length === 0}
      <div class="empty-panel">
        <h4>No accounts yet</h4>
        <p>Start with something you own or owe, then add a starting balance or import setup so totals are grounded.</p>
      </div>
    {:else if filteredTrackedAccounts.length === 0}
      <div class="empty-panel">
        <h4>No matching accounts</h4>
        <p>Try a different account name, institution, or last four digits.</p>
      </div>
    {:else}
      <div class="account-group-list">
        {#each accountGroups as group}
          <div class="account-group">
            <div class="account-group-head">
              <div>
                <h4 class="account-group-title">{group.title}</h4>
                <p class="account-group-note">{group.note}</p>
              </div>
              <div class="account-group-summary">
                <span>{group.accounts.length} account{group.accounts.length === 1 ? '' : 's'}</span>
                <strong>{groupBalanceLabel(group.balanceTotal)}</strong>
              </div>
            </div>

            <div class="account-list">
              {#each group.accounts as account}
                <article class:liability-card={account.kind === 'liability'} class="account-card">
                  <div class="account-card-main">
                    <div class:liability-panel={account.kind === 'liability'} class="account-balance-panel">
                      <div class="account-balance-header">
                        <p class:liability-context={account.kind === 'liability'} class="account-balance-context">
                          {accountSubtypeLine(account)}
                        </p>
                        <p class="metric-label">Current balance</p>
                        <p
                          class:positive={(currentBalance(account.id) ?? 0) > 0}
                          class:negative={(currentBalance(account.id) ?? 0) < 0}
                          class="account-balance-value"
                        >
                          {formatCurrency(currentBalance(account.id))}
                        </p>
                      </div>
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
                          <p class="account-identity-note">{accountIdentity(account)}</p>
                        </div>
                        <div class="account-card-actions">
                          <a class="inline-link" href={`/transactions?accountId=${account.id}`}>Transactions</a>
                          <a class="inline-link" href={`/accounts/configure?accountId=${account.id}`}>Edit</a>
                        </div>
                      </div>

                      <div class="pill-row">
                        <span class={`pill status-pill ${accountStatusTone(account)}`}>{accountStatusLabel(account)}</span>
                        <span class:ok={account.importConfigured} class="pill">{modeLabel(account)}</span>
                        <span class={`pill subtype-pill ${accountSubtypePillTone(account)}`}>{accountSubtypePillLabel(account)}</span>
                        {#if account.last4}
                          <span class="pill">••{account.last4}</span>
                        {/if}
                      </div>

                      <p class="account-trust-note">{accountStatusNote(account)}</p>

                      <dl class="account-meta-grid">
                        <div class="account-meta-item">
                          <dt>Balance coverage</dt>
                          <dd>{balanceTrust(account).label}</dd>
                          <span class="account-meta-note">
                            {accountStatusNote(account)}
                          </span>
                        </div>

                        <div class="account-meta-item">
                          <dt>Starting balance</dt>
                          <dd>{account.openingBalance ? formatStoredAmount(account.openingBalance) : 'Not set'}</dd>
                          <span class="account-meta-note">
                            {account.openingBalanceDate ? shortDate(account.openingBalanceDate) : 'Add a starting date if older history is still missing.'}
                          </span>
                        </div>

                        <div class="account-meta-item">
                          <dt>Subtype</dt>
                          <dd>{accountSubtypePillLabel(account)}</dd>
                          <span class="account-meta-note">{subtypeStateNote(account)}</span>
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
                      <summary>Accounting details</summary>
                      <p class="muted small">Ledger account: {account.ledgerAccount}</p>
                      {#if account.importMode === 'custom' && account.importProfile}
                        <p class="muted small">{customProfileSummary(account)}</p>
                        <p class="muted small">Currency symbol: {account.importProfile.currency || '$'}</p>
                        <p class="muted small">Date column: {account.importProfile.dateColumn || 'Not set'}</p>
                        <p class="muted small">Description column: {account.importProfile.descriptionColumn || 'Not set'}</p>
                        <p class="muted small">Code column: {account.importProfile.codeColumn || 'Not set'}</p>
                      {/if}
                    </details>
                  {/if}
                </article>
              {/each}
            </div>
          </div>
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

  .inventory-toolbar {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
  }

  .search-field {
    display: grid;
    gap: 0.35rem;
    min-width: min(26rem, 100%);
    flex: 1 1 20rem;
  }

  .search-field span {
    font-size: 0.86rem;
    color: var(--muted-foreground);
    font-weight: 600;
  }

  .inventory-results {
    margin: 0;
    color: var(--muted-foreground);
  }

  .account-group-list {
    display: grid;
    gap: 1.15rem;
  }

  .account-group {
    display: grid;
    gap: 0.85rem;
  }

  .account-group-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .account-group-title {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.15rem;
  }

  .account-group-note {
    margin: 0.35rem 0 0;
    color: var(--muted-foreground);
    max-width: 56ch;
  }

  .account-group-summary {
    min-width: 12rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 1rem;
    padding: 0.8rem 0.9rem;
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.9), rgba(243, 249, 255, 0.84));
  }

  .account-group-summary span {
    display: block;
    margin-bottom: 0.2rem;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .account-group-summary strong {
    display: block;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.35rem;
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

  .liability-card {
    border-color: rgba(154, 81, 41, 0.14);
    background: rgba(255, 250, 246, 0.72);
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
    gap: 0.4rem;
    min-height: 100%;
    padding: 1rem;
    border-radius: 1rem;
    border: 1px solid rgba(15, 95, 136, 0.12);
    background: linear-gradient(160deg, rgba(244, 249, 255, 0.96), rgba(239, 248, 244, 0.9));
  }

  .liability-panel {
    border-color: rgba(154, 81, 41, 0.14);
    background: linear-gradient(160deg, rgba(255, 248, 243, 0.96), rgba(255, 244, 237, 0.92));
  }

  .account-balance-header {
    display: grid;
    gap: 0.3rem;
    align-items: start;
  }

  .account-balance-context {
    margin: 0;
    color: var(--brand-strong);
    font-size: 0.88rem;
    font-weight: 700;
  }

  .liability-context {
    color: #9a5129;
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

  .account-title-group h4 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.35rem;
  }

  .account-identity-note {
    margin: 0.35rem 0 0;
    color: var(--muted-foreground);
    font-weight: 600;
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

  .account-trust-note {
    margin: 0;
    color: var(--muted-foreground);
    line-height: 1.5;
  }

  .pill.ok {
    background: rgba(13, 127, 88, 0.12);
    color: var(--ok);
  }

  .status-pill.attention,
  .subtype-pill.liability {
    background: rgba(154, 81, 41, 0.12);
    color: #9a5129;
    border-color: rgba(154, 81, 41, 0.18);
  }

  .status-pill.manual,
  .subtype-pill.asset {
    background: rgba(15, 95, 136, 0.08);
    color: var(--brand-strong);
    border-color: rgba(15, 95, 136, 0.14);
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

    .account-group-head {
      align-items: stretch;
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
