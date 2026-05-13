<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import { showImportUndoToast, showInfoToast } from '$lib/undo-toast';

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

  type FenceRow = {
    date: string;
    payee: string;
    amount: string;
    sourceIdentity: string;
    conflictReason: string;
    reconciledThrough: string;
  };

  type PreviewResult = {
    stageId: string;
    importAccountId?: string;
    importAccountDisplayName?: string;
    destinationAccount?: string;
    trackedAccountId?: string | null;
    summary?: {
      newCount: number;
      duplicateCount: number;
      fenceCount: number;
      unknownCount: number;
    };
    conflicts?: FenceRow[];
    targetJournalPath?: string;
    result?: {
      applied: boolean;
      backupPath?: string | null;
      archivedCsvPath?: string | null;
      appendedTxnCount: number;
      skippedDuplicateCount: number;
      conflicts?: FenceRow[];
      sourceCsvWarning?: string | null;
      historyId?: string;
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

  type LoadingState = 'idle' | 'upload' | 'preview' | 'apply' | 'undo' | 'remove';

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

  type ConflictView = {
    stageId: string;
    importAccountDisplayName: string;
    trackedAccountId: string | null;
    reconciledThrough: string;
    newCount: number;
    fenceCount: number;
    fenceRows: FenceRow[];
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
  let historyEntries: ImportHistoryEntry[] = [];
  let historyMessage = '';
  let error = '';
  let recoveryState: ImportRecoveryState | null = null;
  let loadingState: LoadingState = 'idle';
  let hydrated = false;
  let lastRefreshToken = refreshToken;
  let statementFileInput: HTMLInputElement | null = null;
  let selectedCandidate: Candidate | null = null;

  // The conflict-resolution view replaces the main panel when a stage
  // produces fence rows. Per DECISIONS §21 this is the only conflict reason
  // the UI surfaces; identity collisions silently skip.
  let conflictView: ConflictView | null = null;

  // Inline year-override affordance: hidden by default, shown when the user
  // clicks "Change". A 400ms debounce on input avoids one-import-per-keystroke.
  let yearOverrideOpen = false;
  let yearDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  // Idempotency: re-trigger only when the selection or year actually changes.
  // Format: `${importAccountId}|${year}|${filePathOrName}`. Reset to '' when
  // a manual retry should fire.
  let lastTriggerKey = '';

  $: selectedCandidate = candidates.find((candidate) => candidate.abs_path === selectedPath) ?? null;
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

  function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
    return count === 1 ? singular : pluralForm;
  }

  /** Format an ISO date (YYYY-MM-DD) as a human-friendly date for the
   *  conflict view body and un-reconcile link copy. */
  function formatReconciledThrough(iso: string): string {
    if (!iso) return 'your last reconciliation date';
    const date = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(date.getTime())) return iso;
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'long' }).format(date);
  }

  /** Short date for register-style rows in the conflict view. Accepts
   *  either YYYY-MM-DD or YYYY/MM/DD from the importer. */
  function formatFenceDate(raw: string): string {
    const normalized = raw.replace(/\//g, '-');
    const date = new Date(`${normalized}T00:00:00`);
    if (Number.isNaN(date.getTime())) return raw;
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
  }

  function clearSelectedFile() {
    selectedFile = null;
    if (statementFileInput) statementFileInput.value = '';
  }

  function resetImportState() {
    error = '';
    historyMessage = '';
    recoveryState = null;
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

  function readyForTrigger(): boolean {
    return Boolean(importAccountId && year && (selectedFile || selectedPath));
  }

  function setImportAccount(nextId: string) {
    if (nextId === importAccountId) return;
    importAccountId = nextId;
    resetImportState();
    conflictView = null;
    lastTriggerKey = '';
    if (readyForTrigger() && !loading) void triggerImport();
  }

  function setYear(nextYear: string) {
    if (nextYear === year) return;
    year = nextYear;
    resetImportState();
    conflictView = null;
    if (yearDebounceTimer !== null) clearTimeout(yearDebounceTimer);
    yearDebounceTimer = setTimeout(() => {
      yearDebounceTimer = null;
      lastTriggerKey = '';
      if (readyForTrigger() && !loading) void triggerImport();
    }, 400);
  }

  function toggleYearOverride() {
    yearOverrideOpen = !yearOverrideOpen;
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
    conflictView = null;
    lastTriggerKey = '';
    if (readyForTrigger() && !loading) void triggerImport();
  }

  function pickCandidate(candidate: Candidate) {
    clearSelectedFile();
    selectedPath = candidate.abs_path;
    year = candidate.detected_year ?? year;
    importAccountId = candidate.detected_import_account_id ?? importAccountId;
    resetImportState();
    conflictView = null;
    lastTriggerKey = '';
    if (readyForTrigger() && !loading) void triggerImport();
  }

  async function loadImportData() {
    try {
      const state = await apiGet<{ initialized: boolean }>('/api/app/state');
      initialized = state.initialized;
      if (!initialized) {
        candidates = [];
        importAccounts = [];
        historyEntries = [];
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
        if (recoveryState?.csvPath === removedPath) {
          recoveryState = null;
        }
      }
    } catch (e) {
      error = errorMessage(e);
    }
  }

  /** End-to-end import sequence. Selection (inbox row OR file pick) triggers
   *  this; the user does not click a Preview button. When the staged result
   *  has no fence rows the apply runs immediately and confirms via toast.
   *  Fence rows transition to the in-place conflict-resolution view.
   *  See DECISIONS §21. */
  async function triggerImport() {
    if (!readyForTrigger() || loading) return;

    const fileKey = selectedFile?.name ?? selectedPath;
    const currentKey = `${importAccountId}|${year}|${fileKey}`;
    if (currentKey === lastTriggerKey) return;
    lastTriggerKey = currentKey;

    resetImportState();

    let stage: PreviewResult | null;
    try {
      if (selectedFile) {
        loadingState = 'upload';
        const form = new FormData();
        form.append('file', selectedFile);
        form.append('year', year);
        form.append('importAccountId', importAccountId);
        form.append('preview', 'true');
        const uploaded = await sendImportRequest<UploadPreviewResult>('/api/import/upload', {
          method: 'POST',
          body: form
        });
        if (!uploaded) {
          // recoveryState set by sendImportRequest
          return;
        }
        // The file is now in the inbox under uploaded.absPath; future
        // re-triggers will read from there.
        selectedPath = uploaded.absPath;
        clearSelectedFile();
        stage = uploaded;
      } else {
        loadingState = 'preview';
        stage = await sendImportRequest<PreviewResult>('/api/import/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            csvPath: selectedPath,
            year,
            importAccountId
          })
        });
        if (!stage) return;
      }

      const newCount = stage.summary?.newCount ?? 0;
      const fenceCount = stage.summary?.fenceCount ?? 0;
      const duplicateCount = stage.summary?.duplicateCount ?? 0;

      if (fenceCount > 0) {
        // Hand off to the conflict-resolution view; do not apply yet.
        conflictView = buildConflictView(stage, newCount, fenceCount);
        return;
      }

      if (newCount === 0) {
        // Nothing to apply. Skip the apply call entirely.
        if (duplicateCount > 0) {
          showInfoToast(`Nothing new to add — ${duplicateCount} already imported`);
        }
        selectedPath = '';
        await loadImportData();
        return;
      }

      await applyStage(stage, { fenceCount: 0 });
    } catch (e) {
      error = errorMessage(e);
      // Allow a fresh retry on the same selection.
      lastTriggerKey = '';
    } finally {
      loadingState = 'idle';
    }
  }

  function buildConflictView(stage: PreviewResult, newCount: number, fenceCount: number): ConflictView {
    const fenceRows = (stage.conflicts ?? []).filter(
      (row) => row.conflictReason === 'reconciled_date_fence'
    );
    const reconciledThrough = fenceRows[0]?.reconciledThrough ?? '';
    return {
      stageId: stage.stageId,
      importAccountDisplayName: stage.importAccountDisplayName ?? '',
      trackedAccountId: stage.trackedAccountId ?? null,
      reconciledThrough,
      newCount,
      fenceCount,
      fenceRows
    };
  }

  async function applyStage(stage: PreviewResult, opts: { fenceCount: number }) {
    loadingState = 'apply';
    const applied = await apiPost<PreviewResult>('/api/import/apply', { stageId: stage.stageId });
    const appendedCount = applied.result?.appendedTxnCount ?? 0;
    const skippedDuplicates = applied.result?.skippedDuplicateCount ?? 0;
    const historyId = applied.result?.historyId;

    const parts: string[] = [`Added ${appendedCount} ${plural(appendedCount, 'transaction')}`];
    if (skippedDuplicates > 0) {
      parts.push(`skipped ${skippedDuplicates} already imported`);
    }
    if (opts.fenceCount > 0) {
      parts.push(`skipped ${opts.fenceCount} reconciled`);
    }
    const summary = parts.join(' · ');

    if (historyId) {
      showImportUndoToast(historyId, summary, async () => {
        await loadImportData();
      });
    }

    selectedPath = '';
    conflictView = null;
    lastTriggerKey = '';
    await loadImportData();

    if (onApplied) {
      await onApplied(applied);
    }
  }

  async function applyFromConflictView() {
    if (!conflictView || loading) return;
    const cv = conflictView;
    if (cv.newCount === 0) return;

    resetImportState();
    try {
      await applyStage(
        { stageId: cv.stageId } as PreviewResult,
        { fenceCount: cv.fenceCount }
      );
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  function cancelConflictView() {
    // Per task: clear the view only. Do NOT remove the stage or the inbox
    // row. The user may un-reconcile and come back. Explicit cleanup belongs
    // on the Remove from Inbox affordance, not Cancel.
    conflictView = null;
    lastTriggerKey = '';
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
      conflictView = null;
      lastTriggerKey = '';
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

  function progressLabel(): string {
    if (loadingState === 'upload') return 'Uploading…';
    if (loadingState === 'preview') return 'Checking statement…';
    if (loadingState === 'apply') return 'Adding…';
    if (loadingState === 'remove') return 'Removing…';
    if (loadingState === 'undo') return 'Undoing…';
    return '';
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
      <p class="subtitle">Drop a CSV or pick a waiting statement. We add new transactions, skip ones already imported, and only pause to ask if a row falls before your last reconciliation.</p>
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
    {:else if conflictView}
      <section class="view-card conflict-card grid gap-4">
        <div class="grid gap-1.5">
          <p class="eyebrow conflict-eyebrow">Needs your attention</p>
          <h3 class="m-0">Some transactions are before your last reconciliation</h3>
          <p class="muted mt-1">
            You reconciled this account through {formatReconciledThrough(conflictView.reconciledThrough)}.
            {conflictView.fenceCount === 1 ? 'This transaction is' : `These ${conflictView.fenceCount} transactions are`}
            dated on or before that, so we won't add {conflictView.fenceCount === 1 ? 'it' : 'them'} automatically.
          </p>
        </div>

        <div class="fence-list">
          {#each conflictView.fenceRows as row}
            <div class="fence-row">
              <span class="fence-date">{formatFenceDate(row.date)}</span>
              <span class="fence-payee">{row.payee}</span>
              <span class="fence-amount">{row.amount}</span>
            </div>
          {/each}
        </div>

        <div class="workflow-footer max-tablet:flex-col max-tablet:items-stretch">
          <p class="muted m-0">
            {#if conflictView.trackedAccountId && conflictView.importAccountDisplayName}
              To include these, un-reconcile {formatReconciledThrough(conflictView.reconciledThrough)} first.
              <a href="/accounts/{conflictView.trackedAccountId}">Open {conflictView.importAccountDisplayName} →</a>
            {:else if conflictView.importAccountDisplayName}
              To include these, un-reconcile {formatReconciledThrough(conflictView.reconciledThrough)} first on {conflictView.importAccountDisplayName}.
            {/if}
          </p>
          <div class="flex gap-2.5 flex-wrap">
            <button class="btn" type="button" disabled={loading} on:click={cancelConflictView}>
              Cancel
            </button>
            <button class="btn btn-primary" type="button"
                    disabled={loading || conflictView.newCount === 0}
                    on:click={applyFromConflictView}>
              {#if conflictView.newCount === 0}
                All rows are before {formatReconciledThrough(conflictView.reconciledThrough)}
              {:else if loadingState === 'apply'}
                Adding…
              {:else}
                Add the other {conflictView.newCount} {plural(conflictView.newCount, 'transaction')}
              {/if}
            </button>
          </div>
        </div>
      </section>
    {:else if mode === 'setup'}
      <section class="view-card grid gap-4">
        <div class="flex justify-between gap-4 items-start flex-wrap">
          <div class="min-w-0">
            <p class="eyebrow">Prepare</p>
            <h3 class="m-0">Upload your first statement</h3>
            <p class="muted mt-1">Pick the account, then drop in a CSV. We add new transactions, skip ones already imported, and pause only if something would change a balance you've already reconciled.</p>
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
            <div class="year-override-row">
              <span class="year-override-label">Year: {year}</span>
              <button type="button" class="year-override-toggle" on:click={toggleYearOverride}>
                {yearOverrideOpen ? 'Done' : 'Change'}
              </button>
            </div>
            {#if yearOverrideOpen}
              <input
                id={`year-${mode}`}
                value={year}
                inputmode="numeric"
                on:input={(e) => setYear((e.currentTarget as HTMLInputElement).value)}
              />
            {/if}
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
            {#if !importAccountId}
              <p class="muted text-xs m-0">Choose an account above to import.</p>
            {/if}
          </div>
        </div>

        <section class="grid gap-3.5">
          <div class="flex justify-between gap-4 items-start flex-wrap">
            <div class="min-w-0">
              <p class="eyebrow">Inbox</p>
              <h3 class="m-0">Pick a statement to continue</h3>
              <p class="muted mt-1">Files that already passed validation wait here until you import them.</p>
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

        {#if loading || selectedCandidate}
          <div class="workflow-footer max-tablet:flex-col max-tablet:items-stretch">
            <p class="muted m-0">
              {#if loading}
                {progressLabel()}
              {:else}
                Selected: {selectedCandidate?.file_name}
              {/if}
            </p>
            {#if selectedCandidate && !loading}
              <button class="btn" type="button" on:click={removeSelectedCandidate}>
                Remove from Inbox
              </button>
            {/if}
          </div>
        {/if}
      </section>
    {:else}
      <section class="import-layout max-desktop:grid-cols-1">
        <article class="view-card grid gap-4">
          <div class="min-w-0">
            <p class="eyebrow">Current Import</p>
            <h3 class="m-0">Add a statement</h3>
            <p class="muted mt-1">Pick an inbox statement or drop in a new CSV — we'll add it as soon as it's selected.</p>
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
              <div class="year-override-row">
                <span class="year-override-label">Year: {year}</span>
                <button type="button" class="year-override-toggle" on:click={toggleYearOverride}>
                  {yearOverrideOpen ? 'Done' : 'Change'}
                </button>
              </div>
              {#if yearOverrideOpen}
                <input
                  id={`year-${mode}`}
                  value={year}
                  inputmode="numeric"
                  on:input={(e) => setYear((e.currentTarget as HTMLInputElement).value)}
                />
              {/if}
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
              {#if !importAccountId}
                <p class="muted text-xs m-0">Choose an account above to import.</p>
              {/if}
            </div>
          </div>

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

          {#if loading || selectedCandidate}
            <div class="workflow-footer max-tablet:flex-col max-tablet:items-stretch">
              <p class="muted m-0">
                {#if loading}
                  {progressLabel()}
                {:else}
                  Selected: {selectedCandidate?.file_name}
                {/if}
              </p>
              {#if selectedCandidate && !loading}
                <button class="btn" type="button" on:click={removeSelectedCandidate}>
                  Remove from Inbox
                </button>
              {/if}
            </div>
          {/if}
        </article>

        <aside class="grid gap-4 items-start">
          <article class="view-card grid gap-4">
            <div class="flex justify-between gap-4 items-start flex-wrap">
              <div class="min-w-0">
                <p class="eyebrow">Waiting Statements</p>
                <h3 class="m-0">Pick a statement to continue</h3>
                <p class="muted mt-1">Validated statements stay here until they're imported or removed.</p>
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
  /* ── Asymmetric two-column layout (standalone) ── */

  .import-layout {
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(19rem, 0.9fr);
    gap: 1rem;
    align-items: start;
  }

  /* ── Inline year override (replaces a labeled input on the resting state) ── */

  .year-override-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.55rem 0;
  }

  .year-override-label {
    font-weight: 600;
    color: var(--brand-strong);
  }

  .year-override-toggle {
    background: transparent;
    border: none;
    padding: 0;
    color: var(--brand);
    font-size: 0.85rem;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .year-override-toggle:hover {
    color: var(--brand-strong);
  }

  /* ── Conflict-resolution view (amber emphasis per project palette) ── */

  .conflict-card {
    border-color: rgba(176, 117, 14, 0.32);
    background: linear-gradient(145deg, rgba(255, 252, 241, 0.96), rgba(255, 246, 225, 0.94));
  }

  .conflict-eyebrow {
    color: #b0750e;
  }

  .fence-list {
    display: grid;
    gap: 0.4rem;
  }

  .fence-row {
    display: grid;
    grid-template-columns: 4rem minmax(0, 1fr) auto;
    gap: 0.75rem;
    align-items: baseline;
    padding: 0.55rem 0.7rem;
    background: rgba(255, 255, 255, 0.7);
    border-radius: 10px;
    border: 1px solid rgba(176, 117, 14, 0.18);
  }

  .fence-date {
    color: var(--muted-foreground);
    font-size: 0.85rem;
    font-weight: 600;
  }

  .fence-payee {
    min-width: 0;
    overflow-wrap: anywhere;
    font-weight: 600;
  }

  .fence-amount {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }

  /* ── Advanced details panel (kept for history row details) ── */

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

  /* ── Workflow footer ── */

  .workflow-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    padding-top: 0.15rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  /* ── Recovery card ── */

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

  /* ── Candidate row ── */

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

  /* ── Empty state panel ── */

  .empty-panel {
    border: 1px dashed rgba(10, 61, 89, 0.14);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.46);
    padding: 1rem;
  }

  /* ── History row ── */

  .history-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 1rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.66);
    padding: 0.9rem;
  }

  /* ── Tablet responsive ── */

  @media (max-width: 720px) {
    .row {
      flex-direction: column;
    }

    .fence-row {
      grid-template-columns: 1fr;
      gap: 0.25rem;
    }
  }
</style>
