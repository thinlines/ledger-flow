/**
 * Roving-focus math for the transactions register (ADR-0003).
 *
 * Pure functions over the flattened, display-ordered list of row ids. The
 * page owns the focused id; these helpers answer "where does j/k go" and
 * "where does focus land after the list changes under it".
 */

export function nextId(ids: string[], focusedId: string | null): string | null {
  if (ids.length === 0) return null;
  const i = focusedId === null ? -1 : ids.indexOf(focusedId);
  if (i === -1) return ids[0];
  return ids[Math.min(i + 1, ids.length - 1)];
}

export function prevId(ids: string[], focusedId: string | null): string | null {
  if (ids.length === 0) return null;
  const i = focusedId === null ? -1 : ids.indexOf(focusedId);
  if (i === -1) return ids[0];
  return ids[Math.max(i - 1, 0)];
}

/**
 * After a reload or filter change, keep focus on the same row when it
 * survived; otherwise land on the row now occupying its old position
 * (clamped to the new tail), so a delete reads as "focus stayed put".
 */
export function reconcileFocus(
  oldIds: string[],
  newIds: string[],
  focusedId: string | null
): string | null {
  if (focusedId === null) return null;
  if (newIds.length === 0) return null;
  if (newIds.includes(focusedId)) return focusedId;
  const oldIndex = oldIds.indexOf(focusedId);
  if (oldIndex === -1) return null;
  return newIds[Math.min(oldIndex, newIds.length - 1)];
}
