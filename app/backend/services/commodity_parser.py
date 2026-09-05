from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from .currency_parser import parse_amount as parse_currency_amount


AMOUNT_RE = re.compile(
    r"^\s*"
    r"(?:(?P<prefix>[^\d\s=,+-][^\d\s=,+-]*)\s*)?"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?)"
    r"(?:\s*(?P<suffix>[^\d\s=,+-][^\d\s=,+-]*))?"
    r"\s*$"
)


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
