<script lang="ts">
	import { Dialog as DialogPrimitive } from 'bits-ui';
	import XIcon from '@lucide/svelte/icons/x';
	import CheckIcon from '@lucide/svelte/icons/check';
	import StickyNoteIcon from '@lucide/svelte/icons/sticky-note';
	import { apiGet, apiPost } from '$lib/api';
	import { showUndoToast } from '$lib/undo-toast';
	import AccountCombobox from '$lib/components/AccountCombobox.svelte';
	import CreateAccountModal from '$lib/components/CreateAccountModal.svelte';
	import { entryModal, closeEntryModal, incrementSession, setLastAccount } from '$lib/stores/entry-modal';
	import type { TrackedAccount } from '$lib/transactions/types';

	let trackedAccounts: TrackedAccount[] = [];
	let allAccounts: string[] = [];
	let dataLoaded = false;
	let lastFetchTime = 0;

	let selectedAccountId = '';
	let txnDate = '';
	let payee = '';
	let amount = '';
	let category = '';
	let notes = '';
	let showNotes = false;

	let submitting = false;
	let error = '';
	let lastSaved = '';
	let suggestionSource: string | null = null;
	let suggestedCategory = '';

	let showCreateModal = false;
	let newAccountName = '';
	let newAccountType = 'Expense';
	let newAccountDescription = '';
	let createError = '';
	let createLoading = false;

	let payeeEl: HTMLInputElement | null = null;
	let notesEl: HTMLTextAreaElement | null = null;

	function todayISO(): string {
		const d = new Date();
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	}

	async function loadData() {
		const now = Date.now();
		if (dataLoaded && now - lastFetchTime < 60_000) return;
		try {
			const [ta, al] = await Promise.all([
				apiGet<{ trackedAccounts: TrackedAccount[] }>('/api/tracked-accounts'),
				apiGet<{ accounts: string[] }>('/api/accounts').catch(() => ({ accounts: [] as string[] }))
			]);
			trackedAccounts = ta.trackedAccounts;
			allAccounts = al.accounts;
			dataLoaded = true;
			lastFetchTime = now;
		} catch {
			error = 'Failed to load accounts.';
		}
	}

	function resetForm() {
		selectedAccountId = $entryModal.lastAccountId || (trackedAccounts[0]?.id ?? '');
		txnDate = todayISO();
		payee = '';
		amount = '';
		category = '';
		notes = '';
		showNotes = false;
		error = '';
		lastSaved = '';
		suggestionSource = null;
		suggestedCategory = '';
	}

	$: if ($entryModal.open) {
		void loadData().then(() => {
			resetForm();
			setTimeout(() => payeeEl?.focus(), 60);
		});
	}

	/* ── Category suggestion ── */
	let suggestionTimer: ReturnType<typeof setTimeout> | null = null;

	function debounceSuggestion() {
		if (suggestionTimer) clearTimeout(suggestionTimer);
		if (!payee.trim()) return;
		suggestionTimer = setTimeout(() => void fetchSuggestion(), 300);
	}

	async function fetchSuggestion() {
		if (!payee.trim()) return;
		try {
			const result = await apiGet<{
				suggestion: string | null;
				confidence: number;
				source: string | null;
				alternatives: { account: string; frequency: number }[];
			}>(`/api/categories/suggest?payee=${encodeURIComponent(payee.trim())}`);
			if (result.suggestion && result.confidence >= 0.5 && !category) {
				category = result.suggestion;
				suggestedCategory = result.suggestion;
				suggestionSource = result.source;
			}
		} catch { /* optional */ }
	}

	function handlePayeeBlur() {
		if (suggestionTimer) clearTimeout(suggestionTimer);
		void fetchSuggestion();
	}

	/* ── Keyboard ── */
	function handleKeydown(event: KeyboardEvent) {
		if ((event.ctrlKey || event.metaKey) && event.key === ';') {
			event.preventDefault();
			showNotes = true;
			setTimeout(() => notesEl?.focus(), 30);
		} else if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'Enter') {
			event.preventDefault();
			void submit(false);
		} else if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
			event.preventDefault();
			void submit(true);
		}
	}

	/* ── Create-account modal ── */
	function inferAccountType(name: string): string {
		const prefix = name.split(':', 1)[0]?.trim().toLowerCase() || '';
		if (prefix === 'assets') return 'Asset';
		if (prefix === 'liabilities' || prefix === 'liability') return 'Liability';
		if (prefix === 'expenses' || prefix === 'expense') return 'Expense';
		if (prefix === 'income' || prefix === 'revenue') return 'Revenue';
		if (prefix === 'equity') return 'Equity';
		return 'Expense';
	}

	function openCreateModal(seed: string) {
		newAccountName = seed;
		newAccountType = inferAccountType(seed);
		newAccountDescription = '';
		createError = '';
		showCreateModal = true;
	}

	async function createAccountAndSelect() {
		if (!newAccountName || !newAccountType) return;
		createLoading = true;
		createError = '';
		try {
			const result = await apiPost<{ added: boolean; warning: string | null }>('/api/accounts', {
				account: newAccountName, accountType: newAccountType, description: newAccountDescription
			});
			if (result.warning) { createError = result.warning; return; }
			const refreshed = await apiGet<{ accounts: string[] }>('/api/accounts');
			allAccounts = refreshed.accounts;
			category = newAccountName;
			showCreateModal = false;
		} catch (e) { createError = String(e); }
		finally { createLoading = false; }
	}

	/* ── Submit ── */
	async function submit(addAnother: boolean) {
		if (!selectedAccountId || !txnDate || !payee.trim() || !amount.trim() || !category.trim()) {
			error = 'All fields are required.';
			return;
		}
		error = '';
		submitting = true;
		try {
			const result = await apiPost<{
				created: boolean; warning?: string | null; eventId?: string | null;
			}>('/api/transactions/create', {
				trackedAccountId: selectedAccountId, date: txnDate,
				payee: payee.trim(), amount: amount.trim(), destinationAccount: category.trim()
			});

			const savedPayee = payee.trim();
			const savedAmount = amount.trim();
			incrementSession();
			setLastAccount(selectedAccountId);

			if (addAnother) {
				lastSaved = `${savedPayee} $${savedAmount}`;
				payee = ''; amount = ''; notes = ''; showNotes = false;
				category = ''; suggestionSource = null; suggestedCategory = ''; error = '';
				setTimeout(() => payeeEl?.focus(), 30);
			} else {
				if (result.eventId) showUndoToast(result.eventId, `Added: ${savedPayee} $${savedAmount}`);
				closeEntryModal();
				lastSaved = '';
			}
			if (result.warning) error = result.warning;
		} catch (e) { error = String(e); }
		finally { submitting = false; }
	}

	function handleOpenChange(open: boolean) {
		if (!open) { closeEntryModal(); lastSaved = ''; }
	}
