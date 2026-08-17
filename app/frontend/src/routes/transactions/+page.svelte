<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onDestroy, onMount, tick } from 'svelte';
	import CheckIcon from '@lucide/svelte/icons/check';
	import { apiGet } from '$lib/api';
	import FilterBar from '$lib/components/register/FilterBar.svelte';
	import RegisterRow from '$lib/components/register/RegisterRow.svelte';
	import DetailPanel from '$lib/components/register/DetailPanel.svelte';
	import type {
		TrackedAccount,
		TransactionRow as TxRow,
		TransactionsResponse,
		TransactionFilters
	} from '$lib/transactions/types';
	import { formatCurrency, countLabel, shortDate, type AccountKind } from '$lib/format';
	import { groupByDate, type TransactionDayGroupData } from '$lib/transactions/helpers';
	import {
		filtersFromUrl,
		filtersToUrl,
		filtersToApiParams,
		EMPTY_FILTERS
	} from '$lib/transactions/transactionFilters';
	import { loadTransactions } from '$lib/transactions/loadTransactions';
	import {
		deleteTransaction,
		resetCategory,
		recategorize,
		reassignAccount,
		unmatchTransaction,
		toggleClearing
	} from '$lib/transactions/transactionActions';
	import { onVerb } from '$lib/keyboard/runtime';
	import { nextId, prevId, reconcileFocus } from '$lib/keyboard/register-nav';

	type AppState = { initialized: boolean; workspaceName: string | null };

	let initialized = false;
	let workspaceName = '';
	let trackedAccounts: TrackedAccount[] = [];
	let categoryAccounts: string[] = [];
	let result: TransactionsResponse | null = null;
	let baseCurrency = 'USD';
	let error = '';
	let loading = true;
	let dataLoading = false;
	let requestSeq = 0;
	let abortController: AbortController | null = null;
	let filterBar: FilterBar | null = null;

	// Selection state: `focusedId` is the roving keyboard focus, `selectedRow`
	// the row whose detail panel is open. j/k moves focus; when the panel is
	// open it follows the focus.
	let focusedId: string | null = null;
	let selectedRow: TxRow | null = null;
	let lastSelectedRowId: string | null = null;
	let actionError = '';
	let actionBusy = false;

	$: if ((selectedRow?.id ?? null) !== lastSelectedRowId) {
		lastSelectedRowId = selectedRow?.id ?? null;
		actionError = '';
	}

	// ── Filters: the URL is the single source of truth ─────────────────────
	// URL → state via these reactive declarations; state → URL via
	// `changeFilters` (a plain goto). The one-shot reconciliation migrates
	// legacy param formats and applies the default period exactly once per
	// mount, so a user's explicit "All time" is never overridden later.
	let hasReconciledUrl = false;
	let lastFiltersKey: string | null = null;

	function pruneAccountsToTracked(
		f: TransactionFilters,
		accounts: TrackedAccount[]
	): TransactionFilters {
		if (f.accounts.length === 0 || accounts.length === 0) return f;
		const ids = new Set(accounts.map((a) => a.id));
		const filtered = f.accounts.filter((id) => ids.has(id));
		if (filtered.length === f.accounts.length) return f;
		return { ...f, accounts: filtered };
	}

	function isFiltersEmpty(f: TransactionFilters): boolean {
		return (
			f.accounts.length === 0 && !f.category && !f.month && !f.period && !f.search && !f.status
		);
	}

	$: parsedFromUrl = filtersFromUrl($page.url);
	$: filters = pruneAccountsToTracked(parsedFromUrl.filters, trackedAccounts);

	$: if (initialized && !hasReconciledUrl) {
		hasReconciledUrl = true;
		let next = filters;
		let needsRedirect = parsedFromUrl.migrated;
		if (isFiltersEmpty(filters)) {
			next = { ...filters, period: 'this-month' };
			needsRedirect = true;
		}
		if (needsRedirect) {
			const willChangeContent = filtersToApiParams(next) !== filtersToApiParams(filters);
			if (willChangeContent) {
				lastFiltersKey = filtersToApiParams(filters);
			}
			void goto(`/transactions${filtersToUrl(next)}`, {
				replaceState: true,
				noScroll: true,
				keepFocus: true
			});
		}
	}

	$: filtersKey = filtersToApiParams(filters);
	$: if (initialized && hasReconciledUrl && filtersKey !== lastFiltersKey) {
		lastFiltersKey = filtersKey;
		selectedRow = null;
		void loadData();
	}

	// ── Derived register data ───────────────────────────────────────────────
	$: isSingleAccount = filters.accounts.length === 1;
	$: selectedAccount = isSingleAccount
		? (trackedAccounts.find((a) => a.id === filters.accounts[0]) ?? null)
		: null;
	$: accountKindById = buildAccountKindMap(trackedAccounts);
	$: scopedAccountKind = isSingleAccount
		? (accountKindById.get(filters.accounts[0]) ?? null)
		: null;
	$: rows = result?.rows ?? [];
	$: dayGroups = groupByDate(rows);
	$: focusableIds = rows.filter((r) => !r.isAssertion).map((r) => r.id);
	$: postedRows = rows.filter((r) => r.transferState !== 'pending');
	$: pendingRows = rows.filter((r) => r.transferState === 'pending');
	$: pendingTotal = pendingRows.reduce((s, r) => s + r.amount, 0);
	$: netTotal = postedRows.reduce((s, r) => s + r.amount, 0);
	$: meta = result?.accountMeta ?? null;
	$: showBalanceRail = isSingleAccount;
	$: periodLabel = describeScope(filters);

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

	function describeScope(f: TransactionFilters): string {
		if (f.month) {
			return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(
				new Date(`${f.month}-01T00:00:00`)
			);
		}
		switch (f.period) {
			case 'this-month':
				return 'this month';
			case 'last-30':
				return 'last 30 days';
			case 'last-3-months':
				return 'last 3 months';
			default:
				return 'all time';
		}
	}

	function dayLines(group: TransactionDayGroupData): { top: string; bottom: string } {
		if (group.header === 'Today' || group.header === 'Yesterday') {
			return { top: group.header, bottom: shortDayDate(group.date) };
		}
		const [datePart, weekday] = group.header.split(' · ');
		return { top: datePart ?? group.header, bottom: weekday ?? '' };
	}

	function shortDayDate(dateStr: string): string {
		return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(
			new Date(`${dateStr}T00:00:00`)
		);
	}

	// ── Data loading ─────────────────────────────────────────────────────────
	async function loadData() {
		if (abortController) abortController.abort();
		abortController = new AbortController();
		const seq = ++requestSeq;
		dataLoading = true;
		error = '';
		try {
			const res = await loadTransactions(filters, { signal: abortController.signal });
			if (seq !== requestSeq) return;
			const previousIds = focusableIds;
			result = res;
			baseCurrency = res.baseCurrency;
			const newIds = res.rows.filter((r) => !r.isAssertion).map((r) => r.id);
			focusedId = reconcileFocus(previousIds, newIds, focusedId);
			if (selectedRow) {
				selectedRow = res.rows.find((r) => r.id === selectedRow?.id) ?? null;
			}
		} catch (e) {
			if (seq !== requestSeq) return;
			if (e instanceof DOMException && e.name === 'AbortError') return;
			error = String(e);
		} finally {
			if (seq === requestSeq) dataLoading = false;
		}
	}

	function changeFilters(next: TransactionFilters) {
		void goto(`/transactions${filtersToUrl(next)}`, {
			replaceState: true,
			noScroll: true,
			keepFocus: true
		});
	}

	async function load() {
		const state = await apiGet<AppState>('/api/app/state');
		workspaceName = state.workspaceName ?? '';
		if (!state.initialized) {
			initialized = false;
			return;
		}
		const [ad, al] = await Promise.all([
			apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts'),
			apiGet<{ accounts: string[] }>('/api/accounts').catch(() => ({ accounts: [] as string[] }))
		]);
		trackedAccounts = ad.trackedAccounts;
		categoryAccounts = al.accounts;
		initialized = true;
	}

	// ── Keyboard verbs ───────────────────────────────────────────────────────
	function moveFocus(direction: 'next' | 'prev'): boolean {
		if (focusableIds.length === 0) return false;
		focusedId =
			direction === 'next' ? nextId(focusableIds, focusedId) : prevId(focusableIds, focusedId);
		if (selectedRow && focusedId) {
			selectedRow = rows.find((r) => r.id === focusedId) ?? selectedRow;
		}
		void tick().then(() => {
			const el = document.querySelector<HTMLElement>(`[data-row-id="${focusedId}"]`);
			// The row scrolls itself into view; focus() must not also scroll.
			el?.focus({ preventScroll: true });
		});
		return true;
	}

	function openFocused(row?: TxRow) {
		const target = row ?? rows.find((r) => r.id === focusedId) ?? null;
		if (!target || target.isAssertion) return false;
		selectedRow = target;
		focusedId = target.id;
		return true;
	}

	function toggleFocusedClearing(): boolean {
		const row = rows.find((r) => r.id === focusedId);
		if (!row || row.isAssertion) return false;
		void handleToggleClearing(row);
		return true;
	}

	// Clearing status is only toggleable in single-account scope (same rule as
	// the row dot), so the verb registers only there — elsewhere `s` is inert
	// and the cheat sheet shows it greyed.
	let offToggleStatus: (() => void) | null = null;
	$: if (isSingleAccount && !offToggleStatus) {
		offToggleStatus = onVerb('row.toggleStatus', toggleFocusedClearing);
	} else if (!isSingleAccount && offToggleStatus) {
		offToggleStatus();
		offToggleStatus = null;
	}

	let verbCleanups: Array<() => void> = [];

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

		verbCleanups = [
			onVerb('focus.next', () => moveFocus('next')),
			onVerb('focus.prev', () => moveFocus('prev')),
			onVerb('row.open', () => openFocused()),
			onVerb('search.focus', () => {
				filterBar?.focusSearch();
				return true;
			}),
			onVerb('dismiss', () => {
				if (selectedRow) {
					selectedRow = null;
					return true;
				}
				if (focusedId) {
					focusedId = null;
					return true;
				}
				return false;
			})
		];
	});

	onDestroy(() => {
		if (abortController) abortController.abort();
		for (const cleanup of verbCleanups) cleanup();
		offToggleStatus?.();
	});

	// ── Actions (delegating to the tested transactionActions layer) ─────────
	async function runAction(fn: () => Promise<{ success: boolean; error?: string }>, close = true) {
		actionBusy = true;
		actionError = '';
		const r = await fn();
		if (r.success) {
			if (close) selectedRow = null;
		} else {
			actionError = r.error ?? 'That didn’t work. Try again.';
		}
		actionBusy = false;
	}

	async function handleToggleClearing(row: TxRow) {
		await toggleClearing(row);
		result = result ? { ...result } : result;
		if (selectedRow?.id === row.id) selectedRow = row;
	}
