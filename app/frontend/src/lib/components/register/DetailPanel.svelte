<script lang="ts">
	import type { TrackedAccount, TransactionRow } from '$lib/transactions/types';
	import { formatCurrency, shortDate, type AccountKind } from '$lib/format';
	import { canDeleteRow, canRecategorizeRow, canUnmatchRow, CLEARING_TOOLTIPS } from '$lib/transactions/helpers';
	import XIcon from '@lucide/svelte/icons/x';

	export let row: TransactionRow;
	export let baseCurrency: string;
	export let accountKind: AccountKind | null;
	/** Category accounts offered for recategorization. */
	export let categoryAccounts: string[];
	export let trackedAccounts: TrackedAccount[];
	export let busy: boolean;
	export let error: string;
	export let onClose: () => void;
	export let onToggleClearing: (row: TransactionRow) => void;
	export let onRecategorize: (row: TransactionRow, category: string) => void;
	export let onReassignAccount: (row: TransactionRow, ledgerName: string) => void;
	export let onUnmatch: (row: TransactionRow) => void;
	export let onDelete: (row: TransactionRow) => void;

	let recategorizeDraft = '';
	let reassignDraft = '';
	let confirming: 'delete' | 'unmatch' | null = null;
	let lastRowId: string | null = null;

	// Reset in-panel drafts when the panel moves to another row (j/k while open).
	$: if (row.id !== lastRowId) {
		lastRowId = row.id;
		recategorizeDraft = row.categories[0]?.account ?? '';
		reassignDraft = '';
		confirming = null;
	}

	$: amountText = formatCurrency(row.amount, baseCurrency, {
		signMode: accountKind ? 'good-change-plus' : 'negative-only',
		accountKind: accountKind ?? undefined
	});
	$: currentCategory = row.categories[0]?.account ?? '';
	$: reassignOptions = trackedAccounts.filter((a) => a.ledgerAccount && a.id !== row.account.id);
</script>

<aside
	class="fixed inset-y-0 right-0 z-30 flex w-[22.5rem] max-w-[calc(100vw-2rem)] flex-col overflow-y-auto border-l border-hairline bg-panel"
	aria-label="Transaction details"
