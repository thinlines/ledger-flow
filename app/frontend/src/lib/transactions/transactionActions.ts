import { apiPost } from '$lib/api';
import { showUndoToast } from '$lib/undo-toast';
import type { TransactionRow } from './types';

type ActionResult = { success: boolean; error?: string };

type MutationResponse = {
  success: boolean;
  eventId: string | null;
  txnId?: string;
  blockHash?: string | null;
};

/** Re-spread the acting leg with the post-edit projected identity so
 * follow-up actions keep working before the row list reloads. */
function respreadIdentity(row: TransactionRow, res: { txnId?: string; blockHash?: string | null }) {
  const leg = row.legs[0];
  if (!leg || !res.txnId) return;
  row.legs[0] = { ...leg, txnId: res.txnId, blockHash: res.blockHash ?? null };
}

export async function deleteTransaction(
  row: TransactionRow,
  reload: () => Promise<void>
): Promise<ActionResult> {
  const leg = row.legs[0];
  if (!leg?.txnId || !leg?.blockHash) return { success: false, error: 'Missing transaction identity' };
  try {
    const res = await apiPost<MutationResponse>('/api/transactions/delete', {
      txnId: leg.txnId,
      blockHash: leg.blockHash
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
  if (!leg?.txnId || !leg?.blockHash) return { success: false, error: 'Missing transaction identity' };
  try {
    const res = await apiPost<MutationResponse>('/api/transactions/recategorize', {
      txnId: leg.txnId,
      blockHash: leg.blockHash
    });
    respreadIdentity(row, res);
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
  if (!leg?.txnId || !leg?.blockHash) return { success: false, error: 'Missing transaction identity' };
  try {
    const res = await apiPost<MutationResponse>('/api/transactions/recategorize', {
      txnId: leg.txnId,
      blockHash: leg.blockHash,
      newCategory
    });
    respreadIdentity(row, res);
    if (res.eventId) showUndoToast(res.eventId, `Recategorized ${row.payee}`, reload);
    await reload();
    return { success: true };
  } catch (e) {
    return { success: false, error: String(e) };
  }
}

export async function reassignAccount(
  row: TransactionRow,
  newAccountLedgerName: string,
  reload: () => Promise<void>
): Promise<ActionResult> {
  const leg = row.legs[0];
  if (!leg?.txnId || !leg?.blockHash) return { success: false, error: 'Missing transaction identity' };
  try {
    const res = await apiPost<MutationResponse>('/api/transactions/reassign-account', {
      txnId: leg.txnId,
      blockHash: leg.blockHash,
      newAccountLedgerName
    });
    respreadIdentity(row, res);
    if (res.eventId) showUndoToast(res.eventId, `Reassigned account on ${row.payee}`, reload);
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
  if (!leg?.txnId || !leg?.blockHash || !row.matchId) return { success: false, error: 'Missing transaction identity' };
  try {
    const res = await apiPost<MutationResponse>('/api/transactions/unmatch', {
      txnId: leg.txnId,
      blockHash: leg.blockHash,
      matchId: row.matchId
    });
    respreadIdentity(row, res);
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
  if (!leg?.txnId || !leg?.blockHash) return;
  const previousStatus = row.status;
  const nextStatus = CLEARING_CYCLE[previousStatus] as 'unmarked' | 'pending' | 'cleared';
  row.status = nextStatus;
  try {
    const res = await apiPost<{
      newStatus: string;
      txnId: string;
      blockHash: string;
    }>('/api/transactions/toggle-status', { txnId: leg.txnId, blockHash: leg.blockHash });
    row.status = res.newStatus as 'unmarked' | 'pending' | 'cleared';
    respreadIdentity(row, res);
  } catch {
    row.status = previousStatus;
  }
}
