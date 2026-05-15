<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import { showImportUndoToast } from '$lib/undo-toast';

  type Candidate = {
    file_name: string;
    abs_path: string;
    detected_year: string | null;
    detected_import_account_id: string | null;
    detected_import_account_display_name: string | null;
    detected_institution_display_name: string | null;
    is_configured_import_account: boolean;
    transaction_count: number | null;
    date_range: { start: string; end: string } | null;
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

  type StagedPreview = {
    stageId: string;
    newCount: number;
    duplicateCount: number;
    fenceCount: number;
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
  let error = '';
  let recoveryState: ImportRecoveryState | null = null;
  let loadingState: LoadingState = 'idle';
  let hydrated = false;
  let lastRefreshToken = refreshToken;
  let statementFileInput: HTMLInputElement | null = null;
  let selectedCandidate: Candidate | null = null;
  let conflictView: ConflictView | null = null;
  let lastTriggerKey = '';
  let stagedPreview: StagedPreview | null = null;
  let dropZoneActive = false;
  let dropError = '';
  let showAllHistory = false;
  let expandedHistoryId = '';

  $: selectedCandidate = candidates.find((c) => c.abs_path === selectedPath) ?? null;
  $: loading = loadingState !== 'idle';
  $: if (hydrated && refreshToken !== lastRefreshToken) {
    lastRefreshToken = refreshToken;
    void loadImportData();
  }
  $: visibleHistory = showAllHistory ? historyEntries : historyEntries.slice(0, 5);

  // ── Helpers ──

  function accountLabel(account: ImportAccountOption): string {
    return account.last4 ? `${account.displayName} ••${account.last4}` : account.displayName;
  }

  function candidateLabel(candidate: Candidate): string {
    return candidate.detected_import_account_display_name ?? candidate.file_name;
  }

  function candidateSecondary(candidate: Candidate): string | null {
    if (!candidate.transaction_count || !candidate.date_range) return null;
    const start = formatShortDate(candidate.date_range.start);
    const end = formatShortDate(candidate.date_range.end);
    return `${candidate.transaction_count} transactions · ${start} – ${end}`;
  }

  function formatShortDate(iso: string): string {
    const date = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(date.getTime())) return iso;
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
  }

  function formatHistoryDate(value?: string | null): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
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

  function formatReconciledThrough(iso: string): string {
    if (!iso) return 'your last reconciliation date';
    const date = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(date.getTime())) return iso;
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'long' }).format(date);
  }

  function formatFenceDate(raw: string): string {
    const normalized = raw.replace(/\//g, '-');
    const date = new Date(`${normalized}T00:00:00`);
    if (Number.isNaN(date.getTime())) return raw;
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
  }

  function optionalPathLabel(path?: string | null, fallback = 'Unknown file'): string {
    return path ? (path.split('/').filter(Boolean).at(-1) ?? path) : fallback;
  }

  function clearSelectedFile() {
    selectedFile = null;
    if (statementFileInput) statementFileInput.value = '';
  }

  function resetImportState() {
    error = '';
    recoveryState = null;
  }

  // ── File validation ──

  function isValidCsv(file: File): boolean {
    return file.name.toLowerCase().endsWith('.csv') || file.type === 'text/csv';
  }

  // ── API helpers ──

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

  // ── State management ──

  function readyForTrigger(): boolean {
    return Boolean(importAccountId && (selectedFile || selectedPath));
  }

  function setImportAccount(nextId: string) {
    if (nextId === importAccountId) return;
    importAccountId = nextId;
    resetImportState();
    conflictView = null;
    stagedPreview = null;
    lastTriggerKey = '';
    if (readyForTrigger() && !loading) void triggerPreview();
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
    stagedPreview = null;
    lastTriggerKey = '';
    if (readyForTrigger() && !loading) void triggerPreview();
  }

  function pickCandidate(candidate: Candidate) {
    clearSelectedFile();
    selectedPath = candidate.abs_path;
    year = candidate.detected_year ?? year;
    importAccountId = candidate.detected_import_account_id ?? importAccountId;
    resetImportState();
    conflictView = null;
    stagedPreview = null;
    lastTriggerKey = '';
    if (readyForTrigger() && !loading) void triggerPreview();
  }

  // ── Drop zone handlers ──

  function onDragOver(e: DragEvent) {
    e.preventDefault();
    dropZoneActive = true;
  }

  function onDragLeave() {
    dropZoneActive = false;
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dropZoneActive = false;
    dropError = '';

    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;

    const file = Array.from(files).find(isValidCsv);
    if (!file) {
      dropError = 'Choose a CSV file';
      return;
    }

    selectedFile = file;
    selectedPath = '';
    resetImportState();
    conflictView = null;
    stagedPreview = null;
    lastTriggerKey = '';
    if (readyForTrigger() && !loading) void triggerPreview();
  }

  function openFilePicker() {
    statementFileInput?.click();
  }

  // ── Data loading ──

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

      if (importAccountId && !importAccounts.some((a) => a.id === importAccountId)) {
        importAccountId = '';
      }

      if (selectedPath && !candidates.some((c) => c.abs_path === selectedPath)) {
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

  // ── Preview (selection does NOT apply) ──

  async function triggerPreview() {
    if (!readyForTrigger() || loading) return;

    const fileKey = selectedFile?.name ?? selectedPath;
    const currentKey = `${importAccountId}|${year}|${fileKey}`;
    if (currentKey === lastTriggerKey) return;
    lastTriggerKey = currentKey;

    resetImportState();
    stagedPreview = null;

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
        if (!uploaded) return;
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
        conflictView = buildConflictView(stage, newCount, fenceCount);
        return;
      }

      stagedPreview = {
        stageId: stage.stageId,
        newCount,
        duplicateCount,
        fenceCount
      };

      // Reload to pick up newly uploaded file in inbox list
      await loadImportData();
    } catch (e) {
      error = errorMessage(e);
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

  // ── Confirm + apply (user-initiated) ──

  async function confirmApply() {
    if (!stagedPreview || loading) return;
    const { stageId, fenceCount } = stagedPreview;

    try {
      loadingState = 'apply';
      const applied = await apiPost<PreviewResult>('/api/import/apply', { stageId });
      const appendedCount = applied.result?.appendedTxnCount ?? 0;
      const skippedDuplicates = applied.result?.skippedDuplicateCount ?? 0;
      const historyId = applied.result?.historyId;

      const parts: string[] = [`Added ${appendedCount} ${plural(appendedCount, 'transaction')}`];
      if (skippedDuplicates > 0) {
        parts.push(`skipped ${skippedDuplicates} already imported`);
      }
      if (fenceCount > 0) {
        parts.push(`skipped ${fenceCount} reconciled`);
      }
      const summary = parts.join(' · ');

      if (historyId) {
        showImportUndoToast(historyId, summary, async () => {
          await loadImportData();
        });
      }

      selectedPath = '';
      stagedPreview = null;
      conflictView = null;
      lastTriggerKey = '';
      await loadImportData();

      if (onApplied) {
        await onApplied(applied);
      }
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  async function applyFromConflictView() {
    if (!conflictView || loading) return;
    const cv = conflictView;
    if (cv.newCount === 0) return;

    resetImportState();
    try {
      loadingState = 'apply';
      const applied = await apiPost<PreviewResult>('/api/import/apply', { stageId: cv.stageId });
      const appendedCount = applied.result?.appendedTxnCount ?? 0;
      const skippedDuplicates = applied.result?.skippedDuplicateCount ?? 0;
      const historyId = applied.result?.historyId;

      const parts: string[] = [`Added ${appendedCount} ${plural(appendedCount, 'transaction')}`];
      if (skippedDuplicates > 0) {
        parts.push(`skipped ${skippedDuplicates} already imported`);
      }
      parts.push(`skipped ${cv.fenceCount} reconciled`);
      const summary = parts.join(' · ');

      if (historyId) {
        showImportUndoToast(historyId, summary, async () => {
          await loadImportData();
        });
      }

      selectedPath = '';
      stagedPreview = null;
      conflictView = null;
      lastTriggerKey = '';
      await loadImportData();

      if (onApplied) {
        await onApplied(applied);
      }
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  function cancelConflictView() {
    conflictView = null;
    lastTriggerKey = '';
  }

  // ── Inbox removal (per-row, not gated on selection) ──

  async function removeCandidate(candidate: Candidate, event: Event) {
    event.stopPropagation();

    const confirmed = window.confirm(
      `Remove ${candidate.detected_import_account_display_name ?? candidate.file_name} from the inbox?`
    );
    if (!confirmed) return;

    loadingState = 'remove';
    error = '';
    recoveryState = null;

    try {
      await apiPost('/api/import/remove', { csvPath: candidate.abs_path });
      if (selectedPath === candidate.abs_path) {
        selectedPath = '';
        stagedPreview = null;
        conflictView = null;
        lastTriggerKey = '';
      }
      await loadImportData();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  // ── History ──

  async function undoHistoryEntry(entry: ImportHistoryEntry) {
    if (!entry.canUndo) return;

    const confirmed = window.confirm(
      `Undo ${entry.csvFileName ?? 'this import'}? This removes the transactions added by this import.`
    );
    if (!confirmed) return;

    error = '';
    recoveryState = null;
    loadingState = 'undo';

    try {
      await apiPost<{ entry: ImportHistoryEntry }>('/api/import/undo', { historyId: entry.id });
      await loadImportData();
    } catch (e) {
      error = errorMessage(e);
    } finally {
      loadingState = 'idle';
    }
  }

  function toggleHistoryDetail(id: string) {
    expandedHistoryId = expandedHistoryId === id ? '' : id;
  }

  // ── Lifecycle ──

  onMount(async () => {
    hydrated = true;
    lastRefreshToken = refreshToken;
    await loadImportData();
  });
</script>

<div class="grid gap-4">
  {#if !initialized}
    <section class="view-card">
      <h3 class="m-0">Finish setup before importing statements</h3>
      <p class="muted">Import becomes available after the workspace exists and at least one account is ready to receive statement activity.</p>
      <a class="btn btn-primary" href="/setup">Open setup</a>
    </section>
  {:else if importAccounts.length === 0}
    <section class="view-card">
      <h3 class="m-0">Add an account before importing</h3>
      <p class="muted">Connect a supported account or save a custom CSV mapping first.</p>
      <div class="flex gap-2.5 flex-wrap">
        <a class="btn btn-primary" href="/accounts/configure?mode=institution">Add supported account</a>
        <a class="btn" href="/accounts/configure?mode=custom">Add custom CSV</a>
      </div>
    </section>
  {:else if conflictView}
    <!-- Conflict resolution view -->
    <section class="view-card conflict-card grid gap-4">
      <div class="grid gap-1.5">
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

      <div class="flex justify-between items-center gap-4 flex-wrap">
        <p class="muted m-0 text-sm">
          {#if conflictView.trackedAccountId && conflictView.importAccountDisplayName}
            <a href="/accounts/{conflictView.trackedAccountId}">Un-reconcile {conflictView.importAccountDisplayName} →</a>
          {:else if conflictView.importAccountDisplayName}
            Un-reconcile {conflictView.importAccountDisplayName} to include these.
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
              No new transactions to add
            {:else if loadingState === 'apply'}
              Adding…
            {:else}
              Add {conflictView.newCount} {plural(conflictView.newCount, 'transaction')}
            {/if}
          </button>
        </div>
      </div>
    </section>
  {:else}
    <!-- Main import flow -->

    {#if error}
      <p class="error-text m-0">{error}</p>
    {/if}

    <!-- Drop zone hero card -->
    <section
      class="view-card import-hero"
      class:drop-zone-active={dropZoneActive}
      on:dragover={onDragOver}
      on:dragleave={onDragLeave}
      on:drop={onDrop}
      aria-label="File drop zone"
    >
      {#if mode !== 'setup'}
        <p class="eyebrow">Import</p>
        <h2 class="page-title">Import transactions</h2>
      {:else}
        <p class="muted text-sm m-0">Pick the account, then drop in a CSV. We add new transactions, skip ones already imported, and pause only if something would change a balance you've already reconciled.</p>
      {/if}

      <input
        bind:this={statementFileInput}
        type="file"
        accept=".csv,text/csv"
        class="hidden"
        on:change={onStatementFileChange}
      />

      <div class="drop-zone-content">
        <svg class="drop-zone-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        <button type="button" class="drop-zone-label" on:click={openFilePicker}>
          Drop a CSV here, or click to browse
        </button>

        {#if dropError}
          <p class="error-text text-sm m-0 mt-1">{dropError}</p>
        {/if}
      </div>

      {#if importAccounts.length > 1}
        <div class="drop-zone-account">
          <select
            value={importAccountId}
            on:change={(e) => setImportAccount((e.currentTarget as HTMLSelectElement).value)}
            class="drop-zone-select"
          >
            <option value="">Select account…</option>
            {#each importAccounts as account}
              <option value={account.id}>{accountLabel(account)}</option>
            {/each}
          </select>
        </div>
      {/if}
    </section>

    <!-- Recovery state -->
    {#if recoveryState}
      <section class="recovery-card">
        <div class="min-w-0">
          <h4 class="m-0">{recoveryState.fileKeptInInbox ? 'This statement needs a different account' : 'Upload blocked'}</h4>
          <p class="muted mt-1 m-0">{recoveryState.message}</p>
          {#if recoveryState.causeMessage}
            <pre class="cause-detail">{recoveryState.causeMessage}</pre>
          {/if}
        </div>
      </section>
    {/if}

    <!-- Inbox list -->
    {#if candidates.length > 0}
      <section class="view-card grid gap-3">
        <div class="flex justify-between items-center">
          <h3 class="m-0 text-sm font-semibold text-muted-foreground uppercase tracking-wide">Inbox</h3>
          <span class="text-xs text-muted-foreground">{candidates.length} waiting</span>
        </div>

        <div class="inbox-list">
          {#each candidates as candidate}
            <div class="inbox-item-wrapper">
              <button
                class="inbox-row"
                class:inbox-row-selected={candidate.abs_path === selectedPath}
                type="button"
                aria-pressed={candidate.abs_path === selectedPath}
                on:click={() => pickCandidate(candidate)}
              >
                <div class="grid gap-0.5 min-w-0">
                  <span class="font-semibold text-sm truncate">{candidateLabel(candidate)}</span>
                  {#if candidateSecondary(candidate)}
                    <span class="text-xs text-muted-foreground">{candidateSecondary(candidate)}</span>
                  {/if}
                </div>

                <div class="flex items-center gap-2 shrink-0">
                  {#if candidate.is_configured_import_account}
                    <span class="pill ok text-xs">Ready</span>
                  {:else}
                    <span class="pill warn text-xs">Needs setup</span>
                  {/if}
                </div>
              </button>

              <button
                class="trash-btn"
                type="button"
                aria-label="Remove from inbox"
                disabled={loading}
                on:click={(e) => removeCandidate(candidate, e)}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="w-3.5 h-3.5">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>

            <!-- Animated preview slot attached to selected row -->
            {#if candidate.abs_path === selectedPath}
              <div class="preview-slot" class:preview-slot-open={stagedPreview || loadingState === 'preview' || loadingState === 'upload'}>
                <div class="preview-slot-inner">
                  {#if loadingState === 'preview' || loadingState === 'upload'}
                    <span class="text-sm text-muted-foreground">Checking…</span>
                  {:else if stagedPreview}
                    <div class="flex items-center justify-between gap-3 flex-wrap">
                      <span class="text-sm">
                        {#if stagedPreview.newCount === 0}
                          Nothing new to add — {stagedPreview.duplicateCount} already imported
                        {:else}
                          {stagedPreview.newCount} new · {stagedPreview.duplicateCount} already imported
                        {/if}
                      </span>
                      {#if stagedPreview.newCount > 0}
                        <button
                          class="btn btn-primary text-sm"
                          type="button"
                          disabled={loading}
                          on:click={confirmApply}
                        >
                          {#if loadingState === 'apply'}
                            Adding…
                          {:else}
                            Add {stagedPreview.newCount} {plural(stagedPreview.newCount, 'transaction')}
                          {/if}
                        </button>
                      {/if}
                    </div>
                  {/if}
                </div>
              </div>
            {/if}
          {/each}
        </div>
      </section>
    {/if}

    <!-- Preview for file drop (no inbox row to attach to) -->
    {#if selectedFile && !selectedPath}
      <div class="preview-slot preview-slot-open">
        <div class="preview-slot-inner">
          {#if loadingState === 'upload'}
            <span class="text-sm text-muted-foreground">Uploading…</span>
          {:else if !importAccountId}
            <span class="text-sm text-muted-foreground">Choose an account to continue.</span>
          {/if}
        </div>
      </div>
    {/if}

    <!-- Compact history -->
    {#if historyEntries.length > 0}
      <section class="view-card grid gap-3">
        <h3 class="m-0 text-sm font-semibold text-muted-foreground uppercase tracking-wide">History</h3>

        <div class="history-compact">
          {#each visibleHistory as entry}
            <div class="history-compact-row">
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <span class="text-xs text-muted-foreground w-12 shrink-0 tabular-nums">{formatHistoryDate(entry.appliedAt)}</span>
                <span class="text-sm truncate">{entry.importAccountDisplayName ?? entry.importAccountId ?? ''}</span>
                <span class="text-xs font-semibold text-ok">+{entry.result?.appendedTxnCount ?? 0}</span>
                {#if entry.status === 'undone'}
                  <span class="text-xs text-muted-foreground">Undone</span>
                {/if}
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                {#if entry.canUndo && entry.status !== 'undone'}
                  <button
                    class="text-xs text-muted-foreground hover:text-brand-strong cursor-pointer bg-transparent border-none p-0"
                    type="button"
                    disabled={loading}
                    on:click={() => undoHistoryEntry(entry)}
                  >Undo</button>
                {/if}
                <button
                  class="info-btn"
                  type="button"
                  aria-label="Show details"
                  on:click={() => toggleHistoryDetail(entry.id)}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="w-3.5 h-3.5">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                </button>
              </div>
            </div>

            {#if expandedHistoryId === entry.id}
              <div class="history-detail">
                <p class="text-xs text-muted-foreground m-0">{formatDateTime(entry.appliedAt)}</p>
                {#if entry.csvFileName}
                  <p class="text-xs text-muted-foreground m-0">File: {entry.csvFileName}</p>
                {/if}
                {#if entry.targetJournalPath}
                  <p class="text-xs text-muted-foreground m-0">Journal: {entry.targetJournalPath}</p>
                {/if}
                {#if entry.backupPath}
                  <p class="text-xs text-muted-foreground m-0">Backup: {entry.backupPath}</p>
                {/if}
                {#if entry.undo?.undoneAt}
                  <p class="text-xs text-muted-foreground m-0">Undone: {formatDateTime(entry.undo.undoneAt)}</p>
                {/if}
                {#if entry.undo?.restoredInboxCsvPath}
                  <p class="text-xs text-muted-foreground m-0">Restored to inbox: {entry.undo.restoredInboxCsvPath}</p>
                {/if}
                {#if !entry.canUndo && entry.undoBlockedReason}
                  <p class="text-xs text-muted-foreground m-0">{entry.undoBlockedReason}</p>
                {/if}
              </div>
            {/if}
          {/each}
        </div>

        {#if historyEntries.length > 5}
          <button
            class="text-xs text-brand cursor-pointer bg-transparent border-none p-0 text-left"
            type="button"
            on:click={() => (showAllHistory = !showAllHistory)}
          >
            {showAllHistory ? 'Show fewer' : `Show all ${historyEntries.length}`}
          </button>
        {/if}
      </section>
    {:else if initialized}
      <p class="text-xs text-muted-foreground m-0 mt-2">No imports yet.</p>
    {/if}
  {/if}
</div>

<style>
  /* ── Drop zone hero card ── */

  .import-hero {
    background:
      radial-gradient(circle at top left, rgba(214, 235, 220, 0.86), transparent 34%),
      linear-gradient(155deg, #fbfdf8 0%, #f6fbff 60%, #eef6f3 100%);
    display: grid;
    gap: 1rem;
    transition:
      border-color 0.18s ease,
      background-color 0.18s ease;
  }

  .drop-zone-active {
    border-color: rgba(13, 127, 88, 0.45);
    background:
      radial-gradient(circle at top left, rgba(13, 127, 88, 0.07), transparent 34%),
      linear-gradient(155deg, #f5fdf8 0%, #edf8f2 60%, #e8f5ef 100%);
  }

  .drop-zone-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    border: 2px dashed rgba(10, 61, 89, 0.18);
    border-radius: 12px;
    padding: 2rem 1.5rem;
    min-height: 140px;
    justify-content: center;
    background: rgba(255, 255, 255, 0.42);
  }

  .drop-zone-active .drop-zone-content {
    border-color: rgba(13, 127, 88, 0.5);
    border-style: solid;
    background: rgba(255, 255, 255, 0.6);
  }

  .drop-zone-icon {
    width: 2.5rem;
    height: 2.5rem;
    color: var(--muted-foreground);
    opacity: 0.6;
  }

  .drop-zone-label {
    background: none;
    border: none;
    padding: 0;
    color: var(--brand);
    font-size: 0.95rem;
    font-weight: 500;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .drop-zone-label:hover {
    color: var(--brand-strong);
  }

  .drop-zone-account {
    width: 100%;
    max-width: 18rem;
  }

  .drop-zone-select {
    width: 100%;
    padding: 0.45rem 0.7rem;
    border: 1px solid rgba(10, 61, 89, 0.14);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.8);
    font-size: 0.85rem;
    color: var(--brand-strong);
    cursor: pointer;
  }

  .drop-zone-select:focus {
    outline: 2px solid var(--brand);
    outline-offset: 1px;
  }

  /* ── Inbox rows ── */

  .inbox-list {
    display: grid;
    gap: 0;
  }

  .inbox-item-wrapper {
    display: flex;
    align-items: stretch;
    gap: 0;
    border-bottom: 1px solid rgba(10, 61, 89, 0.06);
  }

  .inbox-item-wrapper:last-child {
    border-bottom: none;
  }

  .inbox-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    flex: 1;
    min-width: 0;
    text-align: left;
    cursor: pointer;
    border: none;
    background: transparent;
    padding: 0.6rem 0.7rem;
    border-radius: 8px;
    transition:
      background-color 0.14s ease;
  }

  .inbox-row:hover {
    background: rgba(15, 95, 136, 0.04);
  }

  .inbox-row-selected {
    background: rgba(15, 95, 136, 0.07);
  }

  .trash-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    background: transparent;
    border: none;
    color: var(--muted-foreground);
    opacity: 0.4;
    cursor: pointer;
    transition: opacity 0.14s ease;
  }

  .trash-btn:hover {
    opacity: 0.9;
    color: #b91c1c;
  }

  /* ── Preview slot (animated) ── */

  .preview-slot {
    display: grid;
    grid-template-rows: 0fr;
    opacity: 0;
    transition:
      grid-template-rows 0.2s ease,
      opacity 0.2s ease;
  }

  .preview-slot-open {
    grid-template-rows: 1fr;
    opacity: 1;
  }

  .preview-slot-inner {
    overflow: hidden;
    padding: 0 0.7rem;
  }

  .preview-slot-open .preview-slot-inner {
    padding: 0.5rem 0.7rem 0.6rem;
  }

  /* ── Compact history ── */

  .history-compact {
    display: grid;
    gap: 0;
  }

  .history-compact-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0;
    border-bottom: 1px solid rgba(10, 61, 89, 0.05);
  }

  .history-compact-row:last-child {
    border-bottom: none;
  }

  .info-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    color: var(--muted-foreground);
    opacity: 0.5;
    cursor: pointer;
    padding: 0.15rem;
  }

  .info-btn:hover {
    opacity: 1;
  }

  .history-detail {
    padding: 0.4rem 0 0.5rem 3.75rem;
    display: grid;
    gap: 0.2rem;
  }

  /* ── Conflict view ── */

  .conflict-card {
    border-color: rgba(176, 117, 14, 0.32);
    background: linear-gradient(145deg, rgba(255, 252, 241, 0.96), rgba(255, 246, 225, 0.94));
  }

  .fence-list {
    display: grid;
    gap: 0.35rem;
  }

  .fence-row {
    display: grid;
    grid-template-columns: 4rem minmax(0, 1fr) auto;
    gap: 0.75rem;
    align-items: baseline;
    padding: 0.5rem 0.65rem;
    background: rgba(255, 255, 255, 0.7);
    border-radius: 8px;
    border: 1px solid rgba(176, 117, 14, 0.15);
  }

  .fence-date {
    color: var(--muted-foreground);
    font-size: 0.82rem;
    font-weight: 600;
  }

  .fence-payee {
    min-width: 0;
    overflow-wrap: anywhere;
    font-weight: 500;
    font-size: 0.9rem;
  }

  .fence-amount {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    font-size: 0.9rem;
  }

  /* ── Recovery card ── */

  .recovery-card {
    border: 1px solid rgba(176, 117, 14, 0.22);
    border-radius: 12px;
    background: linear-gradient(145deg, rgba(255, 252, 241, 0.96), rgba(255, 246, 225, 0.94));
    padding: 0.8rem 0.9rem;
  }

  .recovery-card .cause-detail {
    margin: 0.4rem 0 0;
    padding: 0.4rem 0.6rem;
    background: rgba(0, 0, 0, 0.04);
    border-radius: 6px;
    font-size: 0.75rem;
    line-height: 1.4;
    white-space: pre-wrap;
    word-break: break-word;
    color: rgba(0, 0, 0, 0.6);
  }

  /* ── Responsive ── */

  @media (max-width: 720px) {
    .fence-row {
      grid-template-columns: 1fr;
      gap: 0.2rem;
    }
  }
</style>
