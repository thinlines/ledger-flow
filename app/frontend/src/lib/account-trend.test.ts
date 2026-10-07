import { describe, expect, it } from 'vitest';
import { balanceHistoryForChart, trendChangeForDisplay } from './account-trend';

describe('balanceHistoryForChart', () => {
	it('plots liability balances as debt magnitude so paydowns descend', () => {
		expect(balanceHistoryForChart([-5000, -4500, -4000], 'liability')).toEqual([
			5000, 4500, 4000
		]);
	});

	it('preserves asset balance history', () => {
		const history = [1000, 1250, 1500];
		expect(balanceHistoryForChart(history, 'asset')).toBe(history);
	});

	it('shows a liability paydown as a negative trend change', () => {
		expect(trendChangeForDisplay(1234.45, 'liability')).toBe(-1234.45);
		expect(trendChangeForDisplay(1234.45, 'asset')).toBe(1234.45);
	});
});
