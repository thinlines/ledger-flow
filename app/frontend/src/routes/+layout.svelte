<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import UndoToast from '$lib/components/UndoToast.svelte';
	import KeyboardListener from '$lib/components/KeyboardListener.svelte';
	import CommandPalette from '$lib/components/CommandPalette.svelte';
	import CheatSheet from '$lib/components/CheatSheet.svelte';
	import { commandPaletteOpen, registerCommands } from '$lib/command-registry';
	import { chordFor, labelFor } from '$lib/keyboard/keymap';
	import { cheatSheetOpen, onVerb, pendingPrefix } from '$lib/keyboard/runtime';
	import { rememberSurfaceUrl, surfaceForPathname, surfaceHrefs } from '$lib/surface-state';

	const nav = [
		{ surface: 'transactions' as const, label: 'Transactions', chord: chordFor('nav.transactions') },
		{ surface: 'import' as const, label: 'Import', chord: chordFor('nav.import') }
	];

	// Every visited surface URL is remembered so navigation restores the
	// surface exactly as the user left it (filters included).
	$: rememberSurfaceUrl($page.url.pathname + $page.url.search);

	// Going to the surface you are already on is a no-op — navigation must
	// never destroy in-surface state like filters.
	function goToTransactions() {
		if (surfaceForPathname($page.url.pathname) === 'transactions') return;
		void goto($surfaceHrefs.transactions);
	}

	function goToImport() {
		if ($page.url.pathname === '/import') return;
		void goto('/import');
	}

	// The overlays are peers, not layers: opening one closes the other so the
	// user never ends up with stacked surfaces to dismiss one by one.
	function toggleCheatSheet() {
		cheatSheetOpen.update((open) => {
			if (!open) commandPaletteOpen.set(false);
			return !open;
		});
	}

	function toggleCommandPalette() {
		commandPaletteOpen.update((open) => {
			if (!open) cheatSheetOpen.set(false);
			return !open;
		});
	}

	onMount(() => {
		registerCommands([
			{
				id: 'nav.transactions',
				label: labelFor('nav.transactions'),
				shortcut: chordFor('nav.transactions'),
				category: 'navigation',
				action: goToTransactions,
				keywords: ['register', 'ledger', 'activity']
			},
			{
				id: 'nav.import',
				label: labelFor('nav.import'),
				shortcut: chordFor('nav.import'),
				category: 'navigation',
				action: goToImport,
				keywords: ['csv', 'statement', 'upload']
			},
			{
				id: 'help.shortcuts',
				label: labelFor('help.toggle'),
				shortcut: chordFor('help.toggle'),
				category: 'actions',
				action: () => cheatSheetOpen.set(true),
				keywords: ['help', 'keys', 'keymap']
			}
		]);

		const offNav = onVerb('nav.transactions', () => {
			goToTransactions();
			return true;
		});
		const offImport = onVerb('nav.import', () => {
			goToImport();
			return true;
		});
		const offHelp = onVerb('help.toggle', () => {
			toggleCheatSheet();
			return true;
		});
		const offPalette = onVerb('palette.toggle', () => {
			toggleCommandPalette();
			return true;
		});

		return () => {
			offNav();
			offImport();
			offHelp();
			offPalette();
		};
	});
</script>

<svelte:head>
	<title>Ledger Flow</title>

	<link
		rel="preconnect"
		href="https://fonts.googleapis.com"
	/>

	<link
		rel="preconnect"
		href="https://fonts.gstatic.com"
		crossorigin="anonymous"
	/>

	<link
		href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap"
		rel="stylesheet"
	/>
</svelte:head>

<div class="mx-auto flex min-h-screen max-w-300">
	<aside
		class="sticky top-0 flex h-screen w-52 shrink-0 flex-col border-r border-hairline max-lg:hidden"
	>
		<a href={$surfaceHrefs.transactions} class="px-5 pt-6 pb-5 no-underline">
			<span class="font-display text-[0.9375rem] font-semibold tracking-tight text-ink">
				Ledger Flow
			</span>
		</a>

		<nav class="grid gap-0.5 px-3" aria-label="Primary">
			{#each nav as item (item.surface)}
				{@const active = surfaceForPathname($page.url.pathname) === item.surface}
				<a
					href={$surfaceHrefs[item.surface]}
					aria-current={active ? 'page' : undefined}
					class="flex items-center justify-between rounded-md px-2 py-1.5 text-sm no-underline
						{active ? 'bg-brand-wash font-medium text-brand-deep' : 'text-ink-mute hover:bg-wash hover:text-ink'}"
				>
					<span>{item.label}</span>
					<span class="text-[0.6875rem] tracking-wide opacity-60">{item.chord}</span>
				</a>
			{/each}
		</nav>

		<div class="mt-auto grid gap-1.5 border-t border-hairline px-5 py-4">
			<button
				type="button"
				class="flex cursor-pointer items-center justify-between border-0 bg-transparent p-0 text-left text-xs text-ink-mute hover:text-ink"
				on:click={() => cheatSheetOpen.set(true)}
			>
				<span>Shortcuts</span>
				<span class="kbd">?</span>
			</button>
			<button
				type="button"
				class="flex cursor-pointer items-center justify-between border-0 bg-transparent p-0 text-left text-xs text-ink-mute hover:text-ink"
				on:click={() => commandPaletteOpen.set(true)}
			>
				<span>Commands</span>
				<span class="flex gap-1"><span class="kbd">Ctrl</span><span class="kbd">K</span></span>
			</button>
		</div>
	</aside>

	<div class="min-w-0 flex-1">
		<header
			class="sticky top-0 z-20 hidden items-center justify-between border-b border-hairline bg-paper px-4 py-3 max-lg:flex"
		>
			<a href={$surfaceHrefs.transactions} class="font-display text-sm font-semibold text-ink no-underline">
				Ledger Flow
			</a>
			<button
				type="button"
				class="cursor-pointer rounded-md border border-hairline bg-panel px-2.5 py-1 text-xs text-ink-mute"
				on:click={() => commandPaletteOpen.set(true)}
			>
				Ctrl K
			</button>
		</header>

		<main class="min-w-0"><slot /></main>
	</div>
</div>

<UndoToast />
<KeyboardListener />
<CommandPalette />
<CheatSheet />

{#if $pendingPrefix}
	<div
		class="fixed right-4 bottom-4 z-50 flex items-center gap-1.5 rounded-md border border-hairline bg-panel px-2.5 py-1.5 text-xs text-ink-mute shadow-sm"
		aria-hidden="true"
	>
		<span class="kbd">{$pendingPrefix}</span>
		<span>then…</span>
	</div>
{/if}
