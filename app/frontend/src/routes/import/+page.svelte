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

<section>
  <h2>Import CSV</h2>
  {#if error}<p class="error">{error}</p>{/if}

  <div class="panel">
    <h3>Candidates</h3>
    {#if candidates.length === 0}
      <p>No CSV files found in `CSVs/`.</p>
    {:else}
      <ul>
        {#each candidates as c}
          <li>
            <button on:click={() => pickCandidate(c)}>{c.file_name}</button>
            {#if !c.is_configured_institution}
              <span class="warn">Unconfigured institution</span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <div class="panel">
    <h3>Preview Settings</h3>
    <label>CSV path <input bind:value={selectedPath} /></label>
    <label>Year <input bind:value={year} /></label>
    <label>Institution
      <select bind:value={institution}>
        <option value="">Select...</option>
        {#each institutions as inst}
          <option value={inst}>{inst}</option>
        {/each}
      </select>
    </label>
    <button disabled={loading || !selectedPath || !year || !institution} on:click={runPreview}>Preview Import</button>
  </div>

  {#if preview}
    <div class="panel">
      <h3>Stage {preview.stageId}</h3>
      <p>Status: {preview.status}</p>
      <p>Target: {preview.targetJournalPath}</p>
      {#if preview.summary}
        <p>Transactions: {preview.summary.count} | Unknowns: {preview.summary.unknownCount}</p>
      {/if}

      {#if preview.result}
        <p>Applied. Appended transactions: {preview.result.appendedTxnCount}</p>
        {#if preview.result.backupPath}<p>Backup: {preview.result.backupPath}</p>{/if}
      {:else}
        <button disabled={loading} on:click={applyStage}>Apply Import</button>
      {/if}

      {#if preview.preview?.length}
        <h4>Transaction Preview</h4>
        <pre>{preview.preview.slice(0, 10).join('\n\n')}</pre>
      {/if}
    </div>
  {/if}
</section>

<style>
  .panel {
    background: #fff;
    border: 1px solid #d2e0ee;
    border-radius: 10px;
    padding: 1rem;
    margin-bottom: 1rem;
  }

  label {
    display: block;
    margin-bottom: 0.6rem;
  }

  input, select {
    display: block;
    margin-top: 0.25rem;
    width: min(36rem, 100%);
    padding: 0.45rem;
  }

  button {
    padding: 0.45rem 0.75rem;
  }

  .warn { color: #9a6417; margin-left: 0.5rem; }
  .error { color: #9f1c1c; }
  pre {
    white-space: pre-wrap;
    max-height: 320px;
    overflow: auto;
    background: #f9fcff;
    border: 1px solid #e2ebf3;
    padding: 0.75rem;
  }
</style>
