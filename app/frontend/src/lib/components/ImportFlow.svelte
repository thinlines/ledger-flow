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
      fenceCount: number;
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

  type UploadPreviewResult = PreviewResult & {
    absPath: string;
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
      // Persisted history entries may carry the old `conflictCount` field
      // (pre-§21). New entries write `fenceCount`. Read both for forward
      // and backward compatibility.
      fenceCount?: number;
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
  type LoadingState = 'idle' | 'upload' | 'preview' | 'apply' | 'undo' | 'remove';
  type FollowUpAction = {
    href: string;
    label: string;
    note: string;
    secondary: {
      href: string;
      label: string;
    };
  };

  type ImportRecoveryState = {
    code: string;
    message: string;
    csvPath: string | null;
    fileName: string | null;
    fileKeptInInbox: boolean;
    causeMessage: string | null;
  };

  type ParsedApiFailure = {
    message: string;
    detail: unknown;
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
  let recoveryState: ImportRecoveryState | null = null;
  let loading = false;
  let loadingState: LoadingState = 'idle';
  let hydrated = false;
  let lastRefreshToken = refreshToken;
  let statementFileInput: HTMLInputElement | null = null;
  let workflowStep: WorkflowStep = 'prepare';
  let selectedImportAccount: ImportAccountOption | null = null;
  let selectedCandidate: Candidate | null = null;
  let actionReady = false;

  $: selectedImportAccount = importAccounts.find((account) => account.id === importAccountId) ?? null;
  $: selectedCandidate = candidates.find((candidate) => candidate.abs_path === selectedPath) ?? null;
  $: actionReady = Boolean(importAccountId && year && (selectedFile || selectedPath));
  $: workflowStep = preview?.result ? 'complete' : preview ? 'apply' : selectedPath || selectedFile ? 'preview' : 'prepare';
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

  function errorMessage(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }

  function currentStatementLabel(): string {
    if (selectedFile) return selectedFile.name;
    if (selectedPath) return pathLabel(selectedPath);
    return 'No statement selected yet';
  }

  function statementStatusNote(): string {
    if (selectedFile) {
      return "Ready to preview. If the file doesn't match this account, it will not be added to the inbox.";
    }
    if (selectedCandidate) {
      return 'Chosen from the inbox.';
    }
    return 'Pick a waiting statement or choose a CSV above.';
  }

  function primaryActionLabel(): string {
    if (loadingState === 'upload' || loadingState === 'preview') {
      return 'Preparing preview...';
    }
    if (selectedFile) {
      return recoveryState ? 'Try Another Account' : 'Preview Statement';
    }
    if (recoveryState) {
      return 'Preview Again';
    }
    return preview && !preview.result ? 'Refresh Preview' : 'Preview Import';
  }

  function clearSelectedFile() {
    selectedFile = null;
    if (statementFileInput) statementFileInput.value = '';
  }

  function resetImportState() {
    error = '';
    historyMessage = '';
    recoveryState = null;
    preview = null;
  }

  function parseApiFailure(path: string, status: number, text: string): ParsedApiFailure {
    let detail: unknown = null;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      detail = parsed.detail;
      if (detail === 'workspace_not_initialized') {
        return {
          message: 'Workspace not initialized. Complete setup before using this feature.',
          detail
        };
      }
      if (typeof detail === 'string') {
        if (detail.includes('Traceback')) {
          return {
            message: 'The operation failed while processing this file. Please verify the selected institution and input format.',
            detail
          };
        }
        return { message: detail, detail };
      }
      if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') {
        return { message: (detail as { message: string }).message, detail };
      }
    } catch {
      // no-op
    }

    if (!text.trim()) {
      return { message: `${path} failed (${status})`, detail };
    }
    return { message: text, detail };
  }

  function parseImportRecovery(detail: unknown): ImportRecoveryState | null {
    if (!detail || typeof detail !== 'object') return null;
    const candidate = detail as Record<string, unknown>;
    if (candidate.code !== 'statement_preview_blocked' || typeof candidate.message !== 'string') {
      return null;
    }
    return {
      code: 'statement_preview_blocked',
      message: candidate.message,
      csvPath: typeof candidate.csvPath === 'string' ? candidate.csvPath : null,
      fileName: typeof candidate.fileName === 'string' ? candidate.fileName : null,
      fileKeptInInbox: candidate.fileKeptInInbox === true,
      causeMessage: typeof candidate.causeMessage === 'string' ? candidate.causeMessage : null
    };
  }

  async function sendImportRequest<T>(path: string, init: RequestInit): Promise<T | null> {
    const res = await fetch(path, init);
    if (!res.ok) {
      const text = await res.text();
      const failure = parseApiFailure(path, res.status, text);
      const recovery = parseImportRecovery(failure.detail);
      if (recovery) {
        recoveryState = recovery;
        error = '';
        return null;
      }
      throw new Error(failure.message);
    }

    recoveryState = null;
    return (await res.json()) as T;
  }

  function setImportAccount(nextId: string) {
    if (nextId === importAccountId) return;
    importAccountId = nextId;
    resetImportState();
  }

  function setYear(nextYear: string) {
    if (nextYear === year) return;
    year = nextYear;
    resetImportState();
  }

  function onStatementFileChange(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0] ?? null;
    if (file) {
      selectedFile = file;
      selectedPath = '';
    } else {
      selectedFile = null;
    }
    resetImportState();
  }

  function setSelectedPath(nextPath: string) {
    if (nextPath === selectedPath) return;
    clearSelectedFile();
    selectedPath = nextPath;
    resetImportState();
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
        recoveryState = null;
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

      if (selectedPath && !candidates.some((candidate) => candidate.abs_path === selectedPath)) {
        const removedPath = selectedPath;
        selectedPath = '';
        preview = null;
        if (recoveryState?.csvPath === removedPath) {
          recoveryState = null;
        }
      }
    } catch (e) {
      error = errorMessage(e);
    }
  }

  async function uploadAndPreviewFile() {
    if (!selectedFile || !importAccountId || !year) return;

    loadingState = 'upload';
    resetImportState();

    try {
      const form = new FormData();
      form.append('file', selectedFile);
      form.append('year', year);
      form.append('importAccountId', importAccountId);
      form.append('preview', 'true');

      const data = await sendImportRequest<UploadPreviewResult>('/api/import/upload', {
        method: 'POST',
        body: form
      });
      if (!data) return;

      preview = data;
      selectedPath = data.absPath;
      clearSelectedFile();
      await loadImportData();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  async function runPreview() {
    if (selectedFile) {
      await uploadAndPreviewFile();
      return;
    }
    if (!selectedPath || !importAccountId || !year) return;

    loadingState = 'preview';
    resetImportState();

    try {
      const data = await sendImportRequest<PreviewResult>('/api/import/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          csvPath: selectedPath,
          year,
          importAccountId
        })
      });
      if (!data) return;
      preview = data;
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  async function applyStage() {
    if (!preview?.stageId) return;

    error = '';
    historyMessage = '';
    recoveryState = null;
    loadingState = 'apply';

    try {
      preview = await apiPost<PreviewResult>('/api/import/apply', { stageId: preview.stageId });
      selectedPath = '';
      await loadImportData();

      if (preview && onApplied) {
        await onApplied(preview);
      }
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  function pickCandidate(candidate: Candidate) {
    clearSelectedFile();
    selectedPath = candidate.abs_path;
    year = candidate.detected_year ?? year;
    importAccountId = candidate.detected_import_account_id ?? importAccountId;
    resetImportState();
  }

  async function removeSelectedCandidate() {
    if (!selectedCandidate) return;

    const confirmed = window.confirm(
      `Remove ${selectedCandidate.file_name} from the inbox? This only deletes the waiting statement and will not change imported activity.`
    );
    if (!confirmed) return;

    loadingState = 'remove';
    error = '';
    historyMessage = '';
    recoveryState = null;

    try {
      await apiPost('/api/import/remove', {
        csvPath: selectedCandidate.abs_path
      });
      historyMessage = `${selectedCandidate.file_name} was removed from the inbox.`;
      selectedPath = '';
      preview = null;
      await loadImportData();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  async function undoHistoryEntry(entry: ImportHistoryEntry) {
    if (!entry.canUndo) return;

    const confirmed = window.confirm(
      `Undo ${entry.csvFileName ?? 'this import'}? This removes the transactions added by this import and creates a recovery backup first.`
    );
    if (!confirmed) return;

    error = '';
    historyMessage = '';
    recoveryState = null;
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
      error = errorMessage(e);
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

<div class="grid gap-4">
  {#if mode === 'standalone'}
    <section class="view-card hero grid gap-1.5">
      <p class="eyebrow">Import</p>
      <h2 class="page-title">Bring in new statement activity</h2>
      <p class="subtitle">Choose a statement, confirm the preview, and only then write changes. New uploads are checked before they stay in the inbox.</p>
    </section>
  {/if}

  {#if !initialized}
    <section class="view-card">
      <p class="eyebrow">Import</p>
      <h3 class="m-0">Finish setup before importing statements</h3>
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
        <h3 class="m-0">Add an account before importing</h3>
        <p class="muted">Connect a supported account or save a custom CSV mapping first. Then statement imports can flow straight into review and overview.</p>
        <div class="flex gap-2.5 flex-wrap">
          <a class="btn btn-primary" href="/accounts/configure?mode=institution">Add supported account</a>
          <a class="btn" href="/accounts/configure?mode=custom">Add custom CSV</a>
        </div>
      </section>
    {:else if mode === 'setup'}
      <section class="view-card grid gap-4">
        <div class="flex justify-between gap-4 items-start flex-wrap">
          <div class="min-w-0">
            <p class="eyebrow">Prepare</p>
            <h3 class="m-0">Upload and preview your first statement</h3>
            <p class="muted mt-1">Use one vertical flow for the first import. New files go straight into preview if they match the selected account.</p>
          </div>
          {#if candidates.length > 0}
            <span class="pill">{candidates.length} waiting</span>
          {/if}
        </div>

        <div class="grid grid-cols-2 gap-3 max-tablet:grid-cols-1">
          <div class="field">
            <label for={`importAccountId-${mode}`}>Import account</label>
            <select id={`importAccountId-${mode}`} value={importAccountId} on:change={(e) => setImportAccount((e.currentTarget as HTMLSelectElement).value)}>
              <option value="">Select...</option>
              {#each importAccounts as account}
                <option value={account.id}>{accountLabel(account)}</option>
              {/each}
            </select>
          </div>

          <div class="field">
            <label for={`year-${mode}`}>Statement year</label>
            <input
              id={`year-${mode}`}
              value={year}
              inputmode="numeric"
              on:input={(e) => setYear((e.currentTarget as HTMLInputElement).value)}
            />
          </div>
        </div>

        <div class="grid">
          <div class="field">
            <label for={`statementFile-${mode}`}>Statement CSV</label>
            <input
              id={`statementFile-${mode}`}
              bind:this={statementFileInput}
              type="file"
              accept=".csv,text/csv"
              on:change={onStatementFileChange}
            />
            {#if selectedFile}
              <p class="muted text-xs m-0">Selected: {selectedFile.name}. Preview is the next step.</p>
            {:else}
              <p class="muted text-xs m-0">Choose a new CSV or keep working from a statement that is already waiting in the inbox.</p>
            {/if}
          </div>
        </div>

        <section class="grid gap-3.5">
          <div class="flex justify-between gap-4 items-start flex-wrap">
            <div class="min-w-0">
              <p class="eyebrow">Inbox</p>
              <h3 class="m-0">Pick a statement to continue</h3>
              <p class="muted mt-1">Files that already passed validation wait here until you preview, apply, or remove them.</p>
            </div>
            {#if candidates.length > 0}
              <span class="pill">{candidates.length} waiting</span>
            {/if}
          </div>

          {#if candidates.length === 0}
            <div class="empty-panel">
              <h4 class="m-0 mb-1.5">No statements in the inbox</h4>
              <p class="m-0">Choose a CSV above to start the first import.</p>
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
                  <div class="grid gap-2 min-w-0">
                    <p class="m-0 font-bold wrap-anywhere">{candidate.file_name}</p>
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

                  <div class="grid justify-items-end gap-1.5 shrink-0">
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

        <div class="grid grid-cols-2 gap-3 max-tablet:grid-cols-1">
          <section class="status-card">
            <p class="eyebrow mb-1">Selected statement</p>
            <p class="m-0 font-bold wrap-anywhere">{currentStatementLabel()}</p>
            <p class="muted text-xs m-0">{statementStatusNote()}</p>
          </section>

          <section class="status-card">
            <p class="eyebrow mb-1">Import target</p>
            <p class="m-0 font-bold wrap-anywhere">{selectedImportAccount ? accountLabel(selectedImportAccount) : 'Choose an import account'}</p>
            <p class="muted text-xs m-0">
              {#if selectedImportAccount}
                {selectedImportAccount.institutionDisplayName} • This statement will flow into balances, transactions, and review for this account.
              {:else}
                The selected account decides where this statement lands after import.
              {/if}
            </p>
          </section>
        </div>

        {#if selectedCandidate && !selectedCandidate.is_configured_import_account && !selectedImportAccount}
          <p class="error-text m-0">
            This inbox file is no longer linked to a saved account. Choose an account above before previewing it.
          </p>
        {/if}

        {#if recoveryState}
          <section class="recovery-card">
            <div class="min-w-0">
              <p class="eyebrow">Recovery</p>
              <h4 class="m-0">{recoveryState.fileKeptInInbox ? 'This statement needs a different account' : 'This upload was blocked before it reached the inbox'}</h4>
              <p class="muted mt-1">{recoveryState.message}</p>
              {#if recoveryState.causeMessage}
                <pre class="cause-detail">{recoveryState.causeMessage}</pre>
              {/if}
            </div>
          </section>
        {/if}

        <details class="advanced-panel">
          <summary>Advanced file selection</summary>
          <div class="field mt-3">
            <label for={`csvPath-${mode}`}>Statement path</label>
            <input
              id={`csvPath-${mode}`}
              value={selectedPath}
              on:input={(e) => setSelectedPath((e.currentTarget as HTMLInputElement).value)}
            />
          </div>
        </details>

        <div class="workflow-footer max-tablet:flex-col max-tablet:items-stretch">
          <p class="muted m-0">
            {#if selectedFile}
              Preview is the next step. The file will only stay in the inbox if the preview succeeds.
            {:else}
              Nothing is written until you apply the preview. Duplicate transactions are skipped automatically.
            {/if}
          </p>
          <div class="flex gap-2.5 flex-wrap">
            {#if selectedCandidate}
              <button class="btn" type="button" disabled={loading} on:click={removeSelectedCandidate}>
                {loadingState === 'remove' ? 'Removing...' : 'Remove from Inbox'}
              </button>
            {/if}
            <button class="btn btn-primary" type="button" disabled={loading || !actionReady} on:click={runPreview}>
              {primaryActionLabel()}
            </button>
          </div>
        </div>
      </section>

      {#if preview}
        <section class="view-card grid gap-4">
          <div class="grid gap-3.5">
            <div class="flex justify-between gap-4 items-start max-tablet:flex-col max-tablet:items-stretch">
              <div class="min-w-0">
                <p class="eyebrow">{preview.result ? 'Import Result' : 'Preview'}</p>
                <h3 class="m-0">{preview.result ? 'Statement imported' : 'Review the import'}</h3>
                <p class="muted mt-1">
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

            <div class="grid grid-cols-2 gap-3 max-tablet:grid-cols-1">
              {#if preview.importAccountDisplayName}
                <section class="status-card">
                  <p class="eyebrow mb-1">Preview account</p>
                  <p class="m-0 font-bold wrap-anywhere">{preview.importAccountDisplayName}</p>
                  <p class="muted text-xs m-0">This statement will update the selected account when you apply the preview.</p>
                </section>
              {/if}
            </div>

            {#if preview.summary}
              <div class="flex gap-2 flex-wrap">
                <span class="pill ok">New {preview.summary.newCount}</span>
                <span class="pill">Duplicates {preview.summary.duplicateCount}</span>
                <span class="pill warn">Conflicts {preview.summary.fenceCount}</span>
                <span class="pill">Unknown {preview.summary.unknownCount}</span>
              </div>
            {/if}

            {#if preview.result}
              <div class="result-banner max-tablet:flex-col">
                <div class="min-w-0">
                  <p class="m-0 mb-0.5 font-bold">Import applied</p>
                  <p class="muted m-0">
                    Added {preview.result.appendedTxnCount}, skipped {preview.result.skippedDuplicateCount} duplicates, conflicts
                    {preview.result.conflicts?.length ?? 0}.
                  </p>
                </div>
                <span class="pill ok">Complete</span>
              </div>

              {#if preview.result.sourceCsvWarning}
                <p class="error-text m-0">{preview.result.sourceCsvWarning}</p>
              {/if}
            {/if}

            <details class="advanced-panel">
              <summary>Technical details</summary>
              <div class="grid gap-3.5">
                <p class="muted text-xs m-0">Import stage: {preview.stageId}</p>
                {#if preview.targetJournalPath}
                  <p class="muted text-xs m-0">Destination file: {preview.targetJournalPath}</p>
                {/if}
                {#if preview.result?.backupPath}
                  <p class="muted text-xs m-0">Backup: {preview.result.backupPath}</p>
                {/if}
                {#if preview.result?.archivedCsvPath}
                  <p class="muted text-xs m-0">Archived source: {preview.result.archivedCsvPath}</p>
                {/if}
              </div>
            </details>

            {#if preview.preview?.length}
              <div>
                <div class="flex justify-between gap-4 items-start max-tablet:flex-col max-tablet:items-stretch">
                  <h4 class="m-0">Sample transactions</h4>
                  <p class="muted text-xs mt-1">Showing the first {Math.min(preview.preview.length, 8)} items from the preview.</p>
                </div>
                <pre>{preview.preview.slice(0, 8).join('\n\n')}</pre>
              </div>
            {/if}
          </div>
        </section>
      {/if}
    {:else}
      <section class="import-layout max-desktop:grid-cols-1">
        <article class="view-card grid gap-4">
          <div class="workflow-head max-desktop:grid-cols-1">
            <div class="min-w-0">
              <p class="eyebrow">Current Import</p>
              <h3 class="m-0">Preview the next statement before you import it</h3>
              <p class="muted mt-1">Use one obvious action to move from a new file or inbox statement into a safe preview.</p>
            </div>

            <div class="grid gap-2" aria-label="Import progress">
              <div
                class="workflow-step"
                class:workflow-step-active={workflowStep === 'prepare'}
                class:workflow-step-complete={Boolean(selectedPath || selectedFile || preview)}
              >
                <span class="step-index">1</span>
                <div class="grid gap-px min-w-0">
                  <strong>Prepare</strong>
                  <span class="muted text-xs">Choose the account, year, and statement.</span>
                </div>
              </div>

              <div
                class="workflow-step"
                class:workflow-step-active={workflowStep === 'preview'}
                class:workflow-step-complete={Boolean(preview)}
              >
                <span class="step-index">2</span>
                <div class="grid gap-px min-w-0">
                  <strong>Preview</strong>
                  <span class="muted text-xs">Review counts and sample transactions.</span>
                </div>
              </div>

              <div
                class="workflow-step"
                class:workflow-step-active={workflowStep === 'apply'}
                class:workflow-step-complete={Boolean(preview?.result)}
              >
                <span class="step-index">3</span>
                <div class="grid gap-px min-w-0">
                  <strong>Apply</strong>
                  <span class="muted text-xs">Append new transactions and log the result.</span>
                </div>
              </div>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3 max-tablet:grid-cols-1">
            <div class="field">
              <label for={`importAccountId-${mode}`}>Import account</label>
              <select id={`importAccountId-${mode}`} value={importAccountId} on:change={(e) => setImportAccount((e.currentTarget as HTMLSelectElement).value)}>
                <option value="">Select...</option>
                {#each importAccounts as account}
                  <option value={account.id}>{accountLabel(account)}</option>
                {/each}
              </select>
            </div>

            <div class="field">
              <label for={`year-${mode}`}>Statement year</label>
              <input
                id={`year-${mode}`}
                value={year}
                inputmode="numeric"
                on:input={(e) => setYear((e.currentTarget as HTMLInputElement).value)}
              />
            </div>
          </div>

          <div class="grid">
            <div class="field">
              <label for={`statementFile-${mode}`}>Statement CSV</label>
              <input
                id={`statementFile-${mode}`}
                bind:this={statementFileInput}
                type="file"
                accept=".csv,text/csv"
                on:change={onStatementFileChange}
              />
              {#if selectedFile}
                <p class="muted text-xs m-0">Selected: {selectedFile.name}. Preview is the next step.</p>
              {:else}
                <p class="muted text-xs m-0">Choose a new CSV or keep working from a statement that is already waiting in the inbox.</p>
              {/if}
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3 max-tablet:grid-cols-1">
            <section class="status-card">
              <p class="eyebrow mb-1">Selected statement</p>
              <p class="m-0 font-bold wrap-anywhere">{currentStatementLabel()}</p>
              <p class="muted text-xs m-0">{statementStatusNote()}</p>
            </section>

            <section class="status-card">
              <p class="eyebrow mb-1">Import target</p>
              <p class="m-0 font-bold wrap-anywhere">{selectedImportAccount ? accountLabel(selectedImportAccount) : 'Choose an import account'}</p>
              <p class="muted text-xs m-0">
                {#if selectedImportAccount}
                  {selectedImportAccount.institutionDisplayName} • This statement will flow into balances, transactions, and review for this account.
                {:else}
                  The selected account decides where this statement lands after import.
                {/if}
              </p>
            </section>
          </div>

          {#if selectedCandidate && !selectedCandidate.is_configured_import_account && !selectedImportAccount}
            <p class="error-text m-0">
              This inbox file is no longer linked to a saved account. Choose an account above before previewing it.
            </p>
          {/if}

          {#if recoveryState}
            <section class="recovery-card max-tablet:flex-col">
              <div class="min-w-0">
                <p class="eyebrow">Recovery</p>
                <h4 class="m-0">{recoveryState.fileKeptInInbox ? 'This statement needs a different account' : 'This upload was blocked before it reached the inbox'}</h4>
                <p class="muted mt-1">{recoveryState.message}</p>
                {#if recoveryState.causeMessage}
                  <pre class="cause-detail">{recoveryState.causeMessage}</pre>
                {/if}
              </div>
            </section>
          {/if}

          <details class="advanced-panel">
            <summary>Advanced file selection</summary>
            <div class="field mt-3">
              <label for={`csvPath-${mode}`}>Statement path</label>
              <input
                id={`csvPath-${mode}`}
                value={selectedPath}
                on:input={(e) => setSelectedPath((e.currentTarget as HTMLInputElement).value)}
              />
            </div>
          </details>

          <div class="workflow-footer max-tablet:flex-col max-tablet:items-stretch">
            <p class="muted m-0">
              {#if selectedFile}
                Preview is the next step. The file will only stay in the inbox if the preview succeeds.
              {:else}
                Nothing is written until you apply the preview. Duplicate transactions are skipped automatically.
              {/if}
            </p>
            <div class="flex gap-2.5 flex-wrap">
              {#if selectedCandidate}
                <button class="btn" type="button" disabled={loading} on:click={removeSelectedCandidate}>
                  {loadingState === 'remove' ? 'Removing...' : 'Remove from Inbox'}
                </button>
              {/if}
              <button class="btn btn-primary" type="button" disabled={loading || !actionReady} on:click={runPreview}>
                {primaryActionLabel()}
              </button>
            </div>
          </div>

          {#if preview}
            <section class="preview-panel">
              <div class="flex justify-between gap-4 items-start max-tablet:flex-col max-tablet:items-stretch">
                <div class="min-w-0">
                  <p class="eyebrow">{preview.result ? 'Import Result' : 'Preview'}</p>
                  <h4 class="m-0">{preview.result ? 'Statement imported' : 'Review the import'}</h4>
                  <p class="muted mt-1">
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

              <div class="grid grid-cols-2 gap-3 max-tablet:grid-cols-1">
                {#if preview.importAccountDisplayName}
                  <section class="status-card">
                    <p class="eyebrow mb-1">Preview account</p>
                    <p class="m-0 font-bold wrap-anywhere">{preview.importAccountDisplayName}</p>
                    <p class="muted text-xs m-0">This statement will update the selected account when you apply the preview.</p>
                  </section>
                {/if}
              </div>

              {#if preview.summary}
                <div class="flex gap-2 flex-wrap">
                  <span class="pill ok">New {preview.summary.newCount}</span>
                  <span class="pill">Duplicates {preview.summary.duplicateCount}</span>
                  <span class="pill warn">Conflicts {preview.summary.fenceCount}</span>
                  <span class="pill">Unknown {preview.summary.unknownCount}</span>
                </div>
              {/if}

              {#if preview.result}
                <div class="result-banner max-tablet:flex-col">
                  <div class="min-w-0">
                    <p class="m-0 mb-0.5 font-bold">Import applied</p>
                    <p class="muted m-0">
                      Added {preview.result.appendedTxnCount}, skipped {preview.result.skippedDuplicateCount} duplicates, conflicts
                      {preview.result.conflicts?.length ?? 0}.
                    </p>
                  </div>
                  <span class="pill ok">Complete</span>
                </div>

                {#if importResultAction()}
                  <div class="next-step-banner max-tablet:flex-col">
                    <div class="min-w-0">
                      <p class="m-0 mb-0.5 font-bold">Next step</p>
                      <p class="muted m-0">{importResultAction()?.note}</p>
                    </div>
                    <div class="flex gap-2.5 flex-wrap">
                      <a class="btn btn-primary" href={importResultAction()?.href}>{importResultAction()?.label}</a>
                      <a class="btn" href={importResultAction()?.secondary.href}>{importResultAction()?.secondary.label}</a>
                    </div>
                  </div>
                {/if}

                {#if preview.result.sourceCsvWarning}
                  <p class="error-text m-0">{preview.result.sourceCsvWarning}</p>
                {/if}
              {/if}

              <details class="advanced-panel">
                <summary>Technical details</summary>
                <p class="muted text-xs m-0">Import stage: {preview.stageId}</p>
                {#if preview.targetJournalPath}
                  <p class="muted text-xs m-0">Destination file: {preview.targetJournalPath}</p>
                {/if}
                {#if preview.result?.backupPath}
                  <p class="muted text-xs m-0">Backup: {preview.result.backupPath}</p>
                {/if}
                {#if preview.result?.archivedCsvPath}
                  <p class="muted text-xs m-0">Archived source: {preview.result.archivedCsvPath}</p>
                {/if}
              </details>

              {#if preview.preview?.length}
                <div>
                  <div class="flex justify-between gap-4 items-start max-tablet:flex-col max-tablet:items-stretch">
                    <h4 class="m-0">Sample transactions</h4>
                    <p class="muted text-xs mt-1">Showing the first {Math.min(preview.preview.length, 8)} items from the preview.</p>
                  </div>
                  <pre>{preview.preview.slice(0, 8).join('\n\n')}</pre>
                </div>
              {/if}
            </section>
          {/if}
        </article>

        <aside class="grid gap-4 items-start">
          <article class="view-card grid gap-4">
            <div class="flex justify-between gap-4 items-start flex-wrap">
              <div class="min-w-0">
                <p class="eyebrow">Waiting Statements</p>
                <h3 class="m-0">Pick a statement to continue</h3>
                <p class="muted mt-1">Validated statements stay here while you preview, apply, or remove them.</p>
              </div>
              {#if candidates.length > 0}
                <span class="pill">{candidates.length} waiting</span>
              {/if}
            </div>

            {#if candidates.length === 0}
              <div class="empty-panel">
                <h4 class="m-0 mb-1.5">No statements in the inbox</h4>
                <p class="m-0">Choose a CSV above to start a new import.</p>
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
                    <div class="grid gap-2 min-w-0">
                      <p class="m-0 font-bold wrap-anywhere">{candidate.file_name}</p>
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

                    <div class="grid justify-items-end gap-1.5 shrink-0">
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
      <section class="view-card grid gap-4">
        <div class="flex justify-between gap-4 items-start flex-wrap">
          <div class="min-w-0">
            <p class="eyebrow">Import History</p>
            <h3 class="m-0">Recent imports</h3>
            <p class="muted mt-1">Undo is available for the latest applied import in each destination year.</p>
          </div>
          {#if historyEntries.length > 0}
            <span class="pill">{historyEntries.length} recorded</span>
          {/if}
        </div>

        {#if historyMessage}
          <p class="m-0 text-ok">{historyMessage}</p>
        {/if}

        {#if !initialized}
          <p class="muted">Complete workspace setup to start recording import history.</p>
        {:else if historyEntries.length === 0}
          <div class="empty-panel">
            <h4 class="m-0 mb-1.5">No imports have been applied yet</h4>
            <p class="m-0">Your recent imports and undo actions will appear here.</p>
          </div>
        {:else}
          <div class="history-list">
            {#each historyEntries as entry}
              <article class="history-row max-tablet:grid-cols-1">
                <div class="min-w-0">
                  <div class="flex justify-between gap-4 items-start max-tablet:flex-col max-tablet:items-stretch">
                    <p class="m-0 font-bold wrap-anywhere">{entry.csvFileName ?? optionalPathLabel(entry.originalCsvPath)}</p>
                    <span class={`pill ${entry.status === 'undone' ? 'warn' : 'ok'}`}>
                      {entry.status === 'undone' ? 'Undone' : 'Applied'}
                    </span>
                  </div>

                  <p class="muted text-xs m-0">
                    {formatDateTime(entry.appliedAt)} • {entry.importAccountDisplayName ?? entry.importAccountId} •
                    {optionalPathLabel(entry.targetJournalPath, 'Unknown journal')}
                  </p>

                  <div class="flex gap-2 flex-wrap">
                    <span class="pill ok">Added {entry.result?.appendedTxnCount ?? 0}</span>
                    <span class="pill">Duplicates {entry.result?.skippedDuplicateCount ?? 0}</span>
                    <span class="pill warn">
                      Conflicts {entry.summary?.fenceCount ?? entry.summary?.conflictCount ?? entry.result?.conflicts?.length ?? 0}
                    </span>
                  </div>

                  {#if entry.undo?.undoneAt}
                    <p class="muted text-xs">Undone {formatDateTime(entry.undo.undoneAt)}.</p>
                  {:else if !entry.canUndo && entry.undoBlockedReason}
                    <p class="muted text-xs">{entry.undoBlockedReason}</p>
                  {/if}

                  <details class="advanced-panel mt-1.5">
                    <summary>Paths and recovery details</summary>
                    {#if entry.targetJournalPath}
                      <p class="muted text-xs m-0">Journal: {entry.targetJournalPath}</p>
                    {/if}
                    {#if entry.backupPath}
                      <p class="muted text-xs m-0">Import backup: {entry.backupPath}</p>
                    {/if}
                    {#if entry.undo?.undoBackupPath}
                      <p class="muted text-xs m-0">Undo backup: {entry.undo.undoBackupPath}</p>
                    {/if}
                    {#if entry.originalCsvPath}
                      <p class="muted text-xs m-0">Original statement: {entry.originalCsvPath}</p>
                    {/if}
                    {#if entry.archivedCsvPath}
                      <p class="muted text-xs m-0">Archived statement: {entry.archivedCsvPath}</p>
                    {/if}
                    {#if entry.undo?.restoredInboxCsvPath}
                      <p class="muted text-xs m-0">Restored to inbox: {entry.undo.restoredInboxCsvPath}</p>
                    {/if}
                    {#if entry.result?.sourceCsvWarning}
                      <p class="error-text">{entry.result.sourceCsvWarning}</p>
                    {/if}
                    {#if entry.undo?.sourceCsvWarning}
                      <p class="error-text">{entry.undo.sourceCsvWarning}</p>
                    {/if}
                  </details>
                </div>

                <div class="flex items-start max-tablet:justify-start">
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
  /* ── Asymmetric layout grids ── */

  .import-layout {
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(19rem, 0.9fr);
    gap: 1rem;
    align-items: start;
  }

  .workflow-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(18rem, 21rem);
    gap: 1rem;
    align-items: start;
  }

  /* ── Workflow step stepper (bespoke border + gradient states) ── */

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

  /* ── Status card (bespoke translucent bg + border) ── */

  .status-card {
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.64);
    border-radius: 14px;
    padding: 0.85rem 0.9rem;
    min-width: 0;
  }

  /* ── Advanced details panel (bespoke border + bg) ── */

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

  /* ── Workflow footer (border-top separator) ── */

  .workflow-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    padding-top: 0.15rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  /* ── Recovery card (bespoke warning gradient) ── */

  .recovery-card {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
    border: 1px solid rgba(176, 117, 14, 0.22);
    border-radius: 14px;
    background: linear-gradient(145deg, rgba(255, 252, 241, 0.96), rgba(255, 246, 225, 0.94));
    padding: 0.85rem 0.9rem;
  }

  .recovery-card .cause-detail {
    margin: 0.5rem 0 0;
    padding: 0.5rem 0.65rem;
    background: rgba(0, 0, 0, 0.04);
    border-radius: 6px;
    font-size: 0.78rem;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
    color: rgba(0, 0, 0, 0.6);
  }

  /* ── Preview panel (border-top separator) ── */

  .preview-panel {
    display: grid;
    gap: 0.9rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  /* ── Result / next-step banners (bespoke border + bg) ── */

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

  /* ── Inbox / history lists ── */

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

  /* ── Candidate row (bespoke transition + hover + selected state) ── */

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

  .row-selected-note {
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--brand);
  }

  /* ── Empty state panel (dashed border) ── */

  .empty-panel {
    border: 1px dashed rgba(10, 61, 89, 0.14);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.46);
    padding: 1rem;
  }

  /* ── History row (bespoke card) ── */

  .history-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.66);
    padding: 0.9rem;
  }

  /* ── Code preview block ── */

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

  /* ── Tablet responsive: row collapses ── */

  @media (max-width: 720px) {
    .row {
      flex-direction: column;
    }
  }
</style>
