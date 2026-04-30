import { describe, expect, it } from 'vitest';
import {
  offByLabel,
  parseBackendCurrency,
  signedExpectedActualLine
} from './reconcile-error-copy';

describe('parseBackendCurrency', () => {
  it('strips a leading minus sign before the dollar prefix', () => {
    expect(parseBackendCurrency('-$99,999.00')).toBe('-99999.00');
  });

  it('accepts an unsigned dollar string', () => {
    expect(parseBackendCurrency('$500.01')).toBe('500.01');
  });

  it('handles negative non-round magnitudes', () => {
    expect(parseBackendCurrency('-$1,234.56')).toBe('-1234.56');
  });

  it('strips an optional leading +', () => {
    expect(parseBackendCurrency('+$100.00')).toBe('100.00');
  });

  it('also accepts an inner-sign shape (parseAmount already handled)', () => {
    expect(parseBackendCurrency('-1234.56')).toBe('-1234.56');
  });

  it('throws on empty input', () => {
    expect(() => parseBackendCurrency('')).toThrow();
    expect(() => parseBackendCurrency(null)).toThrow();
    expect(() => parseBackendCurrency(undefined)).toThrow();
  });

  it('throws on non-numeric input', () => {
    expect(() => parseBackendCurrency('not-a-number')).toThrow();
    expect(() => parseBackendCurrency('-$abc')).toThrow();
  });
});

describe('offByLabel', () => {
  it('returns the unsigned magnitude for a positive expected (asset over-asserted)', () => {
    const label = offByLabel(
      { expected: '$510.50', actual: '$500.01' },
      'USD'
    );
    expect(label).toBe('$10.49');
  });

  it('returns the unsigned magnitude when expected is negative (liability case)', () => {
    const label = offByLabel(
      { expected: '-$99,999.00', actual: '$500.01' },
      'USD'
    );
    // |(-99999.00) - 500.01| = 100499.01
    expect(label).toBe('$100,499.01');
  });

  it('returns the unsigned magnitude for two negative liability balances', () => {
    const label = offByLabel(
      { expected: '-$1,200.00', actual: '-$1,000.00' },
      'USD'
    );
    // |(-1200) - (-1000)| = 200
    expect(label).toBe('$200.00');
  });

  it('falls back to the server message when expected/actual are missing', () => {
    const label = offByLabel(
      { message: 'Reconciliation rejected — bad input' },
      'USD'
    );
    expect(label).toBe('Reconciliation rejected — bad input');
  });

  it('falls back to a generic message when nothing is provided', () => {
    const label = offByLabel({}, 'USD');
    expect(label).toBe('Reconciliation rejected.');
  });

  it('falls back to the server message when expected/actual fail to parse', () => {
    const label = offByLabel(
      {
        expected: 'garbage',
        actual: 'also garbage',
        message: 'Reconciliation rejected — assertion failed'
      },
      'USD'
    );
    expect(label).toBe('Reconciliation rejected — assertion failed');
  });
});

describe('signedExpectedActualLine', () => {
  it('renders signed values for an asset with positive expected', () => {
    const line = signedExpectedActualLine(
      { expected: '$510.50', actual: '$500.01' },
      'USD',
      'asset'
    );
    // good-change-plus on asset: positive change gets + prefix
    expect(line).toMatch(/^Your statement: .*510\.50.*·.*500\.01/);
  });

  it('renders signed values for a liability with negative expected (the bug case)', () => {
    const line = signedExpectedActualLine(
      { expected: '-$99,999.00', actual: '$500.01' },
      'USD',
      'liability'
    );
    expect(line).toContain('Your statement:');
    expect(line).toContain('Journal:');
    // The negative magnitude must round-trip — the previous bug dropped this entirely.
    expect(line).toContain('99,999');
  });

  it('renders signed values for a liability with positive expected', () => {
    const line = signedExpectedActualLine(
      { expected: '$1,200.00', actual: '$1,000.00' },
      'USD',
      'liability'
    );
    // good-change-plus on liability: positive amount is a balance increase = neutral
    // the line still renders both values, just without the + prefix
    expect(line).toContain('1,200');
    expect(line).toContain('1,000');
  });

  it('renders signed values for an asset with negative expected', () => {
    const line = signedExpectedActualLine(
      { expected: '-$50.00', actual: '$10.00' },
      'USD',
      'asset'
    );
    expect(line).toContain('Your statement:');
    expect(line).toContain('50');
    expect(line).toContain('10');
  });

  it('returns null when expected is missing', () => {
    expect(
      signedExpectedActualLine({ actual: '$10.00' }, 'USD', 'asset')
    ).toBeNull();
  });

  it('returns null when actual is missing', () => {
    expect(
      signedExpectedActualLine({ expected: '$10.00' }, 'USD', 'asset')
    ).toBeNull();
  });

  it('returns null when expected/actual fail to parse', () => {
    expect(
      signedExpectedActualLine(
        { expected: 'garbage', actual: '$10.00' },
        'USD',
        'asset'
      )
    ).toBeNull();
  });
});
