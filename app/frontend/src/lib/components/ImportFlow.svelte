<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';

  type Candidate = {
    file_name: string;
    abs_path: string;
    detected_year: string | null;
    detected_import_account_id: string | null;
    detected_import_account_display_name: string | null;
    detected_institution_display_name: string | null;
    is_configured_import_account: boolean;
  };

  type ImportAccountOption = {
    id: string;
    displayName: string;
    institutionDisplayName: string;
    ledgerAccount: string;
    last4?: string | null;
  };

  type PreviewResult = {
    stageId: string;
    importAccountDisplayName?: string;
    destinationAccount?: string;
    summary?: {
      newCount: number;
      duplicateCount: number;
      conflictCount: number;
      unknownCount: number;
    };
    preview?: string[];
    targetJournalPath?: string;
    result?: {
      applied: boolean;
      backupPath?: string | null;
      archivedCsvPath?: string | null;
      appendedTxnCount: number;
      skippedDuplicateCount: number;
      conflicts?: Array<{ warning?: string }>;
      sourceCsvWarning?: string | null;
    };
  };

  type ImportHistoryEntry = {
    id: string;
    status: 'applied' | 'undone';
    appliedAt: string;
    importAccountId?: string;
    importAccountDisplayName?: string;
    destinationAccount?: string;
    csvFileName?: string;
    originalCsvPath?: string | null;
    archivedCsvPath?: string | null;
    targetJournalPath?: string;
    backupPath?: string | null;
    canUndo: boolean;
    undoBlockedReason?: string | null;
    result?: {
      appendedTxnCount?: number;
      skippedDuplicateCount?: number;
      conflicts?: Array<{ warning?: string }>;
      sourceCsvWarning?: string | null;
    };
    summary?: {
      conflictCount?: number;
    };
    undo?: {
      undoneAt?: string;
      undoBackupPath?: string | null;
      restoredInboxCsvPath?: string | null;
      sourceCsvWarning?: string | null;
    };
  };

  type WorkflowStep = 'prepare' | 'preview' | 'apply' | 'complete';
  type LoadingState = 'idle' | 'upload' | 'preview' | 'apply' | 'undo';
  type FollowUpAction = {
    href: string;
    label: string;
    note: string;
    secondary: {
      href: string;
      label: string;
    };
  };

  export let mode: 'standalone' | 'setup' = 'standalone';
  export let refreshToken = 0;
  export let onApplied: ((preview: PreviewResult) => void | Promise<void>) | null = null;

  let initialized = false;
  let candidates: Candidate[] = [];
  let importAccounts: ImportAccountOption[] = [];
  let selectedPath = '';
  let year = String(new Date().getFullYear());
  let importAccountId = '';
  let selectedFile: File | null = null;
  let preview: PreviewResult | null = null;
  let historyEntries: ImportHistoryEntry[] = [];
  let historyMessage = '';
  let error = '';
  let loading = false;
  let loadingState: LoadingState = 'idle';
  let hydrated = false;
  let lastRefreshToken = refreshToken;
  let statementFileInput: HTMLInputElement | null = null;
  let workflowStep: WorkflowStep = 'prepare';
  let selectedImportAccount: ImportAccountOption | null = null;
  let selectedCandidate: Candidate | null = null;
  let uploadReady = false;
  let previewReady = false;

  $: selectedImportAccount = importAccounts.find((account) => account.id === importAccountId) ?? null;
  $: selectedCandidate = candidates.find((candidate) => candidate.abs_path === selectedPath) ?? null;
  $: uploadReady = Boolean(selectedFile && importAccountId && year);
  $: previewReady = Boolean(selectedPath && importAccountId && year);
  $: workflowStep = preview?.result ? 'complete' : preview ? 'apply' : selectedPath ? 'preview' : 'prepare';
  $: loading = loadingState !== 'idle';
  $: if (hydrated && refreshToken !== lastRefreshToken) {
    lastRefreshToken = refreshToken;
    void loadImportData();
  }

  function pathLabel(path: string): string {
    const parts = path.split('/').filter(Boolean);
    return parts.at(-1) ?? path;
  }

  function optionalPathLabel(path?: string | null, fallback = 'Unknown file'): string {
    return path ? pathLabel(path) : fallback;
  }

  function importResultAction(): FollowUpAction | null {
    if (!preview?.result) return null;

    const unknownCount = preview.summary?.unknownCount ?? 0;
    if (unknownCount > 0) {
      return {
        href: '/unknowns',
        label: unknownCount === 1 ? 'Review 1 transaction' : `Review ${unknownCount} transactions`,
        note: 'Imported activity is in. Review the remaining uncategorized transactions next so balances and recent activity stay clean.',
        secondary: {
          href: '/',
          label: 'See overview'
        }
      };
    }

    return {
      href: '/',
      label: 'See overview',
      note: 'Imported activity is in and nothing from this statement still needs review.',
      secondary: {
        href: '/transactions',
        label: 'Open transactions'
      }
    };
  }

  function accountLabel(account: ImportAccountOption): string {
    return account.last4 ? `${account.displayName} ••${account.last4}` : account.displayName;
  }

  function formatDateTime(value?: string | null): string {
    if (!value) return 'Unknown time';
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? value
      : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  async function loadImportData() {
    try {
      const state = await apiGet<{ initialized: boolean }>('/api/app/state');
      initialized = state.initialized;
      if (!initialized) {
        candidates = [];
        importAccounts = [];
        historyEntries = [];
        preview = null;
        return;
      }

      const [candidateData, historyData] = await Promise.all([
        apiGet<{ candidates: Candidate[]; importAccounts: ImportAccountOption[] }>('/api/import/candidates'),
        apiGet<{ history: ImportHistoryEntry[] }>('/api/import/history')
      ]);

      candidates = candidateData.candidates;
      importAccounts = candidateData.importAccounts;
      historyEntries = historyData.history;

      if (!importAccountId && importAccounts.length === 1) {
        importAccountId = importAccounts[0].id;
      }

      if (importAccountId && !importAccounts.some((account) => account.id === importAccountId)) {
        importAccountId = '';
      }
    } catch (e) {
      error = String(e);
    }
  }

  async function uploadFile() {
    if (!selectedFile || !importAccountId || !year) return;

    loadingState = 'upload';
    error = '';
    historyMessage = '';
    preview = null;

    try {
      const form = new FormData();
      form.append('file', selectedFile);
      form.append('year', year);
      form.append('importAccountId', importAccountId);

      const res = await fetch('/api/import/upload', { method: 'POST', body: form });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || 'Upload failed');
      }

      const data = (await res.json()) as { absPath: string };
      selectedPath = data.absPath;
      selectedFile = null;
      if (statementFileInput) statementFileInput.value = '';
      await loadImportData();
    } catch (e) {
      error = String(e);
    } finally {
      loadingState = 'idle';
    }
  }

  async function runPreview() {
    error = '';
    historyMessage = '';
    preview = null;
    loadingState = 'preview';

    try {
      preview = await apiPost<PreviewResult>('/api/import/preview', {
        csvPath: selectedPath,
        year,
        importAccountId
      });
    } catch (e) {
      error = String(e);
    } finally {
      loadingState = 'idle';
    }
  }

  async function applyStage() {
    if (!preview?.stageId) return;

    error = '';
    historyMessage = '';
    loadingState = 'apply';

    try {
      preview = await apiPost<PreviewResult>('/api/import/apply', { stageId: preview.stageId });
      selectedPath = '';
      await loadImportData();

      if (preview && onApplied) {
        await onApplied(preview);
      }
    } catch (e) {
      error = String(e);
    } finally {
      loadingState = 'idle';
    }
  }

  function pickCandidate(candidate: Candidate) {
    selectedPath = candidate.abs_path;
    year = candidate.detected_year ?? year;
    importAccountId = candidate.detected_import_account_id ?? '';
    preview = null;
  }

  async function undoHistoryEntry(entry: ImportHistoryEntry) {
    if (!entry.canUndo) return;

    const confirmed = window.confirm(
      `Undo ${entry.csvFileName ?? 'this import'}? This removes the transactions added by this import and creates a recovery backup first.`
    );
    if (!confirmed) return;

    error = '';
    historyMessage = '';
    loadingState = 'undo';

    try {
      const data = await apiPost<{ entry: ImportHistoryEntry }>('/api/import/undo', {
        historyId: entry.id
      });
      preview = null;
      await loadImportData();
      historyMessage = data.entry.undo?.restoredInboxCsvPath
        ? 'Import undone, its transactions were removed, and the source statement was restored to the inbox.'
        : 'Import undone and its transactions were removed.';
    } catch (e) {
      error = String(e);
    } finally {
      loadingState = 'idle';
    }
  }

  onMount(async () => {
    hydrated = true;
    lastRefreshToken = refreshToken;
    await loadImportData();
  });
