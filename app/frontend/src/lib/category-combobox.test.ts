import { describe, expect, it } from 'vitest';
import { filterCategoryOptions } from './category-combobox';

describe('filterCategoryOptions', () => {
  const accounts = ['Expenses:Dining', 'Expenses:Groceries', 'Income:Salary'];

  it('matches category names without requiring the account prefix', () => {
    expect(filterCategoryOptions(accounts, 'gro')).toEqual(['Expenses:Groceries']);
  });

  it('returns the available choices when the query is blank', () => {
    expect(filterCategoryOptions(accounts, '')).toEqual(accounts);
  });
});
