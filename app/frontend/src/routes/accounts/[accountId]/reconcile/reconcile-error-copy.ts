/**
 * Diff-prominent error copy for the 8c rejection panel.
 *
 * The backend's reconciliation_service emits signed currency strings with the
 * sign *outside* the dollar prefix (e.g. `-$99,999.00`). The shared
 * `parseAmount` rejects that shape on purpose — it's the user-input parser and
 * its parity fixture is intentionally strict. `parseBackendCurrency` peels the
 * sign off, delegates to `parseAmount`, then re-applies the sign so the route
 * can compute the headline magnitude and the signed expected/actual line.
 */
import {
  decimalSub,
  parseAmount,
  InvalidAmountError
} from '$lib/currency-parser';
import { formatCurrency, type AccountKind } from '$lib/format';

/**
 * Parse a currency string emitted by the backend's reconciliation formatter.
 *
 * Accepts an optional leading `+` or `-` before the dollar prefix (the shape
 * `reconciliation_service._compute_assertion_from_actual_and_offset` produces),
 * delegates the rest to the strict user-input parser, then re-prefixes the
 * sign. Throws {@link InvalidAmountError} on empty / non-numeric input.
 */
export function parseBackendCurrency(raw: string | null | undefined): string {
  const text = String(raw ?? '').trim();
  if (!text) throw new InvalidAmountError(raw);

  let sign = '';
  let body = text;
  if (body.startsWith('-') || body.startsWith('+')) {
    sign = body[0] === '-' ? '-' : '';
    body = body.slice(1);
  }
  const parsed = parseAmount(body);
  if (sign === '-' && parsed !== '0') return `-${parsed}`;
  return parsed;
}

export type ReconcileErrorDetails = {
  outcome?: string;
  message?: string;
  expected?: string | null;
  actual?: string | null;
  rawError?: string;
};

/**
 * Build the headline magnitude (`Off by $X.XX`) for the rejection panel.
 * Returns the formatted absolute difference, or the server `message` /
 * a generic fallback when expected/actual are missing or malformed.
 */
export function offByLabel(
  details: ReconcileErrorDetails,
  currency: string
): string {
  if (details.expected != null && details.actual != null) {
    try {
      const expectedDecimal = parseBackendCurrency(details.expected);
      const actualDecimal = parseBackendCurrency(details.actual);
      const diff = decimalSub(expectedDecimal, actualDecimal);
      const magnitude = Math.abs(Number.parseFloat(diff));
      return formatCurrency(magnitude, currency, { signMode: 'negative-only' });
    } catch {
      // fall through
    }
  }
  return details.message || 'Reconciliation rejected.';
}

/**
 * Build the supporting "Your statement: $X · Journal: $Y" subtitle, signed via
 * good-change-plus so liability accounts read naturally. Returns null when the
 * backend payload is missing or malformed (caller hides the line).
 */
export function signedExpectedActualLine(
  details: ReconcileErrorDetails,
  currency: string,
  accountKind: AccountKind | undefined
): string | null {
  if (details.expected == null || details.actual == null) return null;
  let expectedNum: number;
  let actualNum: number;
  try {
    expectedNum = Number.parseFloat(parseBackendCurrency(details.expected));
    actualNum = Number.parseFloat(parseBackendCurrency(details.actual));
  } catch {
    return null;
  }
  const expected = formatCurrency(expectedNum, currency, {
    signMode: 'good-change-plus',
    accountKind
  });
  const actual = formatCurrency(actualNum, currency, {
    signMode: 'good-change-plus',
    accountKind
  });
  return `Your statement: ${expected} · Journal: ${actual}`;
}
