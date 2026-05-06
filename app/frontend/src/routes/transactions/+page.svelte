<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onDestroy, onMount } from 'svelte';
  import { apiGet } from '$lib/api';
  import AddTransactionForm from '$lib/components/transactions/AddTransactionForm.svelte';
  import ManualResolutionDialog from '$lib/components/transactions/ManualResolutionDialog.svelte';
  import TransactionDayGroup from '$lib/components/transactions/TransactionDayGroup.svelte';
  import TransactionRow from '$lib/components/transactions/TransactionRow.svelte';
  import TransactionDetailSheet from '$lib/components/transactions/TransactionDetailSheet.svelte';
  import TransactionsExplanationHeader from '$lib/components/transactions/TransactionsExplanationHeader.svelte';
  import TransactionsFilterBar from '$lib/components/transactions/TransactionsFilterBar.svelte';
  import TransactionsFilterDialog from '$lib/components/transactions/TransactionsFilterDialog.svelte';
  import { describeBalanceTrust } from '$lib/account-trust';
  import type {
    TrackedAccount, TransactionRow as TxRow, TransactionsResponse,
    TransactionFilters, ManualResolutionApplyResult
  } from '$lib/transactions/types';
  import { formatCurrency, formatStoredAmount, shortDate, countLabel, type AccountKind } from '$lib/format';
  import { groupByDate, CLEARING_TOOLTIPS } from '$lib/transactions/helpers';
  import { filtersFromUrl, filtersToUrl, EMPTY_FILTERS } from '$lib/transactions/transactionFilters';
  import { loadTransactions } from '$lib/transactions/loadTransactions';
  import {
    deleteTransaction, resetCategory, recategorize,
    unmatchTransaction, toggleClearing
  } from '$lib/transactions/transactionActions';

  type AppState = { initialized: boolean; workspaceName: string | null };

  let initialized = false;
  let workspaceName = '';
  let trackedAccounts: TrackedAccount[] = [];
  let allAccounts: string[] = [];
  let filters: TransactionFilters = { ...EMPTY_FILTERS };
  let result: TransactionsResponse | null = null;
  let baseCurrency = 'USD';
  let error = '';
  let loading = true;
  let dataLoading = false;
  let requestSeq = 0;
  let abortController: AbortController | null = null;
  let selectedRow: TxRow | null = null;
  let lastSelectedRowId: string | null = null;
  let confirmDeleteRow: TxRow | null = null;
  let confirmUnmatchRow: TxRow | null = null;
  let actionError = '';
  let actionBusy = false;

  // Clear stale action error whenever the selected row changes (open/close/swap).
  $: if ((selectedRow?.id ?? null) !== lastSelectedRowId) {
    lastSelectedRowId = selectedRow?.id ?? null;
    actionError = '';
  }
  let manualResolutionEntry: import('$lib/transactions/types').RegisterEntry | null = null;
  let manualResolutionSuccess = '';
  let showAddForm = false;
  let addSuccess = '';
  let filterDialogOpen = false;
  let filterBarWrap: HTMLElement | null = null;
  let filterBarObserver: ResizeObserver | null = null;

  $: isSingleAccount = filters.accounts.length === 1;
  $: selectedAccount = isSingleAccount ? trackedAccounts.find((a) => a.id === filters.accounts[0]) ?? null : null;
  $: accountKindById = buildAccountKindMap(trackedAccounts);
  // Single-account view drives the filtered-account kind; cross-account views
  // render unsigned/neutral because mixed accounts have no coherent "good"
  // direction.
  $: filteredAccountKind = isSingleAccount ? (accountKindById.get(filters.accounts[0]) ?? null) : null;
  $: rows = result?.rows ?? [];
  $: postedRows = rows.filter((r: TxRow) => r.transferState !== 'pending');
  $: pendingRows = isSingleAccount ? rows.filter((r: TxRow) => r.transferState === 'pending') : [];
  $: dayGroups = groupByDate(postedRows);
  $: pendingCount = pendingRows.length;
  $: pendingTotal = pendingRows.reduce((s: number, r: TxRow) => s + r.amount, 0);
  $: filteredTotal = postedRows.reduce((s: number, r: TxRow) => s + r.amount, 0);
  $: meta = result?.accountMeta ?? null;
  $: curBal = meta?.currentBalance ?? null;
  $: balPending = curBal !== null ? curBal + pendingTotal : null;
  $: showRunBal = isSingleAccount;
  $: showExpl = !isSingleAccount && result?.summary != null;
  $: explTxs = postedRows.map(toExplTx);

  function buildAccountKindMap(accounts: TrackedAccount[]): Map<string, AccountKind> {
    const map = new Map<string, AccountKind>();
    for (const account of accounts) {
      if (account.kind === 'asset' || account.kind === 'liability') {
        map.set(account.id, account.kind);
      }
    }
    return map;
  }

  function rowAccountKind(row: TxRow): AccountKind | null {
    return accountKindById.get(row.account.id) ?? null;
  }

  function toExplTx(r: TxRow) {
    return {
      date: r.date, payee: r.payee, accountLabel: r.account.label,
      importAccountId: r.account.id, category: r.categories[0]?.label ?? '',
      categoryAccount: r.categories[0]?.account ?? '', amount: r.amount,
      isIncome: r.amount > 0, isUnknown: r.isUnknown,
    };
  }

  function trust() {
    if (!selectedAccount || !meta) return null;
    return describeBalanceTrust({
      hasOpeningBalance: meta.hasOpeningBalance, hasTransactionActivity: meta.hasTransactionActivity,
      hasBalanceSource: meta.hasBalanceSource, importConfigured: selectedAccount.importConfigured,
      openingBalanceDate: selectedAccount.openingBalanceDate, latestActivityDate: meta.latestActivityDate,
    });
  }

  async function loadData() {
    if (abortController) abortController.abort();
    abortController = new AbortController();
    const seq = ++requestSeq;
    dataLoading = true; error = '';
    try {
      const res = await loadTransactions(filters, { signal: abortController.signal });
      if (seq !== requestSeq) return;
      result = res; baseCurrency = res.baseCurrency;
    } catch (e) {
      if (seq !== requestSeq) return;
      if (e instanceof DOMException && e.name === 'AbortError') return;
      error = String(e);
    } finally { if (seq === requestSeq) dataLoading = false; }
  }

  function changeFilters(next: TransactionFilters) {
    filters = next;
    selectedRow = null;
    void goto(`/transactions${filtersToUrl(filters)}`, { replaceState: true, noScroll: true, keepFocus: true });
    void loadData();
  }

  async function load() {
    const state = await apiGet<AppState>('/api/app/state');
    initialized = state.initialized; workspaceName = state.workspaceName ?? '';
    if (!initialized) return;
    const [ad, al] = await Promise.all([
      apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts'),
      apiGet<{ accounts: string[] }>('/api/accounts').catch(() => ({ accounts: [] as string[] }))
    ]);
    trackedAccounts = ad.trackedAccounts; allAccounts = al.accounts;
    const { filters: parsed, migrated } = filtersFromUrl($page.url);
    filters = parsed;
    if (filters.accounts.length > 0) {
      const ids = new Set(trackedAccounts.map((a) => a.id));
      filters = { ...filters, accounts: filters.accounts.filter((id: string) => ids.has(id)) };
    }
    if (migrated) void goto(`/transactions${filtersToUrl(filters)}`, { replaceState: true, noScroll: true, keepFocus: true });
    await loadData();
  }

  onMount(async () => {
    loading = true; error = '';
    try { await load(); } catch (e) { error = String(e); } finally { loading = false; }
    if (filterBarWrap && typeof ResizeObserver !== 'undefined') {
      filterBarObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const h = entry.contentRect.height;
          document.documentElement.style.setProperty('--filter-bar-height', `${h}px`);
        }
      });
      filterBarObserver.observe(filterBarWrap);
    }
  });

  onDestroy(() => {
    if (abortController) abortController.abort();
    if (filterBarObserver) {
      filterBarObserver.disconnect();
      filterBarObserver = null;
    }
    if (typeof document !== 'undefined') document.documentElement.style.removeProperty('--filter-bar-height');
  });

  async function doDelete(row: TxRow) {
    actionBusy = true; actionError = '';
    const r = await deleteTransaction(row, loadData);
    if (r.success) { confirmDeleteRow = null; selectedRow = null; } else actionError = r.error ?? '';
    actionBusy = false;
  }
  async function doResetCat(row: TxRow) {
    actionBusy = true; actionError = '';
    const r = await resetCategory(row, loadData);
    if (r.success) selectedRow = null; else actionError = r.error ?? '';
    actionBusy = false;
  }
  async function doRecat(row: TxRow, cat: string) {
    actionBusy = true; actionError = '';
    const r = await recategorize(row, cat, loadData);
    if (r.success) selectedRow = null; else actionError = r.error ?? '';
    actionBusy = false;
  }
  async function doUnmatch(row: TxRow) {
    actionBusy = true; actionError = '';
    const r = await unmatchTransaction(row, loadData);
    if (r.success) { confirmUnmatchRow = null; selectedRow = null; } else actionError = r.error ?? '';
    actionBusy = false;
  }

  async function handleToggleClearing(row: TxRow, event: MouseEvent) {
    event.preventDefault(); event.stopPropagation();
    await toggleClearing(row);
    result = result ? { ...result } : result;
  }

  function openManualRes(row: TxRow) {
    if (!row.manualResolutionToken) return;
    const leg = row.legs[0];
    manualResolutionSuccess = '';
    manualResolutionEntry = {
      id: row.id, date: row.date, payee: row.payee, summary: row.categories[0]?.label ?? '',
      amount: row.amount, runningBalance: row.runningBalance ?? 0, isUnknown: row.isUnknown,
      isOpeningBalance: row.isOpeningBalance, detailLines: row.detailLines,
      manualResolutionToken: row.manualResolutionToken, manualResolutionNote: row.manualResolutionNote ?? null,
      clearingStatus: row.status, headerLine: leg?.headerLine, journalPath: leg?.journalPath,
      lineNumber: leg?.lineNumber ?? null,
      matchId: row.matchId ?? null, notes: row.notes ?? null, transferState: row.transferState ?? null,
    };
  }

  async function handleResolved(r: ManualResolutionApplyResult) {
    manualResolutionSuccess = `Resolved: ${r.sourceAccountName} to ${r.destinationAccountName}.`;
    await loadData();
  }

  async function handleAddSuccess(r: { payee: string; date: string; warning: string | null; eventId: string | null }) {
    addSuccess = `Added: ${r.payee} on ${r.date}${r.warning ? ` (${r.warning})` : ''}`;
    showAddForm = false;
    if (r.eventId) {
      const { showUndoToast } = await import('$lib/undo-toast');
      showUndoToast(r.eventId, `Added ${r.payee}`, loadData);
    }
    await loadData();
  }

  function handleSheetDelete(row: TxRow) { selectedRow = null; confirmDeleteRow = row; }
  function handleSheetResetCat(row: TxRow) { void doResetCat(row); }
  function handleSheetRecat(row: TxRow, cat: string) { void doRecat(row, cat); }
  function handleSheetUnmatch(row: TxRow) { selectedRow = null; confirmUnmatchRow = row; }
  function handleFilterApply(next: TransactionFilters) { filterDialogOpen = false; changeFilters(next); }
  function clearAll() { changeFilters({ ...EMPTY_FILTERS }); }
