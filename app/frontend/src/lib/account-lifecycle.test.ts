import { describe, expect, it } from 'vitest';

import {
  canClose,
  canReopen,
  deleteDisabledCopy,
  leafName,
  lifecycleBadges,
  type ManagedAccount
} from './account-lifecycle';

function row(overrides: Partial<ManagedAccount> = {}): ManagedAccount {
  return {
    name: 'Assets:Checking',
    accountType: 'assets',
    depth: 1,
    subtype: null,
    note: null,
    closedOn: null,
    declared: true,
    used: true,
    postingCount: 3,
    deletable: false,
    deleteBlockedReason: '3 posting(s) reference Assets:Checking or its sub-accounts.',
    ...overrides
  };
}

describe('leafName', () => {
  it('returns the last segment', () => {
    expect(leafName('Assets:Bank:Checking')).toBe('Checking');
    expect(leafName('Assets')).toBe('Assets');
  });
});

describe('lifecycleBadges', () => {
  it('shows a closed badge with the date', () => {
    const badges = lifecycleBadges(row({ closedOn: '2026-06-30' }));
    expect(badges.some((badge) => badge.label === 'Closed 2026-06-30')).toBe(true);
  });

  it('marks used-only rows as auto-tracked instead of declared', () => {
    const badges = lifecycleBadges(row({ declared: false }));
    expect(badges.some((badge) => badge.label === 'Auto')).toBe(true);
    expect(badges.some((badge) => badge.label === 'Declared')).toBe(false);
  });

  it('includes the subtype when present', () => {
    const badges = lifecycleBadges(row({ subtype: 'credit_card' }));
    expect(badges.some((badge) => badge.label === 'Credit card')).toBe(true);
  });
});

describe('close/reopen eligibility', () => {
  it('open accounts can close, closed accounts can reopen', () => {
    expect(canClose(row())).toBe(true);
    expect(canReopen(row())).toBe(false);

    const closed = row({ closedOn: '2026-06-30' });
    expect(canClose(closed)).toBe(false);
    expect(canReopen(closed)).toBe(true);
  });

  it('closed reopen requires a declaration', () => {
    // A closed flag can only come from a declaration, but guard anyway.
    expect(canReopen(row({ closedOn: '2026-06-30', declared: false }))).toBe(false);
  });
});

describe('deleteDisabledCopy', () => {
  it('is null when deletable', () => {
    expect(deleteDisabledCopy(row({ deletable: true, deleteBlockedReason: null }))).toBeNull();
  });

  it('passes through the backend reason', () => {
    expect(deleteDisabledCopy(row())).toContain('3 posting(s)');
  });

  it('explains undeclared rows', () => {
    const copy = deleteDisabledCopy(
      row({ declared: false, deletable: false, deleteBlockedReason: null })
    );
    expect(copy).toContain('postings');
  });
});
