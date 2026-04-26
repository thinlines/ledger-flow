import { writable, get } from 'svelte/store';

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

export type UndoCallResult =
  | { kind: 'success' }
  | { kind: 'already_compensated' }
  | { kind: 'error'; message: string };

/** Invoke `POST /api/events/undo/{id}` and translate the response into a
 *  small, UI-friendly union. Shared between the toast and the history sheet
 *  so neither has to know the wire format. */
export async function callUndoApi(eventId: string): Promise<UndoCallResult> {
  let res: Response;
  try {
    res = await fetch(`/api/events/undo/${eventId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    });
  } catch (e) {
    return { kind: 'error', message: e instanceof Error ? e.message : 'Network error' };
  }

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* leave body null */
  }

  if (res.ok) {
    const outcome = (body as { outcome?: string } | null)?.outcome;
    if (outcome === 'already_compensated') return { kind: 'already_compensated' };
    return { kind: 'success' };
  }

  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const m = (detail as { message?: unknown }).message;
    if (typeof m === 'string') return { kind: 'error', message: m };
  }
  return { kind: 'error', message: 'Undo failed' };
}

export async function triggerUndo() {
  const current = get(undoToast);
  if (!current || current.status === 'undoing') return;

  clearTimer();
  undoToast.set({ ...current, status: 'undoing' });

  const result = await callUndoApi(current.eventId);
  if (result.kind === 'success' || result.kind === 'already_compensated') {
    undoToast.set({ ...current, status: 'restored', message: 'Restored' });
    autoDismiss(2000);
    if (refreshCallback) await refreshCallback();
  } else {
    undoToast.set({ ...current, status: 'error', message: result.message });
    // Error toasts do not auto-dismiss.
  }
}
