// Merchant layer client helpers (issue #24). Merchants are declared payees
// projected from the journal; aliases are ledger-style regex patterns matched
// against raw statement text at import time.

export type Merchant = {
  name: string;
  defaultAccount: string | null;
  aliases: string[];
};

export type MerchantSuggestion = {
  name: string;
};

/** Turn raw statement text into a safe alias regex seed: metacharacters are
 * escaped and whitespace runs become `\s+` so the pattern survives the
 * spacing drift banks produce between exports. */
export function escapeAliasPattern(text: string): string {
  return text
    .trim()
    .split(/\s+/)
    .map((part) => part.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&'))
    .join('\\s+');
}

/** Categorization precedence helper: the merchant default account for a
 * canonical payee name, or null. */
export function merchantDefaultAccount(payee: string, merchants: Merchant[]): string | null {
  const merchant = merchants.find((candidate) => candidate.name === payee);
  return merchant?.defaultAccount ?? null;
}
