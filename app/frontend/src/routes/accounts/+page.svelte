<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { apiGet } from '$lib/api';
  import { describeAccountSubtype } from '$lib/account-subtypes';
  import { effectiveOpeningBalanceDate } from '$lib/account-defaults';
  import { describeBalanceTrust } from '$lib/account-trust';
  import { normalizeCurrencyCode } from '$lib/currency-format';

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
    reconciliationStatus?: { ok: boolean; broken?: { date?: string | null; expected?: string | null; actual?: string | null; rawError?: string } };
    lastReconciledDate?: string | null;
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
      currency: normalizeCurrencyCode(baseCurrency),
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

  function accountStartingBalanceDate(account: Pick<TrackedAccount, 'openingBalance' | 'openingBalanceDate'>): string | null {
    return effectiveOpeningBalanceDate(account.openingBalanceDate, Boolean(account.openingBalance));
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

  function canReconcile(account: TrackedAccount): boolean {
    return account.kind === 'asset' || account.kind === 'liability';
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
  <section class="hero view-card">
    <p class="eyebrow">Accounts</p>
    <h2 class="page-title">Could not load account inventory</h2>
    <p class="subtitle">{error}</p>
    <div class="mt-3 flex flex-wrap gap-2.5">
      <button class="btn btn-primary" type="button" on:click={() => window.location.reload()}>Reload page</button>
      <a class="btn" href="/">Back to overview</a>
    </div>
  </section>
{/if}

{#if loading}
  <section class="hero view-card">
    <p class="eyebrow">Accounts</p>
    <h2 class="page-title">Loading account inventory</h2>
    <p class="subtitle">Pulling together tracked accounts, import setup, and current balances.</p>
  </section>
{:else if !initialized}
  <section class="hero view-card">
    <p class="eyebrow">Accounts</p>
    <h2 class="page-title">Create a workspace first</h2>
    <p class="subtitle">Accounts live inside a workspace. Finish setup before adding or configuring them.</p>
    <div class="mt-3 flex flex-wrap gap-2.5">
      <a class="btn btn-primary" href="/setup">Open setup</a>
    </div>
  </section>
{:else}
  <section
    class="hero view-card flex items-end justify-between gap-4 max-shell:flex-col max-shell:items-stretch"
  >
    <div>
      <p class="eyebrow">Accounts</p>
      <h2 class="page-title">{workspaceName || 'Workspace'} account inventory</h2>
      <p class="subtitle">
        Review the assets and liabilities you track here. Open the configuration workspace when you want to add
        accounts, save a subtype explicitly, or edit import setup.
      </p>
    </div>

    <div
      class="grid grid-cols-3 gap-3 min-w-[min(420px,100%)] max-shell:grid-cols-1"
    >
      <div class="rounded-2xl border border-card-edge bg-white/68 px-3.5 py-3">
        <span class="block mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Tracked</span>
        <strong class="block font-display text-2xl">{trackedAccounts.length}</strong>
      </div>
      <div class="rounded-2xl border border-card-edge bg-white/68 px-3.5 py-3">
        <span class="block mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Balance ready</span>
        <strong class="block font-display text-2xl">{balanceReadyCount}</strong>
      </div>
      <div class="rounded-2xl border border-card-edge bg-white/68 px-3.5 py-3">
        <span class="block mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">Needs setup</span>
        <strong class="block font-display text-2xl">{balanceNeedsSetupCount}</strong>
      </div>
    </div>
  </section>

  <section class="view-card">
    <div class="mb-4 flex items-start justify-between gap-4">
      <div>
        <p class="eyebrow">Next step</p>
        <h3 class="m-0 font-display text-xl">{primaryAction?.title}</h3>
        <p class="muted">
          {primaryAction?.note}
          {#if openingBalanceOnlyCount > 0}
            {` ${openingBalanceOnlyCount} account${openingBalanceOnlyCount === 1 ? '' : 's'} still rely on a starting balance only.`}
          {/if}
        </p>
      </div>
      <a class="text-link" href="/">Back to overview</a>
    </div>

    <div class="flex flex-wrap items-center gap-2.5">
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
    <div class="mb-4 flex items-start justify-between gap-4">
      <div>
        <p class="eyebrow">Inventory</p>
        <h3 class="m-0 font-display text-xl">Tracked accounts</h3>
      </div>
    </div>

    {#if trackedAccounts.length > 0}
      <div class="mb-4 flex flex-wrap items-end justify-between gap-4">
        <label class="grid gap-1.5 flex-1 basis-80 min-w-[min(26rem,100%)]" for="account-search">
          <span class="text-sm font-semibold text-muted-foreground">Find an account</span>
          <input
            id="account-search"
            bind:value={accountQuery}
            type="search"
            placeholder="Search by name, institution, or last four"
          />
        </label>
        <p aria-live="polite" class="m-0 text-muted-foreground">
          {#if normalizedAccountQuery}
            Showing {filteredTrackedAccounts.length} of {trackedAccounts.length} accounts
          {:else}
            {trackedAccounts.length} tracked account{trackedAccounts.length === 1 ? '' : 's'}
          {/if}
        </p>
      </div>
    {/if}

    {#if trackedAccounts.length === 0}
      <div class="rounded-2xl border border-dashed border-card-edge bg-white/52 p-4">
        <h4 class="m-0 font-display text-lg">No accounts yet</h4>
        <p class="m-0 mt-1.5 text-muted-foreground">Start with something you own or owe, then add a starting balance or import setup so totals are grounded.</p>
      </div>
    {:else if filteredTrackedAccounts.length === 0}
      <div class="rounded-2xl border border-dashed border-card-edge bg-white/52 p-4">
        <h4 class="m-0 font-display text-lg">No matching accounts</h4>
        <p class="m-0 mt-1.5 text-muted-foreground">Try a different account name, institution, or last four digits.</p>
      </div>
    {:else}
      <div class="grid gap-5">
        {#each accountGroups as group}
          <div class="grid gap-3.5">
            <div class="flex flex-wrap items-end justify-between gap-4 max-shell:items-stretch">
              <div>
                <h4 class="m-0 font-display text-lg">{group.title}</h4>
                <p class="mt-1.5 mb-0 max-w-[56ch] text-muted-foreground">{group.note}</p>
              </div>
              <div class="account-group-summary min-w-48 rounded-2xl border border-card-edge px-3.5 py-3">
                <span class="block mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">{group.accounts.length} account{group.accounts.length === 1 ? '' : 's'}</span>
                <strong class="block font-display text-2xl">{groupBalanceLabel(group.balanceTotal)}</strong>
              </div>
            </div>

            <div class="grid gap-3">
              {#each group.accounts as account}
                <article
                  class:liability-card={account.kind === 'liability'}
                  class="account-card grid gap-3.5 rounded-2xl border border-card-edge bg-white/64 p-4"
                >
                  <div
                    class="grid items-start gap-4 grid-cols-[minmax(17rem,20rem)_minmax(0,1fr)] max-shell:grid-cols-1"
                  >
                    <div
                      class:liability-panel={account.kind === 'liability'}
                      class="account-balance-panel flex flex-col gap-1.5 min-h-full rounded-2xl border p-4"
                    >
                      <div class="grid items-start gap-1">
                        <p
                          class:liability-context={account.kind === 'liability'}
                          class="account-balance-context m-0 text-sm font-bold text-brand-strong"
                        >
                          {accountSubtypeLine(account)}
                        </p>
                        <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">Current balance</p>
                        <p
                          class:positive={(currentBalance(account.id) ?? 0) > 0}
                          class:negative={(currentBalance(account.id) ?? 0) < 0}
                          class="m-0 font-display leading-[0.96] text-[clamp(2rem,3vw,2.7rem)]"
                        >
                          {formatCurrency(currentBalance(account.id))}
                        </p>
                      </div>
                      <p class="m-0 max-w-[28ch] text-sm text-muted-foreground max-shell:max-w-none">
                        {#if account.openingBalance}
                          Started at {formatStoredAmount(account.openingBalance)}
                          {#if accountStartingBalanceDate(account)}
                            on {shortDate(accountStartingBalanceDate(account))}
                          {/if}
                        {:else}
                          Opening balance not set yet.
                        {/if}
                      </p>
                      {#if account.reconciliationStatus && !account.reconciliationStatus.ok}
                        <p class="m-0 text-sm font-semibold text-bad">
                          <a class="text-bad no-underline hover:underline" href={`/accounts/${encodeURIComponent(account.id)}/reconcile`}>Reconciliation failed</a>
                        </p>
                      {:else if account.lastReconciledDate}
                        <p class="m-0 text-xs text-muted-foreground">
                          Last reconciled: {shortDate(account.lastReconciledDate)}
                        </p>
                      {/if}
                    </div>

                    <div class="grid min-w-0 gap-3.5">
                      <div class="flex items-start justify-between gap-3.5 max-shell:flex-col">
                        <div class="min-w-0">
                          <h4 class="m-0 font-display text-2xl">{account.displayName}</h4>
                          <p class="mt-1.5 mb-0 font-semibold text-muted-foreground">{accountIdentity(account)}</p>
                        </div>
                        <div class="flex flex-wrap justify-end gap-2 max-shell:justify-start">
                          <a class="inline-link" href={`/transactions?accounts=${account.id}`}>Transactions</a>
                        </div>
                      </div>

                      <div class="m-0 flex flex-wrap gap-1.5">
                        <span class={`pill status-pill ${accountStatusTone(account)}`}>{accountStatusLabel(account)}</span>
                        <span class:ok={account.importConfigured} class="pill">{modeLabel(account)}</span>
                        <span class={`pill subtype-pill ${accountSubtypePillTone(account)}`}>{accountSubtypePillLabel(account)}</span>
                        {#if account.last4}
                          <span class="pill">••{account.last4}</span>
                        {/if}
                      </div>

                      <p class="m-0 leading-normal text-muted-foreground">{accountStatusNote(account)}</p>

                      <dl class="m-0 grid grid-cols-3 gap-3 max-shell:grid-cols-1">
                        <div class="m-0 rounded-2xl border border-card-edge bg-white/70 px-3.5 py-3">
                          <dt class="m-0 mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">Balance coverage</dt>
                          <dd class="m-0 font-bold wrap-anywhere">{balanceTrust(account).label}</dd>
                          <span class="block mt-1 text-sm text-muted-foreground wrap-anywhere">
                            {accountStatusNote(account)}
                          </span>
                        </div>

                        <div class="m-0 rounded-2xl border border-card-edge bg-white/70 px-3.5 py-3">
                          <dt class="m-0 mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">Starting balance</dt>
                          <dd class="m-0 font-bold wrap-anywhere">{account.openingBalance ? formatStoredAmount(account.openingBalance) : 'Not set'}</dd>
                          <span class="block mt-1 text-sm text-muted-foreground wrap-anywhere">
                            {accountStartingBalanceDate(account)
                              ? shortDate(accountStartingBalanceDate(account))
                              : 'Add a starting balance or import history when you want this account included in totals.'}
                          </span>
                        </div>

                        <div class="m-0 rounded-2xl border border-card-edge bg-white/70 px-3.5 py-3">
                          <dt class="m-0 mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">Subtype</dt>
                          <dd class="m-0 font-bold wrap-anywhere">{accountSubtypePillLabel(account)}</dd>
                          <span class="block mt-1 text-sm text-muted-foreground wrap-anywhere">{subtypeStateNote(account)}</span>
                        </div>

                        <div class="m-0 rounded-2xl border border-card-edge bg-white/70 px-3.5 py-3">
                          <dt class="m-0 mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">Import setup</dt>
                          <dd class="m-0 font-bold wrap-anywhere">{importSetupTitle(account)}</dd>
                          <span class="block mt-1 text-sm text-muted-foreground wrap-anywhere">{importSetupNote(account)}</span>
                        </div>
                      </dl>
                    </div>
                  </div>

                  <details class="advanced-details border-t border-card-edge pt-3.5">
                    <summary class="cursor-pointer font-bold text-brand-strong">Accounting details</summary>
                    <div class="mt-3 grid gap-2">
                      <div class="flex flex-wrap gap-2">
                        <a class="btn w-fit" href={`/accounts/configure?accountId=${account.id}`}>Edit account</a>
                        {#if canReconcile(account)}
                          <button
                            type="button"
                            class="btn w-fit"
                            on:click={() => void goto(`/accounts/${encodeURIComponent(account.id)}/reconcile`)}
                          >
                            Reconcile
                          </button>
                        {/if}
                      </div>
                      {#if account.ledgerAccount}
                        <p class="muted text-sm">Ledger account: {account.ledgerAccount}</p>
                      {/if}
                      {#if account.importMode === 'custom' && account.importProfile}
                        <p class="muted text-sm">{customProfileSummary(account)}</p>
                        <p class="muted text-sm">Currency symbol: {account.importProfile.currency || '$'}</p>
                        <p class="muted text-sm">Date column: {account.importProfile.dateColumn || 'Not set'}</p>
                        <p class="muted text-sm">Description column: {account.importProfile.descriptionColumn || 'Not set'}</p>
                        <p class="muted text-sm">Code column: {account.importProfile.codeColumn || 'Not set'}</p>
                      {/if}
                    </div>
                  </details>
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
  .liability-card {
    border-color: rgba(154, 81, 41, 0.14);
    background: rgba(255, 250, 246, 0.72);
  }

  .account-balance-panel {
    border-color: rgba(15, 95, 136, 0.12);
    background: linear-gradient(160deg, rgba(244, 249, 255, 0.96), rgba(239, 248, 244, 0.9));
  }

  .liability-panel {
    border-color: rgba(154, 81, 41, 0.14);
    background: linear-gradient(160deg, rgba(255, 248, 243, 0.96), rgba(255, 244, 237, 0.92));
  }

  .liability-context {
    color: #9a5129;
  }

  .account-group-summary {
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.9), rgba(243, 249, 255, 0.84));
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

  .inline-link:hover {
    background: #f7fbff;
    border-color: rgba(15, 95, 136, 0.18);
  }

  .advanced-details p + p {
    margin-top: 0.35rem;
  }

  .positive {
    color: var(--ok);
  }

  .negative {
    color: var(--bad);
  }
</style>
