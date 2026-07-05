import { describe, expect, it } from 'vitest';
import { ruleMatches } from './rules';

describe('rule matching', () => {
  it('matches OR groups with AND conditions inside each group', () => {
    const rule = {
      enabled: true,
      conditions: [
        { field: 'payee' as const, operator: 'contains' as const, value: 'coffee', joiner: 'and' as const },
        { field: 'date' as const, operator: 'before' as const, value: '2026-02-01', joiner: 'and' as const },
        { field: 'payee' as const, operator: 'contains' as const, value: 'books', joiner: 'or' as const },
        { field: 'date' as const, operator: 'on_or_after' as const, value: '2026-03-01', joiner: 'and' as const }
      ]
    };

    expect(ruleMatches(rule, { payee: 'Coffee Shop', date: '2026-01-15' })).toBe(true);
    expect(ruleMatches(rule, { payee: 'Neighborhood Books', date: '2026-03-15' })).toBe(true);
    expect(ruleMatches(rule, { payee: 'Coffee Shop', date: '2026-03-15' })).toBe(false);
    expect(ruleMatches(rule, { payee: 'Neighborhood Books', date: '2026-01-15' })).toBe(false);
  });
});