>
	<header class="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
		<div class="min-w-0">
			<h2 class="m-0 truncate text-sm font-semibold text-ink">{row.payee}</h2>
			<p class="m-0 mt-0.5 text-xs text-ink-mute">
				{shortDate(row.date)} · {row.account.label}
			</p>
		</div>
		<button
			type="button"
			class="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-ink-mute hover:bg-wash hover:text-ink"
			aria-label="Close details"
			on:click={onClose}
		>
			<XIcon class="size-4" />
		</button>
	</header>

	<div class="grid gap-5 px-5 py-4">
		<p class="amount font-display m-0 text-2xl font-semibold text-ink">{amountText}</p>

		<dl class="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
			{#if row.isTransfer}
				<dt class="text-ink-mute">Transfer</dt>
				<dd class="m-0 text-ink">
					{row.account.label} → {row.transferPeer?.label ?? 'other account'}
				</dd>
			{:else if row.categories.length > 0}
				<dt class="text-ink-mute">{row.categories.length === 1 ? 'Category' : 'Categories'}</dt>
				<dd class="m-0 text-ink">
					{row.categories.map((c) => c.label).join(', ')}
				</dd>
			{:else if row.isUnknown}
				<dt class="text-ink-mute">Category</dt>
				<dd class="m-0 text-warn">Not set yet</dd>
			{/if}

			<dt class="text-ink-mute">Status</dt>
			<dd class="m-0 flex items-center gap-2 text-ink">
				{CLEARING_TOOLTIPS[row.status ?? 'unmarked']}
				<button
					type="button"
					class="cursor-pointer rounded-md border border-hairline bg-panel px-2 py-0.5 text-xs text-ink-mute hover:bg-wash hover:text-ink"
					disabled={busy}
					on:click={() => onToggleClearing(row)}
				>
					Change
				</button>
			</dd>

			{#if row.statementPayee && row.statementPayee !== row.payee}
				<dt class="text-ink-mute">On statement</dt>
				<dd class="m-0 text-ink-mute">{row.statementPayee}</dd>
			{/if}

			{#if row.notes}
				<dt class="text-ink-mute">Notes</dt>
				<dd class="m-0 text-ink">{row.notes}</dd>
			{/if}
		</dl>

		{#if error}
			<p class="m-0 rounded-md border border-bad/30 bg-bad/5 px-3 py-2 text-sm text-bad" role="alert">
				{error}
			</p>
		{/if}

		{#if canRecategorizeRow(row)}
			<section class="grid gap-1.5">
				<label for="detail-recategorize" class="text-xs font-medium text-ink-mute">
					Move to category
				</label>
				<div class="flex gap-2">
					<input
						id="detail-recategorize"
						list="detail-category-options"
						bind:value={recategorizeDraft}
						placeholder="Expenses:…"
					/>
					<datalist id="detail-category-options">
						{#each categoryAccounts as account (account)}
							<option value={account}></option>
						{/each}
					</datalist>
					<button
						type="button"
						class="shrink-0 cursor-pointer rounded-md border-0 bg-brand px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
						disabled={busy || !recategorizeDraft || recategorizeDraft === currentCategory}
						on:click={() => onRecategorize(row, recategorizeDraft)}
					>
						Save
					</button>
				</div>
			</section>
		{/if}

		{#if reassignOptions.length > 0 && !row.isTransfer}
			<section class="grid gap-1.5">
				<label for="detail-reassign" class="text-xs font-medium text-ink-mute">
					Move to account
				</label>
				<div class="flex gap-2">
					<select id="detail-reassign" bind:value={reassignDraft}>
						<option value="">Choose an account…</option>
						{#each reassignOptions as account (account.id)}
							<option value={account.ledgerAccount}>{account.displayName}</option>
						{/each}
					</select>
					<button
						type="button"
						class="shrink-0 cursor-pointer rounded-md border border-hairline-strong bg-panel px-3 py-1.5 text-sm text-ink hover:bg-wash disabled:cursor-not-allowed disabled:opacity-50"
						disabled={busy || !reassignDraft}
						on:click={() => onReassignAccount(row, reassignDraft)}
					>
						Move
					</button>
				</div>
			</section>
		{/if}
	</div>

	<footer class="mt-auto grid gap-2 border-t border-hairline px-5 py-4">
		{#if confirming === 'delete'}
			<p class="m-0 text-sm text-ink">Remove this transaction from your records?</p>
			<div class="flex gap-2">
				<button
					type="button"
					class="cursor-pointer rounded-md border-0 bg-bad px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
					disabled={busy}
					on:click={() => onDelete(row)}
				>
					{busy ? 'Removing…' : 'Remove'}
				</button>
				<button
					type="button"
					class="cursor-pointer rounded-md border border-hairline-strong bg-panel px-3 py-1.5 text-sm text-ink hover:bg-wash"
					on:click={() => (confirming = null)}
				>
					Keep it
				</button>
			</div>
		{:else if confirming === 'unmatch'}
			<p class="m-0 text-sm text-ink">
				Undo this match? The original manual entry comes back.
			</p>
			<div class="flex gap-2">
				<button
					type="button"
					class="cursor-pointer rounded-md border-0 bg-bad px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
					disabled={busy}
					on:click={() => onUnmatch(row)}
				>
					{busy ? 'Undoing…' : 'Undo match'}
				</button>
				<button
					type="button"
					class="cursor-pointer rounded-md border border-hairline-strong bg-panel px-3 py-1.5 text-sm text-ink hover:bg-wash"
					on:click={() => (confirming = null)}
				>
					Keep the match
				</button>
			</div>
		{:else}
			<div class="flex flex-wrap gap-2">
				{#if canUnmatchRow(row)}
					<button
						type="button"
						class="cursor-pointer rounded-md border border-hairline-strong bg-panel px-3 py-1.5 text-sm text-ink hover:bg-wash"
						on:click={() => (confirming = 'unmatch')}
					>
						Undo match
					</button>
				{/if}
				{#if canDeleteRow(row)}
					<button
						type="button"
						class="cursor-pointer rounded-md border border-hairline-strong bg-panel px-3 py-1.5 text-sm text-bad hover:bg-bad/5"
						on:click={() => (confirming = 'delete')}
					>
						Remove…
					</button>
				{/if}
				<span class="ml-auto self-center text-xs text-ink-mute">
					<span class="kbd">Esc</span> closes
				</span>
			</div>
		{/if}
	</footer>
</aside>
