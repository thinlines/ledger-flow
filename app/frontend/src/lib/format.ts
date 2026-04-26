import { normalizeCurrencyCode } from '$lib/currency-format';

export type AccountKind = 'asset' | 'liability';

export type SignMode = 'negative-only' | 'good-change-plus' | 'always';

export type FormatCurrencyOptions = {
  /** @deprecated Use signMode: 'always' instead */
  signed?: boolean;
  signMode?: SignMode;
  accountKind?: AccountKind;
};

export type CurrencyTone = 'positive' | 'neutral';

/**
 * Determine the visual tone for an amount rendered with `good-change-plus`.
 * Positive changes on assets and positive changes on liability accounts (which
 * represent balance decreases — a paydown) are "good" and get the positive
 * tone. Everything else (including $0) is neutral. Returns neutral when
 * accountKind is missing so callers fall through gracefully.
 */
export function goodChangeTone(
  amount: number,
  accountKind: AccountKind | undefined
): CurrencyTone {
  if (!accountKind) return 'neutral';
  if (amount > 0) return 'positive';
  return 'neutral';
}

export function formatCurrency(
  value: number | null | undefined,
  baseCurrency: string,
  options: FormatCurrencyOptions = {}
): string {
  if (value == null) return 'No balance yet';

  const mode = resolveSignMode(options);
  const signDisplay = mode === 'always' ? 'always' : 'auto';

  // In good-change-plus mode, hand-format the sign: "+$X" for good changes,
  // unsigned for everything else (including $0 and bad-direction changes).
  if (mode === 'good-change-plus') {
    const absolute = new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: normalizeCurrencyCode(baseCurrency),
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
      signDisplay: 'never'
    }).format(Math.abs(value));
    return goodChangeTone(value, options.accountKind) === 'positive' ? `+${absolute}` : absolute;
  }

  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: normalizeCurrencyCode(baseCurrency),
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay
  }).format(value);
}

function resolveSignMode(options: FormatCurrencyOptions): SignMode {
  if (options.signMode === 'good-change-plus' && !options.accountKind) {
    // Missing account kind falls through to negative-only per spec.
    return 'negative-only';
  }
  if (options.signMode) {
    if (
      options.signMode !== 'negative-only' &&
      options.signMode !== 'good-change-plus' &&
      options.signMode !== 'always'
    ) {
      return 'negative-only';
    }
    return options.signMode;
  }
  // Back-compat: signed:true behaves like 'always'.
  if (options.signed) return 'always';
  return 'negative-only';
}

export function formatStoredAmount(
  value: string | null | undefined,
  baseCurrency: string
): string {
  if (!value) return 'Not set';
  const parsed = Number(value);
  if (!Number.isNaN(parsed)) return formatCurrency(parsed, baseCurrency);
  return value;
}

/**
 * Consumer-app relative time: `Just now`, `2 minutes ago`, `1 hour ago`,
 * `Yesterday at 3:42 PM`, `Apr 18`. Tuned for the operation-history list, not
 * for high-precision timestamps.
 */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return '';
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return '';

  const diffMs = now.getTime() - then.getTime();
  if (diffMs < 0) return 'Just now';

  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return 'Just now';
  if (diffMin === 1) return '1 minute ago';
  if (diffMin < 60) return `${diffMin} minutes ago`;

  const diffHr = Math.floor(diffMin / 60);
  if (diffHr === 1) return '1 hour ago';
  if (diffHr < 24) return `${diffHr} hours ago`;

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfToday.getDate() - 1);
  if (then >= startOfYesterday && then < startOfToday) {
    const time = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(then);
    return `Yesterday at ${time}`;
  }

  // Older than yesterday: short month-day, year if it crosses a year.
  const sameYear = then.getFullYear() === now.getFullYear();
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' })
  }).format(then);
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return 'No activity yet';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  }).format(new Date(`${value}T00:00:00`));
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function countLabel(
  count: number,
  singular: string,
  plural = `${singular}s`
): string {
  return `${count} ${count === 1 ? singular : plural}`;
}
