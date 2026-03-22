function cleanedDate(value: string | null | undefined): string {
  return String(value || '').trim();
}

export function defaultOpeningBalanceDate(today = new Date()): string {
  return `${today.getFullYear()}-01-01`;
}

export function openingBalanceDateForDraft(value: string | null | undefined, today = new Date()): string {
  return cleanedDate(value) || defaultOpeningBalanceDate(today);
}

export function effectiveOpeningBalanceDate(
  value: string | null | undefined,
  hasOpeningBalance: boolean,
  today = new Date()
): string | null {
  const savedDate = cleanedDate(value);
  if (savedDate) return savedDate;
  return hasOpeningBalance ? defaultOpeningBalanceDate(today) : null;
}
