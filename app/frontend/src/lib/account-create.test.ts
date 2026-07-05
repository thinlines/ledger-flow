import { describe, expect, it } from 'vitest';

import { splitAccountSeed, validateNewAccount } from './account-create';

/**
 * Create-account flow (issue #18): the modal is a parent picker plus a leaf
 * name. A combobox "create …" seed may be a bare leaf ("Tea") or a fully
 * qualified name ("Expenses:Dining:Tea") — the latter pre-fills the parent.
 */

describe('splitAccountSeed', () => {
  it('treats a bare name as the leaf with no parent', () => {
    expect(splitAccountSeed('Tea')).toEqual({ parent: '', leaf: 'Tea' });
  });

  it('splits a fully qualified seed at the last colon', () => {
    expect(splitAccountSeed('Expenses:Dining:Tea')).toEqual({
      parent: 'Expenses:Dining',
      leaf: 'Tea'
    });
  });

  it('trims whitespace around seed and segments', () => {
    expect(splitAccountSeed('  Expenses:Dining : Tea ')).toEqual({
      parent: 'Expenses:Dining',
      leaf: 'Tea'
    });
    expect(splitAccountSeed('   ')).toEqual({ parent: '', leaf: '' });
  });

  it('keeps a trailing-colon seed as parent with empty leaf', () => {
    expect(splitAccountSeed('Expenses:Dining:')).toEqual({
      parent: 'Expenses:Dining',
      leaf: ''
    });
  });
});

describe('validateNewAccount', () => {
  it('requires a parent', () => {
    expect(validateNewAccount('', 'Tea')).toMatch(/parent/i);
  });

  it('requires a leaf name', () => {
    expect(validateNewAccount('Expenses', '  ')).toMatch(/name/i);
  });

  it('rejects a leaf containing a colon', () => {
    expect(validateNewAccount('Expenses', 'Dining:Tea')).toMatch(/:/);
  });

  it('accepts a valid parent + leaf', () => {
    expect(validateNewAccount('Expenses:Dining', 'Tea')).toBeNull();
  });
});
