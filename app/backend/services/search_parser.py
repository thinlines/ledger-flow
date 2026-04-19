"""Search formula parser for transaction filtering.

Parses structured search queries like ``amount:>100 category:groceries``
into a list of ``SearchTerm`` objects that the unified transactions service
can apply as filters.  The parser is maximally lenient — it never raises on
any input.  Unrecognized syntax falls through as a bare payee substring term.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

RECOGNIZED_FIELDS = {"amount", "category", "date", "account", "status", "payee"}


@dataclass(frozen=True)
class SearchTerm:
    field: str  # "payee", "amount", "category", "date", "account", "status"
    operator: str  # "contains", "gt", "lt", "gte", "lte", "eq", "range", "exact"
    value: str  # the raw value string
    value_num: Decimal | None  # parsed for amount terms
    value_num_end: Decimal | None  # end of range for amount:N..M


def _clean_amount(raw: str) -> str:
    """Strip ``$`` signs and commas so ``$1,000`` becomes ``1000``."""
    return raw.replace("$", "").replace(",", "")


def _parse_amount(raw: str) -> SearchTerm | None:
    """Attempt to parse an amount value into a SearchTerm.

    Returns ``None`` when the value is malformed (the caller should fall
    through to a bare payee term).
    """
    cleaned = _clean_amount(raw)

    # Range: N..M
    if ".." in cleaned:
        parts = cleaned.split("..", 1)
        try:
            lo = Decimal(parts[0].lstrip("-"))
            hi = Decimal(parts[1].lstrip("-"))
        except (InvalidOperation, IndexError):
            return None
        return SearchTerm(
            field="amount",
            operator="range",
            value=raw,
            value_num=lo,
            value_num_end=hi,
        )

    # Comparison operators: >=, <=, >, <
    m = re.match(r"^(>=|<=|>|<)(.+)$", cleaned)
    if m:
        op_str, num_str = m.group(1), m.group(2).lstrip("-")
        try:
            num = Decimal(num_str)
        except InvalidOperation:
            return None
        op_map = {">=": "gte", "<=": "lte", ">": "gt", "<": "lt"}
        return SearchTerm(
            field="amount",
            operator=op_map[op_str],
            value=raw,
            value_num=num,
            value_num_end=None,
        )

    # Exact match: bare number
    try:
        num = Decimal(cleaned.lstrip("-"))
    except InvalidOperation:
        return None
    return SearchTerm(
        field="amount",
        operator="eq",
        value=raw,
        value_num=num,
        value_num_end=None,
    )


def parse_search(query: str) -> list[SearchTerm]:
    """Parse a raw search string into a list of search terms.

    Multiple terms are space-separated and AND-combined at apply time.
    The function never raises; malformed input silently falls through to
    bare payee substring matching.
    """
    if not query or not query.strip():
        return []

    terms: list[SearchTerm] = []
    for token in query.split():
        colon_pos = token.find(":")
        if colon_pos > 0:
            field = token[:colon_pos].lower()
            value = token[colon_pos + 1:]
            if field in RECOGNIZED_FIELDS and value:
                if field == "amount":
                    parsed = _parse_amount(value)
                    if parsed is not None:
                        terms.append(parsed)
                        continue
                    # Malformed amount — fall through to bare payee term.
                elif field == "status":
                    terms.append(SearchTerm(
                        field="status",
                        operator="exact",
                        value=value.lower(),
                        value_num=None,
                        value_num_end=None,
                    ))
                    continue
                elif field == "date":
                    terms.append(SearchTerm(
                        field="date",
                        operator="exact",
                        value=value.lower(),
                        value_num=None,
                        value_num_end=None,
                    ))
                    continue
                elif field in ("category", "account", "payee"):
                    terms.append(SearchTerm(
                        field=field,
                        operator="contains",
                        value=value,
                        value_num=None,
                        value_num_end=None,
                    ))
                    continue

        # Bare term — payee substring match.
        terms.append(SearchTerm(
            field="payee",
            operator="contains",
            value=token,
            value_num=None,
            value_num_end=None,
        ))

    return terms
