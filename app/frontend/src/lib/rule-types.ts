// Rule condition/action shapes shared by the rules logic layer. Formerly
// lived beside the RuleEditor component; the editor UI returns in the
// Review tracer bullet, but the types are logic-layer and live here.

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
