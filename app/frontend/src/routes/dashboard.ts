import { normalizeCurrencyCode } from '$lib/currency-format';

export type DashboardOverview = {
	baseCurrency: string;
	hasData: boolean;
	lastUpdated: string | null;
	summary: { netWorth: number; trackedBalanceTotal: number; incomeThisMonth: number; spendingThisMonth: number; savingsThisMonth: number; transactionCount: number; unknownTransactionCount: number };
	balances: { id: string; displayName: string; kind: string; balance: number; last4: string | null; lastTransactionDate: string | null; reconciliationStatus: { ok: boolean } }[];
	cashFlow: { income: number; spending: number; net: number; series: { month: string; label: string; income: number; spending: number; net: number }[] };
	categoryTrends: { category: string; current: number; previous: number; delta: number; direction: string; account: string }[];
	categoryHistory: { month: string; category: string; categoryLabel: string; amount: number }[];
	recentTransactions: { date: string; payee: string; accountLabel: string; category: string; amount: number; isIncome: boolean; isUnknown: boolean }[];
};

export type Direction = {
	runway: { months: number; spendableCash: number; avgMonthlySpending: number; monthlyObligations: number } | null;
	netWorthTrend: { month: string; value: number }[] | null;
	recurringVsDiscretionary: { recurring: number; discretionary: number; total: number; recurringCategories: string[] };
	notableSignals: { largestThisWeek: { payee: string; amount: number; date: string } | null; categorySpike: { category: string; current: number; average: number; ratio: number } | null; spendingStreak: { months: number } | null };
	looseEnds: { reviewQueueCount: number; statementInboxCount: number; staleAccounts: { displayName: string; daysSinceActivity: number }[]; missingOpeningBalances: { displayName: string }[]; brokenReconciliations: { displayName: string }[] };
};

export function money(value: number, currency = 'USD', hidden = false) {
	if (hidden) return '••••••';
	return new Intl.NumberFormat(undefined, { style: 'currency', currency: normalizeCurrencyCode(currency), maximumFractionDigits: 0 }).format(value);
}
