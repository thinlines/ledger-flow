// Local recovery memory for the unknowns review: which stage the user was
// working on, per workspace, so a reload or navigation can resume it.
const UNKNOWN_STAGE_STORAGE_PREFIX = 'ledger-flow:unknown-review:';

export type RememberedUnknownStage = { stageId: string; journalPath: string };

function storageKey(workspacePath: string): string | null {
  return workspacePath ? `${UNKNOWN_STAGE_STORAGE_PREFIX}${workspacePath}` : null;
}

function resolveStorage(storage?: Storage): Storage | null {
  if (storage) return storage;
  return typeof window === 'undefined' ? null : window.localStorage;
}

export function rememberUnknownStage(
  workspacePath: string,
  stage: { stageId?: string | null; journalPath?: string | null } | null,
  storage?: Storage
): void {
  const key = storageKey(workspacePath);
  const store = resolveStorage(storage);
  if (!key || !store) return;
  if (!stage?.stageId) {
    store.removeItem(key);
    return;
  }
  store.setItem(key, JSON.stringify({ stageId: stage.stageId, journalPath: stage.journalPath }));
}

export function recallUnknownStage(workspacePath: string, storage?: Storage): RememberedUnknownStage | null {
  const key = storageKey(workspacePath);
  const store = resolveStorage(storage);
  if (!key || !store) return null;
  const raw = store.getItem(key);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { stageId?: string; journalPath?: string };
    const stageId = parsed.stageId?.trim() ?? '';
    const journalPath = parsed.journalPath?.trim() ?? '';
    if (!stageId) return null;
    return { stageId, journalPath };
  } catch {
    store.removeItem(key);
    return null;
  }
}

export function clearRememberedUnknownStage(workspacePath: string, storage?: Storage): void {
  const key = storageKey(workspacePath);
  const store = resolveStorage(storage);
  if (!key || !store) return;
  store.removeItem(key);
}
