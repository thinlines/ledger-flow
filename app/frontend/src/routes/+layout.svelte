<script lang="ts">
  import { page } from '$app/stores';
</script>

<svelte:head>
  <title>Ledger Workflow</title>
</svelte:head>

<div class="shell">
  <header>
    <h1>Ledger Workflow MVP</h1>
    <nav>
      <a href="/" class:active={$page.url.pathname === '/'}>Home</a>
      <a href="/import" class:active={$page.url.pathname.startsWith('/import')}>Import</a>
      <a href="/unknowns" class:active={$page.url.pathname.startsWith('/unknowns')}>Unknowns</a>
    </nav>
  </header>
  <main>
    <slot />
  </main>
</div>

<style>
  :global(body) {
    margin: 0;
    font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
    background: linear-gradient(160deg, #f3f8ff 0%, #f8fff5 100%);
    color: #1b2b34;
  }

  .shell {
    max-width: 1100px;
    margin: 0 auto;
    padding: 1.25rem;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    border-bottom: 1px solid #c8d6e5;
    margin-bottom: 1.25rem;
  }

  h1 {
    font-size: 1.2rem;
  }

  nav {
    display: flex;
    gap: 0.75rem;
  }

  a {
    color: #1f6f8b;
    text-decoration: none;
    padding: 0.4rem 0.6rem;
    border-radius: 8px;
  }

  a.active {
    background: #d8f1ff;
    color: #0e4f66;
  }
</style>
