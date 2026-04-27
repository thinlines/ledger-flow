import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  decimalAdd,
  decimalEquals,
  decimalSub,
  isValidAmount,
  parseAmount
} from './currency-parser';

type FixtureCase = { input: string; expected?: string };
type Fixture = {
  description: string;
  accepted: FixtureCase[];
  rejected: FixtureCase[];
};

const FIXTURE_PATH = fileURLToPath(
  new URL('../../../backend/tests/fixtures/currency_parser_cases.json', import.meta.url)
);

const fixture = JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8')) as Fixture;

describe('parseAmount — parity with backend currency_parser', () => {
  for (const { input, expected } of fixture.accepted) {
    it(`accepts ${JSON.stringify(input)} → ${expected}`, () => {
      expect(parseAmount(input)).toBeTruthy();
      expect(decimalEquals(parseAmount(input), expected!)).toBe(true);
    });
  }

  for (const { input } of fixture.rejected) {
    it(`rejects ${JSON.stringify(input)}`, () => {
      expect(() => parseAmount(input)).toThrow();
      expect(isValidAmount(input)).toBe(false);
    });
  }
});

describe('decimal helpers', () => {
  it('decimalEquals normalizes trailing zeros', () => {
    expect(decimalEquals('100.00', '100')).toBe(true);
    expect(decimalEquals('-0.00', '0')).toBe(true);
    expect(decimalEquals('-100.50', '-100.5')).toBe(true);
    expect(decimalEquals('100.01', '100.0100')).toBe(true);
  });

  it('decimalEquals distinguishes different values', () => {
    expect(decimalEquals('100.00', '100.01')).toBe(false);
    expect(decimalEquals('-1', '1')).toBe(false);
  });

  it('decimalAdd handles signs and scales', () => {
    expect(decimalEquals(decimalAdd('100.00', '50.50'), '150.50')).toBe(true);
    expect(decimalEquals(decimalAdd('-4.75', '4.75'), '0')).toBe(true);
    expect(decimalEquals(decimalAdd('1234567.89', '0.11'), '1234568.00')).toBe(true);
  });

  it('decimalSub mirrors decimalAdd with negation', () => {
    expect(decimalEquals(decimalSub('100', '25.50'), '74.50')).toBe(true);
    expect(decimalEquals(decimalSub('100', '100'), '0')).toBe(true);
    expect(decimalEquals(decimalSub('-50', '50'), '-100')).toBe(true);
  });
});
