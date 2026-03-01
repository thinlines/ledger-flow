<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';

  let health: any = null;
  let candidates: any[] = [];
  let journals: any[] = [];
  let error = '';

  onMount(async () => {
    try {
      const [h, c, j] = await Promise.all([
        apiGet('/api/health'),
        apiGet<{ candidates: any[] }>('/api/import/candidates'),
        apiGet<{ journals: any[] }>('/api/journals')
      ]);
      health = h;
      candidates = c.candidates;
      journals = j.journals;
    } catch (e) {
      error = String(e);
    }
  });
</script>

<section class="view-card hero">
  <p class="eyebrow">Operations Home</p>
  <h2 class="page-title">Financial Workflow Dashboard</h2>
  <p class="subtitle">Run imports, resolve review queues, and keep transaction data current.</p>
  <div class="hero-actions">
    <a class="btn btn-primary" href="/import">Import Transactions</a>
    <a class="btn" href="/unknowns">Resolve Unknowns</a>
    <a class="btn" href="/setup">Setup Guide</a>
  </div>
</section>

{#if error}
  <section class="view-card"><p class="error-text">{error}</p></section>
{:else}
  <section class="grid-3">
    <article class="view-card metric">
      <p class="eyebrow">System</p>
      <h3>Backend Health</h3>
      {#if health}
        <p><span class="pill ok">Online</span></p>
        <p class="muted">{health.ledgerVersion}</p>
      {:else}
        <p class="muted">Loading...</p>
      {/if}
    </article>

    <article class="view-card metric">
      <p class="eyebrow">Import Queue</p>
      <h3>CSV Inbox</h3>
      <p class="big">{candidates.length}</p>
      <p class="muted">Files ready for preview and import.</p>
    </article>

    <article class="view-card metric">
      <p class="eyebrow">Coverage</p>
      <h3>Journal Files</h3>
      <p class="big">{journals.length}</p>
      <p class="muted">Detected institution journal artifacts.</p>
    </article>
  </section>

  <section class="grid-2">
    <article class="view-card">
      <p class="eyebrow">Next Action</p>
      <h3>Import New Statements</h3>
      <p class="muted">Open import inbox, inspect match statuses, then apply new entries.</p>
      <a class="btn btn-primary" href="/import">Open Import</a>
    </article>

    <article class="view-card">
      <p class="eyebrow">Review Queue</p>
      <h3>Resolve Unknown Accounts</h3>
      <p class="muted">Scan a journal and apply account mappings in grouped batches.</p>
      <a class="btn" href="/unknowns">Open Review</a>
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
