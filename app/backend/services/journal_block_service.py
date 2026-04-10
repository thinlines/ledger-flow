"""Shared helpers for locating and extracting transaction blocks in journal files."""

from __future__ import annotations

from services.journal_query_service import TXN_START_RE


class HeaderNotFoundError(LookupError):
    """The header line does not exist in the journal."""


class AmbiguousHeaderError(ValueError):
    """Multiple lines match the header — cannot disambiguate."""


def locate_header(lines: list[str], header_line: str) -> int:
    """Find the unique line index matching *header_line*.

    Raises ``HeaderNotFoundError`` if absent, ``AmbiguousHeaderError`` if
    multiple lines match.
    """
    match_indexes = [i for i, line in enumerate(lines) if line == header_line]
    if len(match_indexes) == 0:
        raise HeaderNotFoundError("Transaction not found in journal")
    if len(match_indexes) > 1:
        raise AmbiguousHeaderError("Ambiguous: multiple matching header lines found")
    return match_indexes[0]


def find_transaction_block(lines: list[str], header_idx: int) -> tuple[int, int]:
    """Return ``(start, end)`` line indices for the transaction block at *header_idx*.

    The block spans from *header_idx* up to (but not including) the next
    transaction header or end-of-file.  Trailing blank lines between blocks
    are trimmed from the range.
    """
    end = header_idx + 1
    while end < len(lines):
        if TXN_START_RE.match(lines[end]):
            break
        end += 1
    # Trim trailing blank lines.
    while end > header_idx + 1 and lines[end - 1].strip() == "":
        end -= 1
    return header_idx, end
