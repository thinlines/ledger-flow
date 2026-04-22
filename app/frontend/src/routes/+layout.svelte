<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { Dialog as DialogPrimitive } from 'bits-ui';
	import MenuIcon from '@lucide/svelte/icons/menu';
	import XIcon from '@lucide/svelte/icons/x';
	import UndoToast from '$lib/components/UndoToast.svelte';

	const navSections = [
		{
			title: 'Daily Use',
			items: [
				{ href: '/', label: 'Overview', note: 'Balances, trends, next steps' },
				{ href: '/accounts', label: 'Accounts', note: 'Tracked accounts and opening balances' },
				{ href: '/transactions', label: 'Transactions', note: 'Per-account register and running balances' }
			]
		},
		{
			title: 'Workflows',
			items: [
				{ href: '/import', label: 'Import', note: 'Bring in new statement activity' },
				{ href: '/unknowns', label: 'Review', note: 'Resolve uncategorized transactions' }
			]
		},
		{
			title: 'Automation',
			items: [{ href: '/rules', label: 'Rules', note: 'Automate how new transactions get categorized' }]
		},
		{
			title: 'Workspace',
			items: [{ href: '/setup', label: 'Setup', note: 'Workspace bootstrap and recovery' }]
		}
	];

	let drawerOpen = false;
	let lastPathname = '';

	function isActive(pathname: string, href: string): boolean {
		if (href === '/') return pathname === '/';

		return pathname.startsWith(href);
	}

	// Auto-close the drawer whenever the route changes so navigation feels
	// immediate and the new page is visible right away.
	$: if ($page.url.pathname !== lastPathname) {
		lastPathname = $page.url.pathname;
		drawerOpen = false;
	}
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
		href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap"
		rel="stylesheet"
	/>
</svelte:head>

<!-- Mobile top bar: visible only below the shell breakpoint. -->
<header class="mobile-topbar hidden max-shell:flex sticky top-0 z-20 items-center justify-between gap-3 border-b border-card-edge bg-white/82 px-4 py-3 backdrop-blur-lg">
	<a href="/" class="flex items-center gap-2.5 no-underline text-brand-strong">
		<span class="brand-mark grid h-8 w-8 place-items-center rounded-lg font-display font-bold text-white">
			LF
		</span>
		<span class="font-display text-base font-bold leading-tight">Ledger Flow</span>
	</a>

	<button
		type="button"
		class="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-card-edge bg-white/70 text-brand-strong hover:bg-white/95"
		aria-label="Open navigation"
		aria-haspopup="dialog"
		aria-expanded={drawerOpen}
		on:click={() => (drawerOpen = true)}
	>
		<MenuIcon class="size-5" />
	</button>
</header>

<div
	class="mx-auto grid max-w-[1440px] items-start gap-4 px-4 pb-8 pt-5 grid-cols-[minmax(250px,290px)_minmax(0,1fr)] max-shell:grid-cols-1 max-shell:pt-4"