</script>

<DialogPrimitive.Root open={$entryModal.open} onOpenChange={handleOpenChange}>
	<DialogPrimitive.Portal>
		<DialogPrimitive.Overlay class="entry-overlay fixed inset-0 z-30 bg-black/25" />

		<DialogPrimitive.Content
			class="entry-dialog fixed top-1/2 left-1/2 z-40 w-full max-w-[min(26rem,calc(100vw-1.5rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto max-h-[calc(100vh-2rem)] rounded-2xl border border-line shadow-card"
		>
			<DialogPrimitive.Title class="sr-only">Add Transaction</DialogPrimitive.Title>
			<DialogPrimitive.Description class="sr-only">Enter a new manual transaction</DialogPrimitive.Description>

			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div class="e-surface" on:keydown={handleKeydown}>

				<!-- Header -->
				<div class="e-head">
					<h2 class="m-0 font-display text-lg">New Transaction</h2>
					<DialogPrimitive.Close class="e-x">
						<XIcon class="size-4" /><span class="sr-only">Close</span>
					</DialogPrimitive.Close>
				</div>

				{#if lastSaved}
					<p class="e-flash"><CheckIcon class="size-3.5" /> {lastSaved}</p>
				{/if}

				<!-- Fields -->
				<div class="e-fields">
					<div class="field">
						<label for="e-acct">Account</label>
						<select id="e-acct" bind:value={selectedAccountId}>
							{#each trackedAccounts as a (a.id)}
								<option value={a.id}>{a.displayName}{a.last4 ? ` (...${a.last4})` : ''}</option>
							{/each}
						</select>
					</div>

					<div class="field">
						<label for="e-date">Date</label>
						<input id="e-date" type="date" bind:value={txnDate} />
					</div>

					<div class="field">
						<label for="e-payee">Payee</label>
						<input id="e-payee" type="text" bind:this={payeeEl} bind:value={payee}
							placeholder="e.g. Coffee Shop"
							on:input={debounceSuggestion} on:blur={handlePayeeBlur} />
					</div>

					<div class="field">
						<label for="e-amt">Amount</label>
						<input id="e-amt" type="text" inputmode="decimal" bind:value={amount} placeholder="0.00" />
					</div>

					<div class="field">
						<label for="e-cat">
							Category
							{#if suggestionSource && category === suggestedCategory}
								<span class="e-badge" class:rule={suggestionSource === 'rule'} class:hist={suggestionSource === 'history'}>
									{suggestionSource === 'rule' ? 'rule' : 'similar'}
								</span>
							{/if}
						</label>
						<AccountCombobox
							accounts={allAccounts} value={category} placeholder="e.g. Expenses:Food"
							onChange={(v) => { category = v; }} onCreate={(s) => openCreateModal(s)} />
					</div>

					{#if showNotes}
						<div class="field">
							<label for="e-notes">Notes</label>
							<textarea id="e-notes" bind:this={notesEl} bind:value={notes}
								rows="2" placeholder="Optional" class="resize-none"></textarea>
						</div>
					{:else}
						<button type="button" class="e-notes-btn" on:click={() => { showNotes = true; setTimeout(() => notesEl?.focus(), 30); }}>
							<StickyNoteIcon class="size-3.5" /> Notes <kbd>Ctrl+;</kbd>
						</button>
					{/if}
				</div>

				{#if error}
					<p class="e-err">{error}</p>
				{/if}

				<!-- Footer -->
				<div class="e-foot">
					<div class="e-meta">
						{#if $entryModal.sessionCount > 0}
							<span class="e-count">{$entryModal.sessionCount} added</span>
						{/if}
						<span class="e-keys"><kbd>⌃↵</kbd> next · <kbd>⌃⇧↵</kbd> close</span>
					</div>
					<div class="e-btns">
						<button type="button" class="btn" disabled={submitting} on:click={() => void submit(false)}>
							{submitting ? 'Saving…' : 'Close'}
						</button>
						<button type="button" class="btn btn-primary" disabled={submitting} on:click={() => void submit(true)}>
							Save & Next
						</button>
					</div>
				</div>
			</div>
		</DialogPrimitive.Content>
	</DialogPrimitive.Portal>
</DialogPrimitive.Root>

<CreateAccountModal
	bind:open={showCreateModal} bind:accountName={newAccountName}
	bind:accountType={newAccountType} bind:accountDescription={newAccountDescription}
	error={createError} loading={createLoading} accountNamePlaceholder="Expenses:Food:Dining"
	onNameInput={() => { newAccountType = inferAccountType(newAccountName); }}
	onClose={() => { createError = ''; showCreateModal = false; }}
	onSubmit={createAccountAndSelect} />

<style>
	:global(.entry-overlay) { animation: e-fade 0.15s ease-out; }
	:global(.entry-dialog) { animation: e-in 0.18s ease-out; }
	@keyframes e-fade { from { opacity: 0 } }
	@keyframes e-in {
		from { opacity: 0; transform: translate(-50%, -50%) scale(0.97) }
	}
	@media (prefers-reduced-motion: reduce) {
		:global(.entry-overlay), :global(.entry-dialog) { animation: none }
	}

	.e-surface {
		background: linear-gradient(168deg, #fafaf5, #f4f4ea 55%, #f5f9fc);
		padding: 1.25rem 1.5rem 1rem;
	}

	.e-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 0.85rem;
	}
	:global(.e-x) {
		display: inline-flex; align-items: center; justify-content: center;
		width: 1.75rem; height: 1.75rem; border-radius: 0.375rem;
		border: none; background: none; color: var(--muted-foreground); cursor: pointer;
	}
	:global(.e-x:hover) { background: var(--accent); color: var(--foreground) }

	.e-flash {
		display: flex; align-items: center; gap: 0.3rem;
		margin: 0 0 0.6rem; font-size: 0.8rem; font-weight: 500; color: var(--ok);
	}

	.e-fields {
		display: grid;
		gap: 0.65rem;
	}

	.e-badge {
		font-size: 0.65rem; font-weight: 500;
		padding: 0.05rem 0.3rem; border-radius: 9999px;
		margin-left: 0.3rem; vertical-align: middle;
	}
	.e-badge.rule { background: rgba(13,127,88,0.1); color: var(--ok) }
	.e-badge.hist { background: rgba(15,95,136,0.1); color: var(--brand) }

	.e-notes-btn {
		display: flex; align-items: center; gap: 0.35rem;
		font-size: 0.82rem; color: var(--muted-foreground);
		background: none; border: none; padding: 0; cursor: pointer;
	}
	.e-notes-btn:hover { color: var(--foreground) }
	.e-notes-btn kbd { font-size: 0.68rem; opacity: 0.5; font-family: inherit }

	.e-err { margin: 0.5rem 0 0; font-size: 0.8rem; color: var(--destructive) }

	.e-foot {
		display: flex; align-items: flex-end; justify-content: space-between;
		gap: 0.75rem; margin-top: 0.85rem; padding-top: 0.7rem;
		border-top: 1px solid var(--line);
	}
	.e-meta { display: grid; gap: 0.1rem; font-size: 0.7rem; color: var(--muted-foreground) }
	.e-count { font-weight: 600; color: var(--ok) }
	.e-keys kbd { font-size: 0.65rem; font-family: inherit; opacity: 0.55 }
	.e-btns { display: flex; gap: 0.35rem; flex-shrink: 0 }

	@media (max-width: 480px) {
		.e-surface { padding: 1rem 1.1rem 0.85rem }
		.e-foot { flex-direction: column; align-items: stretch; gap: 0.5rem }
		.e-btns { justify-content: stretch }
		.e-btns .btn { flex: 1 }
		.e-keys { display: none }
	}
</style>
