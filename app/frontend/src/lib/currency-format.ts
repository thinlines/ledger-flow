const SYMBOL_TO_CURRENCY_CODE: Record<string, string> = {
  '$': 'USD',
  '€': 'EUR',
  '£': 'GBP',
  '¥': 'JPY'
};

export function normalizeCurrencyCode(value: string | null | undefined, fallback = 'USD'): string {
  const cleaned = String(value || '').trim();
  if (!cleaned) return fallback;

  const upper = cleaned.toUpperCase();
  if (/^[A-Z]{3}$/.test(upper)) {
    return upper;
  }

  return SYMBOL_TO_CURRENCY_CODE[cleaned] ?? fallback;
}
