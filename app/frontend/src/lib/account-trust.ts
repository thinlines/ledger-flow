import { effectiveOpeningBalanceDate } from '$lib/account-defaults';

export type BalanceTrustTone = 'ok' | 'warn' | 'neutral';

export type BalanceTrustInput = {
	hasOpeningBalance: boolean;
	hasTransactionActivity: boolean;
	hasBalanceSource: boolean;
	importConfigured?: boolean;
	openingBalanceDate?: string | null;
	latestActivityDate?: string | null;
};

export type BalanceTrustState = {
	shortLabel: string;
	label: string;
	note: string;
	tone: BalanceTrustTone;
};

function formatDate(value: string | null | undefined): string | null {
	if (!value) return null;
	const parsed = new Date(`${value}T12:00:00`);
	if (Number.isNaN(parsed.getTime())) return value;
	return new Intl.DateTimeFormat(undefined, {
		month: 'short',
		day: 'numeric',
		year: 'numeric'
	}).format(parsed);
}

export function describeBalanceTrust(input: BalanceTrustInput): BalanceTrustState {
	const openingDate = formatDate(effectiveOpeningBalanceDate(input.openingBalanceDate, input.hasOpeningBalance));
	const latestActivityDate = formatDate(input.latestActivityDate);

	if (!input.hasBalanceSource) {
		return {
			shortLabel: 'Needs setup',
			label: 'Needs a starting point',
			note: input.importConfigured
				? 'Add a starting balance or import history before relying on this account in totals.'
				: 'Add a starting balance before relying on this manually tracked account in totals.',
			tone: 'warn'
		};
	}

	if (input.hasTransactionActivity && input.hasOpeningBalance) {
		return {
			shortLabel: 'History + start',
			label: 'History and starting balance',
			note: latestActivityDate
				? `Imported activity is on file, and the starting balance anchors older history before ${latestActivityDate}.`
				: 'Imported activity is on file, and the starting balance anchors older history.',
			tone: 'ok'
		};
	}

	if (input.hasTransactionActivity) {
		return {
			shortLabel: 'History',
			label: input.importConfigured ? 'Imported history' : 'Activity on file',
			note: latestActivityDate
				? `Recent activity through ${latestActivityDate} is included in this balance.`
				: 'Recent activity is already included in this balance.',
			tone: 'ok'
		};
	}

	return {
		shortLabel: 'Starting balance',
		label: input.importConfigured ? 'Starting balance only' : 'Manual starting balance',
		note: openingDate
			? `This balance starts from ${openingDate}. Older transactions can be imported or added later.`
			: 'This balance starts from the opening amount on file. Older transactions can be imported or added later.',
		tone: 'neutral'
	};
}
