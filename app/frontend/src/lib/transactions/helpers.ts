import type { RegisterEntry, ActivityTransaction, TransactionRow } from './types';

export function truncatePayee(payee: string, max = 50): string {
  if (payee.length <= max) return payee;
  return payee.slice(0, max - 1) + '…';
}

export function activityShortDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
}

export function categoryLeadingSegment(category: string | null): string {
  if (!category) return '';
  return category.split(':')[0] ?? '';
}

export function entryHasActions(entry: RegisterEntry): boolean {
  return !entry.isOpeningBalance;
}

export function canDelete(entry: RegisterEntry): boolean {
  return !entry.isOpeningBalance;
}

export function canRecategorize(entry: RegisterEntry): boolean {
  if (entry.isOpeningBalance || entry.isUnknown) return false;
  if (entry.transferState) return false;
  const categoryLines = entry.detailLines.filter((l) => l.kind !== 'source');
  if (categoryLines.length > 1) return false;
  return true;
}

export function canUnmatch(entry: RegisterEntry): boolean {
  return !!entry.matchId;
}

export const CLEARING_TOOLTIPS: Record<string, string> = {
  cleared: 'Bank-confirmed',
  pending: 'Flagged',
  unmarked: 'Manual entry'
};

export function groupActivityByDate(
  transactions: ActivityTransaction[]
): Array<{ header: string; transactions: ActivityTransaction[] }> {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const todayStr = today.toISOString().slice(0, 10);
  const yesterdayStr = yesterday.toISOString().slice(0, 10);

  const groups: Array<{ header: string; transactions: ActivityTransaction[] }> = [];
  let currentGroup: { header: string; transactions: ActivityTransaction[] } | null = null;

  for (const tx of transactions) {
    const header =
      tx.date === todayStr
        ? 'Today'
        : tx.date === yesterdayStr
          ? 'Yesterday'
          : activityShortDate(tx.date);

    if (!currentGroup || currentGroup.header !== header) {
      currentGroup = { header, transactions: [] };
      groups.push(currentGroup);
    }
    currentGroup.transactions.push(tx);
  }
  return groups;
}

// --- Unified TransactionRow helpers ---

export type TransactionDayGroupData = {
  header: string;
  date: string;
  rows: TransactionRow[];
  dailySum: number;
};

export function groupByDate(rows: TransactionRow[]): TransactionDayGroupData[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const todayStr = today.toISOString().slice(0, 10);
  const yesterdayStr = yesterday.toISOString().slice(0, 10);

  const groups: TransactionDayGroupData[] = [];
  let currentGroup: TransactionDayGroupData | null = null;

  for (const row of rows) {
    const dateStr = row.date;
    const header =
      dateStr === todayStr
        ? 'Today'
        : dateStr === yesterdayStr
          ? 'Yesterday'
          : formatDayHeader(dateStr);

    if (!currentGroup || currentGroup.date !== dateStr) {
      currentGroup = { header, date: dateStr, rows: [], dailySum: 0 };
      groups.push(currentGroup);
    }
    currentGroup.rows.push(row);
    currentGroup.dailySum += row.amount;
  }

  return groups;
}

function formatDayHeader(dateStr: string): string {
  const parsed = new Date(`${dateStr}T00:00:00`);
  const dayName = new Intl.DateTimeFormat(undefined, { weekday: 'long' }).format(parsed);
  const datePart = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
  return `${datePart} \u00B7 ${dayName}`;
}

export function canDeleteRow(row: TransactionRow): boolean {
  return !row.isOpeningBalance;
}

export function canRecategorizeRow(row: TransactionRow): boolean {
  if (row.isOpeningBalance || row.isUnknown) return false;
  if (row.isTransfer) return false;
  if (row.categories.length > 1) return false;
  return true;
}

export function canUnmatchRow(row: TransactionRow): boolean {
  return !!row.matchId;
}
