<script lang="ts">
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import XIcon from '@lucide/svelte/icons/x';
  import { apiGet } from '$lib/api';
  import { callUndoApi } from '$lib/undo-toast';
  import { relativeTime } from '$lib/format';

  type EventRow = {
    id: string;
    type: string;
    summary: string;
    timestamp: string;
    undoable: boolean;
    compensated: boolean;
    compensatedBy: string | null;
  };

  export let open = false;
  export let onOpenChange: (next: boolean) => void = () => {};

  type LoadState = 'idle' | 'loading' | 'loaded' | 'error';
  let loadState: LoadState = 'idle';
  let loadError = '';
  let events: EventRow[] = [];
  let inFlight: Record<string, 'undoing'> = {};
  let rowErrors: Record<string, string> = {};

  async function load() {
    loadState = 'loading';
    loadError = '';
    try {
      const res = await apiGet<{ events: EventRow[] }>('/api/events');
      events = res.events ?? [];
      loadState = 'loaded';
    } catch (e) {
      loadError = e instanceof Error ? e.message : "Couldn't load activity. Try again.";
      loadState = 'error';
    }
  }

  $: if (open && loadState === 'idle') void load();

  function handleOpenChange(next: boolean) {
    if (next && loadState !== 'loading') void load();
    if (!next) {
      // Reset transient row state on close so a re-open starts clean.
      inFlight = {};
      rowErrors = {};
    }
    onOpenChange(next);
  }

  async function undoRow(row: EventRow) {
    if (inFlight[row.id]) return;
    inFlight = { ...inFlight, [row.id]: 'undoing' };
    rowErrors = { ...rowErrors, [row.id]: '' };

    const result = await callUndoApi(row.id);
    const next = { ...inFlight };
    delete next[row.id];
    inFlight = next;

    if (result.kind === 'success' || result.kind === 'already_compensated') {
      await load();
    } else {
      rowErrors = { ...rowErrors, [row.id]: result.message };
    }
  }
</script>

<DialogPrimitive.Root {open} onOpenChange={handleOpenChange}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="fixed inset-0 z-30 bg-black/25 max-desktop:bg-black/35" />

    <DialogPrimitive.Content
      class="fixed top-0 right-0 z-40 flex h-full w-[min(26rem,100vw)] flex-col border-l border-line bg-white shadow-card animate-[sheet-slide-in_0.2s_ease-out]"
      aria-labelledby="recent-activity-title"
    >
      <div class="flex items-center justify-between gap-3 border-b border-line/60 px-5 pt-5 pb-4">
        <h3 id="recent-activity-title" class="m-0 font-display text-lg">Recent activity</h3>

        <DialogPrimitive.Close
          class="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="Close"
        >
          <XIcon class="size-4" />
        </DialogPrimitive.Close>
      </div>

      <div class="grow overflow-y-auto px-1 py-2">
        {#if loadState === 'loading'}
          <p class="px-4 py-3 text-sm text-muted-foreground">Loading…</p>
        {:else if loadState === 'error'}
          <div class="grid gap-2 px-4 py-3">
            <p class="m-0 text-sm text-destructive">Couldn't load activity. {loadError}</p>
            <button class="btn w-fit" type="button" on:click={() => void load()}>Try again</button>
          </div>
        {:else if events.length === 0}
          <p class="px-4 py-6 text-center text-sm text-muted-foreground">No recent activity yet.</p>
        {:else}
          <ul class="m-0 grid list-none gap-0 p-0">
            {#each events as row (row.id)}
              <li class="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 border-b border-line/40 px-4 py-3 last:border-b-0">
                <div class="min-w-0">
                  <p class="m-0 truncate text-sm font-semibold text-foreground" title={row.summary}>
                    {row.summary || row.type}
                  </p>
                  <p class="m-0 mt-0.5 text-xs text-muted-foreground">
                    {relativeTime(row.timestamp)}
                  </p>
                  {#if rowErrors[row.id]}
                    <p class="m-0 mt-1 text-xs text-destructive">
                      Undo failed: {rowErrors[row.id]}
                    </p>
                  {/if}
                </div>

                <div class="shrink-0 self-center">
                  {#if row.compensated}
                    <span class="text-xs font-semibold text-muted-foreground">Undone</span>
                  {:else if row.undoable}
                    <button
                      type="button"
                      class="cursor-pointer rounded-lg border border-card-edge bg-white px-3 py-1 text-xs font-bold text-brand-strong hover:bg-white/95 disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={!!inFlight[row.id]}
                      on:click={() => void undoRow(row)}
                    >
                      {inFlight[row.id] ? 'Undoing…' : 'Undo'}
                    </button>
                  {/if}
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>
