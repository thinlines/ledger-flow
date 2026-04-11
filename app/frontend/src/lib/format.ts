import { normalizeCurrencyCode } from '$lib/currency-format';

export type FormatCurrencyOptions = {
  signed?: boolean;
};

export function formatCurrency(
  value: number | null | undefined,
  baseCurrency: string,
  options: FormatCurrencyOptions = {}
): string {
  if (value == null) return 'No balance yet';

  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: normalizeCurrencyCode(baseCurrency),
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: options.signed ? 'always' : 'auto'
  }).format(value);
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
