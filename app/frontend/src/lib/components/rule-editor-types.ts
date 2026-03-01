export type RuleCondition = {
  field: 'payee';
  operator: 'exact' | 'contains';
  value: string;
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
