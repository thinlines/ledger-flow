import { ACCOUNT_SUBTYPE_OPTIONS } from './account-subtypes';

export type ManagedAccount = {
  name: string;
  accountType: string;
  depth: number;
  subtype: string | null;
  note: string | null;
  closedOn: string | null;
  declared: boolean;
  used: boolean;
  postingCount: number;
  deletable: boolean;
  deleteBlockedReason: string | null;
};

export type LifecycleBadge = {
  label: string;
  tone: 'closed' | 'subtype' | 'auto';
};

export function leafName(name: string): string {
  const segments = name.split(':');
  return segments[segments.length - 1] ?? name;
}

function subtypeLabel(subtype: string): string {
  const option = ACCOUNT_SUBTYPE_OPTIONS.find((entry) => entry.value === subtype);
  if (option) return option.label;
  const spaced = subtype.replaceAll('_', ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function lifecycleBadges(account: ManagedAccount): LifecycleBadge[] {
  const badges: LifecycleBadge[] = [];
  if (account.closedOn) {
    badges.push({ label: `Closed ${account.closedOn}`, tone: 'closed' });
  }
  if (account.subtype) {
    badges.push({ label: subtypeLabel(account.subtype), tone: 'subtype' });
  }
  if (!account.declared) {
    badges.push({ label: 'Auto', tone: 'auto' });
  }
  return badges;
}

export function canClose(account: ManagedAccount): boolean {
  return account.closedOn === null;
}

export function canReopen(account: ManagedAccount): boolean {
  return account.closedOn !== null && account.declared;
}

export function deleteDisabledCopy(account: ManagedAccount): string | null {
  if (account.deletable) return null;
  if (!account.declared) {
    return 'Nothing to remove — this account only appears through its postings.';
  }
  return account.deleteBlockedReason ?? 'This account cannot be removed.';
}
