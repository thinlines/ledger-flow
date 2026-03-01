<script lang="ts">
  import { page } from '$app/stores';

  const navItems = [
    { href: '/setup', label: 'Setup' },
    { href: '/', label: 'Home' },
    { href: '/import', label: 'Import' },
    { href: '/unknowns', label: 'Review' }
  ];

  function isActive(pathname: string, href: string): boolean {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  }
</script>

<svelte:head>
  <title>Ledger Flow</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet" />
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
        <a href={item.href} class:active={isActive($page.url.pathname, item.href)}>{item.label}</a>
      {/each}
    </nav>
  </header>

  <main class="content">
    <slot />
  </main>
</div>

<style>
  :global(:root) {
    --bg: #edf2f9;
    --bg-accent: #e9f8f2;
    --card: #ffffff;
    --card-2: #f9fbff;
    --text: #102133;
    --muted: #607184;
    --line: #d4deea;
    --brand: #0f5f88;
    --brand-strong: #0a3d59;
    --ok: #0d7f58;
    --warn: #ad6a00;
    --bad: #b73a3a;
    --shadow: 0 12px 28px rgba(16, 33, 51, 0.08);
    --radius: 14px;
  }

  :global(body) {
    margin: 0;
    font-family: 'Inter', sans-serif;
    color: var(--text);
    background:
      radial-gradient(circle at 12% 8%, #d7e7ff 0%, transparent 36%),
      radial-gradient(circle at 90% 0%, #d7f4ea 0%, transparent 30%),
      linear-gradient(165deg, var(--bg) 0%, var(--bg-accent) 100%);
    min-height: 100vh;
  }

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
    color: var(--muted);
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

  :global(.view-card) {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 1rem;
  }

  :global(.hero) {
    background: linear-gradient(145deg, #fefefe, #f2f7ff);
  }

  :global(.eyebrow) {
    color: var(--muted);
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 700;
    margin-bottom: 0.35rem;
  }

  :global(.page-title) {
    font-family: 'Space Grotesk', sans-serif;
    margin: 0;
    font-size: 1.7rem;
  }

  :global(.subtitle) {
    margin: 0.45rem 0 0;
    color: var(--muted);
  }

  :global(.grid-2) {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1rem;
  }

  :global(.grid-3) {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1rem;
  }

  :global(.btn) {
    border-radius: 10px;
    padding: 0.55rem 0.85rem;
    border: 1px solid var(--line);
    background: #f7fbff;
    color: var(--brand-strong);
    font-weight: 600;
    cursor: pointer;
  }

  :global(.btn:hover) {
    background: #eef6ff;
  }

  :global(.btn-primary) {
    color: #fff;
    background: linear-gradient(130deg, #0f5f88, #0a3d59);
    border-color: #0b4a6b;
  }

  :global(.btn-primary:hover) {
    filter: brightness(1.05);
  }

  :global(.btn:disabled) {
    opacity: 0.5;
    cursor: not-allowed;
  }

  :global(.field) {
    display: grid;
    gap: 0.35rem;
  }

  :global(.field label) {
    font-size: 0.86rem;
    color: var(--muted);
    font-weight: 600;
  }

  :global(input), :global(select), :global(textarea) {
    width: 100%;
    border: 1px solid #c8d6e5;
    border-radius: 10px;
    padding: 0.58rem 0.65rem;
    font: inherit;
    background: #fff;
    box-sizing: border-box;
  }

  :global(input:focus), :global(select:focus), :global(textarea:focus) {
    outline: 2px solid rgba(15, 95, 136, 0.24);
    border-color: var(--brand);
  }

  :global(.pill) {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.2rem 0.5rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    border: 1px solid;
  }

  :global(.pill.ok) {
    color: var(--ok);
    border-color: #9ad6be;
    background: #edf9f4;
  }

  :global(.pill.warn) {
    color: var(--warn);
    border-color: #f3cf96;
    background: #fff7ea;
  }

  :global(.pill.bad) {
    color: var(--bad);
    border-color: #f3b4b4;
    background: #fff1f1;
  }

  :global(.muted) {
    color: var(--muted);
  }

  :global(.error-text) {
    color: var(--bad);
  }

  @media (max-width: 900px) {
    .topbar {
      flex-direction: column;
      align-items: flex-start;
    }

    :global(.grid-3), :global(.grid-2) {
      grid-template-columns: 1fr;
    }
  }
</style>
