export type RunwayData = {
  months: number;
  spendableCash: number;
  avgMonthlySpending: number;
};

export type NetWorthPoint = {
  month: string;
  value: number;
};

export type RecurringVsDiscretionary = {
  recurring: number;
  discretionary: number;
  recurringCategories: string[];
  total: number;
};

export type LargestThisWeek = {
  payee: string;
  amount: number;
  date: string;
  accountLabel: string;
};

export type CategorySpike = {
  category: string;
  current: number;
  average: number;
  ratio: number;
};

export type SpendingStreak = {
  months: number;
};

export type StaleAccount = {
  id: string;
  displayName: string;
  daysSinceActivity: number;
};

export type MissingOB = {
  id: string;
  displayName: string;
};

export type DirectionData = {
  runway: RunwayData | null;
  netWorthTrend: NetWorthPoint[] | null;
  recurringVsDiscretionary: RecurringVsDiscretionary;
  notableSignals: {
    largestThisWeek: LargestThisWeek | null;
    categorySpike: CategorySpike | null;
    spendingStreak: SpendingStreak | null;
  };
  looseEnds: {
    reviewQueueCount: number;
    statementInboxCount: number;
    staleAccounts: StaleAccount[];
    missingOpeningBalances: MissingOB[];
  };
  baseCurrency: string;
};
