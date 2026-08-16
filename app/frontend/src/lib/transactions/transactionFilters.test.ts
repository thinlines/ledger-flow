import { describe, expect, it } from 'vitest';
import {
  EMPTY_FILTERS,
  filtersFromUrl,
  filtersToApiParams,
  filtersToUrl
} from './transactionFilters';

describe('transaction filters — URL round-trip (characterization)', () => {
  it('empty filters serialize to an empty string', () => {
    expect(filtersToUrl(EMPTY_FILTERS)).toBe('');
    expect(filtersToApiParams(EMPTY_FILTERS)).toBe('');
  });

  it('round-trips a full filter set through the page URL', () => {
    const filters = {
      accounts: ['chase', 'amex'],
      period: null,
      month: '2026-07',
      category: 'Expenses:Groceries',
      search: 'coffee',
      status: 'cleared'
    };
    const url = new URL(`https://x/transactions${filtersToUrl(filters)}`);
    expect(filtersFromUrl(url)).toEqual({ filters, migrated: false });
  });

  it('month wins over period in both serializers', () => {
    const filters = { ...EMPTY_FILTERS, month: '2026-07', period: 'this-month' };
    expect(filtersToUrl(filters)).toBe('?month=2026-07');
    expect(filtersToApiParams(filters)).toBe('month=2026-07');
  });

  it('page URLs say q/category; API params say search/categories', () => {
    const filters = { ...EMPTY_FILTERS, search: 'rent', category: 'Expenses:Housing' };
    expect(filtersToUrl(filters)).toContain('q=rent');
    expect(filtersToUrl(filters)).toContain('category=Expenses%3AHousing');
    expect(filtersToApiParams(filters)).toContain('search=rent');
    expect(filtersToApiParams(filters)).toContain('categories=Expenses%3AHousing');
  });

  it('migrates the legacy ?accountId= deep link', () => {
    const { filters, migrated } = filtersFromUrl(new URL('https://x/transactions?accountId=chase'));
    expect(migrated).toBe(true);
    expect(filters.accounts).toEqual(['chase']);
  });

  it('migrates the legacy ?view=activity format', () => {
    const { migrated } = filtersFromUrl(new URL('https://x/transactions?view=activity&period=90d'));
    expect(migrated).toBe(true);
  });
});
