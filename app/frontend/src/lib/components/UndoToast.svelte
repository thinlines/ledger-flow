<script lang="ts">
  import { undoToast, triggerUndo, dismissUndoToast } from '$lib/undo-toast';

  $: toast = $undoToast;

  const btnClass =
    'cursor-pointer rounded-lg border border-card-edge bg-white/90 px-3.5 py-1.5 text-sm font-bold text-brand-strong transition-colors hover:bg-white/95 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-strong';
</script>

{#if toast}
  <div
    class="undo-toast fixed bottom-6 right-6 z-50 flex w-90 max-w-[calc(100vw-2rem)] items-center justify-between gap-3 rounded-xl border border-card-edge bg-white px-4 py-3.5"
    class:undo-toast-error={toast.status === 'error'}
    class:undo-toast-restored={toast.status === 'restored'}
    role="status"
    aria-live="polite"
  >
    <p class="undo-toast-message m-0 min-w-0 truncate text-sm font-semibold text-foreground">
      {#if toast.status === 'restored'}
        Restored
      {:else if toast.status === 'error'}
        {toast.message || 'Undo failed'}
      {:else}
        {toast.summary}
      {/if}
    </p>

    <div class="shrink-0">
      {#if toast.kind === 'undoable'}
        {#if toast.status === 'idle'}
          <button class={btnClass} type="button" on:click={() => void triggerUndo()}>
            Undo
          </button>
        {:else if toast.status === 'undoing'}
          <button class={btnClass} type="button" disabled>
            Undoing…
          </button>
        {:else if toast.status === 'error'}
          <button class={btnClass} type="button" on:click={dismissUndoToast}>
            Dismiss
          </button>
        {/if}
      {/if}
    </div>
  </div>
{/if}

<style>
  .undo-toast {
    box-shadow: 0 8px 24px rgba(10, 20, 30, 0.14);
    animation: toast-slide-in 0.2s ease-out;
  }

  .undo-toast-error {
    border-color: rgba(197, 48, 48, 0.25);
    background: #fef5f5;
  }

  .undo-toast-error .undo-toast-message {
    color: #c53030;
    white-space: normal;
  }

  .undo-toast-restored {
    border-color: rgba(13, 127, 88, 0.25);
    background: #f0faf5;
  }

  .undo-toast-restored .undo-toast-message {
    color: #0d7f58;
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
