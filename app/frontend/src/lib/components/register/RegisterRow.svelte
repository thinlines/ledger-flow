<script lang="ts">
	import type { TransactionRow } from '$lib/transactions/types';
	import { formatCurrency, goodChangeTone, type AccountKind } from '$lib/format';
	import { CLEARING_TOOLTIPS } from '$lib/transactions/helpers';
	import ArrowLeftRightIcon from '@lucide/svelte/icons/arrow-left-right';

	export let row: TransactionRow;
	export let baseCurrency: string;
	/** Kind of the scoped account; null in cross-account views. */
	export let accountKind: AccountKind | null;
	export let focused: boolean;
	/** Running balance rail renders only in single-account scope. */
	export let showBalance: boolean;
	/** Account label renders only in cross-account scope. */
	export let showAccount: boolean;
	export let onOpen: (row: TransactionRow) => void;
	export let onToggleClearing: ((row: TransactionRow) => void) | null;

	// Row amount: transfers read as unsigned movement; in single-account scope
	// "good" changes (asset up, liability down) earn a + and the accent tone.
	$: amountText = row.isTransfer
		? formatCurrency(Math.abs(row.amount), baseCurrency, { signMode: 'negative-only' })
		: formatCurrency(row.amount, baseCurrency, {
				signMode: accountKind ? 'good-change-plus' : 'negative-only',
				accountKind: accountKind ?? undefined
			});
	$: amountGood = !row.isTransfer && accountKind && goodChangeTone(row.amount, accountKind) === 'positive';
	$: pending = row.transferState === 'pending' || row.status === 'pending';

	let element: HTMLButtonElement | null = null;

	$: if (focused && element) {
		element.scrollIntoView({ block: 'nearest' });
	}
</script>

<button
	bind:this={element}
	type="button"
	tabindex={focused ? 0 : -1}
	data-row-id={row.id}
	class="grid w-full cursor-pointer items-center gap-x-3 border-b border-hairline bg-transparent px-3 py-2 text-left text-sm transition-colors duration-75 max-md:grid-cols-[1rem_minmax(0,1fr)_auto]
		{showBalance ? 'grid-cols-[1rem_minmax(0,1fr)_7.5rem_8.5rem]' : 'grid-cols-[1rem_minmax(0,1fr)_7.5rem]'}
		{focused ? 'bg-brand-wash shadow-[inset_2px_0_0_var(--accent)]' : 'hover:bg-wash'}"
	on:click={() => onOpen(row)}
>
	{#if onToggleClearing}
		<span
			role="button"
			tabindex="-1"
			title={CLEARING_TOOLTIPS[row.status ?? 'unmarked']}
			class="size-2 justify-self-center rounded-full
				{row.status === 'cleared'
				? 'bg-brand'
				: row.status === 'pending'
					? 'bg-transparent shadow-[inset_0_0_0_1.5px_var(--warn)]'
					: 'bg-hairline-strong'}"
			on:click|stopPropagation={() => onToggleClearing?.(row)}
			on:keydown={() => {}}
		></span>
	{:else}
		<span
			class="size-2 justify-self-center rounded-full
				{row.status === 'cleared' ? 'bg-hairline-strong' : 'bg-transparent'}"
			aria-hidden="true"
		></span>
	{/if}

	<span class="flex min-w-0 items-center gap-2 max-md:flex-wrap max-md:gap-y-0.5">
		<span class="truncate font-medium text-ink max-md:w-full">{row.payee}</span>

		{#if row.isTransfer}
			<span class="flex shrink-0 items-center gap-1 text-xs text-ink-mute">
				<ArrowLeftRightIcon class="size-3" />
				{row.transferPeer?.label ?? 'Transfer'}
			</span>
		{:else if row.isUnknown}
			<span class="shrink-0 rounded-sm bg-warn/10 px-1.5 py-0.5 text-xs font-medium text-warn">
				Needs category
			</span>
		{:else}
			{#each row.categories.slice(0, 2) as category (category.account)}
				<span class="shrink-0 truncate rounded-sm border border-hairline px-1.5 py-0.5 text-xs text-ink-mute">
					{category.label}
				</span>
			{/each}
			{#if row.categories.length > 2}
				<span class="shrink-0 text-xs text-ink-mute">+{row.categories.length - 2}</span>
			{/if}
		{/if}

		{#if pending}
			<span class="shrink-0 rounded-sm bg-warn/10 px-1.5 py-0.5 text-xs font-medium text-warn">
				Pending
			</span>
		{/if}

		{#if showAccount}
			<span class="shrink-0 text-xs text-ink-mute">{row.account.label}</span>
		{/if}
	</span>

	<span class="amount justify-self-end {amountGood ? 'font-medium text-brand-deep' : 'text-ink'}">
		{amountText}
	</span>

	{#if showBalance}
		<span
			class="amount self-stretch content-center border-l border-hairline pl-3 text-right text-ink-mute max-md:hidden"
		>
			{row.runningBalance == null
				? '—'
				: formatCurrency(row.runningBalance, baseCurrency, { signMode: 'negative-only' })}
		</span>
	{/if}
</button>
