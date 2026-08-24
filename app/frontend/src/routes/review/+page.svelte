<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { apiGet, apiPost } from '$lib/api';
	import { filterCategoryOptions, transferTargetOptions, type TransferTargetAccount } from '$lib/category-combobox';
	import { applyUnknownStage, saveUnknownSelections, type UnknownSelectionPayload } from '$lib/stage-client';

	type ManualCandidate = { manualTxnId: string; lfTxnId?: string | null; lineStart: number; lineEnd: number; payee: string; date: string; amount: string | null; destinationAccount?: string; matchReason: string };
	type TransferCandidate = { candidateTxnId: string; targetTrackedAccountId: string; targetTrackedAccountName: string; candidateDate?: string; candidatePayee?: string; candidateAmount?: string };
	type ReviewTxn = { txnId: string; transactionId: string; date: string; amount: string; sourceTrackedAccountId?: string; transferSuggestion?: TransferCandidate | null; transferSuggestions?: TransferCandidate[]; matchCandidates?: ManualCandidate[] };
	type ReviewGroup = { payeeDisplay: string; sourceAccountLabel?: string; suggestedAccount?: string | null; txns: ReviewTxn[] };
	type ImportedTxn = { transactionId: string; date: string; payee: string; amount: string | null; accountLabel?: string; transferState?: string | null };
	type ReviewStage = { stageId: string; transactions: ImportedTxn[]; groups: ReviewGroup[]; selections: Record<string, UnknownSelectionPayload> };
	type Item = { id: string; payee: string; date: string; amount: string; account: string; state: string; kind: 'category' | 'transfer' | 'ready'; txn?: ReviewTxn; group?: ReviewGroup };
	type Filter = 'all' | 'categories' | 'transfers';

	let stage: ReviewStage | null = null;
	let categories: string[] = [];
	let trackedAccounts: TransferTargetAccount[] = [];
	let filter: Filter = 'all';
	let focusedId = '';
	let detail: HTMLElement;
	let searchInput: HTMLInputElement;
	let categoryInput: HTMLInputElement;
	let categoryQuery = '';
	let transferQuery = '';
	let treatingAsCategory = false;
	let treatingAsTransfer = false;
	let showSearch = false;
	let lastActiveId = '';
	let loading = true;
	let busy = false;
	let error = '';

	$: journalPath = $page.url.searchParams.get('journal') ?? '';
	$: sourceFileSha256 = $page.url.searchParams.get('source') ?? '';
	$: attention = stage ? flattenAttention(stage.groups) : [];
	$: allItems = stage ? flattenAll(stage.transactions, attention) : [];
	$: visible = filter === 'all' ? allItems : allItems.filter((item) => filter === 'categories' ? item.kind === 'category' : item.kind === 'transfer');
	$: if (visible.length && !visible.some((item) => item.id === focusedId)) focusedId = visible[0].id;
	$: active = visible.find((item) => item.id === focusedId) ?? null;
	$: if ((active?.id ?? '') !== lastActiveId) { lastActiveId = active?.id ?? ''; treatingAsCategory = false; treatingAsTransfer = false; showSearch = false; transferQuery = ''; categoryQuery = ''; }
	$: transferCandidates = active?.txn?.transferSuggestions?.length ? active.txn.transferSuggestions : active?.txn?.transferSuggestion ? [active.txn.transferSuggestion] : [];
	$: topTransferCandidates = transferCandidates.slice(0, 4);
	$: searchedTransferCandidates = transferCandidates.filter((candidate) => {
		const query = transferQuery.trim().toLowerCase();
		return !query || [candidate.candidatePayee, candidate.candidateDate, candidate.candidateAmount, candidate.targetTrackedAccountName].some((value) => value?.toLowerCase().includes(query));
	});
	$: manualCandidates = active?.txn?.matchCandidates?.slice(0, 4) ?? [];
	$: categoryChoices = [active?.group?.suggestedAccount, ...categories.filter((entry) => entry !== active?.group?.suggestedAccount)].filter((entry): entry is string => Boolean(entry)).slice(0, 3);
	$: filteredCategories = filterCategoryOptions(categories, categoryQuery);
	$: filteredTransferTargets = transferTargetOptions(trackedAccounts, active?.txn?.sourceTrackedAccountId, transferQuery);
	$: stagedCategory = active?.txn ? stage?.selections[active.txn.txnId]?.categoryAccount : undefined;
	$: stagedCount = Object.keys(stage?.selections ?? {}).length;

	function flattenAttention(groups: ReviewGroup[]): Item[] {
		return groups.flatMap((group) => group.txns.map((txn) => {
			const isTransfer = Boolean(txn.transferSuggestion || txn.transferSuggestions?.length);
			return { id: txn.txnId, payee: group.payeeDisplay, date: txn.date, amount: txn.amount, account: group.sourceAccountLabel ?? '', state: isTransfer ? 'Possible transfer' : txn.matchCandidates?.length ? 'Possible manual match' : 'Needs category', kind: isTransfer ? 'transfer' : 'category', txn, group };
		}));
	}
	function flattenAll(imported: ImportedTxn[], unresolved: Item[]): Item[] {
		const byTransaction = new Map(unresolved.map((item) => [item.txn?.transactionId, item]));
		return imported.map((row) => byTransaction.get(row.transactionId) ?? { id: row.transactionId, payee: row.payee, date: row.date, amount: row.amount ?? '—', account: row.accountLabel ?? '', state: row.transferState === 'matched' ? 'Matched automatically' : 'Ready', kind: row.transferState === 'matched' ? 'transfer' : 'ready' });
	}

	async function load() {
		if (!journalPath) { error = 'This review link is missing its journal context.'; loading = false; return; }
		try {
			const [scanned, accountData, trackedData] = await Promise.all([apiPost<ReviewStage>('/api/unknowns/scan', { journalPath, sourceFileSha256: sourceFileSha256 || null }), apiGet<{ accounts: string[] }>('/api/accounts'), apiGet<{ trackedAccounts: TransferTargetAccount[] }>('/api/tracked-accounts')]);
			stage = scanned;
			categories = accountData.accounts.filter((account) => account.startsWith('Expenses:') || account.startsWith('Income:'));
			trackedAccounts = trackedData.trackedAccounts;
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { loading = false; }
	}
	async function choose(selection: UnknownSelectionPayload) {
		if (!stage || !active?.txn) return;
		busy = true; error = '';
		try {
			stage = await saveUnknownSelections<ReviewStage>(stage.stageId, Object.values({ ...stage.selections, [selection.txnId]: selection }));
			const next = visible.slice(visible.findIndex((item) => item.id === active?.id) + 1).find((item) => item.kind !== 'ready' && !stage?.selections[item.id]);
			if (next) focusedId = next.id;
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { busy = false; }
	}
	function chooseTransfer(candidate: TransferCandidate) {
		if (!active?.txn) return;
		void choose({ txnId: active.txn.txnId, selectionType: 'transfer', targetTrackedAccountId: candidate.targetTrackedAccountId, matchedTransferCandidateTxnId: candidate.candidateTxnId });
	}
	function chooseTransferTarget(account: TransferTargetAccount) {
		if (!active?.txn) return;
		void choose({ txnId: active.txn.txnId, selectionType: 'transfer', targetTrackedAccountId: account.id });
	}
	function chooseManual(candidate: ManualCandidate) {
		if (!active?.txn) return;
		void choose({ txnId: active.txn.txnId, selectionType: 'match', matchedCandidateId: candidate.manualTxnId, matchedManualTxnId: candidate.manualTxnId, matchedManualLfTxnId: candidate.lfTxnId ?? undefined, matchedManualLineRange: [candidate.lineStart, candidate.lineEnd] });
	}
	async function apply() {
		if (!stage || !stagedCount) return;
		busy = true; error = '';
		try { await applyUnknownStage(stage.stageId); await goto('/transactions'); }
		catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { busy = false; }
	}
	function openSearch() { showSearch = true; transferQuery = ''; requestAnimationFrame(() => searchInput?.focus()); }
	function focusCategoryPicker() { requestAnimationFrame(() => categoryInput?.focus()); }
	function keydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement;
		if (target === categoryInput && event.key === 'Enter' && !busy) {
			event.preventDefault();
			const category = filteredCategories[0];
			if (category && active?.txn) void choose({ txnId: active.txn.txnId, selectionType: 'category', categoryAccount: category });
			return;
		}
		if (target.matches('input, select, textarea')) { if (event.key === 'Escape') { event.preventDefault(); detail?.focus(); } return; }
		if (active?.txn && !busy && event.key.toLowerCase() === 'm') {
			event.preventDefault(); treatingAsTransfer = true; treatingAsCategory = false; transferQuery = ''; return;
		}
		if (!active?.txn || busy || event.key < '1' || event.key > '4') return;
		const index = Number(event.key) - 1;
		if (treatingAsTransfer && filteredTransferTargets[index]) { event.preventDefault(); chooseTransferTarget(filteredTransferTargets[index]); return; }
		if (active.kind === 'transfer' && !treatingAsCategory && topTransferCandidates[index]) { event.preventDefault(); chooseTransfer(topTransferCandidates[index]); return; }
		if (active.kind === 'category' || treatingAsCategory) {
			if (index === 3) { event.preventDefault(); focusCategoryPicker(); return; }
			const category = categoryChoices[index];
			if (category) { event.preventDefault(); void choose({ txnId: active.txn.txnId, selectionType: 'category', categoryAccount: category }); }
		}
	}
	onMount(() => { void load(); });
</script>

<svelte:window on:keydown={keydown} />

{#if loading}
	<p class="px-6 py-10 text-sm text-ink-mute">Preparing your review queue…</p>
{:else if error && !stage}
	<section class="px-6 py-10"><h1 class="font-display m-0 text-xl">Couldn’t open review</h1><p class="mt-2 text-sm text-ink-mute">{error}</p></section>
{:else if stage}
	<section class="px-8 py-9 max-lg:px-5">
		<header class="flex flex-wrap items-end justify-between gap-5 border-b border-hairline pb-6"><div><p class="m-0 text-xs font-medium tracking-widest text-brand-deep uppercase">Imported transactions</p><h1 class="font-display m-0 mt-2 text-3xl font-semibold">Review this import</h1><p class="m-0 mt-2 text-sm text-ink-mute">Make sure imported activity is accurately categorized and matched. You can leave any item for later.</p></div><div class="flex items-center gap-3"><span class="text-xs text-ink-mute">{attention.length} need attention</span><button type="button" class="cursor-pointer rounded-md border-0 bg-brand px-3 py-1.5 text-sm font-medium text-panel disabled:opacity-40" disabled={!stagedCount || busy} on:click={apply}>{busy ? 'Applying…' : `Apply ${stagedCount} changes`}</button></div></header>
		<div class="mt-6 grid grid-cols-[21rem_minmax(0,1fr)] gap-6 max-md:grid-cols-1">
			<aside class="overflow-hidden rounded-lg border border-hairline-strong bg-panel"><div class="border-b border-hairline px-4 pt-3"><div class="flex gap-5" role="tablist">{#each [['all', 'All imported', allItems.length], ['categories', 'Categorize', attention.filter((item) => item.kind === 'category').length], ['transfers', 'Transfers', allItems.filter((item) => item.kind === 'transfer').length]] as tab}<button type="button" role="tab" aria-selected={filter === tab[0]} class="relative cursor-pointer border-0 bg-transparent px-0 pb-3 text-xs {filter === tab[0] ? 'font-medium text-ink' : 'text-ink-mute'}" on:click={() => filter = tab[0] as Filter}>{tab[1]} <span class="ml-1 text-brand-deep">{tab[2]}</span>{#if filter === tab[0]}<span class="absolute right-0 bottom-0 left-0 h-0.5 bg-brand"></span>{/if}</button>{/each}</div></div><ol class="m-0 list-none p-0">{#each visible as item}<li class="grid grid-cols-[0.25rem_minmax(0,1fr)] border-b border-hairline last:border-0"><span class={item.kind === 'category' ? 'bg-[oklch(0.72_0.055_82)]' : item.kind === 'transfer' ? 'bg-brand' : 'bg-hairline-strong'}></span><button type="button" class="min-w-0 cursor-pointer border-0 px-3.5 py-3.5 text-left {focusedId === item.id ? 'bg-brand-wash' : 'bg-panel hover:bg-wash'}" on:click={() => { focusedId = item.id; categoryQuery = ''; }}><span class="flex justify-between gap-2"><span class="truncate text-sm font-medium">{item.payee}</span><span class="amount shrink-0 text-sm">{item.amount}</span></span><span class="mt-1 flex justify-between gap-2"><span class="text-xs text-ink-mute">{item.date}</span><span class="rounded-full px-1.5 py-0.5 text-[0.6875rem] {item.kind === 'category' ? 'bg-[oklch(0.974_0.018_92)] text-[oklch(0.46_0.055_82)]' : item.kind === 'transfer' ? 'bg-brand-wash text-brand-deep' : 'bg-wash text-ink-mute'}">{stage.selections[item.id] ? 'Staged' : item.state}</span></span></button></li>{/each}</ol></aside>
			<main bind:this={detail} tabindex="-1" class="rounded-lg border border-hairline-strong bg-panel p-6">{#if active}<p class="m-0 text-xs font-medium text-brand-deep">{treatingAsTransfer ? 'MARK AS TRANSFER' : active.kind === 'transfer' && !treatingAsCategory ? (active.txn ? 'POSSIBLE TRANSFER' : 'MATCHED TRANSFER') : active.kind === 'ready' ? 'IMPORTED TRANSACTION' : 'NEEDS ATTENTION'}</p><div class="mt-2 flex items-start justify-between gap-4"><span><h2 class="m-0 text-xl font-semibold">{active.payee}</h2><p class="m-0 mt-1 text-sm text-ink-mute">{active.date} · {active.account}</p></span><span class="amount text-lg font-semibold">{active.amount}</span></div>
				{#if treatingAsTransfer && active.txn}
					<section class="mt-7"><h3 class="m-0 text-sm font-semibold">Which account received the other side?</h3><p class="m-0 mt-1 text-sm text-ink-mute">Choose any tracked account, including accounts maintained manually.</p><label class="sr-only" for="transfer-target-search">Search accounts</label><input bind:value={transferQuery} id="transfer-target-search" class="mt-3 w-full max-w-xl" placeholder="Search accounts…" /><div class="mt-2 grid max-w-xl gap-2">{#each filteredTransferTargets.slice(0, 6) as account, index}<button type="button" class="cursor-pointer rounded-md border border-hairline-strong bg-panel px-4 py-3 text-left text-sm hover:bg-wash" on:click={() => chooseTransferTarget(account)}>{account.displayName}<span class="float-right text-xs text-ink-mute">{account.ledgerAccount}{#if index < 4} · <span class="kbd">{index + 1}</span>{/if}</span></button>{:else}<p class="m-0 px-1 py-2 text-sm text-ink-mute">No accounts match.</p>{/each}</div><button type="button" class="mt-5 cursor-pointer rounded-md border border-hairline-strong bg-panel px-4 py-2 text-sm" on:click={() => treatingAsTransfer = false}>Back to categories</button></section>
				{:else if active.kind === 'transfer' && active.txn && !treatingAsCategory}
					<section class="mt-7"><h3 class="m-0 text-sm font-semibold">Does it match one of these?</h3><p class="m-0 mt-1 text-sm text-ink-mute">Suggested from same-amount activity in your other accounts.</p>{#each topTransferCandidates as candidate, index}<button type="button" class="mt-3 w-full cursor-pointer rounded-md border border-brand bg-brand-wash p-4 text-left" on:click={() => chooseTransfer(candidate)}><span class="flex justify-between gap-4"><span><span class="block text-sm font-semibold">{candidate.candidatePayee ?? 'Transfer deposit'}</span><span class="mt-1 block text-xs text-ink-mute">{candidate.candidateDate} · {candidate.targetTrackedAccountName}</span></span><span class="amount text-sm font-semibold">{candidate.candidateAmount}</span></span><span class="mt-2 block text-xs font-medium text-brand-deep"><span class="kbd">{index + 1}</span> Match this transfer</span></button>{/each}<button type="button" class="mt-4 cursor-pointer border-0 bg-transparent p-0 text-sm font-medium text-brand-deep" on:click={openSearch}>Can’t find it? Search other transactions</button>{#if showSearch}<div class="mt-3 rounded-md border border-hairline-strong bg-paper p-3"><label class="text-xs font-medium text-ink-mute" for="match-search">Search likely matches</label><input bind:this={searchInput} bind:value={transferQuery} id="match-search" class="mt-1" placeholder="Payee, amount, date, or account" />{#each searchedTransferCandidates as candidate}<button type="button" class="mt-2 w-full cursor-pointer border-0 bg-transparent p-1 text-left text-sm hover:text-brand-deep" on:click={() => chooseTransfer(candidate)}>{candidate.candidatePayee ?? 'Transfer'} · {candidate.candidateDate} · {candidate.targetTrackedAccountName} <span class="amount float-right">{candidate.candidateAmount}</span></button>{:else}<p class="m-0 mt-2 text-xs text-ink-mute">No likely transfers match that search.</p>{/each}</div>{/if}</section><button type="button" class="mt-7 cursor-pointer rounded-md border border-hairline-strong bg-panel px-4 py-2 text-sm" on:click={() => treatingAsCategory = true}>Not a transfer</button>
				{:else if (active.kind === 'category' || treatingAsCategory) && active.txn}
					<!-- svelte-ignore a11y_role_has_required_aria_props -->
					<section class="mt-7">{#if manualCandidates.length}<h3 class="m-0 text-sm font-semibold">Possible existing manual entry</h3>{#each manualCandidates as candidate}<button type="button" class="mt-3 w-full cursor-pointer rounded-md border border-hairline-strong p-4 text-left hover:bg-wash" on:click={() => chooseManual(candidate)}><span class="flex justify-between gap-4"><span><span class="block text-sm font-semibold">{candidate.payee}</span><span class="mt-1 block text-xs text-ink-mute">{candidate.date} · {candidate.destinationAccount}</span></span><span class="amount text-sm">{candidate.amount}</span></span><span class="mt-2 block text-xs text-ink-mute">{candidate.matchReason}</span></button>{/each}{/if}<h3 class="m-0 mt-6 text-sm font-semibold">Where should this transaction go?</h3><div class="mt-3 grid max-w-xl gap-2">{#each categoryChoices as account, index}<button type="button" class="cursor-pointer rounded-md border px-4 py-3 text-left text-sm {stagedCategory === account ? 'border-brand bg-brand-wash font-medium' : index === 0 ? 'border-brand bg-brand-wash' : 'border-hairline-strong bg-panel hover:bg-wash'}" on:click={() => void choose({ txnId: active.txn!.txnId, selectionType: 'category', categoryAccount: account })}>{account}<span class="float-right text-xs font-normal text-ink-mute"><span class="kbd">{index + 1}</span>{index === 0 ? ' Suggested' : ''}</span></button>{/each}<div class="mt-2"><label class="sr-only" for="category-search">Choose another category</label><input bind:this={categoryInput} bind:value={categoryQuery} id="category-search" class="w-full" role="combobox" aria-expanded="true" aria-controls="category-options" aria-autocomplete="list" placeholder="Choose another category…" />{#if categoryQuery}<div id="category-options" role="listbox" class="mt-1 max-h-40 overflow-y-auto rounded-md border border-hairline bg-panel">{#each filteredCategories.slice(0, 6) as account}<button type="button" role="option" class="block w-full cursor-pointer border-0 bg-transparent px-3 py-2 text-left text-sm hover:bg-wash" on:click={() => void choose({ txnId: active.txn!.txnId, selectionType: 'category', categoryAccount: account })}>{account}</button>{:else}<p class="m-0 px-3 py-2 text-sm text-ink-mute">No categories match.</p>{/each}</div>{/if}<p class="m-0 mt-1 text-xs text-ink-mute"><span class="kbd">4</span> search · <span class="kbd">Enter</span> select top result · <span class="kbd">m</span> mark as transfer</p></div></div></section>
				{:else}<p class="m-0 mt-7 rounded-md bg-wash p-4 text-sm text-ink-mute">This transaction has no follow-up work. It remains visible here so the review is an accurate view of the import.</p>{/if}{/if}</main>
		</div>{#if error}<p class="m-0 mt-5 rounded-md border border-bad/25 bg-bad/5 px-3 py-2 text-sm text-bad" role="alert">{error}</p>{/if}
	</section>
{/if}
