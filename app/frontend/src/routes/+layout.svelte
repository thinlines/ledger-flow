<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';

	const navItems = [
		{ href: '/', label: 'Overview' },
		{ href: '/unknowns', label: 'Review' },
		{ href: '/import', label: 'Import' },
		{ href: '/rules', label: 'Automation' },
		{ href: '/setup', label: 'Setup' }
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
				<p>Money at a glance</p>
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
		max-width: 1240px;
		margin: 0 auto;
		padding: 1.4rem 1rem 2.4rem;
	}

	.topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		margin-bottom: 1.15rem;
		padding: 0.85rem 1rem;
		border-radius: 1.2rem;
		background: rgba(255, 255, 255, 0.7);
		border: 1px solid rgba(10, 61, 89, 0.08);
		backdrop-filter: blur(18px);
		box-shadow: 0 12px 24px rgba(17, 35, 52, 0.06);
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 0.8rem;
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

	nav {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	nav a {
		text-decoration: none;
		color: var(--brand-strong);
		font-weight: 700;
		padding: 0.5rem 0.8rem;
		border-radius: 999px;
		border: 1px solid rgba(10, 61, 89, 0.06);
		background: rgba(255, 255, 255, 0.58);
	}

	nav a:hover {
		border-color: rgba(15, 95, 136, 0.18);
		background: rgba(244, 249, 255, 0.95);
	}

	nav a.active {
		color: #fff;
		background: linear-gradient(130deg, #0f5f88, #0c7b59);
		box-shadow: 0 10px 22px rgba(15, 95, 136, 0.22);
	}

	.content {
		display: grid;
		gap: 1.1rem;
	}

	@media (max-width: 900px) {
		.topbar {
			flex-direction: column;
			align-items: flex-start;
		}
	}
</style>
