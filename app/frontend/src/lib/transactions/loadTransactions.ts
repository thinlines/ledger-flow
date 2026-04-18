import { apiGet } from '$lib/api';
import type { TransactionFilters, TransactionsResponse } from './types';
import { filtersToApiParams } from './transactionFilters';

/**
 * Load transactions from the unified API endpoint.
 */
export async function loadTransactions(filters: TransactionFilters, opts?: { signal?: AbortSignal }): Promise<TransactionsResponse> {
  const params = filtersToApiParams(filters);
  const path = params ? `/api/transactions?${params}` : '/api/transactions';
  return apiGet<TransactionsResponse>(path, opts);
}
