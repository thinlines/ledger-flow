<script lang="ts">
	import { apiGet } from '$lib/api';
	import { formatCurrency, goodChangeTone, type AccountKind } from '$lib/format';
	import type { DashboardOverview, Direction } from './dashboard';
	import { money } from './dashboard';

	export let overview: DashboardOverview;
	export let direction: Direction;
	export let hidden = false;

	type PeriodTransaction = { date: string; payee: string; amount: number; categoryLabel: string; accountLabel: string; accountId: string | null; isTransfer: boolean };
	type PeriodResponse = { transactions: PeriodTransaction[]; total: number };

	let selectedIndex = overview.cashFlow.series.length - 1;
	let periodTransactions: PeriodTransaction[] = [];
	let loadingActivity = false;
	let lastLoadedPeriod = '';

	$: selected = overview.cashFlow.series[selectedIndex] ?? overview.cashFlow.series.at(-1)!;
	$: previous = overview.cashFlow.series[selectedIndex - 1] ?? null;
	$: if (selected?.month && selected.month !== lastLoadedPeriod) void loadPeriod(selected.month);
	$: categories = categoriesFor(selected.month);
	$: maxCategory = Math.max(...categories.map((item) => item.current), 1);
	$: selectedWorth = direction.netWorthTrend?.find((point) => point.month === selected.month)?.value ?? null;
	$: selectedWorthIndex = direction.netWorthTrend?.findIndex((point) => point.month === selected.month) ?? -1;
	$: previousWorth = selectedWorthIndex > 0 ? direction.netWorthTrend?.[selectedWorthIndex - 1] ?? null : null;
	$: worthChangePercent = selectedWorth != null && previousWorth?.value
		? ((selectedWorth - previousWorth.value) / Math.abs(previousWorth.value)) * 100
		: null;
	$: savingsRateCents = Math.round((selected.net / Math.max(selected.income, 1)) * 100);
	$: topChange = [...categories].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0] ?? null;
	$: worthCoordinates = chartCoordinates(direction.netWorthTrend ?? []);
	$: worthLine = worthCoordinates.map((point) => `${point.x},${point.y}`).join(' ');
	$: worthArea = worthCoordinates.length ? `0,110 ${worthLine} 600,110` : '';
	$: selectedWorthPoint = selectedWorthIndex >= 0 ? worthCoordinates[selectedWorthIndex] ?? null : null;
	$: accountKindById = new Map(
		overview.balances
			.filter((account): account is typeof account & { kind: AccountKind } => account.kind === 'asset' || account.kind === 'liability')
			.map((account) => [account.id, account.kind])
	);

	function categoriesFor(month: string) {
		const monthIndex = overview.cashFlow.series.findIndex((item) => item.month === month);
		const previousMonth = overview.cashFlow.series[monthIndex - 1]?.month;
		const currentRows = overview.categoryHistory.filter((row) => row.month === month);
		return currentRows
			.map((row) => {
				const prior = overview.categoryHistory.find((item) => item.month === previousMonth && item.category === row.category)?.amount ?? 0;
				return { ...row, current: row.amount, previous: prior, delta: row.amount - prior };
			})
			.sort((a, b) => b.current - a.current)
			.slice(0, 6);
	}

	async function loadPeriod(period: string) {
		lastLoadedPeriod = period;
		loadingActivity = true;
		try {
			const result = await apiGet<PeriodResponse>(`/api/dashboard/transactions?period=${period}&limit=6`);
			if (lastLoadedPeriod === period) periodTransactions = result.transactions;
		} catch {
			periodTransactions = overview.recentTransactions
				.filter((item) => item.date.startsWith(period))
				.map((item) => ({ ...item, categoryLabel: item.category, accountId: null, isTransfer: item.category === 'Transfer' }));
		} finally {
			if (lastLoadedPeriod === period) loadingActivity = false;
		}
	}

	function selectPeriod(index: number) {
		selectedIndex = index;
	}

	function shortMonth(month: string) {
		if (!/^\d{4}-\d{2}$/.test(month)) return month;
		return new Intl.DateTimeFormat(undefined, { month: 'short' }).format(
			new Date(`${month}-01T00:00:00`)
		);
	}

	function activityAmount(transaction: PeriodTransaction) {
		if (hidden) return '••••••';
		if (transaction.isTransfer) {
			return formatCurrency(Math.abs(transaction.amount), overview.baseCurrency, {
				signMode: 'negative-only'
			});
		}
		const accountKind = transaction.accountId ? accountKindById.get(transaction.accountId) : undefined;
		return formatCurrency(transaction.amount, overview.baseCurrency, {
			signMode: accountKind ? 'good-change-plus' : 'negative-only',
			accountKind
		});
	}

	function activityAmountIsGood(transaction: PeriodTransaction) {
		if (transaction.isTransfer) return false;
		const accountKind = transaction.accountId ? accountKindById.get(transaction.accountId) : undefined;
		return accountKind ? goodChangeTone(transaction.amount, accountKind) === 'positive' : false;
	}

	function chartCoordinates(series: { value: number }[]) {
		if (series.length === 0) return [];
		const values = series.map((point) => point.value);
		const minimum = Math.min(...values);
		const maximum = Math.max(...values);
		const span = Math.max(maximum - minimum, 1);
		return series.map((point, index) => ({
			x: series.length === 1 ? 300 : (index / (series.length - 1)) * 600,
			y: 98 - ((point.value - minimum) / span) * 86
		}));
	}
