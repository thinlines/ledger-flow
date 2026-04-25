"""Shared helpers for locating and extracting transaction blocks in journal files."""

from __future__ import annotations

from services.journal_query_service import TXN_START_RE


class HeaderNotFoundError(LookupError):
    """The header line does not exist (or no longer exists) at the expected position."""


class AmbiguousHeaderError(ValueError):
    """Multiple lines match the header — cannot disambiguate.

    .. deprecated::
        Mutation endpoints now identify transactions by ``(journalPath,
        lineNumber)`` and verify with :func:`locate_header_at`. This error
        is kept only for legacy event-log undo paths in ``undo_service``,
        which still locate by header-line text.
    """


def locate_header(lines: list[str], header_line: str) -> int:
    """Find the unique line index matching *header_line* (legacy path).

    Raises ``HeaderNotFoundError`` if absent, ``AmbiguousHeaderError`` if
    multiple lines match.

    .. note::
        Mutation endpoints use :func:`locate_header_at` instead. This
        helper remains for ``undo_service``: event-log payloads carry only
        the historical ``header_line`` text, not a line number, so undo
        replay still has to scan.
    """
    match_indexes = [i for i, line in enumerate(lines) if line == header_line]
    if len(match_indexes) == 0:
        raise HeaderNotFoundError("Transaction not found in journal")
    if len(match_indexes) > 1:
        raise AmbiguousHeaderError("Ambiguous: multiple matching header lines found")
    return match_indexes[0]


def locate_header_at(lines: list[str], line_number: int, expected_header: str) -> int:
    """Position-based identity with a byte-for-byte drift check.

    Verifies that ``lines[line_number]`` exists and equals
    ``expected_header`` exactly (no whitespace normalization, no parsing).
    Returns ``line_number`` on success.

    Raises :class:`HeaderNotFoundError` when the line number is out of
    range or the file content has shifted under the caller — either case
    means the caller's row was constructed from a stale read of the
    journal and the mutation must be refused.
    """
    if line_number < 0 or line_number >= len(lines):
        raise HeaderNotFoundError(
            "Transaction not found in journal (stale data — try refreshing)"
        )
    if lines[line_number] != expected_header:
        raise HeaderNotFoundError(
            "Transaction not found in journal (stale data — try refreshing)"
        )
    return line_number


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
