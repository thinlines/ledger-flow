<script lang="ts">
	import { onMount, tick } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import X from '@lucide/svelte/icons/x';
	import { apiGet, apiPost } from '$lib/api';
	import { onVerb } from '$lib/keyboard/runtime';
	import { showUndoToast } from '$lib/undo-toast';
	import type { TrackedAccount } from '$lib/transactions/types';

	type Suggestion = { account: string; probability: number };
	type SuggestionResult = {
		status: 'ready' | 'insufficient_history' | 'unavailable';
		suggestions: Suggestion[];
	};
	type CreateResult = { created: boolean; txnId: string; eventId?: string };
	type Draft = {
		date: string;
		payee: string;
		amount: string;
		from: string;
		category: string;
		note: string;
	};

	let open = false;
	let dateInput: HTMLInputElement | null = null;
	let memoInput: HTMLInputElement | null = null;
	let transactionForm: HTMLFormElement | null = null;
	let trackedAccounts: TrackedAccount[] = [];
	let categories: string[] = [];
	let optionsLoaded = false;
	let optionsLoading = false;
	let draft = freshDraft();
	let categoryQuery = '';
	let categoryQueryDirty = false;
	let categoryOpen = false;
	let categoryActiveIndex = 0;
	let predictions: Suggestion[] = [];
	let predictionState: SuggestionResult['status'] | 'idle' | 'loading' = 'idle';
	let predictionMs: number | null = null;
	let predictionTimer: ReturnType<typeof setTimeout> | null = null;
	let predictionRequest: AbortController | null = null;
	let status = '';
	let submitting = false;

	$: orderedCategories = rankCategoryOptions(categoryQuery);

	function localDate() {
		const now = new Date();
		return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
	}

	function freshDraft(): Draft {
		return { date: localDate(), payee: '', amount: '', from: '', category: '', note: '' };
	}

	function friendlyDate(value: string) {
		if (!value) return 'Choose a date';
		const date = new Date(`${value}T00:00:00`);
		if (Number.isNaN(date.getTime())) return 'Choose a date';
		return new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
			.format(date);
	}

	async function loadOptions() {
		if (optionsLoaded || optionsLoading) return;
		optionsLoading = true;
		try {
			const [tracked, categoryResult] = await Promise.all([
				apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts'),
				apiGet<{ accounts: string[] }>('/api/accounts')
			]);
			trackedAccounts = tracked.trackedAccounts;
			categories = categoryResult.accounts;
			if (!draft.from) draft.from = trackedAccounts[0]?.ledgerAccount ?? '';
			if (!draft.category) draft.category = categories[0] ?? '';
			optionsLoaded = true;
		} catch (error) {
			status = String(error);
		} finally {
			optionsLoading = false;
		}
	}

	async function show() {
		open = true;
		status = '';
		void loadOptions();
		await tick();
		dateInput?.focus();
	}

	function hide() {
		if (submitting) return;
		open = false;
		categoryOpen = false;
		categoryQuery = '';
		categoryQueryDirty = false;
		status = '';
	}

	function rankCategoryOptions(query: string) {
		const q = query.trim().toLowerCase();
		const predictedRank = new Map(predictions.map((item, index) => [item.account, index]));
		return [...new Set([...predictions.map((item) => item.account), ...categories])]
			.map((account) => {
				const normalized = account.toLowerCase();
				const segments = normalized.split(':');
				const leaf = segments.at(-1) ?? normalized;
				const matchRank = !q ? 0
					: leaf === q || normalized === q ? 0
					: leaf.startsWith(q) ? 1
					: segments.some((segment) => segment.startsWith(q)) ? 2
					: normalized.includes(q) ? 3
					: Number.POSITIVE_INFINITY;
				return { account, matchRank, predictedRank: predictedRank.get(account) ?? Number.POSITIVE_INFINITY };
			})
			.filter((item) => Number.isFinite(item.matchRank))
			.sort((a, b) => {
				const aPredicted = Number.isFinite(a.predictedRank);
				const bPredicted = Number.isFinite(b.predictedRank);
				return Number(bPredicted) - Number(aPredicted)
					|| a.predictedRank - b.predictedRank
					|| a.matchRank - b.matchRank
					|| a.account.localeCompare(b.account);
			})
			.map((item) => item.account);
	}

	function chooseCategory(account: string) {
		draft.category = account;
		categoryQuery = '';
		categoryQueryDirty = false;
		categoryOpen = false;
		categoryActiveIndex = 0;
	}

	function openCategory() {
		categoryOpen = true;
		categoryActiveIndex = Math.max(0, orderedCategories.indexOf(draft.category));
	}

	function updateCategoryQuery(value: string) {
		categoryQuery = value;
		categoryQueryDirty = true;
		categoryOpen = true;
		categoryActiveIndex = 0;
	}

	function handleCategoryKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && (event.ctrlKey || event.shiftKey)) return;
		if (event.key === 'Tab') {
			if (categoryOpen && categoryQueryDirty && orderedCategories[0]) chooseCategory(orderedCategories[0]);
			else categoryOpen = false;
			return;
		}
		if (event.key === 'Escape') {
			event.stopPropagation();
			categoryQuery = '';
			categoryQueryDirty = false;
			categoryOpen = false;
			return;
		}
		if (!categoryOpen && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) openCategory();
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			categoryActiveIndex = Math.min(categoryActiveIndex + 1, orderedCategories.length - 1);
		}
		if (event.key === 'ArrowUp') {
			event.preventDefault();
			categoryActiveIndex = Math.max(categoryActiveIndex - 1, 0);
		}
		if (event.key === 'Enter' && categoryOpen && orderedCategories[categoryActiveIndex]) {
			event.preventDefault();
			chooseCategory(orderedCategories[categoryActiveIndex]);
		}
	}

	function queuePrediction() {
		cancelPrediction();
		predictions = [];
		predictionMs = null;
		if (draft.payee.trim().length < 2) {
			predictionState = 'idle';
			return;
		}
		predictionState = 'loading';
		predictionTimer = setTimeout(() => void loadPrediction(draft.payee.trim()), 180);
	}

	function cancelPrediction() {
		if (predictionTimer) clearTimeout(predictionTimer);
		predictionTimer = null;
		predictionRequest?.abort();
		predictionRequest = null;
	}

	async function loadPrediction(payee: string) {
		predictionRequest = new AbortController();
		const started = performance.now();
		try {
			const result = await apiGet<SuggestionResult>(
				`/api/categories/review-suggestions?payee=${encodeURIComponent(payee)}`,
				{ signal: predictionRequest.signal }
			);
			predictionMs = Math.round(performance.now() - started);
			predictionState = result.status;
			predictions = result.suggestions;
			if (result.suggestions[0] && !categoryQueryDirty) draft.category = result.suggestions[0].account;
		} catch (error) {
			if (error instanceof DOMException && error.name === 'AbortError') return;
			predictionState = 'unavailable';
			predictionMs = Math.round(performance.now() - started);
		}
	}

	async function submit(keepOpen = false) {
		if (submitting) return;
		if (!draft.from || !draft.category) {
			status = 'Choose a source account and category.';
			return;
		}
		submitting = true;
		status = '';
		try {
			const result = await apiPost<CreateResult>('/api/transactions/create', {
				date: draft.date,
				payee: draft.payee.trim(),
				amount: draft.amount,
				sourceAccount: draft.from,
				destinationAccount: draft.category,
				notes: draft.note.trim() || null
			});
			const created = { ...draft };
			cancelPrediction();
			draft = freshDraft();
			draft.from = trackedAccounts[0]?.ledgerAccount ?? '';
			draft.category = categories[0] ?? '';
			categoryQuery = '';
			categoryQueryDirty = false;
			predictions = [];
			predictionState = 'idle';
			if (result.eventId) showUndoToast(result.eventId, `Created ${created.payee} for $${created.amount}`);
			window.dispatchEvent(new CustomEvent('transactions:changed'));
			if (!keepOpen) open = false;
			else await tick();
		} catch (error) {
			status = String(error);
		} finally {
			submitting = false;
		}
	}

	function shortcutSubmit(keepOpen: boolean) {
		if (!transactionForm?.checkValidity()) {
			transactionForm?.reportValidity();
			return;
		}
		void submit(keepOpen);
	}

	function handleWindowKey(event: KeyboardEvent) {
		if (!open) return;
		if (event.altKey && event.code === 'Semicolon') {
			event.preventDefault();
			memoInput?.focus();
			return;
		}
		if (event.shiftKey && event.key === 'Enter') {
			event.preventDefault();
			shortcutSubmit(true);
			return;
		}
		if (event.ctrlKey && event.key === 'Enter') {
			event.preventDefault();
			shortcutSubmit(false);
			return;
		}
		if (!event.altKey || !/^Digit[1-3]$/.test(event.code)) return;
		const suggestion = predictions[Number(event.code.slice(-1)) - 1];
		if (suggestion) {
			event.preventDefault();
			chooseCategory(suggestion.account);
		}
	}

	onMount(() => {
		const offNew = onVerb('transaction.new', () => { void show(); return true; });
		const offDismiss = onVerb('dismiss', () => {
			if (!open || submitting) return false;
			hide();
			return true;
		});
		return () => {
			offNew();
			offDismiss();
			cancelPrediction();
		};
	});
