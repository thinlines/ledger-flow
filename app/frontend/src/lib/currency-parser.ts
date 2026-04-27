/**
 * Currency-amount parser used by the reconcile modal and any other surface
 * that accepts a free-form user-typed money string.
 *
 * Behavior is byte-equivalent to the backend `parse_amount` in
 * `services/currency_parser.py`. A shared JSON fixture
 * (`app/backend/tests/fixtures/currency_parser_cases.json`) drives parity
 * tests on both sides.
 *
 * Accepted shape: optional leading `$`, optional minus sign, comma group
 * separators, optional surrounding whitespace. Empty input rejects.
 *
 * The parser intentionally deals in decimal *strings* rather than `Number`
 * to preserve precision — the diff math compares against the backend's
 * Decimal-derived value for the assertion check, and floating-point drift
 * would let the modal enable Reconcile when the server will 422.
 */

const NUMERIC_RE = /^-?(?:\d+)(?:\.\d+)?$/;

export class InvalidAmountError extends Error {
  constructor(raw: unknown) {
    super(`Invalid amount: ${JSON.stringify(raw)}`);
    this.name = 'InvalidAmountError';
  }
}

/**
 * Parse a user-typed currency amount string into a normalized decimal string.
 *
 * Returns the cleaned numeric string (e.g. `"-1234.56"`, `"100"`). Trailing
 * zeros are preserved exactly as the user typed them so equality with the
 * backend Decimal is byte-stable when compared after `Decimal()`-style
 * normalization on either side.
 *
 * Throws {@link InvalidAmountError} on empty or non-numeric input.
 */
export function parseAmount(raw: string | null | undefined): string {
  const cleaned = String(raw ?? '')
    .trim()
    .replace(/^\$+/, '')
    .replace(/,/g, '');

  if (!cleaned) {
    throw new InvalidAmountError(raw);
  }
  if (!NUMERIC_RE.test(cleaned)) {
    throw new InvalidAmountError(raw);
  }
  return cleaned;
}

/**
 * Convenience: returns true when `parseAmount` would accept the input.
 */
export function isValidAmount(raw: string | null | undefined): boolean {
  try {
    parseAmount(raw);
    return true;
  } catch {
    return false;
  }
}

/**
 * Normalize a decimal string the way Python's `Decimal()` does for equality
 * comparisons. Strips trailing zeros after the decimal point, then collapses
 * a bare `.` or empty result to `"0"`. Used by the diff-zero check so the
 * modal stays in lockstep with the backend's strict balance check.
 */
export function decimalEquals(a: string, b: string): boolean {
  return normalizeDecimal(a) === normalizeDecimal(b);
}

function normalizeDecimal(value: string): string {
  if (!value) return '0';
  let sign = '';
  let body = value;
  if (body.startsWith('-')) {
    sign = '-';
    body = body.slice(1);
  } else if (body.startsWith('+')) {
    body = body.slice(1);
  }
  if (body.includes('.')) {
    body = body.replace(/0+$/, '').replace(/\.$/, '');
  }
  if (body === '' || body === '0') return '0';
  // Drop redundant leading zeros (but keep "0.5" → "0.5").
  body = body.replace(/^0+(?=\d)/, '');
  return `${sign}${body}`;
}

/**
 * Add two decimal strings, returning the normalized result. Avoids floating
 * point — uses BigInt under the hood with a fixed scale derived from the
 * inputs.
 */
export function decimalAdd(a: string, b: string): string {
  return decimalAddAll([a, b]);
}

export function decimalSub(a: string, b: string): string {
  const negated = b.startsWith('-') ? b.slice(1) : `-${b}`;
  return decimalAdd(a, negated);
}

export function decimalAddAll(values: string[]): string {
  if (values.length === 0) return '0';
  const scaled = values.map(decimalToScaled);
  const scale = Math.max(...scaled.map(([, s]) => s));
  let total = 0n;
  for (const [intValue, s] of scaled) {
    total += intValue * 10n ** BigInt(scale - s);
  }
  return scaledToDecimal(total, scale);
}

function decimalToScaled(value: string): [bigint, number] {
  const normalized = normalizeDecimal(value);
  const sign = normalized.startsWith('-') ? -1n : 1n;
  const body = normalized.replace(/^-/, '');
  const dot = body.indexOf('.');
  if (dot === -1) {
    return [sign * BigInt(body || '0'), 0];
  }
  const intPart = body.slice(0, dot) || '0';
  const fracPart = body.slice(dot + 1);
  return [sign * BigInt(intPart + fracPart), fracPart.length];
}

function scaledToDecimal(value: bigint, scale: number): string {
  if (scale === 0) return value.toString();
  const negative = value < 0n;
  const abs = negative ? -value : value;
  const str = abs.toString().padStart(scale + 1, '0');
  const intPart = str.slice(0, str.length - scale);
  const fracPart = str.slice(str.length - scale);
  const trimmedFrac = fracPart.replace(/0+$/, '');
  const body = trimmedFrac ? `${intPart}.${trimmedFrac}` : intPart;
  return negative && body !== '0' ? `-${body}` : body;
}
