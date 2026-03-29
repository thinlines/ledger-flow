"""Shared transaction-header parser.

Extracts date, clearing status, optional code, and payee from a ledger
transaction header line.  All services that previously defined their own
``HEADER_RE`` should import from this module instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TransactionStatus(str, Enum):
    unmarked = "unmarked"
    pending = "pending"
    cleared = "cleared"


HEADER_RE = re.compile(
    r"^(?P<date>\d{4}[-/]\d{2}[-/]\d{2})"
    r"(?:\s+(?P<status>[*!]))?"
    r"(?:\s+(?P<code>\([^)]+\)))?"
    r"\s*(?P<payee>.*)$"
)

_STATUS_CHAR_MAP: dict[str | None, TransactionStatus] = {
    "*": TransactionStatus.cleared,
    "!": TransactionStatus.pending,
    None: TransactionStatus.unmarked,
}

_STATUS_TO_CHAR: dict[TransactionStatus, str | None] = {
    TransactionStatus.cleared: "*",
    TransactionStatus.pending: "!",
    TransactionStatus.unmarked: None,
}


@dataclass(frozen=True)
class ParsedHeader:
    date: str
    status: TransactionStatus
    code: str | None
    payee: str


def parse_header(line: str) -> ParsedHeader | None:
    """Parse a transaction header line into its components.

    Returns ``None`` if the line does not match the header pattern.
    """
    match = HEADER_RE.match(line)
    if not match:
        return None
    return ParsedHeader(
        date=match.group("date"),
        status=_STATUS_CHAR_MAP.get(match.group("status"), TransactionStatus.unmarked),
        code=match.group("code"),
        payee=match.group("payee").strip(),
    )


def set_header_status(line: str, new_status: TransactionStatus) -> str:
    """Rewrite a header line with a new clearing flag.

    Preserves date, code, and payee.  Returns the original line unchanged
    if it cannot be parsed.
    """
    parsed = parse_header(line)
    if parsed is None:
        return line

    parts: list[str] = [parsed.date]
    flag_char = _STATUS_TO_CHAR[new_status]
    if flag_char is not None:
        parts.append(flag_char)
    if parsed.code is not None:
        parts.append(parsed.code)
    if parsed.payee:
        parts.append(parsed.payee)
    return " ".join(parts)
