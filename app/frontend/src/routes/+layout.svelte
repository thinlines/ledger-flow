<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';

	const navSections = [
		{
			title: 'Daily Use',
			items: [
				{ href: '/', label: 'Overview', note: 'Balances, trends, next steps' },
				{ href: '/accounts', label: 'Accounts', note: 'Tracked accounts and opening balances' }
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
			items: [{ href: '/rules', label: 'Rules', note: 'Matching and categorization logic' }]
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

<div class="app-shell">
	<aside class="sidebar">
		<div class="brand-card">
			<div class="brand">
				<span class="brand-mark">LF</span>

				<div>
					<h1>Ledger Flow</h1>
					<p>Finance workspace</p>
				</div>
			</div>

			<p class="brand-copy">
				Track balances, imports, and review work without exposing the accounting internals unless you need them.
			</p>
		</div>

		<nav class="sidebar-nav" aria-label="Primary">
			{#each navSections as section}
				<section class="nav-section">
					<p class="nav-section-title">{section.title}</p>

					<div class="nav-items">
						{#each section.items as item}
							<a
								href={item.href}
								class:active={isActive($page.url.pathname, item.href)}
								class="nav-link"
							>
								<span class="nav-link-label">{item.label}</span>
								<span class="nav-link-note">{item.note}</span>
							</a>
						{/each}
					</div>
				</section>
			{/each}
		</nav>
	</aside>

	<main class="content"><slot /></main>
</div>

<style>
	.app-shell {
		max-width: 1440px;
		margin: 0 auto;
		padding: 1.2rem 1rem 2rem;
		display: grid;
		grid-template-columns: minmax(250px, 290px) minmax(0, 1fr);
		gap: 1.1rem;
		align-items: start;
	}

	.sidebar {
		position: sticky;
		top: 1rem;
		display: grid;
		gap: 0.9rem;
	}

	.brand-card,
	.nav-section {
		background: rgba(255, 255, 255, 0.76);
		border: 1px solid rgba(10, 61, 89, 0.08);
		border-radius: 1.2rem;
		padding: 1rem;
		backdrop-filter: blur(18px);
		box-shadow: 0 12px 24px rgba(17, 35, 52, 0.06);
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 0.8rem;
	}

	.brand-card {
		background:
			linear-gradient(150deg, rgba(255, 255, 255, 0.88), rgba(243, 249, 255, 0.82)),
			radial-gradient(circle at top right, rgba(42, 163, 122, 0.18), transparent 40%);
	}

	.brand-mark {
		width: 2.5rem;
		height: 2.5rem;
		border-radius: 0.85rem;
		display: grid;
		place-items: center;
		font-family: 'Space Grotesk', sans-serif;
		font-weight: 700;
		background: linear-gradient(140deg, #0f5f88, #2aa37a);
		color: #fff;
		box-shadow: 0 10px 24px rgba(15, 95, 136, 0.22);
	}

	h1 {
		margin: 0;
		font-family: 'Space Grotesk', sans-serif;
		font-size: 1.12rem;
		line-height: 1.1;
	}

	.brand p {
		margin: 0.2rem 0 0;
		font-size: 0.82rem;
		color: var(--muted-foreground);
	}

	.brand-copy {
		margin: 0.9rem 0 0;
		color: var(--muted-foreground);
		font-size: 0.92rem;
		line-height: 1.45;
	}

	.sidebar-nav {
		display: grid;
		gap: 0.9rem;
	}

	.nav-section {
		display: grid;
		gap: 0.75rem;
	}

	.nav-section-title {
		margin: 0;
		font-size: 0.78rem;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--muted-foreground);
	}

	.nav-items {
		display: grid;
		gap: 0.45rem;
	}

	.nav-link {
		display: grid;
		gap: 0.15rem;
		text-decoration: none;
		color: var(--brand-strong);
		padding: 0.8rem 0.9rem;
		border-radius: 1rem;
		border: 1px solid rgba(10, 61, 89, 0.06);
		background: rgba(255, 255, 255, 0.58);
	}

	.nav-link:hover {
		border-color: rgba(15, 95, 136, 0.18);
		background: rgba(244, 249, 255, 0.95);
	}

	.nav-link.active {
		color: #fff;
		background: linear-gradient(130deg, #0f5f88, #0c7b59);
		box-shadow: 0 10px 22px rgba(15, 95, 136, 0.22);
	}

	.nav-link-label {
		font-weight: 700;
	}

	.nav-link-note {
		font-size: 0.84rem;
		line-height: 1.35;
		color: inherit;
		opacity: 0.84;
	}

	.content {
		display: grid;
		gap: 1.1rem;
		min-width: 0;
	}

	@media (max-width: 980px) {
		.app-shell {
			grid-template-columns: 1fr;
		}

		.sidebar {
			position: static;
		}

		.sidebar-nav {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}

	@media (max-width: 720px) {
		.sidebar-nav {
			grid-template-columns: 1fr;
		}
	}
</style>
