import { describe, expect, it } from 'vitest';
import { escapeAliasPattern, merchantDefaultAccount, type Merchant } from './merchants';

describe('escapeAliasPattern', () => {
  it('escapes regex metacharacters in statement text', () => {
    expect(escapeAliasPattern('SQ *CORNER CAFE (OAKLAND)')).toBe(
      'SQ\\s+\\*CORNER\\s+CAFE\\s+\\(OAKLAND\\)'
    );
  });

  it('turns whitespace into \\s+ so the pattern survives spacing drift', () => {
    expect(escapeAliasPattern('PURCHASE    04/13')).toBe('PURCHASE\\s+04/13');
  });

  it('trims surrounding whitespace', () => {
    expect(escapeAliasPattern('  WAL-MART #2734  ')).toBe('WAL\\-MART\\s+#2734');
  });
});

describe('merchantDefaultAccount', () => {
  const merchants: Merchant[] = [
    { name: 'Walmart', defaultAccount: 'Expenses:Groceries', aliases: ['WAL-?MART'] },
    { name: 'Corner Cafe', defaultAccount: null, aliases: [] }
  ];

  it('returns the default account for a canonical merchant name', () => {
    expect(merchantDefaultAccount('Walmart', merchants)).toBe('Expenses:Groceries');
  });

  it('returns null for merchants without a default or unknown payees', () => {
    expect(merchantDefaultAccount('Corner Cafe', merchants)).toBeNull();
    expect(merchantDefaultAccount('Mystery Vendor', merchants)).toBeNull();
  });
});
