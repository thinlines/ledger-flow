<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';

  type CandidateResponse = { candidates: Array<{ abs_path: string }>; institutions: string[] };
  type JournalsResponse = { journals: Array<{ absPath: string }> };

  let loading = true;
  let error = '';
  let health: any = null;
  let candidateCount = 0;
  let institutionCount = 0;
  let journalCount = 0;

  onMount(async () => {
    loading = true;
    error = '';
    try {
      const [h, candidates, journals] = await Promise.all([
        apiGet('/api/health'),
        apiGet<CandidateResponse>('/api/import/candidates'),
        apiGet<JournalsResponse>('/api/journals')
      ]);
      health = h;
      candidateCount = candidates.candidates.length;
      institutionCount = candidates.institutions.length;
      journalCount = journals.journals.length;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  });
</script>

<section class="view-card hero">
  <p class="eyebrow">First Contact</p>
  <h2 class="page-title">Set Up Your Workspace</h2>
  <p class="subtitle">Connect imports, verify readiness, and run your first preview in a few steps.</p>
  <div class="actions">
    <a class="btn btn-primary" href="/import">Start First Import</a>
    <a class="btn" href="/unknowns">Open Review Queue</a>
  </div>
</section>

{#if error}
  <section class="view-card">
    <p class="error-text">{error}</p>
  </section>
{:else}
  <section class="grid-3">
    <article class="view-card">
      <p class="eyebrow">Environment</p>
      <h3>Service Health</h3>
      {#if loading}
        <p class="muted">Checking...</p>
      {:else if health}
        <p><span class="pill ok">Ready</span></p>
        <p class="muted">{health.ledgerVersion}</p>
        <p class="muted">{health.hledgerVersion}</p>
      {/if}
    </article>

    <article class="view-card">
      <p class="eyebrow">Coverage</p>
      <h3>Institutions</h3>
      {#if loading}
        <p class="muted">Loading...</p>
      {:else}
        <p><strong>{institutionCount}</strong> configured</p>
        <p class="muted">You can import from any configured institution immediately.</p>
      {/if}
    </article>

    <article class="view-card">
      <p class="eyebrow">Readiness</p>
      <h3>Import Inputs</h3>
      {#if loading}
        <p class="muted">Loading...</p>
      {:else}
        <p><strong>{candidateCount}</strong> CSV files detected</p>
        <p><strong>{journalCount}</strong> journal files detected</p>
      {/if}
    </article>
  </section>

  <section class="view-card">
    <p class="eyebrow">Suggested Path</p>
    <h3>Onboarding Flow</h3>
    <ol>
      <li>Open <a href="/import">Import</a> and select a candidate CSV.</li>
      <li>Run Preview and verify new vs duplicate vs conflict counts.</li>
      <li>Apply import and move to <a href="/unknowns">Review</a> for unknown account mapping.</li>
    </ol>
  </section>
{/if}

<style>
  h3 {
    margin: 0.1rem 0 0.6rem;
  }

  .actions {
    margin-top: 1rem;
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  ol {
    margin: 0.5rem 0 0;
    padding-left: 1rem;
  }

  li {
    margin-bottom: 0.4rem;
  }
</style>
