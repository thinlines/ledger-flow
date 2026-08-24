<script lang="ts">
	import { onMount } from 'svelte';
	import Eye from '@lucide/svelte/icons/eye';
	import EyeOff from '@lucide/svelte/icons/eye-off';
	import { apiGet } from '$lib/api';
	import Dashboard from './Dashboard.svelte';
	import type { DashboardOverview, Direction } from './dashboard';

	let overview: DashboardOverview | null = null;
	let direction: Direction | null = null;
	let loading = true;
	let error = '';
	let hidden = false;

	onMount(() => {
		void loadDashboard();
	});

	async function loadDashboard() {
		loading = true;
		error = '';
		try {
			[overview, direction] = await Promise.all([
				apiGet<DashboardOverview>('/api/dashboard/overview'),
				apiGet<Direction>('/api/dashboard/direction')
			]);
		} catch (caught) {
			error = caught instanceof Error ? caught.message : String(caught);
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head><title>Dashboard · Ledger Flow</title></svelte:head>

<div class="relative">
	{#if overview && direction}
		<div class="absolute top-5 right-6 z-10">
			<button type="button" class="grid size-8 cursor-pointer place-items-center rounded-md border bg-panel text-ink-mute hover:text-ink" on:click={() => hidden = !hidden} aria-label={hidden ? 'Show amounts' : 'Hide amounts'}>{#if hidden}<EyeOff size={15}/>{:else}<Eye size={15}/>{/if}</button>
		</div>
		{#if overview.hasData}
			<Dashboard {overview} {direction} {hidden}/>
		{:else}
			<section class="mx-auto grid min-h-[70vh] max-w-160 place-items-center px-6 text-center"><div><p class="text-xs font-medium uppercase tracking-[0.16em] text-brand-deep">Financial dashboard</p><h1 class="mt-2 font-display text-3xl font-semibold">Your dashboard is ready for activity.</h1><p class="mx-auto mt-3 max-w-100 text-sm leading-relaxed text-ink-mute">Import a statement or add transactions to see cash flow, spending patterns, runway, and net worth here.</p><a href="/import" class="mt-6 inline-flex rounded-md bg-brand px-4 py-2 text-sm font-medium text-white no-underline hover:bg-brand-deep">Import transactions</a></div></section>
		{/if}
	{:else if loading}
		<section class="mx-auto max-w-250 px-6 pt-10"><div class="h-5 w-32 animate-pulse rounded bg-wash"></div><div class="mt-4 h-10 w-72 animate-pulse rounded bg-wash"></div><div class="mt-8 grid grid-cols-[1.65fr_1fr] gap-5"><div class="h-70 animate-pulse rounded-xl bg-wash"></div><div class="h-70 animate-pulse rounded-xl bg-wash"></div></div></section>
	{:else}
		<section class="mx-auto grid min-h-[70vh] max-w-160 place-items-center px-6 text-center"><div><h1 class="font-display text-2xl font-semibold">Couldn’t load your overview</h1><p class="mt-2 text-sm text-bad">{error}</p><button type="button" class="mt-5 cursor-pointer rounded-md border bg-panel px-3.5 py-2 text-sm font-medium" on:click={loadDashboard}>Try again</button></div></section>
	{/if}
</div>
