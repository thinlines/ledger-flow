import type { RuleAction, RuleCondition } from '$lib/components/rule-editor-types';

export type EditableRule = {
  conditions: RuleCondition[];
  actions: RuleAction[];
  enabled?: boolean;
};

export function createDefaultRuleConditions(payee = ''): RuleCondition[] {
  return [{ field: 'payee', operator: 'exact', value: payee, joiner: 'and' }];
}

export function createDefaultRuleActions(account = ''): RuleAction[] {
  return [{ type: 'set_account', account }];
}

export function normalizeConditions(conditions: RuleCondition[]): RuleCondition[] {
  return (conditions || []).map((condition, index) => ({
    field: condition.field ?? 'payee',
    operator: condition.operator ?? 'exact',
    value: condition.value ?? '',
    joiner: index === 0 ? 'and' : (condition.joiner ?? 'and')
  }));
}

export function normalizeActions(actions: RuleAction[]): RuleAction[] {
  return [...(actions || [])].map((action) => ({ ...action }));
}

export function normalizeRule<T extends EditableRule>(rule: T): T {
  return {
    ...rule,
    conditions: normalizeConditions(rule.conditions),
    actions: normalizeActions(rule.actions)
  };
}

export function ensureSetAccountAction(actions: RuleAction[], fallbackAccount: string): RuleAction[] {
  const normalized = normalizeActions(actions);
  if (normalized.some((action) => action.type === 'set_account')) return normalized;
  return [{ type: 'set_account', account: fallbackAccount }, ...normalized];
}

export function sanitizedConditions(conditions: RuleCondition[]): RuleCondition[] {
  return normalizeConditions(conditions)
    .map((condition) => ({ ...condition, value: condition.value.trim() }))
    .filter((condition) => condition.value.length > 0)
    .map((condition, index) => ({ ...condition, joiner: index === 0 ? 'and' : condition.joiner }));
}

export function sanitizedActions(actions: RuleAction[]): RuleAction[] {
  const output: RuleAction[] = [];
  for (const action of normalizeActions(actions)) {
    if (action.type === 'set_account') {
      const account = (action.account ?? '').trim();
      if (account) output.push({ type: 'set_account', account });
    } else if (action.type === 'add_tag') {
      const tag = (action.tag ?? '').trim();
      if (tag) output.push({ type: 'add_tag', tag });
    } else if (action.type === 'set_kv') {
      const key = (action.key ?? '').trim();
      const value = (action.value ?? '').trim();
      if (key && value) output.push({ type: 'set_kv', key, value });
    } else if (action.type === 'append_comment') {
      const text = (action.text ?? '').trim();
      if (text) output.push({ type: 'append_comment', text });
    }
  }
  return output;
}

export function extractSetAccount(actions: RuleAction[]): string {
  return actions.find((action) => action.type === 'set_account')?.account?.trim() ?? '';
}

function matchesCondition(condition: RuleCondition, context: Record<string, string>): boolean {
  const expected = condition.value.trim().toLowerCase();
  const actual = (context[condition.field] ?? '').trim().toLowerCase();

  if (condition.operator === 'exact') return actual === expected;
  if (condition.operator === 'contains') return actual.includes(expected);
  return false;
}

export function ruleMatches(rule: Pick<EditableRule, 'conditions' | 'enabled'>, context: Record<string, string>): boolean {
  if (rule.enabled === false) return false;

  const conditions = normalizeConditions(rule.conditions);
  if (!conditions.length) return false;

  let matched = false;
  for (const [index, condition] of conditions.entries()) {
    const conditionMatch = matchesCondition(condition, context);
    if (index === 0) {
      matched = conditionMatch;
      continue;
    }
    matched = condition.joiner === 'or' ? matched || conditionMatch : matched && conditionMatch;
  }
  return matched;
}

export function findMatchingRule<T extends Pick<EditableRule, 'conditions' | 'enabled'>>(
  context: Record<string, string>,
  rules: T[]
): T | null {
  for (const rule of rules) {
    if (ruleMatches(rule, context)) return rule;
  }
  return null;
}
