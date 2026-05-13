import { writable, get } from 'svelte/store';

export type ToastStatus = 'idle' | 'undoing' | 'restored' | 'error';
export type ToastKind = 'undoable' | 'info';

export type ToastState = {
  kind: ToastKind;
  summary: string;
  status: ToastStatus;
  message?: string;
};

export const undoToast = writable<ToastState | null>(null);

let dismissTimer: ReturnType<typeof setTimeout> | null = null;
let refreshCallback: (() => Promise<void>) | null = null;
let undoFn: (() => Promise<UndoCallResult>) | null = null;

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
    undoFn = null;
  }, ms);
}

/** Default Gmail-style undoable toast for event-log-backed mutations
 *  (delete, recategorize, notes-update, etc.). Undo routes through
 *  /api/events/undo/{eventId}. */
export function showUndoToast(eventId: string, summary: string, refresh?: () => Promise<void>) {
  clearTimer();
  refreshCallback = refresh ?? null;
  undoFn = () => callUndoApi(eventId);
  undoToast.set({ kind: 'undoable', summary, status: 'idle' });
  autoDismiss(8000);
}

/** Import-specific undoable toast. Undo routes through /api/import/undo
 *  with the history entry id (matches the per-row Undo Import button in
 *  the import history). Per DECISIONS §21. */
export function showImportUndoToast(historyId: string, summary: string, refresh?: () => Promise<void>) {
  clearTimer();
  refreshCallback = refresh ?? null;
  undoFn = () => callImportUndoApi(historyId);
  undoToast.set({ kind: 'undoable', summary, status: 'idle' });
  autoDismiss(8000);
}

/** Info-only toast — no Undo button, shorter auto-dismiss. For cases
 *  where the user acted but no journal write happened (e.g. importing a
 *  statement that produces no new transactions). */
export function showInfoToast(summary: string) {
  clearTimer();
  refreshCallback = null;
  undoFn = null;
  undoToast.set({ kind: 'info', summary, status: 'idle' });
  autoDismiss(5000);
}

export function dismissUndoToast() {
  clearTimer();
  undoToast.set(null);
  refreshCallback = null;
  undoFn = null;
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

/** Invoke `POST /api/import/undo` for an applied import history entry.
 *  Same response shape contract as callUndoApi so triggerUndo can branch
 *  uniformly. */
async function callImportUndoApi(historyId: string): Promise<UndoCallResult> {
  let res: Response;
  try {
    res = await fetch('/api/import/undo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ historyId })
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

  if (res.ok) return { kind: 'success' };

  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return { kind: 'error', message: detail };
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const m = (detail as { message?: unknown }).message;
    if (typeof m === 'string') return { kind: 'error', message: m };
  }
  return { kind: 'error', message: 'Undo failed' };
}

export async function triggerUndo() {
  const current = get(undoToast);
  if (!current || current.status === 'undoing' || current.kind !== 'undoable' || !undoFn) return;

  clearTimer();
  undoToast.set({ ...current, status: 'undoing' });

  const result = await undoFn();
  if (result.kind === 'success' || result.kind === 'already_compensated') {
    undoToast.set({ ...current, status: 'restored', message: 'Restored' });
    autoDismiss(2000);
    if (refreshCallback) await refreshCallback();
  } else {
    undoToast.set({ ...current, status: 'error', message: result.message });
    // Error toasts do not auto-dismiss.
  }
}
