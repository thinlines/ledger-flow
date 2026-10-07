export type AccountTrendKind = 'asset' | 'liability';

/**
 * Return values in the direction a person experiences the account balance.
 * Liability balances are stored as negative ledger values, so a paydown moves
 * from (for example) -5000 to -4000 but should descend from 5000 to 4000 in a
 * debt trend chart.
 */
export function balanceHistoryForChart(
	history: number[],
	kind: AccountTrendKind
): number[] {
	return kind === 'liability' ? history.map((value) => -value) : history;
}

export function trendChangeForDisplay(
	change: number,
	kind: AccountTrendKind
): number {
	return kind === 'liability' ? -change : change;
}
