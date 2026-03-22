export const ACCOUNT_SUBTYPE_OPTIONS = [
  { value: 'checking', label: 'Checking', longLabel: 'Checking account', kind: 'asset' },
  { value: 'savings', label: 'Savings', longLabel: 'Savings account', kind: 'asset' },
  { value: 'cash', label: 'Cash', longLabel: 'Cash account', kind: 'asset' },
  { value: 'investment', label: 'Investment', longLabel: 'Investment account', kind: 'asset' },
  { value: 'vehicle', label: 'Vehicle', longLabel: 'Vehicle asset', kind: 'asset' },
  { value: 'real_estate', label: 'Property', longLabel: 'Property asset', kind: 'asset' },
  { value: 'other_asset', label: 'Other asset', longLabel: 'Other asset', kind: 'asset' },
  { value: 'credit_card', label: 'Credit card', longLabel: 'Credit card', kind: 'liability' },
  { value: 'loan', label: 'Loan', longLabel: 'Loan', kind: 'liability' },
  { value: 'mortgage', label: 'Mortgage', longLabel: 'Mortgage', kind: 'liability' },
  { value: 'other_liability', label: 'Other liability', longLabel: 'Other liability', kind: 'liability' }
] as const;

export const BALANCE_SHEET_KIND_OPTIONS = [
  { value: 'asset', label: 'Asset', longLabel: 'Asset account' },
  { value: 'liability', label: 'Liability', longLabel: 'Liability account' }
] as const;

export type AccountSubtype = (typeof ACCOUNT_SUBTYPE_OPTIONS)[number]['value'];
export type AccountSubtypeKind = (typeof ACCOUNT_SUBTYPE_OPTIONS)[number]['kind'];
export type BalanceSheetKind = (typeof BALANCE_SHEET_KIND_OPTIONS)[number]['value'];
export type AccountSubtypeSource = 'saved' | 'suggested' | 'broad';

type AccountSubtypeContext = {
  subtype?: string | null;
  kind?: string;
  displayName?: string;
  ledgerAccount?: string;
  institutionDisplayName?: string | null;
};

type SuggestedTrackedLedgerAccountContext = {
  kind?: string | null;
  displayName?: string | null;
  institutionDisplayName?: string | null;
  templateLedgerPrefix?: string | null;
};

export type AccountSubtypePresentation = {
  subtype: AccountSubtype | null;
  kind: string;
  source: AccountSubtypeSource;
  shortLabel: string;
  longLabel: string;
};

const ACCOUNT_SUBTYPE_LOOKUP = new Map(ACCOUNT_SUBTYPE_OPTIONS.map((option) => [option.value, option]));

function normalizedText(parts: Array<string | null | undefined>): string {
  return parts
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

export function normalizeBalanceSheetKind(value: string | null | undefined): BalanceSheetKind {
  return value === 'liability' ? 'liability' : 'asset';
}

export function accountKindFromLedger(ledgerAccount: string | null | undefined): string {
  const prefix = String(ledgerAccount || '')
    .split(':', 1)[0]
    .trim()
    .toLowerCase();
  if (prefix === 'assets') return 'asset';
  if (prefix === 'liabilities' || prefix === 'liability') return 'liability';
  if (prefix === 'expenses' || prefix === 'expense') return 'expense';
  if (prefix === 'income' || prefix === 'revenue') return 'income';
  if (prefix === 'equity' || prefix === 'capital') return 'equity';
  return 'other';
}

export function accountKindLabel(kind: string | null | undefined): string {
  if (kind === 'asset') return 'Asset';
  if (kind === 'liability') return 'Liability';
  if (kind === 'expense') return 'Expense';
  if (kind === 'income') return 'Income';
  if (kind === 'equity') return 'Equity';
  return 'Tracked';
}

export function normalizeAccountSubtype(value: string | null | undefined): AccountSubtype | null {
  if (!value) return null;
  return ACCOUNT_SUBTYPE_LOOKUP.has(value as AccountSubtype) ? (value as AccountSubtype) : null;
}

export function accountSubtypeKind(value: string | null | undefined): AccountSubtypeKind | null {
  return normalizeAccountSubtype(value) ? ACCOUNT_SUBTYPE_LOOKUP.get(value as AccountSubtype)?.kind ?? null : null;
}

export function subtypeMatchesKind(value: string | null | undefined, kind: string | null | undefined): boolean {
  const subtypeKind = accountSubtypeKind(value);
  if (subtypeKind == null) return true;
  return subtypeKind === normalizeBalanceSheetKind(kind);
}

export function subtypeOptionsForKind(kind: string | null | undefined) {
  if (kind === 'asset' || kind === 'liability') {
    return ACCOUNT_SUBTYPE_OPTIONS.filter((option) => option.kind === kind);
  }
  return ACCOUNT_SUBTYPE_OPTIONS;
}

export function ledgerSuffix(
  templateDisplayName: string | null | undefined,
  displayName: string | null | undefined
): string {
  let candidate = String(displayName || '').trim();
  const template = String(templateDisplayName || '').trim();
  if (template && candidate.toLowerCase().startsWith(template.toLowerCase())) {
    const remainder = candidate.slice(template.length).replace(/^[\s:._-]+/, '').trim();
    if (remainder) candidate = remainder;
  }
  const parts = candidate
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1).toLowerCase());
  return parts.join(':') || 'Account';
}

