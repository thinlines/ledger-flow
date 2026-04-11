<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { apiPost } from '$lib/api';
  import { formatCurrency, shortDate } from '$lib/format';
  import type {
    RegisterEntry,
    ManualResolutionPreview,
    ManualResolutionApplyResult
  } from '$lib/transactions/types';

  export let entry: RegisterEntry | null;
  export let baseCurrency: string;
  export let onResolved: (result: ManualResolutionApplyResult) => void | Promise<void> = () => {};

  let preview: ManualResolutionPreview | null = null;
  let error = '';
  let loading: 'preview' | 'apply' | null = null;
  let currentEntryId: string | null = null;

  $: open = entry !== null;
  $: if (entry && entry.id !== currentEntryId) {
    currentEntryId = entry.id;
    void loadPreview(entry);
  }

  async function loadPreview(e: RegisterEntry) {
    if (!e.manualResolutionToken) return;
    preview = null;
    error = '';
    loading = 'preview';
    try {
      preview = await apiPost<ManualResolutionPreview>(
        '/api/transactions/manual-transfer-resolution/preview',
        { resolutionToken: e.manualResolutionToken }
      );
      baseCurrency = preview.baseCurrency;
    } catch (err) {
      error = String(err);
    } finally {
      loading = null;
    }
  }

  function close() {
    entry = null;
    preview = null;
    error = '';
    loading = null;
    currentEntryId = null;
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) close();
  }

  async function confirm() {
    const resolutionToken = preview?.resolutionToken ?? entry?.manualResolutionToken ?? null;
    if (!resolutionToken) return;

    error = '';
    loading = 'apply';
    try {
      const result = await apiPost<ManualResolutionApplyResult>(
        '/api/transactions/manual-transfer-resolution/apply',
        { resolutionToken }
      );
      await onResolved(result);
      close();
    } catch (err) {
      error = String(err);
    } finally {
      loading = null;
    }
  }
</script>

<DialogPrimitive.Root {open} onOpenChange={handleOpenChange}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="manual-resolution-backdrop" />

    <DialogPrimitive.Content
      class="manual-resolution-modal"
      aria-labelledby="manual-resolution-title"
      aria-describedby="manual-resolution-description"
    >
      <h3 id="manual-resolution-title">Resolve manually</h3>
      <p id="manual-resolution-description" class="muted">
        Add the missing side of this transfer only when no imported counterpart is expected.
      </p>

      {#if loading === 'preview'}
        <div class="empty-panel">
          <h4>Loading preview</h4>
          <p>Validating the pending transfer and building the missing side.</p>
        </div>
      {:else if preview}
        <div class="manual-resolution-preview">
          <div class="manual-resolution-grid">
            <div>
              <p class="stat-label">From</p>
              <p>{preview.fromAccountName}</p>
            </div>
            <div>
              <p class="stat-label">To</p>
              <p>{preview.toAccountName}</p>
            </div>
            <div>
              <p class="stat-label">Date</p>
              <p>{shortDate(preview.date)}</p>
            </div>
            <div>
              <p class="stat-label">Amount</p>
              <p>{formatCurrency(preview.amount, baseCurrency)}</p>
            </div>
          </div>

          <div class="detail-line preview-payee">
            <p>{preview.payee}</p>
            <p class="muted small">The imported side stays in place. The missing destination-side transaction will be added and marked matched.</p>
          </div>

          <p class="details-note pending-details-note">{preview.warning}</p>
        </div>
      {/if}

      {#if error}
        <p class="error-text">{error}</p>
      {/if}

      <div class="modal-actions">
        <button class="btn" type="button" on:click={close}>Cancel</button>
        <button
          class="btn btn-primary"
          type="button"
          disabled={!preview || loading === 'apply'}
          on:click={() => void confirm()}
        >
          {loading === 'apply' ? 'Applying...' : 'Confirm resolution'}
        </button>
      </div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>

<style>
  /* CSS lifted verbatim from transactions/+page.svelte. Rules like
     .stat-label, .empty-panel, .detail-line, .details-note,
     .pending-details-note, .modal-actions, and .small are also defined
     in the page — Svelte's per-component scoping means the page's copies
     don't reach this component, so we duplicate them here. Phase 2 or the
     parallel Tailwind migration will consolidate. */

  .stat-label {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .empty-panel {
    border: 1px dashed rgba(10, 61, 89, 0.18);
    border-radius: 1rem;
    padding: 1rem;
    background: rgba(255, 255, 255, 0.52);
  }

  .detail-line {
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 0.9rem;
    padding: 0.7rem 0.8rem;
    background: rgba(255, 255, 255, 0.62);
  }

  .details-note {
    color: var(--muted-foreground);
    font-size: 0.92rem;
  }

  .pending-details-note {
    color: #7d5200;
  }

  .modal-actions {
    display: flex;
    gap: 0.7rem;
    flex-wrap: wrap;
  }

  .small {
    font-size: 0.84rem;
  }

  .manual-resolution-preview {
    display: grid;
    gap: 0.9rem;
  }

  .manual-resolution-grid {
    display: grid;
    gap: 0.8rem;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  }

  .preview-payee {
    background: rgba(255, 255, 255, 0.72);
  }

  :global(.manual-resolution-backdrop) {
    position: fixed;
    inset: 0;
    background: rgba(10, 20, 30, 0.35);
    z-index: 30;
  }

  :global(.manual-resolution-modal) {
    width: min(640px, calc(100vw - 2rem));
    max-height: calc(100vh - 2rem);
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 1rem;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    overflow: auto;
    z-index: 31;
    display: grid;
    gap: 1rem;
  }
</style>
