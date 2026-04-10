import { writable, get } from 'svelte/store';
import { apiPost } from '$lib/api';

export type ToastStatus = 'idle' | 'undoing' | 'restored' | 'error';

export type ToastState = {
  eventId: string;
  summary: string;
  status: ToastStatus;
  message?: string;
};

export const undoToast = writable<ToastState | null>(null);

let dismissTimer: ReturnType<typeof setTimeout> | null = null;
let refreshCallback: (() => Promise<void>) | null = null;

function clearTimer() {
  if (dismissTimer !== null) {
    clearTimeout(dismissTimer);
    dismissTimer = null;
  }
}

function autoDismiss(ms: number) {
  clearTimer();
  dismissTimer = setTimeout(() => {
    undoToast.set(null);
    refreshCallback = null;
  }, ms);
}

export function showUndoToast(eventId: string, summary: string, refresh?: () => Promise<void>) {
  clearTimer();
  refreshCallback = refresh ?? null;
  undoToast.set({ eventId, summary, status: 'idle' });
  autoDismiss(8000);
}

export function dismissUndoToast() {
  clearTimer();
  undoToast.set(null);
  refreshCallback = null;
}

export async function triggerUndo() {
  const current = get(undoToast);
  if (!current || current.status === 'undoing') return;

  clearTimer();
  undoToast.set({ ...current, status: 'undoing' });

  try {
    await apiPost<{ outcome: string; message: string }>(
      `/api/events/undo/${current.eventId}`,
      {}
    );
    undoToast.set({ ...current, status: 'restored', message: 'Restored' });
    autoDismiss(2000);
    if (refreshCallback) await refreshCallback();
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Undo failed';
    undoToast.set({ ...current, status: 'error', message: msg });
    // Error toasts do not auto-dismiss.
  }
}
