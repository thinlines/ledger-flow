import { beforeEach, describe, expect, it, vi } from 'vitest';
import { toggleClearing } from './transactionActions';
import { apiPost } from '$lib/api';
import type { TransactionRow } from './types';

vi.mock('$lib/api', () => ({ apiPost: vi.fn() }));
vi.mock('$lib/undo-toast', () => ({ showUndoToast: vi.fn() }));

const apiPostMock = vi.mocked(apiPost);

function makeRow(): TransactionRow {
  return {
    status: 'unmarked',
    legs: [
      {
        journalPath: 'journals/2026.journal',
        headerLine: '2026-01-05 Grocery Store',
        lineNumber: 4,
        txnId: 'txn_grocery',
        blockHash: 'sha256:before'
      }
    ]
  } as unknown as TransactionRow;
}

describe('toggleClearing — stable identity contract', () => {
  beforeEach(() => {
    apiPostMock.mockReset();
  });

  it('posts txnId + blockHash, not positional fields', async () => {
    apiPostMock.mockResolvedValue({
      newStatus: 'pending',
      newHeaderLine: '2026-01-05 ! Grocery Store',
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
      newHeaderLine: '2026-01-05 ! Grocery Store',
      txnId: 'txn_grocery',
      blockHash: 'sha256:after'
    });
    const row = makeRow();

    await toggleClearing(row);

    expect(row.status).toBe('pending');
    expect(row.legs[0]).toEqual({
      journalPath: 'journals/2026.journal',
      headerLine: '2026-01-05 ! Grocery Store',
      lineNumber: 4,
      txnId: 'txn_grocery',
      blockHash: 'sha256:after'
    });
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
