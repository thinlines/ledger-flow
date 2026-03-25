from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


BASE_CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
}
POSTING_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
AMOUNT_RE = re.compile(
    r"^\s*"
    r"(?:(?P<prefix>[^\d\s=,+-][^\d\s=,+-]*)\s*)?"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?)"
    r"(?:\s*(?P<suffix>[^\d\s=,+-][^\d\s=,+-]*))?"
    r"\s*$"
)


class CommodityMismatchError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedAmount:
    value: Decimal
    commodity: str | None
    number_text: str


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
        value = Decimal(number_text.replace(",", ""))
    except InvalidOperation:
        return None

    return ParsedAmount(value=value, commodity=commodity, number_text=number_text)


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
        return f"{currency} {parsed.number_text}"

    primary, assertion = split_balance_assertion(raw)
    parts = [canonicalize(primary)]
    if assertion is not None:
        parts.append(f"= {canonicalize(assertion)}")
    return " ".join(parts).strip()


def canonicalize_base_currency_posting(line: str, base_currency: str) -> str:
    match = POSTING_RE.match(line)
    if not match:
        return line

    amount_text = match.group(4).strip()
    if not amount_text:
        return line

    return (
        f"{match.group(1)}{match.group(2)}{match.group(3)}"
        f"{canonicalize_base_currency_amount(amount_text, base_currency)}"
    )


def commodity_label(commodity: str | None) -> str:
    return commodity or "unmarked amount"
