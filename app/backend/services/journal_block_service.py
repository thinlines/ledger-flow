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
    """Find one unique legacy block that predates durable transaction IDs."""
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
