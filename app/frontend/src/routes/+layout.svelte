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
	import { cheatSheetOpen, onVerb } from '$lib/keyboard/runtime';

	const nav = [{ href: '/transactions', label: 'Transactions', chord: 'g t' }];

	onMount(() => {
		registerCommands([
			{
				id: 'nav.transactions',
				label: 'Go to Transactions',
				shortcut: 'G T',
				category: 'navigation',
				action: () => goto('/transactions'),
				href: '/transactions',
				keywords: ['register', 'ledger', 'activity']
			},
			{
				id: 'help.shortcuts',
				label: 'Keyboard shortcuts',
				shortcut: '?',
				category: 'actions',
				action: () => cheatSheetOpen.set(true),
				keywords: ['help', 'keys', 'keymap']
			}
		]);

		const offNav = onVerb('nav.transactions', () => {
			void goto('/transactions');
			return true;
		});
		const offHelp = onVerb('help.toggle', () => {
			cheatSheetOpen.update((v) => !v);
			return true;
		});
		const offPalette = onVerb('palette.toggle', () => {
			commandPaletteOpen.update((v) => !v);
			return true;
		});

		return () => {
			offNav();
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
		<a href="/transactions" class="px-5 pt-6 pb-5 no-underline">
			<span class="font-display text-[0.9375rem] font-semibold tracking-tight text-ink">
				Ledger Flow
			</span>
		</a>

		<nav class="grid gap-0.5 px-3" aria-label="Primary">
			{#each nav as item (item.href)}
				{@const active = $page.url.pathname.startsWith(item.href)}
				<a
					href={item.href}
					aria-current={active ? 'page' : undefined}
					class="flex items-center justify-between rounded-md px-2 py-1.5 text-sm no-underline
						{active ? 'bg-brand-wash font-medium text-brand-deep' : 'text-ink-mute hover:bg-wash hover:text-ink'}"
				>
					<span>{item.label}</span>
					<span class="text-[0.6875rem] tracking-wide opacity-60">{item.chord}</span>
				</a>
			{/each}
		</nav>

		<p class="m-0 px-5 pt-4 text-xs leading-relaxed text-ink-mute">
			Import, review and reconcile are being rebuilt and will return here.
		</p>

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
			<a href="/transactions" class="font-display text-sm font-semibold text-ink no-underline">
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
