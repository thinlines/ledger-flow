"""Commodity amounts: parsing, labelling, and canonical journal rendering.

One module for the whole round trip. :func:`parse_amount` reads a Ledger
posting amount into a :class:`ParsedAmount`, :func:`format_currency_amount`
renders one back out in canonical journal form, and the ``canonicalize_*``
functions compose the two to normalize base-currency amounts on import.

The renderer lives here rather than in ``journal_writer`` because it is
commodity vocabulary, not part of the journal mutation ritual; keeping it
here is also what lets parsing and rendering share one module without an
import cycle through the writer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .currency_parser import parse_amount as parse_currency_amount
from .journal_syntax import ACCOUNT_LINE_RE

AMOUNT_RE = re.compile(
    r"^\s*"
    r"(?:(?P<prefix>[^\d\s=,+-][^\d\s=,+-]*)\s*)?"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?)"
    r"(?:\s*(?P<suffix>[^\d\s=,+-][^\d\s=,+-]*))?"
    r"\s*$"
)

BASE_CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
}


@dataclass(frozen=True)
class ParsedAmount:
    value: Decimal
    commodity: str | None
    number_text: str


class CommodityMismatchError(ValueError):
    pass


def split_balance_assertion(raw: str) -> tuple[str, str | None]:
    primary, separator, remainder = raw.partition("=")
    if not separator:
        return primary.strip(), None
    return primary.strip(), remainder.strip() or None


def parse_amount(raw: str) -> ParsedAmount | None:
    primary, _ = split_balance_assertion(raw)
    if not primary:
        return None

    match = AMOUNT_RE.match(primary)
    if not match:
        return None

    number_text = match.group("number")
    commodity = (match.group("prefix") or match.group("suffix") or "").strip() or None
    try:
        value = parse_currency_amount(number_text)
    except ValueError:
        return None

    return ParsedAmount(value=value, commodity=commodity, number_text=number_text)


def commodity_label(commodity: str | None) -> str:
    return commodity or "unmarked amount"


def format_currency_amount(
    amount: Decimal,
    currency: str,
    *,
    decimal_places: int | None = 2,
) -> str:
    """Render a currency amount in Ledger Flow's canonical journal form.

    App-authored money uses two decimal places by default. Passing ``None``
    preserves a parsed source amount's precision during import normalization.
    """
    commodity = str(currency or "").strip().upper()
    if not commodity:
        raise ValueError("Currency is required when formatting a journal amount.")
    number = format(amount, "f") if decimal_places is None else f"{amount:.{decimal_places}f}"
    return f"{commodity} {number}"


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
