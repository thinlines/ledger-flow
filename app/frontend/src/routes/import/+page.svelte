<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';

  type Candidate = {
    file_name: string;
    abs_path: string;
    detected_year: string | null;
    detected_institution: string | null;
    is_configured_institution: boolean;
  };

  let candidates: Candidate[] = [];
  let institutions: string[] = [];
  let selectedPath = '';
  let year = '';
  let institution = '';
  let preview: any = null;
  let error = '';
  let loading = false;

  async function loadCandidates() {
    try {
      const data = await apiGet<{ candidates: Candidate[]; institutions: string[] }>('/api/import/candidates');
      candidates = data.candidates;
      institutions = data.institutions;
    } catch (e) {
      error = String(e);
    }
  }

  async function runPreview() {
    error = '';
    preview = null;
    loading = true;
    try {
      preview = await apiPost('/api/import/preview', {
        csvPath: selectedPath,
        year,
        institution
      });
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function applyStage() {
    if (!preview?.stageId) return;
    error = '';
    loading = true;
    try {
      preview = await apiPost('/api/import/apply', { stageId: preview.stageId });
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function pickCandidate(c: Candidate) {
    selectedPath = c.abs_path;
    year = c.detected_year ?? '';
    institution = c.detected_institution ?? '';
  }

  onMount(loadCandidates);
</script>

<section class="view-card hero">
  <p class="eyebrow">Import Center</p>
  <h2 class="page-title">Preview and Import Institution Transactions</h2>
  <p class="subtitle">Select a file, preview match outcomes, and apply only net-new transactions.</p>
</section>

{#if error}
  <section class="view-card"><p class="error-text">{error}</p></section>
{/if}

<section class="grid-2">
  <article class="view-card">
    <p class="eyebrow">Inbox</p>
    <h3>Detected CSV Files</h3>
    {#if candidates.length === 0}
      <p class="muted">No CSV files found in the import folder.</p>
    {:else}
      <div class="list">
        {#each candidates as c}
          <button class="row" on:click={() => pickCandidate(c)}>
            <span>{c.file_name}</span>
            {#if c.is_configured_institution}
              <span class="pill ok">Configured</span>
            {:else}
              <span class="pill warn">Needs setup</span>
            {/if}
          </button>
        {/each}
      </div>
    {/if}
  </article>

  <article class="view-card">
    <p class="eyebrow">Configuration</p>
    <h3>Import Preview Inputs</h3>

    <div class="field">
      <label for="csvPath">CSV Path</label>
      <input id="csvPath" bind:value={selectedPath} />
    </div>

    <div class="field grid-2 compact">
      <div class="field">
        <label for="year">Year</label>
        <input id="year" bind:value={year} />
      </div>

      <div class="field">
        <label for="institution">Institution</label>
        <select id="institution" bind:value={institution}>
          <option value="">Select...</option>
          {#each institutions as inst}
            <option value={inst}>{inst}</option>
          {/each}
        </select>
      </div>
    </div>

    <button class="btn btn-primary" disabled={loading || !selectedPath || !year || !institution} on:click={runPreview}>
      {loading ? 'Preparing preview...' : 'Preview Import'}
    </button>
  </article>
</section>

{#if preview}
  <section class="view-card">
    <p class="eyebrow">Preview Result</p>
    <h3>Stage {preview.stageId}</h3>
    <p class="muted">Target journal: {preview.targetJournalPath}</p>

    {#if preview.summary}
      <div class="summary">
        <span class="pill ok">New {preview.summary.newCount}</span>
        <span class="pill">Duplicates {preview.summary.duplicateCount}</span>
        <span class="pill warn">Conflicts {preview.summary.conflictCount}</span>
        <span class="pill">Unknown {preview.summary.unknownCount}</span>
      </div>
    {/if}

    {#if preview.result}
      <div class="result">
        <p><span class="pill ok">Applied</span></p>
        <p>
          Appended {preview.result.appendedTxnCount} | Skipped duplicates {preview.result.skippedDuplicateCount} |
          Conflicts {preview.result.conflicts?.length ?? 0}
        </p>
        {#if preview.result.backupPath}
          <p class="muted">Backup: {preview.result.backupPath}</p>
        {/if}
      </div>
    {:else}
      <button class="btn btn-primary" disabled={loading} on:click={applyStage}>Apply Import</button>
    {/if}

    {#if preview.preview?.length}
      <h4>Sample Transactions</h4>
      <pre>{preview.preview.slice(0, 8).join('\n\n')}</pre>
    {/if}
  </section>
{/if}

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .compact {
    gap: 0.8rem;
    margin: 0.3rem 0 0.8rem;
  }

  .list {
    display: grid;
    gap: 0.5rem;
    max-height: 360px;
    overflow: auto;
  }

  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border: 1px solid var(--line);
    background: var(--card-2);
    border-radius: 10px;
    padding: 0.55rem 0.6rem;
    cursor: pointer;
    text-align: left;
    width: 100%;
  }

  .row:hover {
    background: #eef6ff;
  }

  .summary {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    margin-bottom: 0.8rem;
  }

  .result {
    margin: 0.4rem 0 0.8rem;
  }

  pre {
    background: #0c1925;
    color: #d5ecff;
    border-radius: 12px;
    padding: 0.8rem;
    white-space: pre-wrap;
    max-height: 320px;
    overflow: auto;
  }
</style>
