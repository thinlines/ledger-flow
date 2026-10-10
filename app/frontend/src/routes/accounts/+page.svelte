<script lang="ts">
	import { onMount } from 'svelte';
	import { apiGet } from '$lib/api';
	import { ACCOUNT_SUBTYPE_OPTIONS } from '$lib/account-subtypes';
	import { balanceHistoryForChart, trendChangeForDisplay } from '$lib/account-trend';
	import AccountModal from '$lib/components/AccountModal.svelte';
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import Check from '@lucide/svelte/icons/check';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import CreditCard from '@lucide/svelte/icons/credit-card';
	import Landmark from '@lucide/svelte/icons/landmark';
	import Plus from '@lucide/svelte/icons/plus';
	import Scale from '@lucide/svelte/icons/scale';

	// Financial-first account dashboard promoted from the validated prototype.
	type Account = { id: string; displayName: string; institutionId: string | null; institutionDisplayName: string | null; importAccountId: string | null; kind: 'asset' | 'liability'; subtype: string | null; last4: string | null; ledgerAccount: string; openingBalance: string | null; openingBalanceDate: string | null; minimumPayment: string | null; importConfigured: boolean; lastReconciledDate: string | null; reconciliationStatus: { ok: boolean }; transactionCount: number; balance: number; history: number[] };
	type InstitutionTemplate = { id: string; displayName: string; suggestedLedgerPrefix: string };
	type Register = { entries: { date: string; runningBalance: number | null }[] };

	let accounts: Account[] = [];
	let expandedId: string | null = null;
	let kindFilter: 'all' | 'asset' | 'liability' = 'all';
	let loading = true;
	let error = '';
	let accountModal: AccountModal;
	let institutionTemplates: InstitutionTemplate[] = [];
	let baseCurrency = 'USD';
	$: shownAccounts = kindFilter === 'all' ? accounts : accounts.filter((a) => a.kind === kindFilter);
	$: assets = accounts.filter((a) => a.kind === 'asset');
	$: liabilities = accounts.filter((a) => a.kind === 'liability');
	$: totalAssets = assets.reduce((sum, a) => sum + a.balance, 0);
	$: totalDebt = Math.abs(liabilities.reduce((sum, a) => sum + a.balance, 0));
	$: netPosition = totalAssets - totalDebt;
	$: portfolioHistory = accounts.length ? Array.from({ length: 6 }, (_, i) => accounts.reduce((sum, a) => sum + (a.history[i] ?? a.balance), 0)) : [0, 0, 0, 0, 0, 0];
	$: portfolioChange = (portfolioHistory.at(-1) ?? 0) - (portfolioHistory[0] ?? 0);
	$: reconciliationDue = accounts.filter((a) => reconciliationState(a) !== 'current');

	onMount(() => {
		void loadAccounts();
	});

	async function loadAccounts(focusAccountId?: string) {
		loading = true;
		error = '';
		try {
			const [tracked, overview] = await Promise.all([apiGet<{ trackedAccounts: Omit<Account, 'balance' | 'history'>[]; institutionTemplates: InstitutionTemplate[] }>('/api/tracked-accounts'), apiGet<{ balances: { id: string; balance: number }[]; baseCurrency?: string }>('/api/dashboard/overview')]);
			const balances = new Map(overview.balances.map((row) => [row.id, row.balance]));
			const rows = await Promise.all(tracked.trackedAccounts.map(async (account) => {
				let history: number[] = [];
				try { history = historyFromRegister(await apiGet<Register>(`/api/transactions/register?accountId=${encodeURIComponent(account.id)}`)); } catch { /* use flat history */ }
				const balance = balances.get(account.id) ?? 0;
				return { ...account, balance, history: history.length > 1 ? history : Array(6).fill(balance) };
			}));
			accounts = rows;
			institutionTemplates = tracked.institutionTemplates;
			baseCurrency = overview.baseCurrency || 'USD';
			expandedId = rows.some((row) => row.id === focusAccountId) ? focusAccountId ?? null : rows[0]?.id ?? null;
		} catch (caught) {
			error = caught instanceof Error ? caught.message : String(caught);
		} finally {
			loading = false;
		}
	}
	function historyFromRegister(register: Register) { const rows = [...register.entries].reverse().filter((e) => e.runningBalance != null); return rows.length ? Array.from({ length: 6 }, (_, i) => rows[Math.min(rows.length - 1, Math.floor(i * (rows.length - 1) / 5))]?.runningBalance ?? 0) : []; }
	function currency(value: number) { return new Intl.NumberFormat(undefined, { style: 'currency', currency: baseCurrency, maximumFractionDigits: 0 }).format(value); }
	function kindLabel(kind: 'all' | 'asset' | 'liability') { return kind === 'all' ? 'All' : kind === 'asset' ? 'Assets' : 'Liabilities'; }
	function subtypeLabel(account: Account) { return ACCOUNT_SUBTYPE_OPTIONS.find((o) => o.value === account.subtype)?.label ?? (account.kind === 'liability' ? 'Liability' : 'Asset'); }
	function change(account: Account) { return account.balance - (account.history[0] ?? account.balance); }
	function financialDirection(account: Account) { return account.kind === 'liability' ? -change(account) : change(account); }
	function chartHistory(account: Account) { return balanceHistoryForChart(account.history, account.kind as 'asset' | 'liability'); }
	function displayedChange(account: Account) { return trendChangeForDisplay(change(account), account.kind as 'asset' | 'liability'); }
	function reconciliationState(account: Account): 'current' | 'never' | 'broken' { if (!account.reconciliationStatus.ok) return 'broken'; return account.lastReconciledDate ? 'current' : 'never'; }
	function reconciledLabel(account: Account) { if (!account.reconciliationStatus.ok) return 'Balance mismatch'; if (!account.lastReconciledDate) return 'Not yet reconciled'; const days = Math.max(0, Math.floor((Date.now() - new Date(`${account.lastReconciledDate}T12:00:00`).getTime()) / 86400000)); return days === 0 ? 'Reconciled today' : `Reconciled ${days}d ago`; }
	function points(values: number[], width = 120, height = 36) { const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, 1); return values.map((value, i) => `${(i / Math.max(values.length - 1, 1)) * width},${height - 3 - ((value - min) / span) * (height - 6)}`).join(' '); }
	function toggleExpanded(accountId: string) { expandedId = expandedId === accountId ? null : accountId; }
