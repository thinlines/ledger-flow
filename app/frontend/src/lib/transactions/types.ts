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

export type AccountRegister = {
  baseCurrency: string;
  accountId: string;
  currentBalance: number;
  entryCount: number;
  transactionCount: number;
  latestTransactionDate: string | null;
  latestActivityDate: string | null;
  hasOpeningBalance: boolean;
  hasTransactionActivity: boolean;
  hasBalanceSource: boolean;
  entries: RegisterEntry[];
};

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

export type ActivityResult = {
  baseCurrency: string;
  period: string | null;
  category: string | null;
  month: string | null;
  transactions: ActivityTransaction[];
  totalCount: number;
  summary?: ActivitySummary | null;
};

export type ActivityDateGroup = {
  header: string;
  transactions: ActivityTransaction[];
};

export type ActionLink = {
  href: string;
  label: string;
};

export type RegisterAction = ActionLink & {
  note: string;
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
