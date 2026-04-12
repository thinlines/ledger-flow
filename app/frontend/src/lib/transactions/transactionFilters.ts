import type { TransactionFilters } from './types';

export const EMPTY_FILTERS: TransactionFilters = {
  accounts: [],
  period: null,
  month: null,
  category: null,
  search: '',
  status: null
};

/**
 * Parse filters from a URL, including migration from old param formats.
 * Old formats:
 *   ?view=activity&period=X&category=C&month=M
 *   ?accountId=X
 * New format:
 *   ?accounts=X,Y&period=X&category=C&month=M&q=text&status=cleared
 */
export function filtersFromUrl(url: URL): { filters: TransactionFilters; migrated: boolean } {
  const params = url.searchParams;
  let migrated = false;

  // Detect old URL formats
  const viewParam = params.get('view');
  const accountIdParam = params.get('accountId');

  if (viewParam === 'activity' || accountIdParam) {
    migrated = true;
  }

  // Build filters from either old or new param names
  let accounts: string[] = [];
  if (accountIdParam) {
    accounts = [accountIdParam];
  } else {
    const accountsParam = params.get('accounts');
    if (accountsParam) {
      accounts = accountsParam.split(',').filter(Boolean);
    }
  }

  const period = params.get('period') ?? null;
  const month = params.get('month') ?? null;
  const category = params.get('category') ?? null;
  const search = params.get('q') ?? '';
  const status = params.get('status') ?? null;

  return {
    filters: { accounts, period, month, category, search, status },
    migrated
  };
}

/**
 * Serialize filters to URL search params string.
 * Omits default/empty values for clean URLs.
 */
export function filtersToUrl(filters: TransactionFilters): string {
  const params = new URLSearchParams();

  if (filters.accounts.length > 0) {
    params.set('accounts', filters.accounts.join(','));
  }
  if (filters.month) {
    params.set('month', filters.month);
  } else if (filters.period) {
    params.set('period', filters.period);
  }
  if (filters.category) {
    params.set('category', filters.category);
  }
  if (filters.search) {
    params.set('q', filters.search);
  }
  if (filters.status) {
    params.set('status', filters.status);
  }

  const str = params.toString();
  return str ? `?${str}` : '';
}

/**
 * Convert filters to API query params for GET /api/transactions.
 */
export function filtersToApiParams(filters: TransactionFilters): string {
  const params = new URLSearchParams();

  if (filters.accounts.length > 0) {
    params.set('accounts', filters.accounts.join(','));
  }
  if (filters.month) {
    params.set('month', filters.month);
  } else if (filters.period) {
    params.set('period', filters.period);
  }
  if (filters.category) {
    params.set('categories', filters.category);
  }
  if (filters.search) {
    params.set('search', filters.search);
  }
  if (filters.status) {
    params.set('status', filters.status);
  }

  return params.toString();
}

/**
 * Count active non-default filters (for badge display).
 */
export function activeFilterCount(filters: TransactionFilters): number {
  let count = 0;
  if (filters.accounts.length > 0) count++;
  if (filters.period) count++;
  if (filters.month) count++;
  if (filters.category) count++;
  if (filters.search) count++;
  if (filters.status) count++;
  return count;
}