export function suggestedTrackedLedgerAccount(context: SuggestedTrackedLedgerAccountContext): string {
  const displayName = String(context.displayName || '').trim();
  if (!displayName) return '';

  const institutionDisplayName = String(context.institutionDisplayName || '').trim();
  const kind = normalizeBalanceSheetKind(context.kind);
  const templateLedgerPrefix = String(context.templateLedgerPrefix || '').trim();
  const defaultPrefix = kind === 'liability' ? 'Liabilities' : 'Assets';
  const baseSegments =
    templateLedgerPrefix && accountKindFromLedger(templateLedgerPrefix) === kind
      ? templateLedgerPrefix.split(':').map((segment) => segment.trim()).filter(Boolean)
      : [
          defaultPrefix,
          ...ledgerSuffix('', institutionDisplayName)
            .split(':')
            .filter(Boolean)
        ];
  const nameSegments = ledgerSuffix(institutionDisplayName, displayName)
    .split(':')
    .filter(Boolean);
  return [...baseSegments, ...nameSegments].join(':');
}

export function inferAccountSubtype(context: AccountSubtypeContext): AccountSubtype | null {
  const kind = context.kind || accountKindFromLedger(context.ledgerAccount);
  const text = normalizedText([context.displayName, context.institutionDisplayName, context.ledgerAccount]);

  if (kind === 'asset') {
    if (/\bchecking\b/.test(text)) return 'checking';
    if (/\bsavings\b/.test(text)) return 'savings';
    if (/\bcash\b|\bwallet\b/.test(text)) return 'cash';
    if (/\bvehicle\b|\bauto\b|\bcar\b|\btruck\b/.test(text)) return 'vehicle';
    if (/\breal estate\b|\bproperty\b|\bhome\b|\bhouse\b|\bcondo\b/.test(text)) return 'real_estate';
    if (/\binvest\b|\bbrokerage\b|\bretirement\b|\bira\b|\b401k\b|\broth\b/.test(text)) return 'investment';
    return null;
  }

  if (kind === 'liability') {
    if (/\bmortgage\b|\bhome loan\b/.test(text)) return 'mortgage';
    if (/\bcredit\b|\bcard\b|\bvisa\b|\bmastercard\b|\bamex\b|\bdiscover\b/.test(text)) return 'credit_card';
    if (/\bloan\b|\bheloc\b|\bdebt\b/.test(text)) return 'loan';
    return null;
  }

  return null;
}

export function describeAccountSubtype(context: AccountSubtypeContext): AccountSubtypePresentation {
  const savedSubtype = normalizeAccountSubtype(context.subtype);
  const kind = context.kind || accountKindFromLedger(context.ledgerAccount);
  const suggestedSubtype = savedSubtype ? null : inferAccountSubtype(context);
  const resolvedSubtype = savedSubtype || suggestedSubtype;

  if (resolvedSubtype) {
    const option = ACCOUNT_SUBTYPE_LOOKUP.get(resolvedSubtype);
    if (option) {
      return {
        subtype: resolvedSubtype,
        kind,
        source: savedSubtype ? 'saved' : 'suggested',
        shortLabel: option.label,
        longLabel: option.longLabel
      };
    }
  }

  const broadLabel = accountKindLabel(kind);
  return {
    subtype: null,
    kind,
    source: 'broad',
    shortLabel: broadLabel,
    longLabel: `${broadLabel} account`
  };
}

export function accountSubtypeLabel(context: AccountSubtypeContext, format: 'short' | 'long' = 'long'): string {
  const presentation = describeAccountSubtype(context);
  return format === 'short' ? presentation.shortLabel : presentation.longLabel;
}
