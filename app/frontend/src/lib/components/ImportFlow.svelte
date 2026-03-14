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
  let hydrated = false;
  let lastRefreshToken = refreshToken;

  $: selectedImportAccount = importAccounts.find((account) => account.id === importAccountId) ?? null;
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
      const data = candidateData;
      candidates = data.candidates;
      importAccounts = data.importAccounts;
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
    loading = true;
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
      await loadImportData();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function runPreview() {
    error = '';
    historyMessage = '';
    preview = null;
    loading = true;
    try {
      preview = await apiPost<PreviewResult>('/api/import/preview', {
        csvPath: selectedPath,
        year,
        importAccountId
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
    historyMessage = '';
    loading = true;
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
      loading = false;
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
      `Undo ${entry.csvFileName ?? 'this import'}? This removes the transactions added by this import and creates a recovery backup of the current journal.`
    );
    if (!confirmed) return;

    error = '';
    historyMessage = '';
    loading = true;
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
      loading = false;
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
    <section class="view-card hero">
      <p class="eyebrow">Import</p>
      <h2 class="page-title">Bring in new statement activity</h2>
      <p class="subtitle">Upload a statement, confirm the preview, and add only transactions that are actually new.</p>
    </section>
  {/if}

  {#if !initialized}
    <section class="view-card">
      <p class="error-text">Workspace not initialized yet.</p>
      <a class="btn btn-primary" href="/setup">Go to Setup</a>
    </section>
  {:else}
    {#if error}
      <section class="view-card"><p class="error-text">{error}</p></section>
    {/if}

    {#if importAccounts.length === 0}
      <section class="view-card">
        <p class="error-text">No import accounts are configured for this workspace yet.</p>
        <a class="btn btn-primary" href="/accounts">Configure Accounts</a>
      </section>
    {:else}
      <section class="grid-2 import-grid">
        <article class="view-card">
          <p class="eyebrow">{mode === 'setup' ? 'Upload' : 'Step 1'}</p>
          <h3>Add a Statement</h3>

          <div class="field grid-2 compact">
            <div class="field">
              <label for={`uploadImportAccount-${mode}`}>Account</label>
              <select id={`uploadImportAccount-${mode}`} bind:value={importAccountId}>
                <option value="">Select...</option>
                {#each importAccounts as account}
                  <option value={account.id}>{accountLabel(account)}</option>
                {/each}
              </select>
            </div>
            <div class="field">
              <label for={`uploadYear-${mode}`}>Year</label>
              <input id={`uploadYear-${mode}`} bind:value={year} />
            </div>
          </div>

          <div class="field">
            <label for={`statementFile-${mode}`}>Statement File</label>
            <input
              id={`statementFile-${mode}`}
              type="file"
              accept=".csv,text/csv"
              on:change={(e) => (selectedFile = (e.currentTarget as HTMLInputElement).files?.[0] ?? null)}
            />
          </div>

          {#if selectedImportAccount}
            <div class="selection-summary">
              <p class="selection-label">Selected account</p>
              <p class="selection-value">{accountLabel(selectedImportAccount)}</p>
              <p class="muted">{selectedImportAccount.institutionDisplayName}</p>
              <p class="muted small">Imports into {selectedImportAccount.ledgerAccount}</p>
            </div>
          {/if}

          <button class="btn btn-primary" disabled={loading || !selectedFile || !importAccountId || !year} on:click={uploadFile}>
            {loading ? 'Uploading...' : 'Upload Statement'}
          </button>
          <p class="muted">Uploaded statements are saved to the inbox and appear below automatically.</p>
        </article>

        <article class="view-card">
          <p class="eyebrow">{mode === 'setup' ? 'Inbox' : 'Step 2'}</p>
          <h3>Statements Waiting</h3>
          {#if candidates.length === 0}
            <p class="muted">No statements are waiting in the inbox.</p>
          {:else}
            <div class="list">
              {#each candidates as candidate}
                <button class="row" on:click={() => pickCandidate(candidate)}>
                  <div class="row-main">
                    <span>{candidate.file_name}</span>
                    {#if candidate.detected_import_account_display_name}
                      <span class="muted small">{candidate.detected_import_account_display_name}</span>
                    {/if}
                    {#if candidate.detected_institution_display_name}
                      <span class="muted small">{candidate.detected_institution_display_name}</span>
                    {/if}
                  </div>
                  {#if candidate.is_configured_import_account}
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
          <p class="eyebrow">{mode === 'setup' ? 'Preview' : 'Step 3'}</p>
          <h3>Review Before Import</h3>

          <div class="selection-summary">
            <p class="selection-label">Selected statement</p>
            <p class="selection-value">{selectedPath ? pathLabel(selectedPath) : 'No statement selected yet'}</p>
            <p class="muted">Choose a statement from the list above or upload a new one.</p>
          </div>

          <div class="field grid-2 compact">
            <div class="field">
              <label for={`year-${mode}`}>Year</label>
              <input id={`year-${mode}`} bind:value={year} />
            </div>

            <div class="field">
              <label for={`importAccountId-${mode}`}>Account</label>
              <select id={`importAccountId-${mode}`} bind:value={importAccountId}>
                <option value="">Select...</option>
                {#each importAccounts as account}
                  <option value={account.id}>{accountLabel(account)}</option>
                {/each}
              </select>
            </div>
          </div>

          {#if selectedImportAccount}
            <div class="selection-summary">
              <p class="selection-label">Import target</p>
              <p class="selection-value">{accountLabel(selectedImportAccount)}</p>
              <p class="muted">{selectedImportAccount.institutionDisplayName}</p>
              <p class="muted small">Ledger account: {selectedImportAccount.ledgerAccount}</p>
            </div>
          {/if}

          <details class="advanced-panel">
            <summary>Advanced file selection</summary>
            <div class="field">
              <label for={`csvPath-${mode}`}>Statement Path</label>
              <input id={`csvPath-${mode}`} bind:value={selectedPath} />
            </div>
          </details>

          <button class="btn btn-primary" disabled={loading || !selectedPath || !year || !importAccountId} on:click={runPreview}>
            {loading ? 'Preparing preview...' : 'Preview Import'}
          </button>
        </article>
      </section>

      {#if preview}
        <section class="view-card import-result-card">
          <p class="eyebrow">Preview Result</p>
          <h3>Import Preview Ready</h3>
          <p class="muted">Confirm what will be added before applying the import.</p>

          {#if preview.importAccountDisplayName}
            <div class="selection-summary">
              <p class="selection-label">Import account</p>
              <p class="selection-value">{preview.importAccountDisplayName}</p>
              <p class="muted">Ledger account: {preview.destinationAccount}</p>
            </div>
          {/if}

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
                Added {preview.result.appendedTxnCount} | Skipped duplicates {preview.result.skippedDuplicateCount} |
                Conflicts {preview.result.conflicts?.length ?? 0}
              </p>
              {#if preview.result.sourceCsvWarning}
                <p class="error-text">{preview.result.sourceCsvWarning}</p>
              {/if}
            </div>
          {:else}
            <button class="btn btn-primary" disabled={loading} on:click={applyStage}>Apply Import</button>
          {/if}

          <details class="advanced-panel">
            <summary>Technical details</summary>
            <p class="muted">Import stage: {preview.stageId}</p>
            <p class="muted">Destination file: {preview.targetJournalPath}</p>
            {#if preview.result?.backupPath}
              <p class="muted">Backup: {preview.result.backupPath}</p>
            {/if}
            {#if preview.result?.archivedCsvPath}
              <p class="muted">Archived source: {preview.result.archivedCsvPath}</p>
            {/if}
          </details>

          {#if preview.preview?.length}
            <h4>Sample Transactions</h4>
            <pre>{preview.preview.slice(0, 8).join('\n\n')}</pre>
          {/if}
        </section>
      {/if}
    {/if}
  {/if}

  <section class="view-card import-history-card">
    <div class="history-header">
      <div>
        <p class="eyebrow">Import History</p>
        <h3>Recent Imports</h3>
        <p class="muted">Applied imports are logged here. Undo is available for the latest applied import on each journal.</p>
      </div>
      {#if historyEntries.length > 0}
        <p class="muted small">{historyEntries.length} recorded</p>
      {/if}
    </div>

    {#if historyMessage}
      <p class="success-text">{historyMessage}</p>
    {/if}

    {#if !initialized}
      <p class="muted">Complete workspace setup to start recording import history.</p>
    {:else if historyEntries.length === 0}
      <p class="muted">No imports have been applied yet.</p>
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

              <p class="muted small">
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
                  <p class="muted">Journal: {entry.targetJournalPath}</p>
                {/if}
                {#if entry.backupPath}
                  <p class="muted">Import backup: {entry.backupPath}</p>
                {/if}
                {#if entry.undo?.undoBackupPath}
                  <p class="muted">Undo backup: {entry.undo.undoBackupPath}</p>
                {/if}
                {#if entry.originalCsvPath}
                  <p class="muted">Original statement: {entry.originalCsvPath}</p>
                {/if}
                {#if entry.archivedCsvPath}
                  <p class="muted">Archived statement: {entry.archivedCsvPath}</p>
                {/if}
                {#if entry.undo?.restoredInboxCsvPath}
                  <p class="muted">Restored to inbox: {entry.undo.restoredInboxCsvPath}</p>
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
              <button class="btn" disabled={loading || !entry.canUndo} on:click={() => undoHistoryEntry(entry)}>
                Undo Import
              </button>
            </div>
          </article>
        {/each}
      </div>
    {/if}
  </section>
</div>

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .import-flow {
    display: grid;
    gap: 1rem;
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
    gap: 1rem;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.72);
    border-radius: 10px;
    padding: 0.55rem 0.6rem;
    cursor: pointer;
    text-align: left;
    width: 100%;
  }

  .row-main {
    display: grid;
    gap: 0.1rem;
  }

  .summary {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    margin-bottom: 0.8rem;
  }

  .selection-summary {
    border: 1px solid rgba(15, 95, 136, 0.12);
    background: rgba(255, 255, 255, 0.65);
    border-radius: 12px;
    padding: 0.8rem;
    margin-bottom: 0.9rem;
  }

  .selection-label {
    margin: 0 0 0.2rem;
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--muted-foreground);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .selection-value {
    margin: 0 0 0.25rem;
    font-weight: 700;
  }

  .advanced-panel {
    margin: 0.9rem 0 0;
    border: 1px solid rgba(15, 95, 136, 0.12);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.7);
    padding: 0.8rem;
  }

  .advanced-panel summary {
    cursor: pointer;
    font-weight: 700;
    color: var(--brand-strong);
  }

  .history-header {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
  }

  .history-list {
    display: grid;
    gap: 0.85rem;
  }

  .history-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 14px;
    padding: 0.9rem;
    background: rgba(255, 255, 255, 0.7);
  }

  .history-main {
    min-width: 0;
  }

  .history-topline {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    align-items: center;
  }

  .history-title {
    margin: 0;
    font-weight: 700;
  }

  .history-actions {
    display: flex;
    align-items: start;
  }

  .history-details {
    margin-top: 0.7rem;
  }

  .success-text {
    color: var(--ok);
    margin-bottom: 0.9rem;
  }

  .small {
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

  @media (max-width: 900px) {
    .history-row {
      grid-template-columns: 1fr;
    }

    .history-actions {
      justify-content: start;
    }

    .history-topline {
      align-items: start;
      flex-direction: column;
    }
  }
</style>
