/** Filter category accounts for the Review picker, ignoring account hierarchy. */
export function filterCategoryOptions(accounts: string[], query: string): string[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return accounts;
  return accounts.filter((account) => account.toLowerCase().includes(normalized));
}

export type TransferTargetAccount = {
  id: string;
  displayName: string;
  ledgerAccount: string;
};

/** Find transfer destinations, including tracked accounts without import configuration. */
export function transferTargetOptions(
  accounts: TransferTargetAccount[],
  sourceAccountId: string | undefined,
  query: string
): TransferTargetAccount[] {
  const normalized = query.trim().toLowerCase();
  return accounts.filter((account) => {
    if (account.id === sourceAccountId) return false;
    return !normalized || [account.displayName, account.ledgerAccount]
      .some((value) => value.toLowerCase().includes(normalized));
  });
}
