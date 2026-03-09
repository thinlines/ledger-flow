<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';

  type Candidate = {
    file_name: string;
    abs_path: string;
    detected_year: string | null;
    detected_institution: string | null;
    detected_institution_display_name: string | null;
    is_configured_institution: boolean;
  };
  type InstitutionOption = { id: string; displayName: string; defaultAccount?: string };

  let initialized = false;
  let candidates: Candidate[] = [];
  let institutions: InstitutionOption[] = [];
  let selectedPath = '';
  let year = String(new Date().getFullYear());
  let institution = '';
  let destinationAccount = '';
  let selectedFile: File | null = null;
  let preview: any = null;
  let error = '';
  let loading = false;

  async function loadCandidates() {
    try {
      const state = await apiGet<{ initialized: boolean }>('/api/app/state');
      initialized = state.initialized;
      if (!initialized) return;

      const data = await apiGet<{ candidates: Candidate[]; institutions: InstitutionOption[] }>('/api/import/candidates');
      candidates = data.candidates;
      institutions = data.institutions;
    } catch (e) {
      error = String(e);
    }
  }

  async function uploadFile() {
    if (!selectedFile || !institution || !year) return;
    loading = true;
    error = '';
    try {
      const form = new FormData();
      form.append('file', selectedFile);
      form.append('year', year);
      form.append('institution', institution);

      const res = await fetch('/api/import/upload', { method: 'POST', body: form });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || 'Upload failed');
      }
      const data = (await res.json()) as { absPath: string };
      selectedPath = data.absPath;
      selectedFile = null;
      await loadCandidates();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
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
        institution,
        destinationAccount: destinationAccount || null
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
      selectedPath = '';
      await loadCandidates();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function pickCandidate(c: Candidate) {
    selectedPath = c.abs_path;
    year = c.detected_year ?? year;
    institution = c.detected_institution ?? '';
    const picked = institutions.find((x) => x.id === institution);
    if (picked?.defaultAccount) {
      destinationAccount = picked.defaultAccount;
    }
  }

  function onInstitutionChange(id: string) {
    institution = id;
    const picked = institutions.find((x) => x.id === id);
    if (picked?.defaultAccount) {
      destinationAccount = picked.defaultAccount;
    }
  }

  onMount(loadCandidates);
</script>

<section class="view-card hero">
  <p class="eyebrow">Import Center</p>
  <h2 class="page-title">Preview and Import Transactions</h2>
  <p class="subtitle">Upload a statement, preview match results, and apply only net-new transactions.</p>
</section>

{#if !initialized}
  <section class="view-card">
    <p class="error-text">Workspace not initialized yet.</p>
    <a class="btn btn-primary" href="/setup">Go to Setup</a>
  </section>
{:else}
  {#if error}
    <section class="view-card"><p class="error-text">{error}</p></section>
  {/if}

  <section class="grid-2">
    <article class="view-card">
      <p class="eyebrow">Step 1</p>
      <h3>Upload Statement File</h3>

      <div class="field grid-2 compact">
        <div class="field">
          <label for="uploadInstitution">Institution</label>
          <select id="uploadInstitution" bind:value={institution} on:change={(e) => onInstitutionChange((e.currentTarget as HTMLSelectElement).value)}>
            <option value="">Select...</option>
            {#each institutions as inst}
              <option value={inst.id}>{inst.displayName}</option>
            {/each}
          </select>
        </div>
        <div class="field">
          <label for="uploadYear">Year</label>
          <input id="uploadYear" bind:value={year} />
        </div>
      </div>

      <div class="field">
        <label for="statementFile">CSV File</label>
        <input
          id="statementFile"
          type="file"
          accept=".csv,text/csv"
          on:change={(e) => (selectedFile = (e.currentTarget as HTMLInputElement).files?.[0] ?? null)}
        />
      </div>

      <button class="btn btn-primary" disabled={loading || !selectedFile || !institution || !year} on:click={uploadFile}>
        {loading ? 'Uploading...' : 'Upload File'}
      </button>
      <p class="muted">Uploaded files are saved to your workspace inbox and auto-detected below.</p>
    </article>

    <article class="view-card">
      <p class="eyebrow">Step 2</p>
      <h3>Detected CSV Files</h3>
      {#if candidates.length === 0}
        <p class="muted">No CSV files found in workspace inbox.</p>
      {:else}
        <div class="list">
          {#each candidates as c}
            <button class="row" on:click={() => pickCandidate(c)}>
              <span>{c.file_name}</span>
              {#if c.detected_institution_display_name}
                <span class="muted small">{c.detected_institution_display_name}</span>
              {/if}
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
      <p class="eyebrow">Step 3</p>
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
          <select id="institution" bind:value={institution} on:change={(e) => onInstitutionChange((e.currentTarget as HTMLSelectElement).value)}>
            <option value="">Select...</option>
            {#each institutions as inst}
              <option value={inst.id}>{inst.displayName}</option>
            {/each}
          </select>
        </div>
      </div>

      <div class="field">
        <label for="destinationAccount">Destination Account</label>
        <input id="destinationAccount" bind:value={destinationAccount} placeholder="Assets:Bank:Checking" />
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
          {#if preview.result.archivedCsvPath}
            <p class="muted">Archived source: {preview.result.archivedCsvPath}</p>
          {/if}
          {#if preview.result.sourceCsvWarning}
            <p class="error-text">{preview.result.sourceCsvWarning}</p>
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

  .summary {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    margin-bottom: 0.8rem;
  }

  .small {
    margin-left: 0.5rem;
    font-size: 0.8rem;
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
