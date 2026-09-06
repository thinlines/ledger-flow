from __future__ import annotations

from .commodity_parser import (
    CommodityMismatchError,
    ParsedAmount,
    commodity_label,
    parse_amount,
    split_balance_assertion,
)
from .journal_syntax import ACCOUNT_LINE_RE
from .journal_writer import format_currency_amount

# Callers treat this module as the commodity facade and import the parser's
# vocabulary through it; re-exports are part of the interface, not dead weight.
__all__ = [
    "BASE_CURRENCY_SYMBOLS",
    "CommodityMismatchError",
    "ParsedAmount",
    "canonicalize_base_currency_amount",
    "canonicalize_base_currency_posting",
    "commodity_label",
    "parse_amount",
    "split_balance_assertion",
]


BASE_CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
}
def canonicalize_base_currency_amount(raw: str, base_currency: str) -> str:
    currency = str(base_currency or "").strip().upper()
    if not currency:
        return raw.strip()

    symbol = BASE_CURRENCY_SYMBOLS.get(currency)

    def canonicalize(expr: str) -> str:
        parsed = parse_amount(expr)
        if parsed is None:
            return expr.strip()
        if parsed.commodity not in {currency, symbol}:
            return expr.strip()
        return format_currency_amount(parsed.value, currency, decimal_places=None)

    primary, assertion = split_balance_assertion(raw)
    parts = [canonicalize(primary)]
    if assertion is not None:
        parts.append(f"= {canonicalize(assertion)}")
    return " ".join(parts).strip()


def canonicalize_base_currency_posting(line: str, base_currency: str) -> str:
    match = ACCOUNT_LINE_RE.match(line)
    if not match:
        return line

    amount_text = match.group(4).strip()
    if not amount_text:
        return line

    return (
        f"{match.group(1)}{match.group(2)}{match.group(3)}"
        f"{canonicalize_base_currency_amount(amount_text, base_currency)}"
    )
