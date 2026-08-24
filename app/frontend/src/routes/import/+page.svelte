<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Check from '@lucide/svelte/icons/check';
	import FileSpreadsheet from '@lucide/svelte/icons/file-spreadsheet';
	import Upload from '@lucide/svelte/icons/upload';
	import { apiGet, apiPostForm } from '$lib/api';
	import { applyImportStage } from '$lib/stage-client';
	import ImportDashboard from './ImportDashboard.svelte';

	type ImportAccount = { id: string; displayName: string; institutionDisplayName: string; last4?: string | null };
	type AppState = { initialized: boolean; importAccounts: ImportAccount[] };
	type ImportStage = {
		stageId: string; sourceFileSha256: string; targetJournalPath: string; importAccountDisplayName?: string;
		trackedAccountId?: string | null;
		summary: { count: number; newCount: number; duplicateCount: number; unknownCount: number; fenceCount: number };
		preview: Array<{ date: string; payee: string; amount: string; matchStatus: string }>;
		status?: string; result?: { appendedTxnCount: number; skippedDuplicateCount: number };
	};

	let accounts: ImportAccount[] = [];
	let selectedAccount = '';
	let file: File | null = null;
	let step = 1;
	let stage: ImportStage | null = null;
	let loading = true;
	let busy = false;
	let error = '';
	let completed = false;
	let mounted = false;
	let wasNew = false;
	let accountsLoaded = false;
	const year = String(new Date().getFullYear());
	$: isNew = $page.url.searchParams.get('new') === '1';
	$: if (mounted && isNew && !wasNew) {
		wasNew = true;
		step = 1;
		file = null;
		stage = null;
		completed = false;
		error = '';
		if (!accountsLoaded) void loadAccounts();
	}
	$: if (!isNew) wasNew = false;

	async function focusSelectedAccount() {
		await tick();
		document.getElementById(`import-account-${selectedAccount}`)?.focus();
	}

	function accountListKeydown(event: KeyboardEvent, index: number) {
		if (event.key === 'Enter') {
			event.preventDefault();
			step = 2;
			return;
		}
		if (event.key !== 'j' && event.key !== 'k') return;
		event.preventDefault();
		const nextIndex = event.key === 'j'
			? Math.min(index + 1, accounts.length - 1)
			: Math.max(index - 1, 0);
		selectedAccount = accounts[nextIndex].id;
		void focusSelectedAccount();
	}

	async function preview() {
		if (!file || !selectedAccount) return;
		busy = true;
		error = '';
		try {
			const form = new FormData();
			form.append('file', file);
			form.append('year', year);
			form.append('importAccountId', selectedAccount);
			form.append('preview', 'true');
			stage = await apiPostForm<ImportStage>('/api/import/upload', form);
			step = 3;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally { busy = false; }
	}

	async function apply() {
		if (!stage) return;
		busy = true;
		error = '';
		try {
			stage = await applyImportStage<ImportStage>(stage.stageId);
			completed = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally { busy = false; }
	}

	async function loadAccounts() {
		accountsLoaded = true;
		loading = true;
		try {
			const state = await apiGet<AppState>('/api/app/state');
			accounts = state.importAccounts;
			selectedAccount = accounts[0]?.id ?? '';
			void focusSelectedAccount();
		} catch (e) { error = e instanceof Error ? e.message : String(e); }
		finally { loading = false; }
	}

	onMount(() => { mounted = true; });
</script>

{#if !isNew}
	<ImportDashboard />
{:else if loading}
	<p class="px-6 py-10 text-sm text-ink-mute">Loading import accounts…</p>
{:else if accounts.length === 0}
	<section class="px-6 py-10 max-lg:px-4"><h1 class="font-display m-0 text-xl font-semibold">No import accounts yet</h1><p class="m-0 mt-2 max-w-prose text-sm leading-relaxed text-ink-mute">Set up an account before importing a statement.</p></section>
{:else if completed && stage}
	<section class="mx-auto max-w-130 px-8 py-14 max-lg:px-5"><div class="border border-hairline-strong bg-panel px-7 py-9 text-center"><span class="mx-auto grid size-12 place-items-center rounded-full bg-brand-wash"><Check class="size-6 text-brand-deep" /></span><p class="m-0 mt-5 text-xs font-medium tracking-widest text-brand-deep uppercase">Import complete</p><h1 class="font-display m-0 mt-2 text-3xl font-semibold tracking-tight">{stage.result?.appendedTxnCount ?? stage.summary.newCount} transactions added.</h1><p class="m-0 mt-3 text-sm leading-relaxed text-ink-mute">{stage.result?.skippedDuplicateCount ?? stage.summary.duplicateCount} duplicates were left alone. Review is optional follow-up work.</p><div class="mt-8 grid gap-3 text-left sm:grid-cols-2"><button type="button" class="cursor-pointer border border-brand bg-brand-wash p-5 text-left" on:click={() => void goto(`/review?${new URLSearchParams({ journal: stage!.targetJournalPath, source: stage!.sourceFileSha256 })}`)}><span class="block text-sm font-semibold">Review items needing attention</span><span class="mt-1 block text-sm text-ink-mute">Categorize or match imported activity.</span></button><button type="button" class="cursor-pointer border border-hairline-strong bg-panel p-5 text-left hover:bg-wash" on:click={() => void goto(stage!.trackedAccountId ? `/transactions?accounts=${encodeURIComponent(stage!.trackedAccountId)}` : '/transactions')}><span class="block text-sm font-semibold">View imported transactions</span><span class="mt-1 block text-sm text-ink-mute">Open this account’s register now.</span></button></div></div></section>
{:else}
	<section class="mx-auto max-w-150 px-8 py-12 max-lg:px-5">
		<header><button type="button" class="mb-5 inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-xs text-ink-mute hover:text-ink" on:click={() => void goto('/import')}><ArrowLeft class="size-3.5" /> Import history</button><p class="m-0 text-xs font-medium tracking-widest text-brand-deep uppercase">New import</p><h1 class="font-display m-0 mt-2 text-3xl font-semibold tracking-tight">{step === 1 ? 'Which account is this statement for?' : step === 2 ? 'Add the statement from your bank.' : 'Here’s what will happen.'}</h1></header>
		<div class="mt-7 flex items-center gap-2" aria-label="Import progress">{#each ['Account', 'Statement', 'Review'] as label, index}<div class="flex items-center gap-2 {index < 2 ? 'flex-1' : ''}"><span class="grid size-6 shrink-0 place-items-center rounded-full text-xs font-medium {index + 1 <= step ? 'bg-brand text-panel' : 'border border-hairline-strong text-ink-mute'}">{index + 1 < step ? '✓' : index + 1}</span><span class="text-xs {index + 1 === step ? 'font-medium text-ink' : 'text-ink-mute'}">{label}</span>{#if index < 2}<span class="h-px flex-1 bg-hairline-strong"></span>{/if}</div>{/each}</div>
		<div class="mt-8 rounded-lg border border-hairline-strong bg-panel p-7">
			{#if step === 1}
				<p class="m-0 text-sm leading-relaxed text-ink-mute">This tells us how to read the file and prevents a statement from landing in the wrong account. You can change it before importing.</p>
				<div class="mt-7 grid gap-2">{#each accounts as account, index}<label class="flex cursor-pointer items-center gap-3 rounded-md border px-4 py-4 {selectedAccount === account.id ? 'border-brand bg-brand-wash' : 'border-hairline hover:bg-wash'}"><input id={`import-account-${account.id}`} type="radio" name="account" value={account.id} bind:group={selectedAccount} on:keydown={(event) => accountListKeydown(event, index)} /><span><span class="block text-sm font-medium">{account.displayName}</span><span class="block text-xs text-ink-mute">{account.institutionDisplayName}{account.last4 ? ` •••• ${account.last4}` : ''}</span></span></label>{/each}</div>
			{:else if step === 2}
				<div class="flex items-center gap-3 rounded-md bg-wash px-3 py-2.5 text-sm"><Check class="size-4 text-brand-deep" /><span><strong>{accounts.find((a) => a.id === selectedAccount)?.displayName}</strong><span class="text-ink-mute"> · statement destination</span></span><button type="button" class="ml-auto cursor-pointer border-0 bg-transparent p-0 text-xs font-medium text-brand-deep" on:click={() => (step = 1)}>Change</button></div>
				<p class="m-0 mt-6 text-sm leading-relaxed text-ink-mute">Export a CSV from your bank. We’ll scan it first; nothing is added to the ledger until you explicitly confirm the import.</p>
				<label class="mt-5 grid min-h-48 cursor-pointer place-items-center rounded-md border border-dashed p-5 text-center {file ? 'border-brand bg-brand-wash' : 'border-hairline-strong bg-paper hover:border-brand hover:bg-brand-wash'}"><input class="sr-only" type="file" accept=".csv,text/csv" on:change={(e) => (file = e.currentTarget.files?.[0] ?? null)} />{#if file}<span><Check class="mx-auto size-5 text-brand-deep" /><span class="mt-2 block text-sm font-medium">{file.name}</span><span class="mt-1 block text-xs text-ink-mute">{Math.ceil(file.size / 1024)} KB · choose another file</span></span>{:else}<span><Upload class="mx-auto size-5 text-brand-deep" /><span class="mt-2 block text-sm font-medium">Drop a CSV here, or choose a file</span><span class="mt-1 block text-xs text-ink-mute">CSV only · Nothing is imported yet</span></span>{/if}</label>
			{:else if stage}
				<div class="rounded-md border border-brand/25 bg-brand-wash px-4 py-3 text-sm"><Check class="mr-2 inline size-4 text-brand-deep" /><strong>{stage.summary.newCount} transactions are ready to import.</strong><span class="block mt-1 text-ink-mute">{stage.summary.duplicateCount} duplicates will be skipped. {stage.summary.unknownCount} items may need review after import.</span></div>
				<div class="mt-6 grid grid-cols-3 gap-px overflow-hidden rounded-md border border-hairline bg-hairline text-center"><div class="bg-panel p-3"><span class="block text-lg font-semibold">{stage.summary.count}</span><span class="text-xs text-ink-mute">found</span></div><div class="bg-panel p-3"><span class="block text-lg font-semibold text-brand-deep">{stage.summary.newCount}</span><span class="text-xs text-ink-mute">to add</span></div><div class="bg-panel p-3"><span class="block text-lg font-semibold">{stage.summary.duplicateCount}</span><span class="text-xs text-ink-mute">duplicates</span></div></div>
				<ol class="m-0 mt-6 list-none overflow-hidden rounded-md border border-hairline p-0">{#each stage.preview.slice(0, 4) as row}<li class="flex items-center justify-between gap-4 border-b border-hairline px-4 py-3 last:border-0 text-sm"><span class="min-w-0"><span class="block truncate font-medium">{row.payee}</span><span class="block text-xs text-ink-mute">{row.date} · {row.matchStatus}</span></span><span class="amount shrink-0 text-sm">{row.amount}</span></li>{/each}</ol>
			{/if}
			{#if error}<p class="m-0 mt-5 rounded-md border border-bad/25 bg-bad/5 px-3 py-2 text-sm text-bad" role="alert">{error}</p>{/if}
			<div class="mt-7 flex items-center justify-between border-t border-hairline pt-5">{#if step > 1}<button type="button" class="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-sm text-ink-mute hover:text-ink" disabled={busy} on:click={() => (step -= 1)}><ArrowLeft class="size-4" /> Back</button>{:else}<span class="text-xs text-ink-mute">You can change any earlier choice.</span>{/if}{#if step === 1}<button type="button" class="inline-flex cursor-pointer items-center gap-2 rounded-md border-0 bg-brand px-4 py-2 text-sm font-medium text-panel" on:click={() => (step = 2)}>Continue <ArrowRight class="size-4" /></button>{:else if step === 2}<button type="button" class="inline-flex cursor-pointer items-center gap-2 rounded-md border-0 bg-brand px-4 py-2 text-sm font-medium text-panel disabled:opacity-40" disabled={!file || busy} on:click={preview}>{busy ? 'Scanning…' : 'Preview import'} <FileSpreadsheet class="size-4" /></button>{:else}<button type="button" class="cursor-pointer rounded-md border-0 bg-brand px-4 py-2 text-sm font-medium text-panel disabled:opacity-40" disabled={busy} on:click={apply}>{busy ? 'Importing…' : `Import ${stage?.summary.newCount ?? 0} transactions`}</button>{/if}</div>
		</div>
	</section>
{/if}
