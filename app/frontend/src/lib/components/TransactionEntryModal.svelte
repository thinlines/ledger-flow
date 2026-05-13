<script lang="ts">
	import { onMount } from 'svelte';
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

	/* ── State ── */
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

	/* ── Create-account modal (for new categories) ── */
	let showCreateModal = false;
	let newAccountName = '';
	let newAccountType = 'Expense';
	let newAccountDescription = '';
	let createError = '';
	let createLoading = false;

	/* ── Refs ── */
	let payeeEl: HTMLInputElement | null = null;
	let notesEl: HTMLTextAreaElement | null = null;
	let dateEl: HTMLInputElement | null = null;

	/* ── Lifecycle ── */
	function todayISO(): string {
		const d = new Date();
		const yyyy = d.getFullYear();
		const mm = String(d.getMonth() + 1).padStart(2, '0');
		const dd = String(d.getDate()).padStart(2, '0');
		return `${yyyy}-${mm}-${dd}`;
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
		} catch (e) {
			error = 'Failed to load accounts.';
		}
	}

	function resetForm(keepContext = false) {
		if (!keepContext) {
			selectedAccountId = $entryModal.lastAccountId || (trackedAccounts[0]?.id ?? '');
			txnDate = todayISO();
		}
		payee = '';
		amount = '';
		category = '';
		notes = '';
		showNotes = false;
		error = '';
		suggestionSource = null;
		suggestedCategory = '';
	}

	// React to modal open
	$: if ($entryModal.open) {
		void loadData().then(() => {
			resetForm(false);
			// Auto-focus date after render
			setTimeout(() => dateEl?.focus(), 60);
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
		} catch {
			// Silent — suggestion is optional
		}
	}

	function handlePayeeBlur() {
		if (suggestionTimer) clearTimeout(suggestionTimer);
		void fetchSuggestion();
	}

	/* ── Account chip helpers ── */
	function chipKind(account: TrackedAccount): string {
		return account.kind === 'asset' ? 'asset' : account.kind === 'liability' ? 'liability' : 'other';
	}

	/* ── Notes toggle (Ctrl+;) ── */
	function handleModalKeydown(event: KeyboardEvent) {
		// Ctrl+; → toggle notes
		if ((event.ctrlKey || event.metaKey) && event.key === ';') {
			event.preventDefault();
			if (!showNotes) {
				showNotes = true;
				setTimeout(() => notesEl?.focus(), 30);
			} else {
				notesEl?.focus();
			}
			return;
		}

		// Ctrl+Enter → Save & Add Another
		if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			void submit(true);
			return;
		}

		// Ctrl+Shift+Enter → Save & Close
		if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'Enter') {
			event.preventDefault();
			void submit(false);
			return;
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

	function closeCreateModal() {
		createError = '';
		showCreateModal = false;
	}

	async function createAccountAndSelect() {
		if (!newAccountName || !newAccountType) return;
		createLoading = true;
		createError = '';
		try {
			const result = await apiPost<{ added: boolean; warning: string | null }>('/api/accounts', {
				account: newAccountName,
				accountType: newAccountType,
				description: newAccountDescription
			});
			if (result.warning) {
				createError = result.warning;
				return;
			}
			const refreshed = await apiGet<{ accounts: string[] }>('/api/accounts');
			allAccounts = refreshed.accounts;
			category = newAccountName;
			showCreateModal = false;
		} catch (e) {
			createError = String(e);
		} finally {
			createLoading = false;
		}
	}

	/* ── Submit ── */
	async function submit(addAnother: boolean) {
		if (!selectedAccountId || !txnDate || !payee.trim() || !amount.trim() || !category.trim()) {
			error = 'Account, date, payee, amount, and category are required.';
			return;
		}
		error = '';
		submitting = true;
		try {
			const result = await apiPost<{
				created: boolean;
				warning?: string | null;
				eventId?: string | null;
				payee?: string;
				amount?: string;
			}>('/api/transactions/create', {
				trackedAccountId: selectedAccountId,
				date: txnDate,
				payee: payee.trim(),
				amount: amount.trim(),
				destinationAccount: category.trim()
			});

			const savedPayee = payee.trim();
			const savedAmount = amount.trim();
			incrementSession();
			setLastAccount(selectedAccountId);

			if (addAnother) {
				lastSaved = `${savedPayee} $${savedAmount}`;
				// Clear form but keep date + account
				payee = '';
				amount = '';
				notes = '';
				showNotes = false;
				category = '';
				suggestionSource = null;
				suggestedCategory = '';
				error = '';
				setTimeout(() => payeeEl?.focus(), 30);
			} else {
				if (result.eventId) {
					showUndoToast(result.eventId, `Added: ${savedPayee} $${savedAmount}`);
				}
				closeEntryModal();
				lastSaved = '';
			}

			if (result.warning) {
				error = result.warning;
			}
		} catch (e) {
			error = String(e);
		} finally {
			submitting = false;
		}
	}

	function handleOpenChange(open: boolean) {
		if (!open) {
			closeEntryModal();
			lastSaved = '';
		}
	}
</script>

<DialogPrimitive.Root open={$entryModal.open} onOpenChange={handleOpenChange}>
	<DialogPrimitive.Portal>
		<DialogPrimitive.Overlay class="entry-modal-overlay fixed inset-0 z-30 bg-black/30 backdrop-blur-[2px]" />

		<DialogPrimitive.Content
			class="entry-modal fixed top-1/2 left-1/2 z-40 w-full max-w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border border-line shadow-card"
		>
			<DialogPrimitive.Title class="sr-only">Add Transaction</DialogPrimitive.Title>
			<DialogPrimitive.Description class="sr-only">Enter a new manual transaction</DialogPrimitive.Description>

			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div class="entry-modal-inner grid gap-5 p-5" on:keydown={handleModalKeydown}>
				<!-- Header -->
				<div class="flex items-center justify-between gap-4">
					<div>
						<p class="eyebrow m-0">New Transaction</p>
						<h2 class="m-0 font-display text-xl">Quick Entry</h2>
					</div>
					<DialogPrimitive.Close
						class="inline-flex size-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
					>
						<XIcon class="size-4" />
						<span class="sr-only">Close</span>
					</DialogPrimitive.Close>
				</div>

				<!-- Account chips -->
				<div class="field" role="group" aria-label="Account">
					<span class="font-semibold text-muted-foreground text-sm">Account</span>
					<div class="flex flex-wrap gap-2">
						{#each trackedAccounts as account (account.id)}
							<button
								type="button"
								class="account-chip"
								class:selected={selectedAccountId === account.id}
								class:chip-asset={chipKind(account) === 'asset'}
								class:chip-liability={chipKind(account) === 'liability'}
								on:click={() => { selectedAccountId = account.id; }}
							>
								<span class="chip-indicator"></span>
								<span class="truncate">{account.displayName}</span>
								{#if account.last4}
									<span class="text-muted-foreground text-xs">...{account.last4}</span>
								{/if}
							</button>
						{/each}
					</div>
				</div>

				<!-- Date + Payee row -->
				<div class="grid grid-cols-[auto_1fr] gap-3 max-shell:grid-cols-1">
					<div class="field">
						<label for="entry-date">Date</label>
						<input
							id="entry-date"
							type="date"
							bind:this={dateEl}
							bind:value={txnDate}
						/>
					</div>
					<div class="field">
						<label for="entry-payee">Payee</label>
						<input
							id="entry-payee"
							type="text"
							bind:this={payeeEl}
							bind:value={payee}
							placeholder="e.g. Coffee Shop"
							on:input={debounceSuggestion}
							on:blur={handlePayeeBlur}
						/>
					</div>
				</div>

				<!-- Amount + Category row -->
				<div class="grid grid-cols-[auto_1fr] gap-3 max-shell:grid-cols-1">
					<div class="field">
						<label for="entry-amount">Amount</label>
						<input
							id="entry-amount"
							type="text"
							inputmode="decimal"
							bind:value={amount}
							placeholder="0.00"
						/>
					</div>
					<div class="field">
						<label for="entry-category">
							Category
							{#if suggestionSource && category === suggestedCategory}
								<span class="suggestion-badge" class:rule={suggestionSource === 'rule'} class:history={suggestionSource === 'history'}>
									{suggestionSource === 'rule' ? 'Rule match' : 'Similar payees'}
								</span>
							{/if}
						</label>
						<AccountCombobox
							accounts={allAccounts}
							value={category}
							placeholder="e.g. Expenses:Food"
							onChange={(account) => { category = account; }}
							onCreate={(seed) => openCreateModal(seed)}
						/>
					</div>
				</div>

				<!-- Notes (collapsible) -->
				{#if showNotes}
					<div class="field">
						<label for="entry-notes">Notes</label>
						<textarea
							id="entry-notes"
							bind:this={notesEl}
							bind:value={notes}
							rows="2"
							placeholder="Optional notes..."
							class="resize-none"
						></textarea>
					</div>
				{:else}
					<button
						type="button"
						class="notes-toggle flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
						on:click={() => { showNotes = true; setTimeout(() => notesEl?.focus(), 30); }}
					>
						<StickyNoteIcon class="size-3.5" />
						Add notes
						<span class="text-xs opacity-60">Ctrl+;</span>
					</button>
				{/if}

				<!-- Error -->
				{#if error}
					<p class="m-0 text-sm text-destructive">{error}</p>
				{/if}

				<!-- Actions -->
				<div class="flex items-center justify-between gap-3">
					<div class="text-sm text-muted-foreground">
						{#if $entryModal.sessionCount > 0}
							<span class="session-counter">
								<CheckIcon class="size-3.5 inline -mt-0.5" />
								{$entryModal.sessionCount} {$entryModal.sessionCount === 1 ? 'entry' : 'entries'} this session
							</span>
						{/if}
						{#if lastSaved}
							<span class="last-saved">Saved: {lastSaved}</span>
						{/if}
					</div>

					<div class="flex gap-2">
						<button
							type="button"
							class="btn"
							disabled={submitting}
							on:click={() => void submit(false)}
						>
							{submitting ? 'Saving...' : 'Save & Close'}
						</button>
						<button
							type="button"
							class="btn btn-primary"
							disabled={submitting}
							on:click={() => void submit(true)}
						>
							Save & Add Another
						</button>
					</div>
				</div>

				<!-- Keyboard hints -->
				<div class="flex flex-wrap gap-3 text-xs text-muted-foreground opacity-60">
					<span>Ctrl+Enter save & add</span>
					<span>Ctrl+Shift+Enter save & close</span>
					<span>Esc close</span>
				</div>
			</div>
		</DialogPrimitive.Content>
	</DialogPrimitive.Portal>
</DialogPrimitive.Root>

<CreateAccountModal
	bind:open={showCreateModal}
	bind:accountName={newAccountName}
	bind:accountType={newAccountType}
	bind:accountDescription={newAccountDescription}
	error={createError}
	loading={createLoading}
	accountNamePlaceholder="Expenses:Food:Dining"
	onNameInput={() => { newAccountType = inferAccountType(newAccountName); }}
	onClose={closeCreateModal}
	onSubmit={createAccountAndSelect}
/>

<style>
	.entry-modal-inner {
		background:
			linear-gradient(165deg, #f9faf6 0%, #f4f4ea 40%, #f6fbff 100%);
	}

	:global(.entry-modal-overlay) {
		animation: entry-fade-in 0.18s ease-out;
	}

	:global(.entry-modal) {
		animation: entry-zoom-in 0.2s ease-out;
	}

	@keyframes entry-fade-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	@keyframes entry-zoom-in {
		from { opacity: 0; transform: translate(-50%, -50%) scale(0.96); }
		to { opacity: 1; transform: translate(-50%, -50%) scale(1); }
	}

	/* ── Account chips ── */
	.account-chip {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.4rem 0.75rem;
		border-radius: 9999px;
		border: 1px solid rgba(10, 61, 89, 0.12);
		background: white;
		font-size: 0.86rem;
		font-weight: 600;
		color: var(--brand-strong, #0a3d59);
		cursor: pointer;
		transition: all 0.15s;
	}

	.account-chip:hover {
		border-color: rgba(15, 95, 136, 0.25);
		background: rgba(255, 255, 255, 0.95);
	}

	.account-chip.selected {
		color: #fff;
		background: linear-gradient(130deg, #0f5f88, #0c7b59);
		border-color: transparent;
		box-shadow: 0 6px 16px rgba(15, 95, 136, 0.2);
	}

	.chip-indicator {
		width: 6px;
		height: 6px;
		border-radius: 50%;
	}

	.chip-asset .chip-indicator {
		background: #0f5f88;
	}

	.chip-liability .chip-indicator {
		background: #9a5129;
	}

	.account-chip.selected .chip-indicator {
		background: rgba(255, 255, 255, 0.7);
	}

	/* ── Suggestion badge ── */
	.suggestion-badge {
		display: inline-block;
		font-size: 0.72rem;
		font-weight: 500;
		padding: 0.1rem 0.45rem;
		border-radius: 9999px;
		margin-left: 0.4rem;
		vertical-align: middle;
	}

	.suggestion-badge.rule {
		background: rgba(13, 127, 88, 0.1);
		color: #0d7f58;
	}

	.suggestion-badge.history {
		background: rgba(15, 95, 136, 0.1);
		color: #0f5f88;
	}

	/* ── Notes toggle ── */
	.notes-toggle {
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}

	/* ── Session counter ── */
	.session-counter {
		color: #0d7f58;
	}

	.last-saved {
		color: #0d7f58;
		margin-left: 0.5rem;
	}

	/* ── Fields ── */
	.field {
		display: grid;
		gap: 0.35rem;
	}

	.field label {
		font-size: 0.86rem;
		font-weight: 600;
		color: var(--muted-foreground);
	}

	@media (prefers-reduced-motion: reduce) {
		:global(.entry-modal-overlay),
		:global(.entry-modal) {
			animation: none;
		}
	}
</style>
