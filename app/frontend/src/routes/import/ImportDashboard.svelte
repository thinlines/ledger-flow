<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Upload from '@lucide/svelte/icons/upload';
	import { apiGet } from '$lib/api';
	import { showImportUndoToast } from '$lib/undo-toast';

	type HistoryEntry = {
		id: string;
		status: 'applied' | 'undone';
		appliedAt?: string;
		importAccountDisplayName?: string;
		importSourceDisplayName?: string;
		csvFileName?: string;
		targetJournalPath?: string;
		sourceFileSha256?: string;
		canUndo?: boolean;
		undoBlockedReason?: string | null;
		currentUnknownCount?: number | null;
		summary?: { newCount?: number; unknownCount?: number };
	};

	let history: HistoryEntry[] = [];
	let loading = true;
	let error = '';
	$: activeHistory = history.filter((item) => item.status !== 'undone');
	$: statusUnavailable = activeHistory.some((item) => item.currentUnknownCount === null || item.currentUnknownCount === undefined);
	$: categorized = activeHistory.reduce((sum, item) => sum + Math.max(0, (item.summary?.newCount ?? 0) - (item.currentUnknownCount ?? 0)), 0);
	$: imported = activeHistory.reduce((sum, item) => sum + (item.summary?.newCount ?? 0), 0);
	$: needsReview = activeHistory.reduce((sum, item) => sum + (item.currentUnknownCount ?? 0), 0);

	async function loadHistory() {
		try {
			error = '';
			const response = await apiGet<{ history: HistoryEntry[] }>('/api/import/history');
			history = response.history;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function dateLabel(value?: string) {
		if (!value) return 'Unknown date';
		return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));
	}

	function reviewHref(item: HistoryEntry) {
		return `/review?${new URLSearchParams({ journal: item.targetJournalPath ?? '', source: item.sourceFileSha256 ?? '' })}`;
	}

	function offerUndo(item: HistoryEntry) {
		showImportUndoToast(item.id, `Undo import from ${item.importAccountDisplayName ?? item.csvFileName ?? 'statement'}?`, loadHistory);
	}

	onMount(() => { void loadHistory(); });
</script>

<section class="mx-auto max-w-230 px-8 py-12 max-lg:px-5">
	<header class="flex items-end justify-between gap-6 max-sm:items-start">
		<div>
			<p class="m-0 text-xs font-medium tracking-widest text-brand-deep uppercase">Import</p>
			<h1 class="font-display m-0 mt-2 text-3xl font-semibold tracking-tight">Statements, in one place.</h1>
			<p class="m-0 mt-2 text-sm text-ink-mute">Bring in new activity or pick up an earlier review.</p>
		</div>
		<button type="button" class="inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-md border-0 bg-brand px-4 py-2.5 text-sm font-medium text-panel" on:click={() => void goto('/import?new=1')}>
			<Upload class="size-4" /> Import a statement
		</button>
	</header>

	{#if error}
		<div class="mt-7 rounded-md border border-bad/25 bg-bad/5 px-4 py-3 text-sm text-bad" role="alert">
			Couldn’t load import history. {error}
			<button type="button" class="ml-2 cursor-pointer border-0 bg-transparent p-0 font-medium underline" on:click={() => void loadHistory()}>Try again</button>
		</div>
	{/if}

	<div class="mt-9 grid gap-4 sm:grid-cols-3">
		<div class="border-t-2 border-brand bg-panel px-5 py-5"><span class="amount block text-2xl font-semibold">{imported}</span><span class="mt-1 block text-xs text-ink-mute">Transactions imported</span></div>
		<div class="border-t-2 border-hairline-strong bg-panel px-5 py-5"><span class="amount block text-2xl font-semibold">{statusUnavailable ? '—' : categorized}</span><span class="mt-1 block text-xs text-ink-mute">Currently categorized</span></div>
		<div class="border-t-2 {needsReview ? 'border-warn' : 'border-hairline-strong'} bg-panel px-5 py-5"><span class="amount block text-2xl font-semibold">{statusUnavailable ? '—' : needsReview}</span><span class="mt-1 block text-xs text-ink-mute">{statusUnavailable ? 'Review status unavailable' : 'Need review now'}</span></div>
	</div>

	<div class="mt-10 flex items-center justify-between">
		<h2 class="font-display m-0 text-lg font-semibold">Recent imports</h2>
		{#if !loading}<span class="text-xs text-ink-mute">{history.length} total</span>{/if}
	</div>

	{#if loading}
		<p class="mt-5 text-sm text-ink-mute">Loading import history…</p>
	{:else if history.length === 0 && !error}
		<div class="mt-3 rounded-md border border-hairline-strong bg-panel px-6 py-10 text-center">
		<p class="m-0 text-sm font-medium">No statements imported yet.</p>
		<p class="m-0 mt-1 text-sm text-ink-mute">Your completed imports and review queues will appear here.</p>
		</div>
	{:else if history.length > 0}
		<div class="mt-3 overflow-hidden rounded-md border border-hairline-strong bg-panel">
			{#each history as item}
				{@const unknowns = item.currentUnknownCount}
				<div class="grid grid-cols-[minmax(0,1fr)_8rem_9rem] items-center gap-5 border-b border-hairline px-5 py-4 last:border-0 max-sm:grid-cols-1 max-sm:gap-2">
					<div class="min-w-0"><span class="block truncate text-sm font-medium">{item.importAccountDisplayName ?? item.csvFileName ?? 'Statement import'}</span><span class="mt-1 block truncate text-xs text-ink-mute">{item.importSourceDisplayName ?? 'Imported statement'} · {dateLabel(item.appliedAt)} · {item.summary?.newCount ?? 0} added</span></div>
					<div>
						{#if item.status === 'undone'}<span class="text-xs text-ink-mute">Undone</span>
						{:else if unknowns === null || unknowns === undefined}<span class="text-xs text-ink-mute">Status unavailable</span>
						{:else if unknowns > 0}<span class="inline-flex items-center gap-1.5 text-xs font-medium text-warn"><CircleAlert class="size-3.5" />{unknowns} to review</span>
						{:else}<span class="text-xs font-medium text-brand-deep">Complete</span>{/if}
					</div>
					<div class="flex items-center justify-end gap-3 max-sm:justify-start">
						{#if item.status !== 'undone' && (item.summary?.newCount ?? 0) > 0 && item.targetJournalPath}<a class="text-xs font-medium text-brand-deep no-underline hover:underline" href={reviewHref(item)}>Open review</a>{/if}
						{#if item.status !== 'undone' && item.canUndo}<button type="button" class="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-xs text-ink-mute hover:text-bad" on:click={() => offerUndo(item)}><RotateCcw class="size-3" /> Undo</button>{/if}
						{#if item.status !== 'undone' && !item.canUndo}<span class="text-xs text-ink-mute" title={item.undoBlockedReason ?? 'This import cannot be undone'}>Undo unavailable</span>{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</section>
