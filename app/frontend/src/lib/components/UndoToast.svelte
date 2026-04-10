<script lang="ts">
  import { undoToast, triggerUndo, dismissUndoToast } from '$lib/undo-toast';

  $: toast = $undoToast;
</script>

{#if toast}
  <div
    class="undo-toast"
    class:undo-toast-error={toast.status === 'error'}
    class:undo-toast-restored={toast.status === 'restored'}
    role="status"
    aria-live="polite"
  >
    <p class="undo-toast-message">
      {#if toast.status === 'restored'}
        Restored
      {:else if toast.status === 'error'}
        {toast.message || 'Undo failed'}
      {:else}
        {toast.summary}
      {/if}
    </p>

    <div class="undo-toast-actions">
      {#if toast.status === 'idle'}
        <button class="undo-toast-btn" type="button" on:click={() => void triggerUndo()}>
          Undo
        </button>
      {:else if toast.status === 'undoing'}
        <button class="undo-toast-btn" type="button" disabled>
          Undoing…
        </button>
      {:else if toast.status === 'error'}
        <button class="undo-toast-btn" type="button" on:click={dismissUndoToast}>
          Dismiss
        </button>
      {/if}
    </div>
  </div>
{/if}

<style>
  .undo-toast {
    position: fixed;
    bottom: 1.5rem;
    right: 1.5rem;
    z-index: 50;
    width: min(360px, calc(100vw - 2rem));
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.85rem 1rem;
    background: #fff;
    border: 1px solid rgba(10, 61, 89, 0.12);
    border-radius: 0.85rem;
    box-shadow: 0 8px 24px rgba(10, 20, 30, 0.14);
    animation: toast-slide-in 0.2s ease-out;
  }

  .undo-toast-error {
    border-color: rgba(197, 48, 48, 0.25);
    background: #fef5f5;
  }

  .undo-toast-restored {
    border-color: rgba(13, 127, 88, 0.25);
    background: #f0faf5;
  }

  .undo-toast-message {
    margin: 0;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--foreground, #1a2b3c);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .undo-toast-error .undo-toast-message {
    color: var(--error, #c53030);
    white-space: normal;
  }

  .undo-toast-restored .undo-toast-message {
    color: var(--ok, #0d7f58);
  }

  .undo-toast-actions {
    flex-shrink: 0;
  }

  .undo-toast-btn {
    padding: 0.4rem 0.85rem;
    border: 1px solid rgba(10, 61, 89, 0.15);
    border-radius: 0.55rem;
    background: rgba(255, 255, 255, 0.9);
    font-size: 0.84rem;
    font-weight: 700;
    color: var(--brand-strong, #0f5f88);
    cursor: pointer;
    transition: background 0.12s;
  }

  .undo-toast-btn:hover:not(:disabled) {
    background: rgba(244, 249, 255, 0.95);
  }

  .undo-toast-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .undo-toast-btn:focus-visible {
    outline: 2px solid var(--brand-strong, #0f5f88);
    outline-offset: 2px;
  }

  @keyframes toast-slide-in {
    from {
      opacity: 0;
      transform: translateY(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
</style>
