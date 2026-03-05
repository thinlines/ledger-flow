<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';

	const navItems = [
		{ href: '/setup', label: 'Setup' },
		{ href: '/', label: 'Home' },
		{ href: '/import', label: 'Import' },
		{ href: '/unknowns', label: 'Review' },
		{ href: '/rules', label: 'Rules' }
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
	<header class="topbar">
		<div class="brand">
			<span class="brand-mark">LF</span>

			<div>
				<h1>Ledger Flow</h1>
				<p>Import and reconciliation workspace</p>
			</div>
		</div>

		<nav>
			{#each navItems as item}
				<a
					href={item.href}
					class:active={isActive($page.url.pathname, item.href)}
				>{item.label}</a>
			{/each}
		</nav>
	</header>

	<main class="content"><slot></slot></main>
</div>

<style>
	.app-shell {
		max-width: 1180px;
		margin: 0 auto;
		padding: 1.4rem 1rem 2rem;
	}

	.topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		margin-bottom: 1rem;
		padding: 0.8rem 0.3rem;
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 0.8rem;
	}

	.brand-mark {
		width: 2.2rem;
		height: 2.2rem;
		border-radius: 0.7rem;
		display: grid;
		place-items: center;
		font-family: 'Space Grotesk', sans-serif;
		font-weight: 700;
		background: linear-gradient(140deg, var(--brand), #3d9ac8);
		color: #fff;
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

	nav {
		display: flex;
		gap: 0.45rem;
		flex-wrap: wrap;
	}

	nav a {
		text-decoration: none;
		color: var(--brand-strong);
		font-weight: 600;
		padding: 0.45rem 0.7rem;
		border-radius: 999px;
		border: 1px solid transparent;
	}

	nav a:hover {
		border-color: #bdd4e6;
		background: #f4f9ff;
	}

	nav a.active {
		color: #fff;
		background: linear-gradient(130deg, #0f5f88, #0a3d59);
		box-shadow: 0 6px 14px rgba(15, 95, 136, 0.25);
	}

	.content {
		display: grid;
		gap: 1rem;
	}

	@media (max-width: 900px) {
		.topbar {
			flex-direction: column;
			align-items: flex-start;
		}
	}
</style>