</script>

{#if loading}
	<section class="px-6 py-10 max-lg:px-4">
		<p class="m-0 text-sm text-ink-mute">Loading your transactions…</p>
	</section>
{:else if error && !initialized}
	<section class="px-6 py-10 max-lg:px-4">
		<h1 class="font-display m-0 text-xl text-ink">Something went wrong</h1>
		<p class="mt-2 mb-0 max-w-prose text-sm text-ink-mute">{error}</p>
	</section>
{:else if !initialized}
	<section class="px-6 py-10 max-lg:px-4">
		<h1 class="font-display m-0 text-xl text-ink">No workspace yet</h1>
		<p class="mt-2 mb-0 max-w-prose text-sm leading-relaxed text-ink-mute">
			Transactions live inside a workspace. The setup flow is being rebuilt — until it returns,
			create the workspace with the command-line tools, then reload this page.
		</p>
	</section>
{:else if trackedAccounts.length === 0}
	<section class="px-6 py-10 max-lg:px-4">
		<h1 class="font-display m-0 text-xl text-ink">
			{workspaceName || 'This workspace'} has no accounts yet
	</h1>
		<p class="mt-2 mb-0 max-w-prose text-sm leading-relaxed text-ink-mute">
			Add a tracked account to start recording activity. Account management is being rebuilt —
			until it returns, add accounts with the command-line tools, then reload this page.
		</p>
	</section>
{:else}
	<header class="px-6 pt-8 pb-5 max-lg:px-4">
		{#if isSingleAccount && selectedAccount}
			<p class="m-0 text-[0.8125rem] text-ink-mute">{selectedAccount.displayName}</p>
			<p class="font-display amount m-0 mt-1 text-[1.75rem] leading-none font-semibold text-ink">
				{meta?.currentBalance == null
					? '—'
					: formatCurrency(meta.currentBalance, baseCurrency)}
			</p>
			<p class="m-0 mt-2 text-[0.8125rem] text-ink-mute">
				Current balance
				· {countLabel(result?.totalCount ?? 0, 'transaction')} {periodLabel}
				{#if pendingRows.length > 0}
					· {countLabel(pendingRows.length, 'pending transfer')} ({formatCurrency(
						pendingTotal,
						baseCurrency,
						{ signMode: 'always' }
					)})
				{/if}
				{#if meta?.latestActivityDate}
					· latest {shortDate(meta.latestActivityDate)}
				{/if}
			</p>
		{:else}
			<h1 class="font-display m-0 text-xl leading-tight font-semibold text-ink">Transactions</h1>
			<p class="m-0 mt-2 text-[0.8125rem] text-ink-mute">
				{countLabel(result?.totalCount ?? 0, 'transaction')}
				{periodLabel} across all accounts
				· net <span class="amount">{formatCurrency(Math.abs(netTotal), baseCurrency)}</span>
				{netTotal > 0 ? 'in' : 'out'}
			</p>
		{/if}
	</header>

	<div class="sticky top-0 z-10">
		<FilterBar bind:this={filterBar} {filters} {trackedAccounts} onChange={changeFilters} />
	</div>

	<!-- Reserved-height refresh indicator: no layout shift when it appears. -->
	<div class="h-0.5" aria-hidden="true">
		{#if dataLoading && result}
			<div class="h-full w-full animate-pulse bg-brand"></div>
		{/if}
	</div>

	{#if result !== null && error}
		<div class="mx-6 mt-3 rounded-md border border-bad/30 bg-bad/5 px-3 py-2 max-lg:mx-4" role="alert">
			<p class="m-0 text-sm text-bad">Couldn’t refresh transactions. {error}</p>
		</div>
	{/if}

	{#if result === null && dataLoading}
		<p class="px-6 py-8 text-sm text-ink-mute max-lg:px-4">Fetching transactions…</p>
	{:else if result === null && error}
		<section class="px-6 py-8 max-lg:px-4">
			<h2 class="m-0 text-sm font-semibold text-ink">Couldn’t load transactions</h2>
			<p class="mt-1 mb-0 text-sm text-ink-mute">{error}</p>
		</section>
	{:else if result !== null && rows.length === 0}
		<section class="px-6 py-8 max-lg:px-4">
			<h2 class="m-0 text-sm font-semibold text-ink">Nothing here for these filters</h2>
			<p class="mt-1 mb-0 text-sm text-ink-mute">
				Try a wider time range, or clear the filters to see everything.
			</p>
			<button
				type="button"
				class="mt-3 cursor-pointer rounded-md border border-hairline-strong bg-panel px-3 py-1.5 text-sm text-ink hover:bg-wash"
				on:click={() => changeFilters({ ...EMPTY_FILTERS })}
			>
				Clear all filters
			</button>
		</section>
	{:else if result !== null}
		<div class="pb-16">
			{#each dayGroups as group (group.date)}
				{@const lines = dayLines(group)}
				<section class="grid grid-cols-[5.5rem_minmax(0,1fr)] max-md:grid-cols-1">
					<div class="pt-2.5 pr-3 pl-4 text-right max-md:border-b max-md:border-hairline max-md:px-4 max-md:py-1.5 max-md:text-left">
						<p class="font-display m-0 text-[0.8125rem] leading-tight font-semibold whitespace-nowrap text-ink max-md:inline">
							{lines.top}
						</p>
						<p class="m-0 text-[0.6875rem] leading-tight text-ink-mute max-md:ml-1.5 max-md:inline">
							{lines.bottom}
						</p>
					</div>
					<ol class="m-0 list-none border-l border-hairline p-0 max-md:border-l-0">
						{#each group.rows as row (row.id)}
							<li class="[contain-intrinsic-size:auto_2.375rem] [content-visibility:auto]">
								{#if row.isAssertion}
									<div
										class="grid items-center gap-x-3 border-b border-hairline px-3 py-1.5 text-xs text-ink-mute max-md:grid-cols-[1rem_minmax(0,1fr)]
										{showBalanceRail ? 'grid-cols-[1rem_minmax(0,1fr)_8.5rem]' : 'grid-cols-[1rem_minmax(0,1fr)]'}"
									>
										<CheckIcon class="size-3 justify-self-center text-brand" />
										<span>Balance verified</span>
										{#if showBalanceRail}
											<span
												class="amount self-stretch content-center border-l border-hairline pl-3 text-right max-md:hidden"
											>
												{row.runningBalance == null
													? ''
													: formatCurrency(row.runningBalance, baseCurrency)}
											</span>
										{/if}
									</div>
								{:else}
									<RegisterRow
										{row}
										{baseCurrency}
										accountKind={isSingleAccount ? scopedAccountKind : rowAccountKind(row)}
										focused={focusedId === row.id}
										showBalance={showBalanceRail}
										showAccount={!isSingleAccount}
										onOpen={(r) => openFocused(r)}
										onToggleClearing={isSingleAccount ? (r) => void handleToggleClearing(r) : null}
									/>
								{/if}
							</li>
						{/each}
					</ol>
				</section>
			{/each}

			<p class="m-0 px-6 pt-4 text-xs text-ink-mute max-lg:px-4">
				<span class="kbd">j</span> <span class="kbd">k</span> to move ·
				<span class="kbd">Enter</span> to open ·
				{#if isSingleAccount}<span class="kbd">s</span> to toggle status ·{/if}
				<span class="kbd">?</span> for all shortcuts
			</p>
		</div>
	{/if}
{/if}

{#if selectedRow}
	<DetailPanel
		row={selectedRow}
		{baseCurrency}
		accountKind={isSingleAccount ? scopedAccountKind : rowAccountKind(selectedRow)}
		{categoryAccounts}
		{trackedAccounts}
		busy={actionBusy}
		error={actionError}
		onClose={() => (selectedRow = null)}
		onToggleClearing={(r) => void handleToggleClearing(r)}
		onRecategorize={(r, cat) =>
			void runAction(() =>
				cat ? recategorize(r, cat, loadData) : resetCategory(r, loadData)
			)}
		onReassignAccount={(r, ledger) => void runAction(() => reassignAccount(r, ledger, loadData))}
		onUnmatch={(r) => void runAction(() => unmatchTransaction(r, loadData))}
		onDelete={(r) => void runAction(() => deleteTransaction(r, loadData))}
	/>
{/if}