</script>

<svelte:head><title>Accounts · Ledger Flow</title></svelte:head>

	<section class="mx-auto max-w-250 px-6 pt-10 pb-24 max-sm:px-4">
		<header class="flex items-start justify-between gap-5"><div><p class="mb-1 text-xs font-medium uppercase tracking-[0.16em] text-brand-deep">Accounts</p><h1 class="font-display text-3xl font-semibold tracking-tight">Your accounts at a glance</h1><p class="mt-1 text-ink-mute">Where your money sits, how it is moving, and which balances need checking.</p></div><button type="button" class="mt-5 flex shrink-0 items-center gap-2 rounded-md border border-brand bg-brand px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90" on:click={() => accountModal.openAdd()}><Plus size={15}/> Add account</button></header>
		<div class="mt-8 grid grid-cols-[1.5fr_1fr] gap-5 max-md:grid-cols-1">
			<div class="rounded-xl bg-ink p-6 text-white"><div class="flex items-start justify-between"><div><p class="text-xs text-white/55">Net account position</p><p class="amount mt-2 font-display text-4xl font-semibold">{currency(netPosition)}</p><p class="mt-2 text-xs text-[#65c7a4]">{portfolioChange >= 0 ? '↑' : '↓'} {currency(Math.abs(portfolioChange))} across recorded history</p></div><Scale size={25} class="text-white/45"/></div><svg class="mt-6 h-20 w-full overflow-visible" viewBox="0 0 560 80" preserveAspectRatio="none"><defs><linearGradient id="portfolio-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#65c7a4" stop-opacity=".32"/><stop offset="1" stop-color="#65c7a4" stop-opacity="0"/></linearGradient></defs><polygon points={`0,80 ${points(portfolioHistory, 560, 74)} 560,80`} fill="url(#portfolio-fill)"/><polyline points={points(portfolioHistory, 560, 74)} fill="none" stroke="#65c7a4" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg><div class="mt-2 flex justify-between text-[0.6875rem] text-white/40"><span>Older</span><span>Current</span></div></div>
			<div class="grid grid-rows-2 gap-4"><div class="rounded-xl border bg-panel p-5"><div class="flex justify-between"><p class="text-xs text-ink-mute">Assets</p><span class="text-xs text-brand-deep">{assets.length} accounts</span></div><p class="amount mt-2 font-display text-2xl font-semibold">{currency(totalAssets)}</p><div class="mt-4 flex h-2 overflow-hidden rounded-full bg-wash">{#each assets as account}<span class="h-full border-r border-panel bg-brand" style={`width:${Math.max(account.balance / totalAssets * 100, 2)}%; opacity:${0.45 + assets.indexOf(account) * 0.18}`}></span>{/each}</div></div><div class="rounded-xl border bg-panel p-5"><div class="flex justify-between"><p class="text-xs text-ink-mute">Liabilities</p><span class="text-xs text-ink-mute">{liabilities.length} accounts</span></div><p class="amount mt-2 font-display text-2xl font-semibold">{currency(totalDebt)}</p><p class="mt-3 text-xs text-ink-mute">{reconciliationDue.length} balance{reconciliationDue.length === 1 ? '' : 's'} need reconciliation</p></div></div>
		</div>
		<div class="mt-5 overflow-hidden rounded-xl border bg-panel"><div class="flex items-center justify-between border-b px-5 py-4"><div><h2 class="font-display text-lg font-semibold">Account portfolio</h2></div><div class="flex rounded-md bg-wash p-0.5 text-xs">{#each ['all', 'asset', 'liability'] as item}<button class="rounded px-2.5 py-1 capitalize {kindFilter === item ? 'bg-panel font-medium shadow-sm' : 'text-ink-mute'}" on:click={() => kindFilter = item as typeof kindFilter} aria-pressed={kindFilter === item}>{kindLabel(item as typeof kindFilter)}</button>{/each}</div></div>
			<div class="grid grid-cols-[minmax(13rem,1.5fr)_0.75fr_0.9fr_0.9fr_auto] gap-5 border-b bg-wash/50 px-5 py-2.5 text-[0.6875rem] font-medium uppercase tracking-wider text-ink-mute max-md:hidden"><span>Account</span><span>Balance</span><span>Trend</span><span>Reconciliation</span><span></span></div>
			{#if loading}<p class="px-5 py-12 text-center text-sm text-ink-mute">Loading accounts…</p>{:else if error}<div class="px-5 py-12 text-center"><p class="text-sm font-medium text-bad">Couldn’t load accounts</p><p class="mt-1 text-xs text-ink-mute">{error}</p><button class="mt-4 rounded-md border bg-panel px-3 py-1.5 text-xs font-medium" on:click={() => void loadAccounts()}>Try again</button></div>{:else if shownAccounts.length === 0}<p class="px-5 py-12 text-center text-sm text-ink-mute">No {kindFilter === 'all' ? '' : kindFilter} accounts to show.</p>{/if}
			{#each shownAccounts as account}
				<div class="border-b last:border-0">
					<div class="grid grid-cols-[minmax(13rem,1.5fr)_0.75fr_0.9fr_0.9fr_auto] items-center gap-5 px-5 py-4 max-md:grid-cols-[1fr_auto] {expandedId === account.id ? 'bg-wash/35' : ''}">
						<div class="flex min-w-0 items-center gap-3"><span class="grid size-9 shrink-0 place-items-center rounded-lg bg-wash">{#if account.kind === 'liability'}<CreditCard size={16}/>{:else}<Landmark size={16}/>{/if}</span><div class="min-w-0"><p class="truncate font-medium">{account.displayName}</p><p class="text-xs text-ink-mute">{subtypeLabel(account)}{account.last4 ? ` · •${account.last4}` : ''}</p></div></div>
						<p class="amount font-medium">{currency(account.balance)}</p>
						<div><svg class="h-9 w-28" viewBox="0 0 120 36" preserveAspectRatio="none"><polyline points={points(chartHistory(account))} fill="none" stroke={financialDirection(account) >= 0 ? 'var(--accent)' : 'var(--warn)'} stroke-width="2" vector-effect="non-scaling-stroke"/></svg><p class="text-[0.625rem] {financialDirection(account) >= 0 ? 'text-brand-deep' : 'text-warn'}">{displayedChange(account) >= 0 ? '+' : ''}{currency(displayedChange(account))}</p></div>
						<p class="flex items-center gap-1.5 text-xs {reconciliationState(account) === 'broken' ? 'font-medium text-warn' : 'text-ink-mute'}">{#if reconciliationState(account) === 'current'}<Check size={13}/>{:else}<CircleAlert size={13}/>{/if}{reconciledLabel(account)}</p>
						<button class="grid size-8 cursor-pointer place-items-center rounded-md border bg-panel hover:bg-wash" on:click={() => toggleExpanded(account.id)} aria-expanded={expandedId === account.id} aria-label={`${expandedId === account.id ? 'Collapse' : 'Expand'} ${account.displayName}`}><span class="transition-transform {expandedId === account.id ? 'rotate-90' : ''}"><ChevronRight size={15}/></span></button>
					</div>
					{#if expandedId === account.id}
						<div class="grid grid-cols-[minmax(0,1.5fr)_minmax(13rem,0.75fr)] gap-7 border-t bg-wash/35 px-5 py-5 max-md:grid-cols-1">
							<div>
								<div class="mb-4 flex items-start justify-between"><div><h3 class="font-display text-base font-semibold">Balance history</h3></div><div class="text-right"><p class="amount text-sm font-semibold {financialDirection(account) >= 0 ? 'text-brand-deep' : 'text-warn'}">{displayedChange(account) >= 0 ? '+' : ''}{currency(displayedChange(account))}</p><p class="text-[0.6875rem] text-ink-mute">historical change</p></div></div>
								<div class="rounded-lg border bg-panel px-4 pt-4"><svg class="h-28 w-full overflow-visible" viewBox="0 0 540 104" preserveAspectRatio="none"><defs><linearGradient id={`row-fill-${account.id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".18"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs><polygon points={`0,104 ${points(chartHistory(account), 540, 98)} 540,104`} fill={`url(#row-fill-${account.id})`}/><polyline points={points(chartHistory(account), 540, 98)} fill="none" stroke="var(--accent)" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg><div class="flex justify-between pb-3 text-[0.625rem] text-ink-mute"><span>Older</span><span>Current</span></div></div>
								<div class="mt-4 grid grid-cols-3 divide-x text-xs"><div><p class="text-ink-mute">Account type</p><p class="mt-1 font-medium">{subtypeLabel(account)}</p></div><div class="px-4"><p class="text-ink-mute">Activity</p><p class="mt-1 font-medium">{account.transactionCount} transactions</p></div><div class="pl-4"><p class="text-ink-mute">Entry method</p><p class="mt-1 font-medium">{account.importConfigured ? 'CSV imports' : 'Manual entries'}</p></div></div>
							</div>
							<aside class="rounded-lg border bg-panel p-4">
								<p class="text-[0.6875rem] font-medium uppercase tracking-wider text-ink-mute">Reconciliation</p>
								<div class="mt-3 flex items-start gap-2.5"><span class="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full {reconciliationState(account) === 'current' ? 'bg-brand-wash text-brand-deep' : reconciliationState(account) === 'broken' ? 'bg-[#fff4dd] text-warn' : 'bg-wash text-ink-mute'}">{#if reconciliationState(account) === 'current'}<Check size={13}/>{:else}<CircleAlert size={13}/>{/if}</span><div><p class="text-sm font-medium">{reconciliationState(account) === 'current' ? 'Balance checks out' : reconciliationState(account) === 'broken' ? 'Balance needs review' : 'Not yet reconciled'}</p><p class="mt-1 text-xs leading-relaxed text-ink-mute">{reconciliationState(account) === 'current' ? reconciledLabel(account) : reconciliationState(account) === 'broken' ? 'The last statement balance and ledger balance do not match.' : 'No reconciliation has been recorded for this account yet.'}</p></div></div>
								<div class="mt-5 grid gap-2 border-t pt-4">{#if !account.importConfigured}<button type="button" class="flex items-center justify-between rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-sm text-ink hover:bg-wash" on:click={() => accountModal.openEdit(account)}><span>Edit account</span><ArrowUpRight size={14}/></button>{/if}<a href={`/transactions?accounts=${encodeURIComponent(account.id)}`} class="flex items-center justify-between rounded-md px-2 py-1.5 text-sm text-ink no-underline hover:bg-wash"><span>View transactions</span><ArrowUpRight size={14}/></a><a href="/import" class="flex items-center justify-between rounded-md px-2 py-1.5 text-sm text-ink no-underline hover:bg-wash"><span>Import CSV</span><ArrowUpRight size={14}/></a></div>
							</aside>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	</section>

	<AccountModal bind:this={accountModal} {institutionTemplates} existingAccounts={accounts} {baseCurrency} onSaved={(id) => void loadAccounts(id)} />
