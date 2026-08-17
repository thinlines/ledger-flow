<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { TrackedAccount, TransactionFilters } from '$lib/transactions/types';
	import { EMPTY_FILTERS } from '$lib/transactions/transactionFilters';
	import { onVerb } from '$lib/keyboard/runtime';

	export let filters: TransactionFilters;
	export let trackedAccounts: TrackedAccount[];
	export let onChange: (next: TransactionFilters) => void;

	let searchInput: HTMLInputElement | null = null;
	let searchDraft = '';
	let searchDebounce: ReturnType<typeof setTimeout> | null = null;

	// While the search input has focus it is the top layer of the dismiss
	// stack: Escape blurs it (keeping the typed query) and hands j/k back to
	// the register, instead of reaching whatever surface sits underneath.
	let offDismiss: (() => void) | null = null;

	function handleSearchFocus() {
		offDismiss?.();
		offDismiss = onVerb('dismiss', () => {
			searchInput?.blur();
			return true;
		});
	}

	function handleSearchBlur() {
		offDismiss?.();
		offDismiss = null;
	}

	onDestroy(() => offDismiss?.());

	// Keep the draft in sync when the URL changes underneath us (back/forward,
	// deep link), but never while the user is mid-keystroke in the input.
	$: if (typeof document === 'undefined' || document.activeElement !== searchInput) {
		searchDraft = filters.search;
	}

	const PERIODS: Array<{ value: string; label: string }> = [
		{ value: 'this-month', label: 'This month' },
		{ value: 'last-30', label: 'Last 30 days' },
		{ value: 'last-3-months', label: 'Last 3 months' },
		{ value: '', label: 'All time' }
	];

	export function focusSearch() {
		searchInput?.focus();
		searchInput?.select();
	}

	function setAccount(id: string) {
		onChange({ ...filters, accounts: id ? [id] : [] });
	}

	function setPeriod(value: string) {
		onChange({ ...filters, period: value || null, month: null });
	}

	function setSearch(value: string) {
		searchDraft = value;
		if (searchDebounce) clearTimeout(searchDebounce);
		searchDebounce = setTimeout(() => onChange({ ...filters, search: searchDraft }), 250);
	}

	function monthLabel(month: string): string {
		const parsed = new Date(`${month}-01T00:00:00`);
		return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(parsed);
	}

	$: hasAnyFilter =
		filters.accounts.length > 0 ||
		!!filters.category ||
		!!filters.month ||
		!!filters.search ||
		!!filters.status;
</script>

<div class="flex flex-wrap items-center gap-2 border-b border-hairline bg-paper px-6 py-2.5 max-lg:px-4">
	<select
		class="w-auto!"
		aria-label="Account"
		value={filters.accounts.length === 1 ? filters.accounts[0] : ''}
		on:change={(e) => setAccount(e.currentTarget.value)}
	>
		<option value="">All accounts</option>
		{#each trackedAccounts as account (account.id)}
			<option value={account.id}>{account.displayName}</option>
		{/each}
	</select>

	{#if filters.month}
		<span
			class="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-panel px-2 py-1 text-xs text-ink"
		>
			{monthLabel(filters.month)}
			<button
				type="button"
				class="cursor-pointer border-0 bg-transparent p-0 text-ink-mute hover:text-ink"
				aria-label="Clear month filter"
				on:click={() => onChange({ ...filters, month: null })}
			>
				&times;
			</button>
		</span>
	{:else}
		<select
			class="w-auto!"
			aria-label="Time range"
			value={filters.period ?? ''}
			on:change={(e) => setPeriod(e.currentTarget.value)}
		>
			{#each PERIODS as period (period.value)}
				<option value={period.value}>{period.label}</option>
			{/each}
		</select>
	{/if}

	{#if filters.category}
		<span
			class="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-panel px-2 py-1 text-xs text-ink"
		>
			{filters.category}
			<button
				type="button"
				class="cursor-pointer border-0 bg-transparent p-0 text-ink-mute hover:text-ink"
				aria-label="Clear category filter"
				on:click={() => onChange({ ...filters, category: null })}
			>
				&times;
			</button>
		</span>
	{/if}

	<div class="relative ml-auto flex items-center">
		<input
			bind:this={searchInput}
			class="w-56! pr-8! max-md:w-40!"
			type="search"
			placeholder="Search payees…"
			aria-label="Search transactions"
			value={searchDraft}
			on:input={(e) => setSearch(e.currentTarget.value)}
			on:focus={handleSearchFocus}
			on:blur={handleSearchBlur}
		/>
		<span class="kbd pointer-events-none absolute right-2">/</span>
	</div>

	{#if hasAnyFilter}
		<button
			type="button"
			class="cursor-pointer rounded-md border-0 bg-transparent px-2 py-1 text-xs text-ink-mute hover:text-ink"
			on:click={() => onChange({ ...EMPTY_FILTERS, period: filters.period })}
		>
			Clear filters
		</button>
	{/if}
</div>
