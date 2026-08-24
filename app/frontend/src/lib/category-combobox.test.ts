import { describe, expect, it } from 'vitest';
import { filterCategoryOptions, transferTargetOptions } from './category-combobox';

describe('filterCategoryOptions', () => {
  const accounts = ['Expenses:Dining', 'Expenses:Groceries', 'Income:Salary'];

  it('matches category names without requiring the account prefix', () => {
    expect(filterCategoryOptions(accounts, 'gro')).toEqual(['Expenses:Groceries']);
  });

  it('returns the available choices when the query is blank', () => {
    expect(filterCategoryOptions(accounts, '')).toEqual(accounts);
  });
});

describe('transferTargetOptions', () => {
  const accounts = [
    { id: 'checking', displayName: 'Checking', ledgerAccount: 'Assets:Bank:Checking' },
    { id: 'vehicle', displayName: 'Subaru', ledgerAccount: 'Assets:Vehicle:Subaru' },
    { id: 'visa', displayName: 'Visa', ledgerAccount: 'Liabilities:Card:Visa' }
  ];

  it('offers manual-only accounts while excluding the imported transaction source', () => {
    expect(transferTargetOptions(accounts, 'checking', 'sub')).toEqual([accounts[1]]);
  });
});
