<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';

  let health: any = null;
  let state: any = null;
  let error = '';

  onMount(async () => {
    try {
      const [h, s] = await Promise.all([apiGet('/api/health'), apiGet('/api/app/state')]);
      health = h;
      state = s;
    } catch (e) {
      error = String(e);
    }
  });
</script>

<section class="view-card hero">
  <p class="eyebrow">Home</p>
  <h2 class="page-title">Financial Operations Dashboard</h2>
  <p class="subtitle">Manage imports, resolve review queues, and keep books current from one workspace.</p>
  <div class="hero-actions">
    {#if state?.initialized}
      <a class="btn btn-primary" href="/import">Import Transactions</a>
      <a class="btn" href="/unknowns">Open Review Queue</a>
    {:else}
      <a class="btn btn-primary" href="/setup">Initialize Workspace</a>
    {/if}
  </div>
</section>

{#if error}
  <section class="view-card"><p class="error-text">{error}</p></section>
{:else}
  <section class="grid-3">
    <article class="view-card metric">
      <p class="eyebrow">System</p>
      <h3>Backend</h3>
      {#if health}
        <p><span class="pill ok">Online</span></p>
        <p class="muted">{health.ledgerVersion}</p>
      {:else}
        <p class="muted">Loading...</p>
      {/if}
    </article>

    <article class="view-card metric">
      <p class="eyebrow">Workspace</p>
      <h3>Status</h3>
      {#if state?.initialized}
        <p><span class="pill ok">Initialized</span></p>
        <p class="muted">{state.workspaceName}</p>
      {:else}
        <p><span class="pill warn">Needs setup</span></p>
      {/if}
    </article>

    <article class="view-card metric">
      <p class="eyebrow">Queue</p>
      <h3>Inbox Files</h3>
      <p class="big">{state?.csvInbox ?? 0}</p>
      <p class="muted">CSV files ready for preview.</p>
    </article>
  </section>
{/if}

<style>
  .hero-actions {
    margin-top: 1rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }

  .metric h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .big {
    margin: 0;
    font-size: 2rem;
    font-family: 'Space Grotesk', sans-serif;
  }
</style>
