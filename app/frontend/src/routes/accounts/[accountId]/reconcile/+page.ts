import { error, redirect } from '@sveltejs/kit';
import type { AccountKind } from '$lib/format';
import type { PageLoad } from './$types';

export type ReconcileTrackedAccount = {
  id: string;
  displayName: string;
  ledgerAccount: string;
  kind: string;
};

export type ReconcileContextRow = {
  id: string;
  date: string;
  payee: string;
  category: string;
  signedAmount: string;
};

export type ReconcileContextResponse = {
  openingBalance: string;
  currency: string;
  lastReconciliationDate: string | null;
  earliestPostingDate: string | null;
  transactions: ReconcileContextRow[];
};

export type ReconcileLoadData = {
  account: ReconcileTrackedAccount;
  accountKind: AccountKind;
  initialPeriodStart: string;
  initialPeriodEnd: string;
  initialContext: ReconcileContextResponse | null;
  initialContextError: string | null;
};

function todayIso(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map((s) => Number.parseInt(s, 10));
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

async function fetchJson<T>(fetcher: typeof fetch, path: string): Promise<T> {
  const res = await fetcher(path);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `${path} failed (${res.status})`);
  }
  return (await res.json()) as T;
}

export const load: PageLoad = async ({ params, fetch }) => {
  const accountId = params.accountId;

  let trackedAccounts: ReconcileTrackedAccount[];
  try {
    const data = await fetchJson<{ trackedAccounts: ReconcileTrackedAccount[] }>(
      fetch,
      '/api/tracked-accounts'
    );
    trackedAccounts = data.trackedAccounts;
  } catch (e) {
    throw error(500, e instanceof Error ? e.message : 'Could not load tracked accounts.');
  }

  const account = trackedAccounts.find((a) => a.id === accountId);
  if (!account) {
    throw error(404, `Tracked account not found: ${accountId}`);
  }

  if (account.kind !== 'asset' && account.kind !== 'liability') {
    throw redirect(303, '/accounts');
  }

  const accountKind: AccountKind = account.kind;

  const today = todayIso();
  let initialPeriodStart = today;
  const initialPeriodEnd = today;

  let initialContext: ReconcileContextResponse | null = null;
  let initialContextError: string | null = null;

  try {
    initialContext = await fetchJson<ReconcileContextResponse>(
      fetch,
      `/api/accounts/${encodeURIComponent(accountId)}/reconciliation-context?period_start=${initialPeriodStart}&period_end=${initialPeriodEnd}`
    );
    if (initialContext.lastReconciliationDate) {
      const floor = addDays(initialContext.lastReconciliationDate, 1);
      if (initialPeriodStart < floor) initialPeriodStart = floor;
    } else if (initialContext.earliestPostingDate) {
      initialPeriodStart = initialContext.earliestPostingDate;
    }
  } catch (e) {
    initialContextError =
      e instanceof Error ? e.message : 'Could not load reconciliation context.';
  }

  return {
    account,
    accountKind,
    initialPeriodStart,
    initialPeriodEnd,
    initialContext,
    initialContextError
  } satisfies ReconcileLoadData;
};
