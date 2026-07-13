"""Shared helpers for locating and extracting transaction blocks in journal files."""

from __future__ import annotations

import hashlib
from .journal_query_service import LF_TXN_ID_META_RE, TXN_START_RE
from uuid import uuid7


def hash_block(lines: list[str], start: int, end: int) -> str:
    """Content hash of one transaction block's lines.

    Computed identically at scan and apply time by the staged flows
    (Review apply, rule history apply) — their block-level staleness
    contract (#17)."""
    return hashlib.sha256("\n".join(lines[start:end]).encode("utf-8")).hexdigest()


def hash_block_text(raw_text: str) -> str:
    """Content hash for a transaction block already captured as raw text."""
    lines = raw_text.splitlines()
    return hash_block(lines, 0, len(lines))


def locate_block_by_id(lines: list[str], lf_txn_id: str) -> tuple[int, int] | None:
    """Find the ``[start, end)`` range of the block whose ``lf_txn_id``
    metadata matches, wherever later edits moved it."""
    starts = [i for i, line in enumerate(lines) if TXN_START_RE.match(line)]
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        for line in lines[start + 1 : end]:
            match = LF_TXN_ID_META_RE.match(line)
            if match and match.group(1) == lf_txn_id:
                while end > start + 1 and lines[end - 1].strip() == "":
                    end -= 1
                return start, end
    return None


def locate_block_by_hash(lines: list[str], block_hash: str) -> tuple[int, int] | None:
    """Find a unique block by content hash for pre-identity legacy rows."""
    starts = [i for i, line in enumerate(lines) if TXN_START_RE.match(line)]
    matches: list[tuple[int, int]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        while end > start + 1 and lines[end - 1].strip() == "":
            end -= 1
        if hash_block(lines, start, end) == block_hash:
            matches.append((start, end))
    return matches[0] if len(matches) == 1 else None


def mint_lf_txn_id() -> str:
    """Mint a durable transaction identity for an app-created block.

    Same shape the one-time migration assigns (``txn_<uuid7 hex>``); every
    writer that creates a new transaction block records it as
    ``    ; lf_txn_id: <id>`` directly after the header line so the block
    stays targetable after later edits move it (spec: Mutation-Time
    Projection).
    """
    return f"txn_{uuid7().hex}"


def lf_txn_id_line(txn_id: str) -> str:
    """The house-style metadata line carrying a block's ``lf_txn_id``."""
    return f"    ; lf_txn_id: {txn_id}"


class HeaderNotFoundError(LookupError):
    """The header line does not exist (or no longer exists) at the expected position."""


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
