import type { RegisterEntry, ActivityTransaction } from './types';

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