</script>

<div class="import-flow">
  {#if mode === 'standalone'}
    <section class="view-card hero import-hero">
      <p class="eyebrow">Import</p>
      <h2 class="page-title">Bring in new statement activity</h2>
      <p class="subtitle">Work through one statement at a time: upload it, preview the append, and only then write changes.</p>
    </section>
  {/if}

  {#if !initialized}
    <section class="view-card">
      <p class="eyebrow">Import</p>
      <h3>Finish setup before importing statements</h3>
      <p class="muted">Import becomes available after the workspace exists and at least one account is ready to receive statement activity.</p>
      <a class="btn btn-primary" href="/setup">Open setup</a>
    </section>
  {:else}
    {#if error}
      <section class="view-card"><p class="error-text">{error}</p></section>
    {/if}

    {#if importAccounts.length === 0}
      <section class="view-card">
        <p class="eyebrow">Import</p>
        <h3>Add an account before importing</h3>
        <p class="muted">Connect a supported account or save a custom CSV mapping first. Then statement imports can flow straight into review and overview.</p>
        <div class="actions">
          <a class="btn btn-primary" href="/accounts/configure?mode=institution">Add supported account</a>
          <a class="btn" href="/accounts/configure?mode=custom">Add custom CSV</a>
        </div>
      </section>
    {:else if mode === 'setup'}
      <section class="view-card setup-workflow-card">
        <div class="section-head setup-workflow-head">
          <div>
            <p class="eyebrow">Prepare</p>
            <h3>Upload and preview your first statement</h3>
            <p class="muted">Use one vertical flow for the first import. Nothing is written until you apply the preview.</p>
          </div>
          {#if candidates.length > 0}
            <span class="pill">{candidates.length} waiting</span>
          {/if}
        </div>

        <div class="workflow-field-grid">
          <div class="field">
            <label for={`importAccountId-${mode}`}>Import account</label>
            <select id={`importAccountId-${mode}`} bind:value={importAccountId}>
              <option value="">Select...</option>
              {#each importAccounts as account}
                <option value={account.id}>{accountLabel(account)}</option>
              {/each}
            </select>
          </div>

          <div class="field">
            <label for={`year-${mode}`}>Statement year</label>
            <input id={`year-${mode}`} bind:value={year} inputmode="numeric" />
          </div>
        </div>

        <div class="upload-row">
          <div class="field upload-field">
            <label for={`statementFile-${mode}`}>Upload a CSV</label>
            <input
              id={`statementFile-${mode}`}
              bind:this={statementFileInput}
              type="file"
              accept=".csv,text/csv"
              on:change={(e) => (selectedFile = (e.currentTarget as HTMLInputElement).files?.[0] ?? null)}
            />
            {#if selectedFile}
              <p class="muted small">Ready to upload: {selectedFile.name}</p>
            {:else}
              <p class="muted small">Upload a new statement or pick one already waiting in the inbox.</p>
            {/if}
          </div>

          <button class="btn" type="button" disabled={loading || !uploadReady} on:click={uploadFile}>
            {loadingState === 'upload' ? 'Uploading...' : 'Upload Statement'}
          </button>
        </div>

        <section class="setup-inbox-section">
          <div class="section-head">
            <div>
              <p class="eyebrow">Inbox</p>
              <h3>Pick a statement to continue</h3>
              <p class="muted">Uploaded statements appear here immediately and can be previewed when you are ready.</p>
            </div>
            {#if candidates.length > 0}
              <span class="pill">{candidates.length} waiting</span>
            {/if}
          </div>

          {#if candidates.length === 0}
            <div class="empty-panel">
              <h4>No statements in the inbox</h4>
              <p>Upload a CSV to start the first import.</p>
            </div>
          {:else}
            <div class="list">
              {#each candidates as candidate}
                <button
                  class="row"
                  class:row-selected={candidate.abs_path === selectedPath}
                  type="button"
                  aria-pressed={candidate.abs_path === selectedPath}
                  on:click={() => pickCandidate(candidate)}
                >
                  <div class="row-main">
                    <p class="row-title">{candidate.file_name}</p>
                    <div class="row-meta">
                      {#if candidate.detected_import_account_display_name}
                        <span>{candidate.detected_import_account_display_name}</span>
                      {/if}
                      {#if candidate.detected_institution_display_name}
                        <span>{candidate.detected_institution_display_name}</span>
                      {/if}
                      {#if candidate.detected_year}
                        <span>{candidate.detected_year}</span>
                      {/if}
                    </div>
                  </div>

                  <div class="row-side">
                    {#if candidate.is_configured_import_account}
                      <span class="pill ok">Ready</span>
                    {:else}
                      <span class="pill warn">Needs setup</span>
                    {/if}

                    {#if candidate.abs_path === selectedPath}
                      <span class="row-selected-note">Selected</span>
                    {/if}
                  </div>
                </button>
              {/each}
            </div>
          {/if}
        </section>

        <div class="workflow-status-grid">
          <section class="status-card">
            <p class="status-label">Selected statement</p>
            <p class="status-value">{selectedPath ? pathLabel(selectedPath) : 'No statement selected yet'}</p>
            <p class="muted small">
              {#if selectedCandidate}
                Chosen from the inbox.
              {:else if selectedFile}
                Upload the selected CSV to move it into the inbox.
              {:else}
                Pick a waiting statement or upload one above.
              {/if}
            </p>
          </section>

          <section class="status-card">
            <p class="status-label">Import target</p>
            <p class="status-value">{selectedImportAccount ? accountLabel(selectedImportAccount) : 'Choose an import account'}</p>
            <p class="muted small">
              {#if selectedImportAccount}
                {selectedImportAccount.institutionDisplayName} • This statement will flow into balances, transactions, and review for this account.
              {:else}
                The selected account decides where this statement lands after import.
              {/if}
            </p>
          </section>
        </div>

        {#if selectedCandidate && !selectedCandidate.is_configured_import_account}
          <p class="error-text inline-message">
            This statement needs account setup before it can be previewed. Configure the account or choose another statement.
          </p>
        {/if}

        <details class="advanced-panel">
          <summary>Advanced file selection</summary>
          <div class="field advanced-field">
            <label for={`csvPath-${mode}`}>Statement path</label>
            <input id={`csvPath-${mode}`} bind:value={selectedPath} />
          </div>
        </details>

        <div class="workflow-footer">
          <p class="muted">Nothing is written until you apply the preview. Duplicate transactions are skipped automatically.</p>
          <button class="btn btn-primary" type="button" disabled={loading || !previewReady} on:click={runPreview}>
            {loadingState === 'preview' ? 'Preparing preview...' : preview && !preview.result ? 'Refresh Preview' : 'Preview Import'}
          </button>
        </div>
      </section>

      {#if preview}
        <section class="view-card setup-preview-card">
          <div class="preview-card-shell">
            <div class="preview-header">
              <div>
                <p class="eyebrow">{preview.result ? 'Import Result' : 'Preview'}</p>
                <h3>{preview.result ? 'Statement imported' : 'Review the import'}</h3>
                <p class="muted">
                  {preview.result
                    ? 'The selected statement was appended. Setup will move on after the first import completes.'
                    : 'Check the counts and sample output before applying changes.'}
                </p>
              </div>

              {#if !preview.result}
                <button class="btn btn-primary" type="button" disabled={loading} on:click={applyStage}>
                  {loadingState === 'apply' ? 'Applying...' : 'Apply Import'}
                </button>
              {/if}
            </div>

            <div class="preview-status-grid">
              {#if preview.importAccountDisplayName}
                <section class="status-card">
                  <p class="status-label">Preview account</p>
                  <p class="status-value">{preview.importAccountDisplayName}</p>
                  <p class="muted small">This statement will update the selected account when you apply the preview.</p>
                </section>
              {/if}
            </div>

            {#if preview.summary}
              <div class="summary">
                <span class="pill ok">New {preview.summary.newCount}</span>
                <span class="pill">Duplicates {preview.summary.duplicateCount}</span>
                <span class="pill warn">Conflicts {preview.summary.conflictCount}</span>
                <span class="pill">Unknown {preview.summary.unknownCount}</span>
              </div>
            {/if}

            {#if preview.result}
              <div class="result-banner">
                <div>
                  <p class="result-title">Import applied</p>
                  <p class="muted">
                    Added {preview.result.appendedTxnCount}, skipped {preview.result.skippedDuplicateCount} duplicates, conflicts
                    {preview.result.conflicts?.length ?? 0}.
                  </p>
                </div>
                <span class="pill ok">Complete</span>
              </div>

              {#if preview.result.sourceCsvWarning}
                <p class="error-text inline-message">{preview.result.sourceCsvWarning}</p>
              {/if}
            {/if}

            <details class="advanced-panel">
              <summary>Technical details</summary>
              <div class="setup-advanced-copy">
                <p class="muted small">Import stage: {preview.stageId}</p>
                {#if preview.targetJournalPath}
                  <p class="muted small">Destination file: {preview.targetJournalPath}</p>
                {/if}
                {#if preview.result?.backupPath}
                  <p class="muted small">Backup: {preview.result.backupPath}</p>
                {/if}
                {#if preview.result?.archivedCsvPath}
                  <p class="muted small">Archived source: {preview.result.archivedCsvPath}</p>
                {/if}
              </div>
            </details>

            {#if preview.preview?.length}
              <div class="sample-block">
                <div class="sample-head">
                  <h4>Sample transactions</h4>
                  <p class="muted small">Showing the first {Math.min(preview.preview.length, 8)} items from the preview.</p>
                </div>
                <pre>{preview.preview.slice(0, 8).join('\n\n')}</pre>
              </div>
            {/if}
          </div>
        </section>
      {/if}
    {:else}
      <section class="import-layout">
        <article class="view-card workflow-card">
          <div class="workflow-head">
            <div class="workflow-copy">
              <p class="eyebrow">Current Workflow</p>
              <h3>Upload, preview, then import</h3>
              <p class="muted">Keep the current statement in one place instead of splitting the task across multiple cards.</p>
            </div>

            <div class="workflow-steps" aria-label="Import progress">
              <div
                class="workflow-step"
                class:workflow-step-active={workflowStep === 'prepare'}
                class:workflow-step-complete={Boolean(selectedPath || preview)}
              >
                <span class="step-index">1</span>
                <div class="workflow-step-copy">
                  <strong>Prepare</strong>
                  <span class="muted small">Choose the account, year, and statement.</span>
                </div>
              </div>

              <div
                class="workflow-step"
                class:workflow-step-active={workflowStep === 'preview'}
                class:workflow-step-complete={Boolean(preview)}
              >
                <span class="step-index">2</span>
                <div class="workflow-step-copy">
                  <strong>Preview</strong>
                  <span class="muted small">Review counts and sample transactions.</span>
                </div>
              </div>

              <div
                class="workflow-step"
                class:workflow-step-active={workflowStep === 'apply'}
                class:workflow-step-complete={Boolean(preview?.result)}
              >
                <span class="step-index">3</span>
                <div class="workflow-step-copy">
                  <strong>Apply</strong>
                  <span class="muted small">Append new transactions and log the result.</span>
                </div>
              </div>
            </div>
          </div>

          <div class="workflow-field-grid">
            <div class="field">
              <label for={`importAccountId-${mode}`}>Import account</label>
              <select id={`importAccountId-${mode}`} bind:value={importAccountId}>
                <option value="">Select...</option>
                {#each importAccounts as account}
                  <option value={account.id}>{accountLabel(account)}</option>
                {/each}
              </select>
            </div>

            <div class="field">
              <label for={`year-${mode}`}>Statement year</label>
              <input id={`year-${mode}`} bind:value={year} inputmode="numeric" />
            </div>
          </div>

          <div class="upload-row">
            <div class="field upload-field">
              <label for={`statementFile-${mode}`}>Upload a CSV</label>
              <input
                id={`statementFile-${mode}`}
                bind:this={statementFileInput}
                type="file"
                accept=".csv,text/csv"
                on:change={(e) => (selectedFile = (e.currentTarget as HTMLInputElement).files?.[0] ?? null)}
              />
              {#if selectedFile}
                <p class="muted small">Ready to upload: {selectedFile.name}</p>
              {:else}
                <p class="muted small">Upload a new statement or pick one already waiting in the inbox.</p>
              {/if}
            </div>

            <button class="btn" type="button" disabled={loading || !uploadReady} on:click={uploadFile}>
              {loadingState === 'upload' ? 'Uploading...' : 'Upload Statement'}
            </button>
          </div>

          <div class="workflow-status-grid">
            <section class="status-card">
              <p class="status-label">Selected statement</p>
              <p class="status-value">{selectedPath ? pathLabel(selectedPath) : 'No statement selected yet'}</p>
              <p class="muted small">
                {#if selectedCandidate}
                  Chosen from the inbox.
                {:else if selectedFile}
                  Upload the selected CSV to move it into the inbox.
                {:else}
                  Pick a waiting statement or upload one above.
                {/if}
              </p>
            </section>

            <section class="status-card">
              <p class="status-label">Import target</p>
              <p class="status-value">{selectedImportAccount ? accountLabel(selectedImportAccount) : 'Choose an import account'}</p>
              <p class="muted small">
                {#if selectedImportAccount}
                  {selectedImportAccount.institutionDisplayName} • This statement will flow into balances, transactions, and review for this account.
                {:else}
                  The selected account decides where this statement lands after import.
                {/if}
              </p>
            </section>
          </div>

          {#if selectedCandidate && !selectedCandidate.is_configured_import_account}
            <p class="error-text inline-message">
              This statement needs account setup before it can be previewed. Configure the account or choose another statement.
            </p>
          {/if}

          <details class="advanced-panel compact-panel">
            <summary>Advanced file selection</summary>
            <div class="field advanced-field">
              <label for={`csvPath-${mode}`}>Statement path</label>
              <input id={`csvPath-${mode}`} bind:value={selectedPath} />
            </div>
          </details>

          <div class="workflow-footer">
            <p class="muted">Nothing is written until you apply the preview. Duplicate transactions are skipped automatically.</p>
            <button class="btn btn-primary" type="button" disabled={loading || !previewReady} on:click={runPreview}>
              {loadingState === 'preview' ? 'Preparing preview...' : preview && !preview.result ? 'Refresh Preview' : 'Preview Import'}
            </button>
          </div>

          {#if preview}
            <section class="preview-panel">
              <div class="preview-header">
                <div>
                  <p class="eyebrow">{preview.result ? 'Import Result' : 'Preview'}</p>
                  <h4>{preview.result ? 'Statement imported' : 'Review the import'}</h4>
                  <p class="muted">
                    {preview.result
                      ? 'The selected statement was appended and recorded in import history.'
                      : 'Check the counts and sample output before applying changes.'}
                  </p>
                </div>

                {#if !preview.result}
                  <button class="btn btn-primary" type="button" disabled={loading} on:click={applyStage}>
                    {loadingState === 'apply' ? 'Applying...' : 'Apply Import'}
                  </button>
                {/if}
              </div>

              <div class="preview-status-grid">
                {#if preview.importAccountDisplayName}
                  <section class="status-card">
                    <p class="status-label">Preview account</p>
                    <p class="status-value">{preview.importAccountDisplayName}</p>
                    <p class="muted small">This statement will update the selected account when you apply the preview.</p>
                  </section>
                {/if}
              </div>

              {#if preview.summary}
                <div class="summary">
                  <span class="pill ok">New {preview.summary.newCount}</span>
                  <span class="pill">Duplicates {preview.summary.duplicateCount}</span>
                  <span class="pill warn">Conflicts {preview.summary.conflictCount}</span>
                  <span class="pill">Unknown {preview.summary.unknownCount}</span>
                </div>
              {/if}

              {#if preview.result}
                <div class="result-banner">
                  <div>
                    <p class="result-title">Import applied</p>
                    <p class="muted">
                      Added {preview.result.appendedTxnCount}, skipped {preview.result.skippedDuplicateCount} duplicates, conflicts
                      {preview.result.conflicts?.length ?? 0}.
                    </p>
                  </div>
                  <span class="pill ok">Complete</span>
                </div>

                {#if importResultAction()}
                  <div class="next-step-banner">
                    <div>
                      <p class="result-title">Next step</p>
                      <p class="muted">{importResultAction()?.note}</p>
                    </div>
                    <div class="actions">
                      <a class="btn btn-primary" href={importResultAction()?.href}>{importResultAction()?.label}</a>
                      <a class="btn" href={importResultAction()?.secondary.href}>{importResultAction()?.secondary.label}</a>
                    </div>
                  </div>
                {/if}

                {#if preview.result.sourceCsvWarning}
                  <p class="error-text inline-message">{preview.result.sourceCsvWarning}</p>
                {/if}
              {/if}

              <details class="advanced-panel compact-panel">
                <summary>Technical details</summary>
                <p class="muted small">Import stage: {preview.stageId}</p>
                {#if preview.targetJournalPath}
                  <p class="muted small">Destination file: {preview.targetJournalPath}</p>
                {/if}
                {#if preview.result?.backupPath}
                  <p class="muted small">Backup: {preview.result.backupPath}</p>
                {/if}
                {#if preview.result?.archivedCsvPath}
                  <p class="muted small">Archived source: {preview.result.archivedCsvPath}</p>
                {/if}
              </details>

              {#if preview.preview?.length}
                <div class="sample-block">
                  <div class="sample-head">
                    <h4>Sample transactions</h4>
                    <p class="muted small">Showing the first {Math.min(preview.preview.length, 8)} items from the preview.</p>
                  </div>
                  <pre>{preview.preview.slice(0, 8).join('\n\n')}</pre>
                </div>
              {/if}
            </section>
          {/if}
        </article>

        <aside class="import-sidebar">
          <article class="view-card inbox-card">
            <div class="section-head">
              <div>
                <p class="eyebrow">Waiting Statements</p>
                <h3>Pick a statement to continue</h3>
                <p class="muted">The inbox stays available while you upload, preview, and decide what to import.</p>
              </div>
              {#if candidates.length > 0}
                <span class="pill">{candidates.length} waiting</span>
              {/if}
            </div>

            {#if candidates.length === 0}
              <div class="empty-panel">
                <h4>No statements in the inbox</h4>
                <p>Upload a CSV to start a new import.</p>
              </div>
            {:else}
              <div class="list">
                {#each candidates as candidate}
                  <button
                    class="row"
                    class:row-selected={candidate.abs_path === selectedPath}
                    type="button"
                    aria-pressed={candidate.abs_path === selectedPath}
                    on:click={() => pickCandidate(candidate)}
                  >
                    <div class="row-main">
                      <p class="row-title">{candidate.file_name}</p>
                      <div class="row-meta">
                        {#if candidate.detected_import_account_display_name}
                          <span>{candidate.detected_import_account_display_name}</span>
                        {/if}
                        {#if candidate.detected_institution_display_name}
                          <span>{candidate.detected_institution_display_name}</span>
                        {/if}
                        {#if candidate.detected_year}
                          <span>{candidate.detected_year}</span>
                        {/if}
                      </div>
                    </div>

                    <div class="row-side">
                      {#if candidate.is_configured_import_account}
                        <span class="pill ok">Ready</span>
                      {:else}
                        <span class="pill warn">Needs setup</span>
                      {/if}

                      {#if candidate.abs_path === selectedPath}
                        <span class="row-selected-note">Selected</span>
                      {/if}
                    </div>
                  </button>
                {/each}
              </div>
            {/if}
          </article>
        </aside>
      </section>
      <section class="view-card import-history-card">
        <div class="section-head history-header">
          <div>
            <p class="eyebrow">Import History</p>
            <h3>Recent imports</h3>
            <p class="muted">Undo is available for the latest applied import in each destination year.</p>
          </div>
          {#if historyEntries.length > 0}
            <span class="pill">{historyEntries.length} recorded</span>
          {/if}
        </div>

        {#if historyMessage}
          <p class="success-text">{historyMessage}</p>
        {/if}

        {#if !initialized}
          <p class="muted">Complete workspace setup to start recording import history.</p>
        {:else if historyEntries.length === 0}
          <div class="empty-panel">
            <h4>No imports have been applied yet</h4>
            <p>Your recent imports and undo actions will appear here.</p>
          </div>
        {:else}
          <div class="history-list">
            {#each historyEntries as entry}
              <article class="history-row">
                <div class="history-main">
                  <div class="history-topline">
                    <p class="history-title">{entry.csvFileName ?? optionalPathLabel(entry.originalCsvPath)}</p>
                    <span class={`pill ${entry.status === 'undone' ? 'warn' : 'ok'}`}>
                      {entry.status === 'undone' ? 'Undone' : 'Applied'}
                    </span>
                  </div>

                  <p class="muted small history-meta">
                    {formatDateTime(entry.appliedAt)} • {entry.importAccountDisplayName ?? entry.importAccountId} •
                    {optionalPathLabel(entry.targetJournalPath, 'Unknown journal')}
                  </p>

                  <div class="summary">
                    <span class="pill ok">Added {entry.result?.appendedTxnCount ?? 0}</span>
                    <span class="pill">Duplicates {entry.result?.skippedDuplicateCount ?? 0}</span>
                    <span class="pill warn">
                      Conflicts {entry.summary?.conflictCount ?? entry.result?.conflicts?.length ?? 0}
                    </span>
                  </div>

                  {#if entry.undo?.undoneAt}
                    <p class="muted small">Undone {formatDateTime(entry.undo.undoneAt)}.</p>
                  {:else if !entry.canUndo && entry.undoBlockedReason}
                    <p class="muted small">{entry.undoBlockedReason}</p>
                  {/if}

                  <details class="advanced-panel history-details">
                    <summary>Paths and recovery details</summary>
                    {#if entry.targetJournalPath}
                      <p class="muted small">Journal: {entry.targetJournalPath}</p>
                    {/if}
                    {#if entry.backupPath}
                      <p class="muted small">Import backup: {entry.backupPath}</p>
                    {/if}
                    {#if entry.undo?.undoBackupPath}
                      <p class="muted small">Undo backup: {entry.undo.undoBackupPath}</p>
                    {/if}
                    {#if entry.originalCsvPath}
                      <p class="muted small">Original statement: {entry.originalCsvPath}</p>
                    {/if}
                    {#if entry.archivedCsvPath}
                      <p class="muted small">Archived statement: {entry.archivedCsvPath}</p>
                    {/if}
                    {#if entry.undo?.restoredInboxCsvPath}
                      <p class="muted small">Restored to inbox: {entry.undo.restoredInboxCsvPath}</p>
                    {/if}
                    {#if entry.result?.sourceCsvWarning}
                      <p class="error-text">{entry.result.sourceCsvWarning}</p>
                    {/if}
                    {#if entry.undo?.sourceCsvWarning}
                      <p class="error-text">{entry.undo.sourceCsvWarning}</p>
                    {/if}
                  </details>
                </div>

                <div class="history-actions">
                  <button class="btn" type="button" disabled={loading || !entry.canUndo} on:click={() => undoHistoryEntry(entry)}>
                    Undo Import
                  </button>
                </div>
              </article>
            {/each}
          </div>
        {/if}
      </section>
    {/if}
  {/if}
</div>

<style>
  h3,
  h4 {
    margin: 0;
  }

  .import-flow {
    display: grid;
    gap: 1rem;
  }

  .import-hero {
    display: grid;
    gap: 0.35rem;
  }

  .import-layout {
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(19rem, 0.9fr);
    gap: 1rem;
    align-items: start;
  }

  .setup-workflow-card,
  .setup-preview-card,
  .workflow-card,
  .import-sidebar,
  .import-history-card {
    display: grid;
    gap: 1rem;
  }

  .section-head {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
    flex-wrap: wrap;
  }

  .section-head p {
    margin: 0.2rem 0 0;
  }

  .section-head > div,
  .workflow-copy,
  .workflow-step-copy,
  .preview-header > div,
  .row-main,
  .history-main {
    min-width: 0;
  }

  .setup-inbox-section,
  .preview-card-shell,
  .setup-advanced-copy {
    display: grid;
    gap: 0.85rem;
  }

  .workflow-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(18rem, 21rem);
    gap: 1rem;
    align-items: start;
  }

  .workflow-copy p,
  .preview-header p,
  .sample-head p {
    margin: 0.35rem 0 0;
  }

  .workflow-steps {
    display: grid;
    gap: 0.55rem;
  }

  .workflow-step {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 14px;
    padding: 0.75rem 0.85rem;
    background: rgba(255, 255, 255, 0.68);
  }

  .workflow-step-active {
    border-color: rgba(15, 95, 136, 0.24);
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.94), rgba(241, 249, 255, 0.92));
  }

  .workflow-step-complete {
    border-color: rgba(12, 123, 89, 0.18);
  }

  .step-index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.9rem;
    height: 1.9rem;
    flex: 0 0 auto;
    border-radius: 999px;
    border: 1px solid rgba(10, 61, 89, 0.12);
    background: rgba(255, 255, 255, 0.92);
    color: var(--brand-strong);
    font-weight: 700;
  }

  .workflow-step-active .step-index {
    border-color: rgba(15, 95, 136, 0.24);
    background: #eef6ff;
  }

  .workflow-step-complete .step-index {
    border-color: rgba(12, 123, 89, 0.18);
    background: #edf9f4;
    color: var(--ok);
  }

  .workflow-step-copy {
    display: grid;
    gap: 0.08rem;
  }

  .workflow-field-grid,
  .workflow-status-grid,
  .preview-status-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.8rem;
  }

  .upload-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.8rem;
    align-items: end;
  }

  .upload-field p,
  .status-card p,
  .workflow-footer p,
  .history-meta,
  .result-banner p,
  .empty-panel p {
    margin: 0;
  }

  .status-card {
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.64);
    border-radius: 14px;
    padding: 0.85rem 0.9rem;
    min-width: 0;
  }

  .status-label {
    margin: 0 0 0.28rem;
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted-foreground);
  }

  .status-value {
    margin: 0;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .advanced-panel {
    margin-top: 0;
    border: 1px solid rgba(15, 95, 136, 0.12);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.68);
    padding: 0.8rem;
  }

  .advanced-panel summary {
    cursor: pointer;
    font-weight: 700;
    color: var(--brand-strong);
  }

  .advanced-field {
    margin-top: 0.8rem;
  }

  .workflow-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    padding-top: 0.15rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .inline-message {
    margin: 0;
  }

  .preview-panel {
    display: grid;
    gap: 0.9rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .preview-header,
  .sample-head,
  .history-topline {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
  }

  .summary {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
  }

  .result-banner {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
    border: 1px solid rgba(12, 123, 89, 0.18);
    border-radius: 14px;
    background: #f4fbf7;
    padding: 0.85rem 0.9rem;
  }

  .next-step-banner {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
    border: 1px solid rgba(15, 95, 136, 0.16);
    border-radius: 14px;
    background: rgba(241, 248, 255, 0.9);
    padding: 0.85rem 0.9rem;
  }

  .result-title {
    margin: 0 0 0.2rem;
    font-weight: 700;
  }

  .actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .list,
  .history-list {
    display: grid;
    gap: 0.7rem;
    overflow: auto;
    padding-right: 0.15rem;
  }

  .list {
    max-height: 30rem;
  }

  .history-list {
    max-height: 32rem;
  }

  .row {
    display: flex;
    justify-content: space-between;
    gap: 0.85rem;
    align-items: start;
    width: 100%;
    text-align: left;
    cursor: pointer;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.7);
    padding: 0.8rem 0.85rem;
    transition:
      border-color 0.16s ease,
      box-shadow 0.16s ease,
      transform 0.16s ease;
  }

  .row:hover {
    border-color: rgba(15, 95, 136, 0.18);
    box-shadow: 0 12px 24px rgba(10, 61, 89, 0.06);
    transform: translateY(-1px);
  }

  .row-selected {
    border-color: rgba(15, 95, 136, 0.24);
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(238, 246, 255, 0.88));
    box-shadow: 0 14px 28px rgba(10, 61, 89, 0.08);
  }

  .row-main {
    display: grid;
    gap: 0.45rem;
    min-width: 0;
  }

  .row-title {
    margin: 0;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .row-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }

  .row-meta span {
    display: inline-flex;
    align-items: center;
    padding: 0.18rem 0.45rem;
    border-radius: 999px;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.86);
    color: var(--muted-foreground);
    font-size: 0.78rem;
    overflow-wrap: anywhere;
  }

  .row-side {
    display: grid;
    justify-items: end;
    gap: 0.35rem;
    flex: 0 0 auto;
  }

  .row-selected-note {
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--brand);
  }

  .empty-panel {
    border: 1px dashed rgba(10, 61, 89, 0.14);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.46);
    padding: 1rem;
  }

  .empty-panel h4 {
    margin: 0 0 0.35rem;
  }

  .history-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.66);
    padding: 0.9rem;
  }

  .history-main {
    min-width: 0;
  }

  .history-title {
    margin: 0;
    font-weight: 700;
    overflow-wrap: anywhere;
  }

  .history-actions {
    display: flex;
    align-items: start;
  }

  .history-details {
    margin-top: 0.35rem;
  }

  .success-text {
    margin: 0;
    color: var(--ok);
  }

  .small {
    font-size: 0.8rem;
  }

  pre {
    margin: 0;
    background: #0c1925;
    color: #d5ecff;
    border-radius: 12px;
    padding: 0.8rem;
    white-space: pre-wrap;
    max-height: 320px;
    overflow: auto;
  }

  @media (max-width: 1100px) {
    .import-layout,
    .workflow-head {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 720px) {
    .workflow-field-grid,
    .workflow-status-grid,
    .preview-status-grid,
    .upload-row,
    .history-row {
      grid-template-columns: 1fr;
    }

    .section-head,
    .workflow-footer,
    .preview-header,
    .sample-head,
    .history-topline {
      flex-direction: column;
      align-items: stretch;
    }

    .row {
      flex-direction: column;
    }

    .row-side {
      justify-items: start;
    }

    .history-actions {
      justify-content: start;
    }

    .result-banner,
    .next-step-banner {
      flex-direction: column;
    }
  }
</style>
