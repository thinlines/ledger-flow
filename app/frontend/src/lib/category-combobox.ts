/** Filter category accounts for the Review picker, ignoring account hierarchy. */
export function filterCategoryOptions(accounts: string[], query: string): string[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return accounts;
  return accounts.filter((account) => account.toLowerCase().includes(normalized));
}