</script>

<svelte:window on:keydown={handleWindowKey} />

{#if open}
	<div class="fixed inset-0 z-40 bg-black/25" aria-hidden="true" on:click={hide}></div>
	<div class="fixed inset-0 z-40 grid place-items-center p-4" role="dialog" aria-modal="true" aria-labelledby="new-transaction-title">
		<form bind:this={transactionForm} class="relative z-50 max-h-[calc(100dvh-1rem)] w-full max-w-3xl overflow-hidden rounded-xl border border-hairline-strong bg-panel shadow-xl" on:submit|preventDefault={() => void submit()}>
			<header class="flex items-start justify-between border-b border-hairline px-5 py-4">
				<div><p class="mb-1 text-xs font-medium tracking-wide text-brand-deep uppercase">Manual entry</p><h2 id="new-transaction-title" class="m-0 font-display text-xl">New transaction</h2></div>
				<button class="rounded-md border-0 bg-transparent p-1 text-ink-mute hover:bg-wash" type="button" aria-label="Close" on:click={hide}><X size={18} /></button>
			</header>

			<div class="grid md:grid-cols-[1fr_17rem]">
				<div class="grid min-h-0 content-start gap-3 border-r border-hairline p-5">
					<div class="grid grid-cols-[11rem_1fr] gap-4"><label class="text-xs font-medium text-ink-mute">Transaction date<input bind:this={dateInput} class="mt-1.5" type="date" bind:value={draft.date} required /></label><div class="self-end pb-2 text-xs text-ink-mute">Posted {friendlyDate(draft.date)}</div></div>
					<div class="grid grid-cols-[1fr_8rem] gap-4"><label class="text-xs font-medium text-ink-mute">Payee<input class="mt-1.5" bind:value={draft.payee} placeholder="Merchant or person" on:input={queuePrediction} required /></label><label class="text-xs font-medium text-ink-mute">Amount<input class="amount mt-1.5 text-right" bind:value={draft.amount} inputmode="decimal" placeholder="0.00" required /></label></div>
					<div class="grid grid-cols-2 gap-4">
						<label class="text-xs font-medium text-ink-mute">From<select class="mt-1.5" bind:value={draft.from} disabled={optionsLoading || trackedAccounts.length === 0} required>{#each trackedAccounts as account}<option value={account.ledgerAccount}>{account.displayName}</option>{/each}</select></label>
						<label class="relative text-xs font-medium text-ink-mute">Category<div class="relative mt-1.5"><input role="combobox" aria-autocomplete="list" aria-expanded={categoryOpen} aria-controls="new-transaction-category-options" aria-activedescendant={categoryOpen && orderedCategories.length ? `new-transaction-category-${categoryActiveIndex}` : undefined} class="!pr-8" value={categoryQuery} placeholder={draft.category || (optionsLoading ? 'Loading categories…' : 'Choose category')} disabled={optionsLoading || categories.length === 0} on:focus={openCategory} on:input={(event) => updateCategoryQuery(event.currentTarget.value)} on:keydown={handleCategoryKeydown} /><Sparkles class="pointer-events-none absolute top-2 right-2.5 text-brand" size={15} /></div>{#if categoryOpen}<div id="new-transaction-category-options" role="listbox" class="absolute top-full right-0 left-0 z-20 mt-1 grid max-h-48 overflow-auto rounded-md border border-hairline bg-panel shadow-lg">{#each orderedCategories as account, index}<button id={`new-transaction-category-${index}`} type="button" role="option" aria-selected={draft.category === account} tabindex="-1" class="flex items-center justify-between border-0 border-b border-hairline px-3 py-2 text-left text-xs last:border-b-0 {categoryActiveIndex === index ? 'bg-brand-wash text-brand-deep' : 'bg-panel hover:bg-wash'}" on:pointerdown|preventDefault={() => chooseCategory(account)}><span>{account}</span>{#if predictions.some((item) => item.account === account)}<span class="flex items-center gap-1 text-[10px] text-brand-deep"><Sparkles size={11} /> predicted</span>{:else if draft.category === account}<Check size={13} />{/if}</button>{:else}<p class="m-0 px-3 py-2 text-xs font-normal text-ink-mute">No categories match “{categoryQuery}”.</p>{/each}</div>{/if}</label>
					</div>

					<section class="h-[9rem] overflow-hidden rounded-lg border border-brand/25 bg-brand-wash"><div class="flex items-center justify-between px-3 py-2"><span class="flex items-center gap-1.5 text-xs font-semibold text-brand-deep"><Sparkles size={13} />Smart suggestions</span>{#if predictionMs !== null}<span class="text-[10px] text-ink-mute">{predictionMs} ms</span>{/if}</div><div class="grid border-t border-brand/15">{#if predictions.length}{#each predictions.slice(0, 3) as suggestion, index}<button type="button" tabindex="-1" class="flex items-center justify-between gap-3 border-0 border-b border-brand/15 px-3 py-2 text-left text-xs last:border-b-0 {draft.category === suggestion.account ? 'bg-panel font-medium text-ink' : 'bg-transparent text-ink-mute hover:bg-panel/70'}" on:click={() => chooseCategory(suggestion.account)}><span class="truncate">{suggestion.account}</span><span class="flex shrink-0 items-center gap-2"><span class="amount text-[10px]">{Math.round(suggestion.probability * 100)}%</span><span class="flex gap-0.5"><span class="kbd">Alt</span><span class="kbd">{index + 1}</span></span></span></button>{/each}{:else}{#each Array(3) as _, index}<div class="flex min-h-9 items-center border-b border-brand/15 px-3 py-2 text-xs text-ink-mute/70 last:border-b-0">{#if index === 0}{predictionState === 'loading' ? 'Finding likely categories…' : 'Enter a payee for suggestions'}{/if}</div>{/each}{/if}</div></section>
					<label class="text-xs font-medium text-ink-mute">Memo<input bind:this={memoInput} class="mt-1.5" bind:value={draft.note} placeholder="Optional note" /></label>
				</div>

				<aside class="bg-wash p-6"><p class="mt-0 mb-4 text-xs font-semibold tracking-wide text-ink-mute uppercase">Journal preview</p><p class="mb-1 font-medium">{draft.date}</p><p class="mt-0 mb-5 text-ink-mute">{draft.payee || 'Payee'}</p><div class="grid grid-cols-1 gap-2 text-xs"><div class="flex justify-between gap-3"><span class="min-w-0 truncate">{draft.category || 'Category'}</span><span class="amount shrink-0">{draft.amount || '0.00'}</span></div><div class="flex justify-between gap-3"><span class="min-w-0 truncate pl-4">{draft.from || 'Source account'}</span><span class="amount shrink-0">−{draft.amount || '0.00'}</span></div></div><div class="mt-5 border-t border-hairline-strong pt-3 text-xs text-ink-mute">Balanced</div></aside>
			</div>

			<footer class="flex items-center justify-between gap-4 border-t border-hairline px-6 py-4"><p class="m-0 truncate text-xs {status ? 'text-bad' : 'text-ink-mute'}" role="status">{status || 'Manual entries can be matched when the bank transaction arrives.'}</p><div class="flex gap-2"><button type="button" class="rounded-md border border-hairline-strong bg-panel px-3 py-1.5 text-sm" disabled={submitting} on:click={hide}>Cancel <span class="ml-1 text-xs text-ink-mute">Esc</span></button><button type="submit" class="rounded-md border border-brand bg-brand px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50" disabled={submitting || optionsLoading}>{submitting ? 'Capturing…' : 'Capture'} <span class="ml-1 text-xs text-white/70">Ctrl ↵</span></button></div></footer>
		</form>
	</div>
{/if}
