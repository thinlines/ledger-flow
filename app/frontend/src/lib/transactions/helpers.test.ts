import { describe, expect, it } from 'vitest';
import { groupByDate } from './helpers';
import type { TransactionRow } from './types';

function row(id: string, date: string, amount: number): TransactionRow {
  return {
    id,
    date,
    payee: `Payee ${id}`,
    amount,
    runningBalance: null,
    account: { id: 'acct', label: 'Checking' },
    categories: [],
    status: 'unmarked',
    isTransfer: false,
    isUnknown: false,
    isManual: false,
    isOpeningBalance: false,
    isAssertion: false,
    legs: []
  } as unknown as TransactionRow;
}

describe('groupByDate — characterization', () => {
  it('starts a new group on every date change, preserving row order', () => {
    const groups = groupByDate([
      row('1', '2026-08-10', -10),
      row('2', '2026-08-10', -20),
      row('3', '2026-08-09', 5)
    ]);
    expect(groups.map((g) => g.date)).toEqual(['2026-08-10', '2026-08-09']);
    expect(groups[0].rows.map((r) => r.id)).toEqual(['1', '2']);
    expect(groups[1].rows.map((r) => r.id)).toEqual(['3']);
  });

  it('sums amounts per day', () => {
    const groups = groupByDate([row('1', '2026-08-10', -10), row('2', '2026-08-10', -20)]);
    expect(groups[0].dailySum).toBe(-30);
  });

  it('does not merge non-adjacent repeats of a date (assumes date-sorted input)', () => {
    const groups = groupByDate([
      row('1', '2026-08-10', -1),
      row('2', '2026-08-09', -1),
      row('3', '2026-08-10', -1)
    ]);
    expect(groups).toHaveLength(3);
  });

  it('returns no groups for an empty register', () => {
    expect(groupByDate([])).toEqual([]);
  });
});
