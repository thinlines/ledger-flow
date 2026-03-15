export type RuleCondition = {
  field: 'payee' | 'date';
  operator: 'exact' | 'contains' | 'on_or_after' | 'before' | 'between';
  value: string;
  secondaryValue?: string;
  joiner: 'and' | 'or';
};

export type RuleAction = {
  type: 'set_account' | 'add_tag' | 'set_kv' | 'append_comment';
  account?: string;
  tag?: string;
  key?: string;
  value?: string;
  text?: string;
};