>
	<aside class="sticky top-4 grid gap-4 max-shell:hidden">
		<div
			class="brand-card rounded-card border border-card-edge bg-white/75 p-4 shadow-shell backdrop-blur-lg"
		>
			<div class="flex items-center gap-3">
				<span
					class="brand-mark grid h-10 w-10 place-items-center rounded-xl font-display font-bold text-white"
				>
					LF
				</span>

				<div>
					<h1 class="m-0 font-display text-lg leading-tight">Ledger Flow</h1>
					<p class="mt-1 mb-0 text-sm text-muted-foreground">Finance workspace</p>
				</div>
			</div>

			<p class="mt-4 mb-0 text-sm leading-snug text-muted-foreground">
				Your money, accounts, and spending &mdash; all in one place.
			</p>
		</div>

		<nav class="grid gap-4" aria-label="Primary">
			{#each navSections as section}
				<section
					class="grid gap-3 rounded-card border border-card-edge bg-white/75 p-4 shadow-shell backdrop-blur-lg"
				>
					<p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">
						{section.title}
					</p>

					<div class="grid gap-2">
						{#each section.items as item}
							<a
								href={item.href}
								class:active={isActive($page.url.pathname, item.href)}
								class="nav-link grid gap-0.5 rounded-2xl border border-card-edge bg-white/60 px-3.5 py-3 font-bold text-brand-strong no-underline hover:bg-white/90"
							>
								<span>{item.label}</span>
								<span class="text-sm font-normal leading-snug opacity-85">{item.note}</span>
							</a>
						{/each}
					</div>
				</section>
			{/each}
		</nav>
	</aside>

	<main class="grid min-w-0 gap-4"><slot /></main>
</div>

<!-- Mobile nav drawer (slide-in from the left). bits-ui handles backdrop
     click and Escape; `drawerOpen` resets on route change. -->
<DialogPrimitive.Root bind:open={drawerOpen}>
	<DialogPrimitive.Portal>
		<DialogPrimitive.Overlay class="mobile-drawer-overlay fixed inset-0 z-30 bg-black/35" />

		<DialogPrimitive.Content
			class="mobile-drawer fixed inset-y-0 left-0 z-40 flex w-[min(20rem,85vw)] flex-col gap-4 overflow-y-auto border-r border-card-edge bg-white p-4 shadow-card"
			aria-label="Main navigation"
		>
			<div class="flex items-center justify-between gap-3">
				<div class="flex items-center gap-2.5">
					<span class="brand-mark grid h-9 w-9 place-items-center rounded-lg font-display font-bold text-white">
						LF
					</span>
					<span class="font-display text-base font-bold leading-tight">Ledger Flow</span>
				</div>
				<button
					type="button"
					class="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
					aria-label="Close navigation"
					on:click={() => (drawerOpen = false)}
				>
					<XIcon class="size-4" />
				</button>
			</div>

			<nav class="grid gap-4" aria-label="Primary">
				{#each navSections as section}
					<section class="grid gap-2.5">
						<p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">
							{section.title}
						</p>

						<div class="grid gap-1.5">
							{#each section.items as item}
								<a
									href={item.href}
									class:active={isActive($page.url.pathname, item.href)}
									class="nav-link grid gap-0.5 rounded-xl border border-card-edge bg-white/60 px-3 py-2.5 font-bold text-brand-strong no-underline hover:bg-white/90"
									on:click={() => (drawerOpen = false)}
								>
									<span>{item.label}</span>
									<span class="text-sm font-normal leading-snug opacity-85">{item.note}</span>
								</a>
							{/each}
						</div>
					</section>
				{/each}
			</nav>
		</DialogPrimitive.Content>
	</DialogPrimitive.Portal>
</DialogPrimitive.Root>

<UndoToast />

<style>
	.brand-card {
		background:
			linear-gradient(150deg, rgba(255, 255, 255, 0.88), rgba(243, 249, 255, 0.82)),
			radial-gradient(circle at top right, rgba(42, 163, 122, 0.18), transparent 40%);
	}

	.brand-mark {
		background: linear-gradient(140deg, #0f5f88, #2aa37a);
		box-shadow: 0 10px 24px rgba(15, 95, 136, 0.22);
	}

	.nav-link:hover {
		border-color: rgba(15, 95, 136, 0.18);
	}

	.nav-link.active {
		color: #fff;
		background: linear-gradient(130deg, #0f5f88, #0c7b59);
		box-shadow: 0 10px 22px rgba(15, 95, 136, 0.22);
	}

	/* Slide-in for the drawer; fade for the overlay. Both are disabled
	   under prefers-reduced-motion per the spec. */
	@keyframes drawer-slide-in {
		from { transform: translateX(-100%); }
		to { transform: translateX(0); }
	}

	@keyframes drawer-fade-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	:global(.mobile-drawer) {
		animation: drawer-slide-in 0.22s ease-out;
	}

	:global(.mobile-drawer-overlay) {
		animation: drawer-fade-in 0.22s ease-out;
	}

	@media (prefers-reduced-motion: reduce) {
		:global(.mobile-drawer),
		:global(.mobile-drawer-overlay) {
			animation: none;
		}
	}
</style>
