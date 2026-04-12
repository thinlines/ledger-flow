import { apiPost } from '$lib/api';
import { showUndoToast } from '$lib/undo-toast';
import type { TransactionRow } from './types';

type ActionResult = { success: boolean; error?: string };

export async function deleteTransaction(
  row: TransactionRow,
  reload: () => Promise<void>
): Promise<ActionResult> {
  const leg = row.legs[0];
  if (!leg?.headerLine || !leg?.journalPath) return { success: false, error: 'Missing journal data' };
  try {
    const res = await apiPost<{ success: boolean; eventId: string | null }>('/api/transactions/delete', {
      journalPath: leg.journalPath,
      headerLine: leg.headerLine,
    });
    if (res.eventId) showUndoToast(res.eventId, `Removed ${row.payee} on ${row.date}`, reload);
    await reload();
    return { success: true };
  } catch (e) {
    return { success: false, error: String(e) };
  }
}

export async function resetCategory(
  row: TransactionRow,
  reload: () => Promise<void>
): Promise<ActionResult> {
  const leg = row.legs[0];
  if (!leg?.headerLine || !leg?.journalPath) return { success: false, error: 'Missing journal data' };
  try {
    const res = await apiPost<{ success: boolean; eventId: string | null }>('/api/transactions/recategorize', {
      journalPath: leg.journalPath,
      headerLine: leg.headerLine,
    });
    if (res.eventId) showUndoToast(res.eventId, `Reset category on ${row.payee}`, reload);
    await reload();
    return { success: true };
  } catch (e) {
    return { success: false, error: String(e) };
  }
}

export async function recategorize(
  row: TransactionRow,
  newCategory: string,
  reload: () => Promise<void>
): Promise<ActionResult> {
  const leg = row.legs[0];
  if (!leg?.headerLine || !leg?.journalPath) return { success: false, error: 'Missing journal data' };
  try {
    const res = await apiPost<{ success: boolean; eventId: string | null }>('/api/transactions/recategorize', {
      journalPath: leg.journalPath,
      headerLine: leg.headerLine,
      newCategory,
    });
    if (res.eventId) showUndoToast(res.eventId, `Recategorized ${row.payee}`, reload);
    await reload();
    return { success: true };
  } catch (e) {
    return { success: false, error: String(e) };
  }
}

export async function unmatchTransaction(
  row: TransactionRow,
  reload: () => Promise<void>
): Promise<ActionResult> {
  const leg = row.legs[0];
  if (!leg?.headerLine || !leg?.journalPath || !row.matchId) return { success: false, error: 'Missing journal data' };
  try {
    const res = await apiPost<{ success: boolean; eventId: string | null }>('/api/transactions/unmatch', {
      journalPath: leg.journalPath,
      headerLine: leg.headerLine,
      matchId: row.matchId,
    });
    if (res.eventId) showUndoToast(res.eventId, `Undid match for ${row.payee}`, reload);
    await reload();
    return { success: true };
  } catch (e) {
    return { success: false, error: String(e) };
  }
}

const CLEARING_CYCLE: Record<string, string> = {
  unmarked: 'pending',
  pending: 'cleared',
  cleared: 'unmarked'
};

export async function toggleClearing(row: TransactionRow): Promise<void> {
  const leg = row.legs[0];
  if (!leg?.headerLine || !leg?.journalPath) return;
  const previousStatus = row.status;
  const nextStatus = CLEARING_CYCLE[previousStatus] as 'unmarked' | 'pending' | 'cleared';
  row.status = nextStatus;
  try {
    const res = await apiPost<{ newStatus: string; newHeaderLine: string }>(
      '/api/transactions/toggle-status',
      { journalPath: leg.journalPath, headerLine: leg.headerLine }
    );
    row.status = res.newStatus as 'unmarked' | 'pending' | 'cleared';
    row.legs[0] = { ...leg, headerLine: res.newHeaderLine };
  } catch {
    row.status = previousStatus;
  }
}