</script>

{#if error && !loading}
  <section class="view-card"><p class="error-text">{error}</p></section>
{/if}

{#if loading}
  <section class="view-card transactions-hero">
    <p class="eyebrow">Transactions</p>
    <h2 class="page-title">Loading transactions</h2>
    <p class="subtitle">Pulling together the latest activity.</p>
  </section>
{:else if !initialized}
  <section class="view-card transactions-hero">
    <p class="eyebrow">Transactions</p>
    <h2 class="page-title">Create a workspace first</h2>
    <p class="subtitle">Transaction registers live inside a workspace. Finish setup before reviewing account activity.</p>
    <div class="mt-3 flex flex-wrap gap-3"><a class="btn btn-primary" href="/setup">Open setup</a></div>
  </section>
{:else if trackedAccounts.length === 0}
  <section class="view-card transactions-hero">
    <p class="eyebrow">Transactions</p>
    <h2 class="page-title">{workspaceName || 'Workspace'} does not have any accounts yet</h2>
    <p class="subtitle">Add at least one tracked account before reviewing transactions.</p>
    <div class="mt-3 flex flex-wrap gap-3">
      <a class="btn btn-primary" href="/accounts/configure?mode=manual">Add first account</a>
      <a class="text-link" href="/accounts">Open accounts</a>
    </div>
  </section>
{:else}
  <section class="view-card transactions-hero">
    <div class="grid gap-3">
      <p class="eyebrow">Transactions</p>
      {#if isSingleAccount && selectedAccount}
        <h2 class="page-title">{selectedAccount.displayName}</h2>
        <p class="subtitle">{trust()?.note || 'Review recent activity and running balances for this account.'}</p>
        {#if selectedAccount.openingBalance}
          <p class="text-muted-foreground text-sm">Starting balance {formatStoredAmount(selectedAccount.openingBalance, baseCurrency)}{#if selectedAccount.openingBalanceDate}{' '}on {shortDate(selectedAccount.openingBalanceDate)}{/if}</p>
        {/if}
      {:else}
        <h2 class="page-title">All activity</h2>
        <p class="subtitle">Cross-account transactions across all tracked accounts.</p>
      {/if}
    </div>
    {#if isSingleAccount}
      <div class="hero-side">
        <div class="flex flex-wrap gap-3">
          {#if filteredAccountKind && selectedAccount}
            <button
              class="btn btn-primary"
              type="button"
              on:click={() => void goto(`/accounts/${encodeURIComponent(selectedAccount.id)}/reconcile`)}
            >
              Reconcile
            </button>
          {/if}
          <button class="btn" type="button" on:click={() => { addSuccess = ''; showAddForm = true; }}>Add transaction</button>
          <a class="text-link" href="/accounts">Back to accounts</a>
        </div>
      </div>
    {/if}
  </section>

  <div class="filter-bar-sticky sticky top-0 z-10" bind:this={filterBarWrap}>
    <TransactionsFilterBar {filters} {trackedAccounts} onChange={changeFilters} onOpenFilterDialog={() => (filterDialogOpen = true)} />
  </div>

  {#if isSingleAccount && meta}
    <section class="grid gap-4 grid-cols-[repeat(auto-fit,minmax(15rem,1fr))] max-shell:grid-cols-1">
      <article class="view-card grid gap-1.5">
        <p class="eyebrow">Balance coverage</p>
        <p class="font-display text-2xl leading-none">{trust()?.label || 'No balance yet'}</p>
        <p class="text-muted-foreground text-sm">{trust()?.note || 'Add activity or a starting balance.'}</p>
      </article>
      <article class="view-card summary-balance-card grid gap-1.5">
        <p class="eyebrow">Current balance</p>
        <p class:positive={(curBal ?? 0) > 0} class:negative={(curBal ?? 0) < 0} class="font-display text-2xl leading-none">{formatCurrency(curBal, baseCurrency)}</p>
        <p class="text-muted-foreground text-sm">{selectedAccount?.institutionDisplayName || 'Tracked account'}{#if selectedAccount?.last4} &bull; {selectedAccount.last4}{/if}</p>
      </article>
      <article class="view-card summary-balance-pending grid gap-1.5">
        <p class="eyebrow">Balance with pending</p>
        <p class:positive={(balPending ?? 0) > 0} class:negative={(balPending ?? 0) < 0} class="font-display text-2xl leading-none">{formatCurrency(balPending, baseCurrency)}</p>
        <p class="text-muted-foreground text-sm">{#if pendingCount > 0}{countLabel(pendingCount, 'pending transfer')} worth {formatCurrency(pendingTotal, baseCurrency, { signed: true })}.{:else}Matches current balance when nothing is pending.{/if}</p>
      </article>
      <article class="view-card grid gap-1.5">
        <p class="eyebrow">Latest activity</p>
        <p class="font-display text-2xl leading-none">{meta.latestTransactionDate ? shortDate(meta.latestTransactionDate) : 'No activity yet'}</p>
        <p class="text-muted-foreground text-sm">{meta.latestTransactionDate ? `Posted to this ${selectedAccount?.kind || 'account'} register.` : 'Posted activity will appear after first import.'}</p>
      </article>
    </section>
  {/if}

  {#if manualResolutionSuccess}
    <section class="view-card result-card grid gap-2">
      <p class="eyebrow">Resolved</p>
      <h3 class="m-0 font-display text-xl">Transfer resolved manually</h3>
      <p class="m-0 text-muted-foreground text-sm">{manualResolutionSuccess}</p>
    </section>
  {/if}
  {#if addSuccess}
    <section class="view-card result-card grid gap-2">
      <p class="eyebrow">Transaction Added</p>
      <h3 class="m-0 font-display text-xl">Manual entry created</h3>
      <p class="m-0 text-muted-foreground text-sm">{addSuccess}</p>
    </section>
  {/if}

  {#if showAddForm && isSingleAccount}
    <AddTransactionForm selectedAccountId={filters.accounts[0]} {allAccounts} onCancel={() => (showAddForm = false)} onSuccess={handleAddSuccess} onAccountsChanged={(a) => (allAccounts = a)} />
  {/if}

  {#if showExpl && result?.summary}
    <TransactionsExplanationHeader summary={result.summary} category={filters.category} month={filters.month} transactions={explTxs} {baseCurrency} />
  {/if}

  {#if isSingleAccount && pendingCount > 0}
    <section class="view-card pending-card">
      <div class="flex items-start justify-between gap-4 mb-4 max-shell:flex-col">
        <div><p class="eyebrow">Pending</p><h3 class="m-0 font-display text-xl">Pending transfers</h3></div>
        <p class="m-0 text-muted-foreground text-sm">These affect <strong>Balance with pending</strong> above.</p>
      </div>
      <div class="grid gap-3">
        {#each pendingRows as row}
          <details class="pending-row">
            <summary class="pending-summary">
              <button class="clearing-indicator clearing-{row.status ?? 'unmarked'}" title={CLEARING_TOOLTIPS[row.status ?? 'unmarked']} on:click|stopPropagation={(e) => handleToggleClearing(row, e)} type="button"></button>
              <div class="text-sm">{shortDate(row.date)}</div>
              <div class="min-w-0">
                <p class="font-bold">{row.payee}</p>
                <div class="flex flex-wrap gap-2 mt-1 text-muted-foreground text-sm">
                  <span>{row.categories[0]?.label ?? 'Transfer'}</span>
                  <span class="pill pending-pill">Pending</span>
                </div>
              </div>
              <div class="text-right"><p class:positive={filteredAccountKind && row.amount > 0 && !row.isTransfer} class="font-bold">{row.isTransfer ? formatCurrency(Math.abs(row.amount), baseCurrency, { signMode: 'negative-only' }) : formatCurrency(row.amount, baseCurrency, { signMode: filteredAccountKind ? 'good-change-plus' : 'negative-only', accountKind: filteredAccountKind ?? undefined })}</p></div>
            </summary>
            <div class="px-4 pb-4 grid gap-3">
              <p class="text-muted-foreground text-sm pending-details-note">{row.manualResolutionToken ? 'Resolve manually when no imported counterpart is expected.' : 'Waiting for the imported transaction to land.'}</p>
              {#if row.manualResolutionToken}
                <button class="btn pending-secondary-action" type="button" on:click={() => openManualRes(row)}>Resolve manually</button>
              {/if}
            </div>
          </details>
        {/each}
      </div>
    </section>
  {/if}

  <section class="view-card relative">
    {#if result !== null && dataLoading}
      <div class="reload-progress" aria-hidden="true"></div>
    {/if}
    <div class="flex items-start justify-between gap-4 mb-4">
      <div><p class="eyebrow">Transactions</p><h3 class="m-0 font-display text-xl">{result?.totalCount ?? 0} {(result?.totalCount ?? 0) === 1 ? 'transaction' : 'transactions'}</h3></div>
    </div>
    {#if result !== null && error}
      <div class="mb-3 px-3.5 py-2.5 rounded-xl bg-bad/10 border border-bad/20" role="alert">
        <p class="error-text m-0"><strong>Couldn't refresh transactions.</strong> {error}</p>
      </div>
    {/if}
    {#if result === null && dataLoading}
      <div class="empty-panel"><h4 class="m-0">Loading transactions</h4><p class="m-0 mt-1 text-muted-foreground">Fetching transaction data.</p></div>
    {:else if result === null && error}
      <div class="empty-panel"><h4 class="m-0">Error loading transactions</h4><p class="m-0 mt-1 text-muted-foreground">{error}</p></div>
    {:else if result !== null && !dataLoading && !error && postedRows.length === 0}
      <div class="empty-panel">
        <h4 class="m-0">No transactions match these filters</h4>
        <p class="m-0 mt-1 text-muted-foreground">Try a different time range or clear filters to see more.</p>
        <div class="mt-3"><button class="btn" type="button" on:click={clearAll}>Clear all filters</button></div>
      </div>
    {:else if result !== null}
      <div class="grid">
        {#each dayGroups as group, gi}
          <TransactionDayGroup header={group.header} isFirst={gi === 0} dailySum={group.dailySum} {baseCurrency} accountKind={filteredAccountKind}>
            {#each group.rows as row}
              <TransactionRow {row} {baseCurrency} accountKind={rowAccountKind(row)} showRunningBalance={showRunBal} showCategory={!filters.category} showAccountLabel={!isSingleAccount} {isSingleAccount} onToggleClearing={isSingleAccount ? handleToggleClearing : null} onRowClick={row.isAssertion ? null : () => (selectedRow = row)} />
            {/each}
          </TransactionDayGroup>
        {/each}
      </div>
      {#if postedRows.length > 0}
        <div class="sticky bottom-0 flex items-center justify-between border-t border-[rgba(10,61,89,0.08)] bg-white/90 backdrop-blur-sm px-4 py-2 text-sm text-muted-foreground">
          <span>{postedRows.length} {postedRows.length === 1 ? 'transaction' : 'transactions'}</span>
          <span class:text-green-600={filteredAccountKind && filteredTotal > 0} class="font-medium">
            {filteredAccountKind
              ? formatCurrency(filteredTotal, baseCurrency, { signMode: 'good-change-plus', accountKind: filteredAccountKind })
              : formatCurrency(Math.abs(filteredTotal), baseCurrency, { signMode: 'negative-only' })}
          </span>
        </div>
      {/if}
    {/if}
  </section>
{/if}

<TransactionDetailSheet row={selectedRow} {baseCurrency} accounts={allAccounts} accountKind={selectedRow ? rowAccountKind(selectedRow) : null} {actionError} onDelete={handleSheetDelete} onResetCategory={handleSheetResetCat} onRecategorize={handleSheetRecat} onUnmatch={handleSheetUnmatch} onClose={() => (selectedRow = null)} reload={loadData} />
<ManualResolutionDialog bind:entry={manualResolutionEntry} bind:baseCurrency onResolved={handleResolved} />
<TransactionsFilterDialog bind:open={filterDialogOpen} {filters} {trackedAccounts} {allAccounts} onApply={handleFilterApply} onClose={() => (filterDialogOpen = false)} />

{#if confirmDeleteRow}
  <div class="confirm-backdrop" on:click={() => { confirmDeleteRow = null; actionError = ''; }} role="presentation">
    <div class="confirm-modal" on:click|stopPropagation on:keydown={(e) => { if (e.key === 'Escape') { confirmDeleteRow = null; actionError = ''; } }} role="dialog" tabindex="-1" aria-labelledby="confirm-delete-title">
      <h3 id="confirm-delete-title" class="m-0">Remove transaction</h3>
      <p>Remove <strong>{confirmDeleteRow.payee}</strong> on {confirmDeleteRow.date}?</p>
      <p class="muted text-sm">This removes the transaction from your records.</p>
      {#if actionError}<p class="action-error">{actionError}</p>{/if}
      <div class="flex flex-wrap gap-3">
        <button class="btn" type="button" on:click={() => { confirmDeleteRow = null; actionError = ''; }}>Cancel</button>
        <button class="btn btn-danger" type="button" disabled={actionBusy} on:click={() => confirmDeleteRow && void doDelete(confirmDeleteRow)}>{actionBusy ? 'Removing...' : 'Remove'}</button>
      </div>
    </div>
  </div>
{/if}
{#if confirmUnmatchRow}
  <div class="confirm-backdrop" on:click={() => { confirmUnmatchRow = null; actionError = ''; }} role="presentation">
    <div class="confirm-modal" on:click|stopPropagation on:keydown={(e) => { if (e.key === 'Escape') { confirmUnmatchRow = null; actionError = ''; } }} role="dialog" tabindex="-1" aria-labelledby="confirm-unmatch-title">
      <h3 id="confirm-unmatch-title" class="m-0">Undo match</h3>
      <p>Undo the match for <strong>{confirmUnmatchRow.payee}</strong> on {confirmUnmatchRow.date}?</p>
      <p class="muted text-sm">This restores the original manual entry.</p>
      {#if actionError}<p class="action-error">{actionError}</p>{/if}
      <div class="flex flex-wrap gap-3">
        <button class="btn" type="button" on:click={() => { confirmUnmatchRow = null; actionError = ''; }}>Cancel</button>
        <button class="btn btn-danger" type="button" disabled={actionBusy} on:click={() => confirmUnmatchRow && void doUnmatch(confirmUnmatchRow)}>{actionBusy ? 'Undoing...' : 'Undo match'}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .transactions-hero {
    display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(18rem, 0.9fr);
    gap: 1.2rem; align-items: start;
    background: radial-gradient(circle at top left, rgba(214, 235, 220, 0.86), transparent 34%), linear-gradient(155deg, #fbfdf8 0%, #f6fbff 60%, #eef6f3 100%);
  }
  .hero-side { display: grid; gap: 0.85rem; padding: 1rem; border-radius: 1rem; background: rgba(255,255,255,0.72); border: 1px solid rgba(10,61,89,0.08); }
  .summary-balance-card { background: linear-gradient(160deg, rgba(250,252,255,0.95), rgba(243,248,252,0.9)), rgba(255,255,255,0.86); }
  .summary-balance-pending { border-color: rgba(15,95,136,0.18); background: radial-gradient(circle at top right, rgba(214,235,220,0.78), transparent 42%), linear-gradient(155deg, rgba(250,253,248,0.98), rgba(241,247,255,0.96)); }
  .result-card { background: radial-gradient(circle at top right, rgba(214,235,220,0.62), transparent 44%), linear-gradient(155deg, rgba(248,252,246,0.98), rgba(242,248,255,0.96)); }
  .pending-card { background: radial-gradient(circle at top right, rgba(214,235,220,0.68), transparent 36%), linear-gradient(155deg, rgba(252,252,247,0.98), rgba(247,250,255,0.96)); }
  .positive { color: var(--ok); }
  .negative { color: var(--bad); }
  .pending-row { border: 1px solid rgba(10,61,89,0.08); border-radius: 1rem; background: rgba(255,255,255,0.62); overflow: hidden; }
  .pending-summary { display: grid; grid-template-columns: 1.5rem minmax(6rem,0.6fr) minmax(0,2fr) minmax(6rem,0.6fr); gap: 1rem; align-items: center; padding: 0.95rem 1rem; cursor: pointer; list-style: none; }
  .pending-summary::-webkit-details-marker { display: none; }
  .pending-pill { color: var(--warn); border-color: #f3cf96; background: #fff7ea; }
  .pending-details-note { color: #7d5200; }
  .pending-secondary-action { background: rgba(255,255,255,0.85); }
  .clearing-indicator { width: 0.7rem; height: 0.7rem; padding: 0; border: none; border-radius: 50%; cursor: pointer; align-self: center; flex-shrink: 0; transition: background 0.15s, box-shadow 0.15s; }
  .clearing-cleared { background: var(--ok, #0d7f58); }
  .clearing-pending { background: transparent; box-shadow: inset 0 0 0 2px var(--warn, #ad6a00); }
  .clearing-unmarked { background: rgba(10,61,89,0.12); }
  .empty-panel { border: 1px dashed rgba(10,61,89,0.18); border-radius: 1rem; padding: 1rem; background: rgba(255,255,255,0.52); }
  .filter-bar-sticky :global(.filter-bar) { box-shadow: 0 6px 18px -12px rgba(10, 61, 89, 0.35); }
  .reload-progress { position: absolute; top: 0; left: var(--radius-card); right: var(--radius-card); height: 2px; background: linear-gradient(90deg, transparent 0%, rgba(15,95,136,0.55) 40%, rgba(15,95,136,0.75) 50%, rgba(15,95,136,0.55) 60%, transparent 100%); background-size: 200% 100%; animation: reload-shimmer 1.2s linear infinite; pointer-events: none; z-index: 2; }
  @keyframes reload-shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }
  .confirm-backdrop { position: fixed; inset: 0; background: rgba(10,20,30,0.35); z-index: 30; }
  .confirm-modal { width: min(480px, calc(100vw - 2rem)); max-height: calc(100vh - 2rem); background: #fff; border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); padding: 1.25rem; position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%); overflow: auto; z-index: 31; display: grid; gap: 0.75rem; }
  .action-error { color: var(--error, #c53030); font-size: 0.88rem; }
  .btn-danger { background: var(--error, #c53030); color: #fff; border-color: var(--error, #c53030); }
  .btn-danger:hover { opacity: 0.9; }
  .btn-danger:disabled { opacity: 0.6; cursor: not-allowed; }
  @media (max-width: 980px) { .transactions-hero { grid-template-columns: 1fr; } }
</style>
