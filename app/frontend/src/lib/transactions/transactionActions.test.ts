import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  deleteTransaction,
  recategorize,
  reassignAccount,
  resetCategory,
  toggleClearing,
  unmatchTransaction
} from './transactionActions';
import { apiPost } from '$lib/api';
import type { TransactionRow } from './types';

vi.mock('$lib/api', () => ({ apiPost: vi.fn() }));
vi.mock('$lib/undo-toast', () => ({ showUndoToast: vi.fn() }));

const apiPostMock = vi.mocked(apiPost);
const reload = vi.fn(async () => {});

function makeRow(extra: Partial<TransactionRow> = {}): TransactionRow {
  return {
    status: 'unmarked',
    payee: 'Grocery Store',
    date: '2026-01-05',
    legs: [
      {
        journalPath: 'journals/2026.journal',
        txnId: 'txn_grocery',
        blockHash: 'sha256:before'
      }
    ],
    ...extra
  } as unknown as TransactionRow;
}

beforeEach(() => {
  apiPostMock.mockReset();
  reload.mockClear();
});

describe('toggleClearing — stable identity contract', () => {
  it('posts txnId + blockHash, not positional fields', async () => {
    apiPostMock.mockResolvedValue({
      newStatus: 'pending',
      txnId: 'txn_grocery',
      blockHash: 'sha256:after'
    });

    await toggleClearing(makeRow());

    expect(apiPostMock).toHaveBeenCalledWith('/api/transactions/toggle-status', {
      txnId: 'txn_grocery',
      blockHash: 'sha256:before'
    });
  });

  it('applies the returned status and re-spreads leg identity from the response', async () => {
    apiPostMock.mockResolvedValue({
      newStatus: 'pending',
      txnId: 'txn_grocery',
      blockHash: 'sha256:after'
    });
    const row = makeRow();

    await toggleClearing(row);

    expect(row.status).toBe('pending');
    expect(row.legs[0].txnId).toBe('txn_grocery');
    expect(row.legs[0].blockHash).toBe('sha256:after');
  });

  it('reverts the optimistic status on error', async () => {
    apiPostMock.mockRejectedValue(new Error('409'));
    const row = makeRow();

    await toggleClearing(row);

    expect(row.status).toBe('unmarked');
    expect(row.legs[0].blockHash).toBe('sha256:before');
  });

  it('does nothing when the leg has no projected identity', async () => {
    const row = makeRow();
    delete (row.legs[0] as Record<string, unknown>).txnId;
    delete (row.legs[0] as Record<string, unknown>).blockHash;

    await toggleClearing(row);

    expect(apiPostMock).not.toHaveBeenCalled();
    expect(row.status).toBe('unmarked');
  });
});

describe('row actions — stable identity contract (#17)', () => {
  it('deleteTransaction posts txnId + blockHash only', async () => {
    apiPostMock.mockResolvedValue({ success: true, eventId: 'evt-1' });

    const result = await deleteTransaction(makeRow(), reload);

    expect(result.success).toBe(true);
    expect(apiPostMock).toHaveBeenCalledWith('/api/transactions/delete', {
      txnId: 'txn_grocery',
      blockHash: 'sha256:before'
    });
  });

  it('recategorize posts identity + newCategory and re-spreads returned identity', async () => {
    apiPostMock.mockResolvedValue({
      success: true,
      eventId: 'evt-2',
      txnId: 'txn_grocery',
      blockHash: 'sha256:after'
    });
    const row = makeRow();

    const result = await recategorize(row, 'Expenses:Coffee', reload);

    expect(result.success).toBe(true);
    expect(apiPostMock).toHaveBeenCalledWith('/api/transactions/recategorize', {
      txnId: 'txn_grocery',
      blockHash: 'sha256:before',
      newCategory: 'Expenses:Coffee'
    });
    expect(row.legs[0].blockHash).toBe('sha256:after');
  });

  it('resetCategory posts identity without newCategory', async () => {
    apiPostMock.mockResolvedValue({ success: true, eventId: 'evt-3' });

    await resetCategory(makeRow(), reload);

    expect(apiPostMock).toHaveBeenCalledWith('/api/transactions/recategorize', {
      txnId: 'txn_grocery',
      blockHash: 'sha256:before'
    });
  });

  it('reassignAccount posts identity + newAccountLedgerName', async () => {
    apiPostMock.mockResolvedValue({ success: true, eventId: 'evt-4' });

    await reassignAccount(makeRow(), 'Assets:Bank:Savings', reload);

    expect(apiPostMock).toHaveBeenCalledWith('/api/transactions/reassign-account', {
      txnId: 'txn_grocery',
      blockHash: 'sha256:before',
      newAccountLedgerName: 'Assets:Bank:Savings'
    });
  });

  it('unmatchTransaction posts identity + matchId', async () => {
    apiPostMock.mockResolvedValue({ success: true, eventId: 'evt-5' });

    await unmatchTransaction(makeRow({ matchId: 'match-1' } as Partial<TransactionRow>), reload);

    expect(apiPostMock).toHaveBeenCalledWith('/api/transactions/unmatch', {
      txnId: 'txn_grocery',
      blockHash: 'sha256:before',
      matchId: 'match-1'
    });
  });

  it('every action refuses rows without projected identity', async () => {
    const row = makeRow();
    delete (row.legs[0] as Record<string, unknown>).txnId;
    delete (row.legs[0] as Record<string, unknown>).blockHash;

    for (const call of [
      () => deleteTransaction(row, reload),
      () => resetCategory(row, reload),
      () => recategorize(row, 'Expenses:Coffee', reload),
      () => reassignAccount(row, 'Assets:Bank:Savings', reload)
    ]) {
      const result = await call();
      expect(result.success).toBe(false);
      expect(result.error).toMatch(/identity/i);
    }
    expect(apiPostMock).not.toHaveBeenCalled();
  });
});
