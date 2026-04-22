<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
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

	function isActive(pathname: string, href: string): boolean {
		if (href === '/') return pathname === '/';

		return pathname.startsWith(href);
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

<div
	class="mx-auto grid max-w-[1440px] items-start gap-4 px-4 pb-8 pt-5 grid-cols-[minmax(250px,290px)_minmax(0,1fr)] max-shell:grid-cols-1"
>
	<aside class="sticky top-4 grid gap-4 max-shell:static">
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

		<nav class="grid gap-4 max-shell:grid-cols-2 max-tablet:grid-cols-1" aria-label="Primary">
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
</style>
