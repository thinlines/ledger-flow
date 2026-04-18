export type TrackedAccount = {
  id: string;
  displayName: string;
  ledgerAccount: string;
  kind: string;
  institutionId: string | null;
  institutionDisplayName?: string | null;
  last4?: string | null;
  importConfigured: boolean;
  openingBalance?: string | null;
  openingBalanceDate?: string | null;
};

/** @deprecated Used by ManualResolutionDialog during transition to TransactionRow */
export type RegisterEntry = {
  id: string;
  date: string;
  payee: string;
  summary: string;
  amount: number;
  runningBalance: number;
  isUnknown: boolean;
  isOpeningBalance: boolean;
  transferState?: string | null;
  detailLines: Array<{
    label: string;
    account: string;
    kind: string;
  }>;
  manualResolutionToken?: string | null;
  manualResolutionNote?: string | null;
  clearingStatus?: 'unmarked' | 'pending' | 'cleared';
  headerLine?: string;
  journalPath?: string;
  matchId?: string | null;
  notes?: string | null;
};

/** @deprecated Used by TransactionsExplanationHeader during transition to TransactionRow */
export type ActivityTransaction = {
  date: string;
  payee: string;
  accountLabel: string;
  importAccountId: string | null;
  category: string;
  categoryAccount: string;
  amount: number;
  isIncome: boolean;
  isUnknown: boolean;
};

export type ActivityTopTransaction = {
  date: string;
  payee: string;
  amount: number;
  accountLabel: string;
};

export type ActivitySummary = {
  periodTotal: number;
  periodCount: number;
  averageAmount: number;
  priorPeriodTotal: number | null;
  priorPeriodCount: number | null;
  deltaAmount: number | null;
  deltaPercent: number | null;
  rollingMonthlyAverage: number | null;
  rollingMonths: number;
  topTransaction: ActivityTopTransaction | null;
};

export type ManualResolutionPreview = {
  resolutionToken: string;
  date: string;
  payee: string;
  amount: number;
  baseCurrency: string;
  sourceAccountId: string;
  sourceAccountName: string;
  destinationAccountId: string;
  destinationAccountName: string;
  fromAccountId: string;
  fromAccountName: string;
  toAccountId: string;
  toAccountName: string;
  warning: string;
};

export type ManualResolutionApplyResult = {
  applied: boolean;
  backupPath: string;
  journalPath: string;
  date: string;
  payee: string;
  amount: number;
  sourceAccountId: string;
  sourceAccountName: string;
  destinationAccountId: string;
  destinationAccountName: string;
};

// --- Unified transactions types (Phase 4b) ---

export type TransactionRow = {
  id: string;
  date: string;
  payee: string;
  amount: number;
  runningBalance: number | null;
  account: { id: string; label: string };
  transferPeer?: { id: string; label: string } | null;
  categories: Array<{ account: string; label: string; amount: number }>;
  status: 'cleared' | 'pending' | 'unmarked';
  isTransfer: boolean;
  isUnknown: boolean;
  isManual: boolean;
  isOpeningBalance: boolean;
  legs: Array<{ journalPath: string; headerLine: string }>;
  matchId?: string | null;
  transferState?: string | null;
  manualResolutionToken?: string | null;
  manualResolutionNote?: string | null;
  detailLines: Array<{ label: string; account: string; kind: string }>;
  notes?: string | null;
};

export type AccountMeta = {
  accountId: string;
  currentBalance: number | null;
  entryCount: number;
  transactionCount: number;
  hasOpeningBalance: boolean;
  hasTransactionActivity: boolean;
  hasBalanceSource: boolean;
  latestTransactionDate: string | null;
  latestActivityDate: string | null;
};

export type TransactionsResponse = {
  baseCurrency: string;
  filters: {
    accounts: string[];
    categories: string[];
    period: string | null;
    month: string | null;
    status: string[] | null;
    search: string | null;
  };
  rows: TransactionRow[];
  totalCount: number;
  summary: ActivitySummary | null;
  accountMeta: AccountMeta | null;
};

export type TransactionFilters = {
  accounts: string[];
  period: string | null;
  month: string | null;
  category: string | null;
  search: string;
  status: string | null;
};