</script>

<section class="mx-auto max-w-250 px-6 pt-10 pb-28 max-sm:px-4">
	<header class="mb-8 flex items-end justify-between gap-4">
		<div><p class="mb-1 text-xs font-medium uppercase tracking-[0.16em] text-brand-deep">Financial dashboard</p><h1 class="font-display text-3xl font-semibold tracking-tight">Your financial position</h1><p class="mt-1 text-ink-mute">Select any month to explore what changed.</p></div>
		<a href="/transactions" class="text-xs font-medium text-brand-deep no-underline">See all transactions →</a>
	</header>

	<div class="grid grid-cols-[minmax(0,1.65fr)_minmax(16rem,1fr)] items-stretch gap-5 max-md:grid-cols-1">
		<div class="min-w-0 rounded-xl border bg-panel p-6 md:col-start-1 md:row-start-1">
			<div class="flex items-start justify-between gap-4"><div><p class="text-xs text-ink-mute">Net worth {selectedIndex === overview.cashFlow.series.length - 1 ? 'today' : `at end of ${selected.label}`}</p><p class="amount mt-1 font-display text-4xl font-semibold tracking-tight">{money(selectedWorth ?? overview.summary.netWorth, overview.baseCurrency, hidden)}</p></div>{#if worthChangePercent != null}<span class="rounded-full bg-brand-wash px-2.5 py-1 text-xs font-medium {worthChangePercent >= 0 ? 'text-brand-deep' : 'text-bad'}">{worthChangePercent >= 0 ? '↑' : '↓'} {Math.abs(worthChangePercent).toFixed(1)}% vs {shortMonth(previousWorth?.month ?? '')}</span>{:else}<span class="rounded-full bg-wash px-2.5 py-1 text-xs font-medium text-ink-mute">Starting point</span>{/if}</div>
			{#if direction.netWorthTrend}
				<div class="relative mt-6 h-32"><svg class="h-full w-full overflow-visible" viewBox="0 0 600 110" preserveAspectRatio="none" aria-label="Net worth trend"><defs><linearGradient id="worth-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".22"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs><polygon points={worthArea} fill="url(#worth-fill)"/><polyline points={worthLine} fill="none" stroke="var(--accent)" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg>{#if selectedWorthPoint}<span class="absolute size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel bg-brand shadow" style="left:{selectedWorthPoint.x / 6}%; top:{selectedWorthPoint.y / 1.1}%"></span>{/if}</div>
				<div class="flex justify-between text-[0.6875rem] text-ink-mute">{#each direction.netWorthTrend as point}<span>{shortMonth(point.month)}</span>{/each}</div>
			{/if}
		</div>

		<div class="h-full min-w-0 rounded-xl bg-ink p-6 text-white md:col-start-2 md:row-start-1">
			<p class="mb-4 text-[0.6875rem] font-medium uppercase tracking-wider text-white/40">Current health · not period-filtered</p>
			<div class="grid grid-cols-2 gap-5"><div><p class="text-xs text-white/55">Discretionary spent</p><p class="amount mt-2 font-display text-3xl font-semibold">{money(direction.recurringVsDiscretionary.discretionary, overview.baseCurrency, hidden)}</p><p class="mt-1 text-xs leading-relaxed text-white/50">so far this month</p></div><div class="border-l border-white/15 pl-5"><p class="text-xs text-white/55">Runway</p><p class="mt-2 font-display text-3xl font-semibold">{direction.runway?.months ?? '—'} <span class="text-sm text-white/55">mo.</span></p><p class="mt-1 text-xs leading-relaxed text-white/50">of typical spending covered</p></div></div>
			<div class="mt-7 flex items-center gap-3 border-t border-white/15 pt-4"><div class="h-1.5 flex-1 overflow-hidden rounded-full bg-white/15"><div class="h-full rounded-full bg-[#65c7a4]" style="width:{Math.min((direction.runway?.months ?? 0) / 9 * 100, 100)}%"></div></div><span class="text-[0.6875rem] text-white/45">9 mo.</span></div>
		</div>

		<div class="min-w-0 rounded-xl border bg-panel p-6 md:col-start-1 md:row-start-2">
			<div class="mb-5 flex items-center justify-between"><div><h2 class="font-display text-lg font-semibold">Money in, money out</h2><p class="text-xs text-ink-mute">Click a month to cross-filter the dashboard</p></div><div class="text-right"><p class="amount text-lg font-semibold text-brand-deep">{selected.net >= 0 ? '+' : ''}{money(selected.net, overview.baseCurrency, hidden)}</p><p class="text-[0.6875rem] text-ink-mute">net in {selected.label}</p></div></div>
			<div class="flex h-48 items-end gap-4">{#each overview.cashFlow.series as month, index}{@const peak = Math.max(...overview.cashFlow.series.flatMap((item) => [item.income, item.spending]), 1)}<button type="button" class="group relative flex h-full flex-1 cursor-pointer flex-col justify-end gap-1 border-0 bg-transparent p-0" aria-pressed={selectedIndex === index} on:click={() => selectPeriod(index)}><span class="pointer-events-none absolute bottom-[calc(100%+0.4rem)] left-1/2 z-10 hidden -translate-x-1/2 rounded-md bg-ink px-2.5 py-2 text-left text-[0.6875rem] whitespace-nowrap text-white shadow-lg group-hover:block group-focus-visible:block"><strong class="block pb-1">{month.label}</strong><span class="block text-white/70">Income {money(month.income, overview.baseCurrency)}</span><span class="block text-white/70">Spending {money(month.spending, overview.baseCurrency)}</span><span class="block pt-1 text-[#65c7a4]">Net {month.net >= 0 ? '+' : ''}{money(month.net, overview.baseCurrency)}</span></span><span class="flex min-h-0 w-full flex-1 items-end justify-center gap-1 rounded-t-md px-1 {selectedIndex === index ? 'bg-brand-wash' : ''}"><i class="w-2/5 rounded-t bg-brand transition-opacity group-hover:opacity-80" style="height:{month.income / peak * 100}%"></i><i class="w-2/5 rounded-t bg-ink/15 transition-colors group-hover:bg-ink/25" style="height:{month.spending / peak * 100}%"></i></span><span class="w-full pt-1 text-center text-[0.6875rem] {selectedIndex === index ? 'font-semibold text-brand-deep' : 'text-ink-mute'}">{month.label}</span></button>{/each}</div>
			<div class="mt-4 flex gap-4 text-xs text-ink-mute"><span class="flex items-center gap-1.5"><i class="size-2 rounded-sm bg-brand"></i>Income</span><span class="flex items-center gap-1.5"><i class="size-2 rounded-sm bg-ink/15"></i>Spending</span><span class="ml-auto">Showing: <strong class="text-ink">{selected.label}</strong></span></div>
		</div>

		<div class="min-w-0 rounded-xl border bg-panel p-6 md:col-start-1 md:row-start-3">
			<div class="mb-5"><h2 class="font-display text-lg font-semibold">Where it went</h2><div class="mt-1 flex gap-4 text-[0.6875rem] text-ink-mute"><span class="flex items-center gap-1"><i class="size-2 rounded-full bg-brand"></i>At or below prior month</span><span class="flex items-center gap-1"><i class="size-2 rounded-full bg-warn"></i>Higher than prior month</span></div></div>
			{#if categories.length}<div class="space-y-5">{#each categories as category}<a href={`/transactions?month=${selected.month}&category=${encodeURIComponent(category.category)}`} class="grid grid-cols-[minmax(9rem,11rem)_minmax(0,1fr)_6rem] items-center gap-5 no-underline"><span class="truncate text-sm font-medium text-ink">{category.categoryLabel}</span><span class="h-3 overflow-hidden rounded-full bg-wash"><span class="block h-full rounded-full {category.delta > 0 ? 'bg-warn' : 'bg-brand'}" style="width:{category.current / maxCategory * 100}%"></span></span><span class="amount text-right text-sm text-ink">{money(category.current, overview.baseCurrency, hidden)}</span></a>{/each}</div>{:else}<p class="py-10 text-center text-sm text-ink-mute">No categorized spending in {selected.label}.</p>{/if}
		</div>

		<div class="min-w-0 rounded-xl border bg-panel p-6 md:col-start-2 md:row-start-3">
			<div class="mb-4 flex items-center justify-between"><div><h2 class="font-display text-lg font-semibold">Activity in {selected.label}</h2><p class="text-xs text-ink-mute">{loadingActivity ? 'Loading…' : `${periodTransactions.length} recent transactions`}</p></div><a href={`/transactions?month=${selected.month}`} class="text-xs font-medium text-brand-deep">View all →</a></div>
			<div class="divide-y">{#each periodTransactions.slice(0, 5) as tx}<div class="flex items-center justify-between gap-4 py-3"><div class="min-w-0"><p class="truncate text-sm font-medium">{tx.payee}</p><p class="truncate text-[0.6875rem] text-ink-mute">{tx.categoryLabel} · {tx.accountLabel}</p></div><p class="amount shrink-0 whitespace-nowrap text-sm font-medium {activityAmountIsGood(tx) ? 'text-brand-deep' : 'text-ink'}">{activityAmount(tx)}</p></div>{/each}{#if !loadingActivity && periodTransactions.length === 0}<p class="py-10 text-center text-sm text-ink-mute">No activity in this period.</p>{/if}</div>
		</div>

		<div class="min-w-0 rounded-xl border bg-panel p-6 md:col-start-2 md:row-start-2">
			<h2 class="font-display text-lg font-semibold">Worth noticing</h2>{#if topChange}<div class="mt-4 border-l-2 {topChange.delta > 0 ? 'border-warn' : 'border-brand'} pl-4"><p class="font-medium">{topChange.categoryLabel} {topChange.delta > 0 ? 'rose' : 'fell'} the most</p><p class="mt-1 text-xs leading-relaxed text-ink-mute">{money(Math.abs(topChange.delta), overview.baseCurrency, hidden)} {topChange.delta > 0 ? 'more' : 'less'} than {previous?.label ?? 'the prior period'}.</p></div>{:else}<p class="mt-4 text-sm text-ink-mute">No comparable spending pattern for this month.</p>{/if}<div class="mt-5 border-t pt-4"><p class="text-xs text-ink-mute">Savings rate</p>{#if selected.income <= 0}<p class="mt-1 font-medium">No income recorded in {selected.label}.</p>{:else if savingsRateCents >= 0}<p class="mt-1 font-medium">You kept {savingsRateCents}¢ of every dollar earned.</p>{:else}<p class="mt-1 font-medium">You spent {Math.abs(savingsRateCents) + 100}¢ for every dollar earned.</p>{/if}<p class="mt-1 text-[0.6875rem] text-ink-mute">Based on income and spending in {selected.label}.</p></div>
		</div>

		<div class="min-w-0 rounded-xl border bg-panel p-6 md:col-start-1 md:row-start-4">
			<div class="mb-3 flex items-center justify-between"><div><h2 class="font-display text-lg font-semibold">Accounts</h2><p class="text-[0.6875rem] text-ink-mute">Current balances · not filtered by period</p></div><span class="amount text-sm font-semibold">{money(overview.summary.trackedBalanceTotal, overview.baseCurrency, hidden)}</span></div><div class="divide-y">{#each overview.balances.slice(0, 5) as account}<div class="flex items-center justify-between py-2.5"><div class="flex items-center gap-2"><i class="size-1.5 rounded-full {account.reconciliationStatus.ok ? 'bg-brand' : 'bg-warn'}"></i><span class="text-sm">{account.displayName}</span></div><span class="amount text-sm font-medium">{money(account.balance, overview.baseCurrency, hidden)}</span></div>{/each}</div>
		</div>

		<div class="min-w-0 rounded-xl border bg-panel p-6 md:col-start-2 md:row-start-4">
			<div class="mb-3 flex items-center justify-between"><h2 class="font-display text-lg font-semibold">To do</h2><span class="text-xs text-ink-mute">Book health</span></div><div class="divide-y">{#if direction.looseEnds.reviewQueueCount > 0}<a href="/transactions?status=unknown" class="flex items-center justify-between py-3 text-sm text-ink no-underline"><span>{direction.looseEnds.reviewQueueCount} transactions need review</span><span>→</span></a>{/if}{#each direction.looseEnds.brokenReconciliations as account}<a href="/transactions" class="flex items-center justify-between py-3 text-sm text-ink no-underline"><span>Reconcile {account.displayName}</span><span>→</span></a>{/each}{#if direction.looseEnds.reviewQueueCount === 0 && direction.looseEnds.brokenReconciliations.length === 0}<p class="py-6 text-center text-sm text-ink-mute">Nothing needs attention.</p>{/if}</div>
		</div>
	</div>
</section>
