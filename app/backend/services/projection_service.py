"""Journal projection: parse plaintext journals into the workspace database.

Implements the projection half of docs/ledger-flow-projection-schema.md:
every physical file reachable from the year journals (via ``include``) is
parsed exactly once into ``journal_files`` / ``journal_items`` /
``transactions`` / ``postings`` / ``comments`` / ``metadata_entries``, with
``journal_diagnostics`` recording anything outside the managed house-style
subset. Journals stay canonical — this module never writes journal files,
and a passive rebuild never assigns missing ``lf_`` ids.

Amounts are stored as integer nanounits (10^-9 major units). Blocks the
managed parser cannot represent exactly (prices, >9 decimal places, virtual
postings, multiple elided postings…) keep their transaction row as
``preserved_raw`` with no posting rows; readers fall back to the block's
raw text for those.

Freshness is content-hash based: ``refresh_projection`` re-projects only
files whose sha256 differs from ``journal_files.content_hash``, removes rows
for deleted files, and picks up new ones. ``rebuild_projection`` is the
wipe-everything recovery path; both end in the same state.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from .archive_service import ARCHIVED_MANUAL_JOURNAL_NAME
from .commodity_service import parse_amount, split_balance_assertion
from .config_service import AppConfig
from .header_parser import parse_header
from .journal_block_service import hash_block_text
from .journal_query_service import (
    ACCOUNT_LINE_RE,
    ACCOUNT_ONLY_RE,
    INCLUDE_RE,
    POSTING_RE,
    TXN_START_RE,
    ParsedTransaction,
    _normalize_include_target,
    _parse_transaction,
    _resolve_include_paths,
)
from .projection_db import PROJECTION_TABLES, connect, database_path, ensure_database
from .reference_projection_service import rebuild_reference_data

COMMENT_CHARS = (";", "#", "%", "|", "*")
DIRECTIVE_KEYWORDS = {
    "account",
    "payee",
    "tag",
    "commodity",
    "alias",
    "bucket",
    "define",
    "year",
    "apply",
    "end",
}

_COMMENT_BODY_RE = re.compile(r"^\s*;\s?(.*)$")
_TAG_RE = re.compile(r"^:([^:\s]+):$")
_TYPED_KV_RE = re.compile(r"^([^:\s][^:]*)::\s*(.*)$")
_KV_RE = re.compile(r"^([^:\s][^:]*):\s*(.*)$")
_TYPED_DATE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]$")


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _short_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _to_nano(value: Decimal) -> int | None:
    scaled = value.scaleb(9)
    whole = int(scaled)
    return whole if scaled == whole else None


@dataclass
class _Diagnostic:
    line_number: int | None
    severity: str
    code: str
    message: str


@dataclass
class _Comment:
    raw_text: str
    source_location: str
    posting_index: int | None  # None = transaction-level
    parse_status: str = "raw"
    parsed_key: str | None = None
    parsed_value_text: str | None = None
    value_type: str | None = None  # set for kv comments only
    value_date: str | None = None
    value_decimal: str | None = None
    value_commodity: str | None = None
    value_boolean: int | None = None


@dataclass
class _Posting:
    account: str
    amount_nano: int | None
    commodity: str | None
    inferred: bool
    balance_assertion_text: str | None
    raw_line: str
    source_line: int


@dataclass
class _ParsedBlock:
    date: str
    effective_date: str | None
    status: str
    code: str | None
    payee: str
    raw_header: str
    managed: bool
    lf_txn_id: str | None
    postings: list[_Posting] = field(default_factory=list)
    comments: list[_Comment] = field(default_factory=list)


@dataclass
class _Item:
    item_type: str
    raw_text: str
    start_line: int  # 1-indexed, inclusive
    end_line: int  # 1-indexed, inclusive
    parse_status: str = "preserved"
    block: _ParsedBlock | None = None
    diagnostics: list[_Diagnostic] = field(default_factory=list)


def _parse_comment(line: str, location: str, posting_index: int | None) -> _Comment:
    comment = _Comment(
        raw_text=line, source_location=location, posting_index=posting_index
    )
    body_match = _COMMENT_BODY_RE.match(line)
    if not body_match:
        return comment
    body = body_match.group(1).strip()

    tag_match = _TAG_RE.match(body)
    if tag_match:
        comment.parse_status = "tag"
        comment.parsed_key = tag_match.group(1)
        return comment

    typed_match = _TYPED_KV_RE.match(body)
    if typed_match:
        key = typed_match.group(1).strip()
        value = typed_match.group(2).strip()
        comment.parse_status = "kv"
        comment.parsed_key = key
        comment.parsed_value_text = value
        date_match = _TYPED_DATE_RE.match(value)
        if date_match:
            try:
                date.fromisoformat(date_match.group(1))
            except ValueError:
                comment.value_type = "unknown"
                return comment
            comment.value_type = "date"
            comment.value_date = date_match.group(1)
            return comment
        if value.lower() in {"true", "false"}:
            comment.value_type = "boolean"
            comment.value_boolean = 1 if value.lower() == "true" else 0
            return comment
        parsed_amount = parse_amount(value)
        if parsed_amount is not None:
            comment.value_type = "amount"
            comment.value_decimal = str(parsed_amount.value)
            comment.value_commodity = parsed_amount.commodity
            return comment
        comment.value_type = "unknown"
        return comment

    kv_match = _KV_RE.match(body)
    if kv_match:
        comment.parse_status = "kv"
        comment.parsed_key = kv_match.group(1).strip()
        comment.parsed_value_text = kv_match.group(2).strip()
        comment.value_type = "string"
        return comment

    return comment


def _parse_block(
    content_lines: list[str], start_line: int
) -> tuple[_ParsedBlock | None, list[_Diagnostic]]:
    """Parse one transaction block. Returns (block, diagnostics).

    ``block is None`` means the header itself was unparseable and no
    transaction row can be stored. A parseable header with out-of-subset
    content returns ``managed = False`` (stored as ``preserved_raw``).
    """
    diagnostics: list[_Diagnostic] = []
    header = parse_header(content_lines[0])
    if header is None:
        return None, [
            _Diagnostic(start_line, "warning", "parse_error", "Unparseable transaction header.")
        ]
    try:
        iso_date = date.fromisoformat(header.date.replace("/", "-")).isoformat()
    except ValueError:
        return None, [
            _Diagnostic(start_line, "warning", "parse_error", "Invalid transaction date.")
        ]

    block = _ParsedBlock(
        date=iso_date,
        effective_date=None,
        status=header.status.value,
        code=header.code,
        payee=header.payee,
        raw_header=content_lines[0],
        managed=True,
        lf_txn_id=None,
    )

    def unmanaged(line_number: int, code: str, message: str) -> None:
        block.managed = False
        diagnostics.append(_Diagnostic(line_number, "info", code, message))

    posting_index = -1
    for offset, line in enumerate(content_lines[1:], start=1):
        line_number = start_line + offset
        stripped = line.lstrip()
        if stripped.startswith(";"):
            location = "txn_comment" if posting_index < 0 else "posting_comment"
            comment = _parse_comment(
                line, location, posting_index if posting_index >= 0 else None
            )
            block.comments.append(comment)
            if comment.parse_status == "kv" and comment.parsed_key == "lf_txn_id":
                block.lf_txn_id = (comment.parsed_value_text or "").strip() or None
            continue

        posting_match = POSTING_RE.match(line)
        if not posting_match:
            unmanaged(line_number, "unsupported_construct", "Unrecognized line in transaction block.")
            continue

        posting_index += 1
        account = posting_match.group(1).strip()
        amount_text = (posting_match.group(2) or "").strip()
        primary, assertion = split_balance_assertion(amount_text)

        if account.startswith(("(", "[")):
            unmanaged(line_number, "unsupported_posting", f"Virtual posting is outside the managed subset: {account}")
            continue

        amount_nano: int | None = None
        commodity: str | None = None
        if primary:
            if "@" in primary:
                unmanaged(line_number, "unsupported_posting", "Priced posting (@/@@) is outside the managed subset.")
                continue
            parsed = parse_amount(primary)
            if parsed is None:
                unmanaged(line_number, "unsupported_posting", f"Unparseable posting amount: {primary!r}")
                continue
            amount_nano = _to_nano(parsed.value)
            if amount_nano is None:
                unmanaged(
                    line_number,
                    "amount_precision_exceeded",
                    "Amount has more than nine decimal places; block preserved raw.",
                )
                continue
            commodity = parsed.commodity

        block.postings.append(
            _Posting(
                account=account,
                amount_nano=amount_nano,
                commodity=commodity,
                inferred=False,
                balance_assertion_text=assertion,
                raw_line=line,
                source_line=line_number,
            )
        )

    if block.managed and not block.postings:
        unmanaged(start_line, "unsupported_construct", "Transaction block has no postings.")

    if block.managed:
        blanks = [i for i, p in enumerate(block.postings) if p.amount_nano is None]
        if len(blanks) == 1:
            known = [p for p in block.postings if p.amount_nano is not None]
            commodities = {p.commodity for p in known}
            if len(commodities) > 1:
                unmanaged(
                    start_line,
                    "commodity_mismatch",
                    "Cannot infer elided amount across mixed commodities.",
                )
            else:
                idx = blanks[0]
                elided = block.postings[idx]
                elided.amount_nano = -sum(p.amount_nano for p in known)
                elided.commodity = next(iter(commodities), None)
                elided.inferred = True
        elif len(blanks) >= 2:
            unmanaged(
                start_line,
                "multiple_elided_postings",
                "More than one posting elides its amount; ledger cannot balance this block.",
            )

    return block, diagnostics


def _classify_file(text: str) -> list[_Item]:
    """Split a physical file into ordered items whose raw_text concatenates
    back to the original text byte-for-byte."""
    raw_lines = text.splitlines(keepends=True)
    contents = [line.rstrip("\n") for line in raw_lines]
    items: list[_Item] = []
    i = 0
    total = len(raw_lines)

    def is_blank(index: int) -> bool:
        return contents[index].strip() == ""

    def is_indented(index: int) -> bool:
        return contents[index][:1] in (" ", "\t") and not is_blank(index)

    def make_item(item_type: str, start: int, end: int, **kwargs) -> _Item:
        return _Item(
            item_type=item_type,
            raw_text="".join(raw_lines[start:end]),
            start_line=start + 1,
            end_line=end,
            **kwargs,
        )

    while i < total:
        content = contents[i]
        if is_blank(i):
            j = i
            while j < total and is_blank(j):
                j += 1
            items.append(make_item("blank", i, j))
            i = j
            continue

        if TXN_START_RE.match(content):
            j = i + 1
            while j < total and is_indented(j):
                j += 1
            block, diagnostics = _parse_block(contents[i:j], i + 1)
            if block is None:
                items.append(
                    make_item("raw", i, j, parse_status="error", diagnostics=diagnostics)
                )
            else:
                items.append(
                    make_item(
                        "transaction",
                        i,
                        j,
                        parse_status="managed" if block.managed else "preserved",
                        block=block,
                        diagnostics=diagnostics,
                    )
                )
            i = j
            continue

        if INCLUDE_RE.match(content):
            items.append(make_item("include", i, i + 1))
            i += 1
            continue

        if content[0] in COMMENT_CHARS:
            j = i
            while j < total and not is_blank(j) and contents[j][:1] in COMMENT_CHARS:
                j += 1
            items.append(make_item("comment", i, j))
            i = j
            continue

        first_word = content.split(None, 1)[0]
        j = i + 1
        while j < total and is_indented(j):
            j += 1
        if first_word in DIRECTIVE_KEYWORDS:
            items.append(make_item("directive", i, j))
        else:
            items.append(
                make_item(
                    "raw",
                    i,
                    j,
                    diagnostics=[
                        _Diagnostic(
                            i + 1,
                            "info",
                            "unsupported_construct",
                            f"Top-level construct is outside the managed subset: {content[:60]!r}",
                        )
                    ],
                )
            )
        i = j

    return items


def _file_role(config: AppConfig, path: Path) -> str:
    if path.name == ARCHIVED_MANUAL_JOURNAL_NAME:
        return "archive"
    try:
        path.resolve().relative_to(config.opening_bal_dir.resolve())
        return "opening"
    except ValueError:
        pass
    if path.suffix == ".dat":
        return "directives"
    return "journal"


def _rel_path(config: AppConfig, path: Path) -> str:
    return os.path.relpath(path.resolve(), config.root_dir.resolve()).replace(
        os.sep, "/"
    )


def _discover_files(config: AppConfig) -> dict[str, dict]:
    """Return every physical file reachable from the top-level journals,
    keyed by workspace-relative path: {rel: {path, role, text, content_hash}}."""
    discovered: dict[str, dict] = {}

    def visit(path: Path, stack: tuple[Path, ...]) -> None:
        resolved = path.resolve()
        if resolved in stack or not path.exists():
            return
        rel = _rel_path(config, path)
        if rel in discovered:
            return
        text = path.read_text(encoding="utf-8")
        discovered[rel] = {
            "path": resolved,
            "role": _file_role(config, path),
            "text": text,
            "content_hash": _sha256_text(text),
        }
        next_stack = (*stack, resolved)
        for line in text.splitlines():
            include_match = INCLUDE_RE.match(line)
            if not include_match:
                continue
            target = _normalize_include_target(include_match.group(1))
            for include_path in _resolve_include_paths(path.parent, target):
                visit(include_path, next_stack)

    for journal_path in sorted(config.journal_dir.glob("*.journal")):
        visit(journal_path, ())
    # Opening-balance readers are projection-served even while a workspace is
    # being bootstrapped, before the generated include index is reachable from
    # a year journal.
    for opening_path in sorted(config.opening_bal_dir.glob("*.journal")):
        visit(opening_path, ())
    return discovered


def _delete_file_rows(conn: sqlite3.Connection, file_id: str) -> None:
    conn.execute(
        """
        DELETE FROM comments WHERE owner_type = 'posting' AND owner_id IN (
            SELECT postings.id FROM postings
            JOIN transactions ON transactions.id = postings.transaction_id
            WHERE transactions.journal_file_id = ?
        )
        """,
        (file_id,),
    )
    conn.execute(
        """
        DELETE FROM comments WHERE owner_type = 'transaction' AND owner_id IN (
            SELECT id FROM transactions WHERE journal_file_id = ?
        )
        """,
        (file_id,),
    )
    conn.execute("DELETE FROM journal_files WHERE id = ?", (file_id,))


def _insert_comment(
    conn: sqlite3.Connection,
    comment: _Comment,
    owner_type: str,
    owner_id: str,
    comment_order: int,
    source_order: int,
) -> None:
    comment_id = _short_id("c", owner_id, str(comment_order), comment.raw_text)
    conn.execute(
        """
        INSERT INTO comments (
            id, owner_type, owner_id, comment_order, source_location,
            raw_text, parse_status, parsed_key, parsed_value_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            comment_id,
            owner_type,
            owner_id,
            comment_order,
            comment.source_location,
            comment.raw_text,
            comment.parse_status,
            comment.parsed_key,
            comment.parsed_value_text,
        ),
    )
    if comment.parse_status != "kv" or comment.value_type is None:
        return
    conn.execute(
        """
        INSERT INTO metadata_entries (
            id, comment_id, owner_type, owner_id, key, value_text, value_type,
            value_string, value_date, value_decimal, value_commodity,
            value_boolean, source_location, source_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _short_id("m", comment_id),
            comment_id,
            owner_type,
            owner_id,
            comment.parsed_key,
            comment.parsed_value_text or "",
            comment.value_type,
            comment.parsed_value_text if comment.value_type == "string" else None,
            comment.value_date,
            comment.value_decimal,
            comment.value_commodity,
            comment.value_boolean,
            comment.source_location,
            source_order,
        ),
    )


def _project_file(
    conn: sqlite3.Connection,
    rel_path: str,
    role: str,
    text: str,
    content_hash: str,
    parsed_at: str,
) -> None:
    file_id = _short_id("jf", rel_path)
    _delete_file_rows(conn, file_id)

    items = _classify_file(text)
    conn.execute(
        """
        INSERT INTO journal_files (id, path, role, content_hash, parsed_at, parse_status)
        VALUES (?, ?, ?, ?, ?, 'ok')
        """,
        (file_id, rel_path, role, content_hash, parsed_at),
    )

    txn_order = 0
    diag_index = 0

    def record_diagnostics(diagnostics: list[_Diagnostic]) -> None:
        nonlocal diag_index
        for diag in diagnostics:
            conn.execute(
                """
                INSERT INTO journal_diagnostics (
                    id, journal_file_id, path, line_number, severity,
                    code, message, blocking, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, FALSE, ?)
                """,
                (
                    _short_id("diag", file_id, str(diag_index)),
                    file_id,
                    rel_path,
                    diag.line_number,
                    diag.severity,
                    diag.code,
                    diag.message,
                    parsed_at,
                ),
            )
            diag_index += 1

    for item_order, item in enumerate(items):
        transaction_id: str | None = None
        if item.item_type == "transaction":
            block = item.block
            assert block is not None
            raw_block_hash = hash_block_text(item.raw_text)
            transaction_id = block.lf_txn_id
            if transaction_id is not None:
                duplicate = conn.execute(
                    "SELECT 1 FROM transactions WHERE id = ?", (transaction_id,)
                ).fetchone()
                if duplicate is not None:
                    item.diagnostics.append(
                        _Diagnostic(
                            item.start_line,
                            "warning",
                            "duplicate_lf_txn_id",
                            f"Duplicate lf_txn_id {transaction_id!r}; "
                            "keeping the first occurrence, this block gets an ephemeral id.",
                        )
                    )
                    transaction_id = None
            if transaction_id is None:
                transaction_id = _short_id(
                    "txn", rel_path, str(txn_order), raw_block_hash
                )
            conn.execute(
                """
                INSERT INTO transactions (
                    id, journal_file_id, txn_order, date, effective_date, status,
                    code, payee, raw_header, raw_block_hash,
                    source_start_line, source_end_line, parse_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    file_id,
                    txn_order,
                    block.date,
                    block.effective_date,
                    block.status,
                    block.code,
                    block.payee,
                    block.raw_header,
                    raw_block_hash,
                    item.start_line,
                    item.end_line,
                    "ok" if block.managed else "preserved_raw",
                ),
            )
            txn_order += 1

            if block.managed:
                posting_ids: list[str] = []
                for posting_order, posting in enumerate(block.postings):
                    posting_id = _short_id(
                        "post", transaction_id, str(posting_order), posting.raw_line
                    )
                    posting_ids.append(posting_id)
                    conn.execute(
                        """
                        INSERT INTO postings (
                            id, transaction_id, posting_order, account,
                            amount_nano, commodity, amount_inferred,
                            balance_assertion_text, raw_line, raw_line_hash,
                            source_line
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            posting_id,
                            transaction_id,
                            posting_order,
                            posting.account,
                            posting.amount_nano,
                            posting.commodity,
                            1 if posting.inferred else 0,
                            posting.balance_assertion_text,
                            posting.raw_line,
                            _sha256_text(posting.raw_line),
                            posting.source_line,
                        ),
                    )

                comment_orders: dict[tuple[str, str], int] = {}
                for source_order, comment in enumerate(block.comments):
                    if comment.posting_index is None:
                        owner_type, owner_id = "transaction", transaction_id
                    else:
                        owner_type = "posting"
                        owner_id = posting_ids[comment.posting_index]
                    order_key = (owner_type, owner_id)
                    comment_order = comment_orders.get(order_key, 0)
                    comment_orders[order_key] = comment_order + 1
                    _insert_comment(
                        conn, comment, owner_type, owner_id, comment_order, source_order
                    )

        item_id = _short_id("ji", file_id, str(item_order), item.raw_text)
        conn.execute(
            """
            INSERT INTO journal_items (
                id, journal_file_id, item_order, item_type, transaction_id,
                raw_text, raw_hash, source_start_line, source_end_line, parse_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                file_id,
                item_order,
                item.item_type,
                transaction_id,
                item.raw_text,
                _sha256_text(item.raw_text),
                item.start_line,
                item.end_line,
                item.parse_status,
            ),
        )
        record_diagnostics(item.diagnostics)


def refresh_projection(config: AppConfig) -> dict[str, list[str]]:
    """Bring the projection up to date with the files on disk.

    Content-hash comparison decides what to touch: unchanged files keep all
    their rows, changed/new files are (re-)projected, rows for files that no
    longer exist are removed. All inside one SQLite transaction.
    """
    ensure_database(config)
    discovered = _discover_files(config)
    parsed_at = datetime.now(UTC).isoformat()

    projected: list[str] = []
    removed: list[str] = []
    unchanged: list[str] = []

    with connect(database_path(config)) as conn:
        existing = {
            path: (file_id, content_hash)
            for file_id, path, content_hash in conn.execute(
                "SELECT id, path, content_hash FROM journal_files"
            ).fetchall()
        }
        for rel, (file_id, _) in existing.items():
            if rel not in discovered:
                _delete_file_rows(conn, file_id)
                removed.append(rel)
        for rel, info in discovered.items():
            if rel in existing and existing[rel][1] == info["content_hash"]:
                unchanged.append(rel)
                continue
            _project_file(
                conn, rel, info["role"], info["text"], info["content_hash"], parsed_at
            )
            projected.append(rel)

        # Reference data is a pure function of the projected files: re-derive
        # when anything changed, or when the tables are empty (first refresh
        # after the reference migration). Unchanged files keep reads write-free.
        reference_stale = bool(projected or removed) or (
            conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        )
        if reference_stale:
            rebuild_reference_data(conn, parsed_at)
        if projected or removed:
            _rebuild_transaction_matches(conn)

    return {
        "projected": sorted(projected),
        "removed": sorted(removed),
        "unchanged": sorted(unchanged),
    }


def _rebuild_transaction_matches(conn: sqlite3.Connection) -> None:
    """Derive active matches from journal-canonical ``lf_match_id`` metadata."""
    conn.execute("DELETE FROM transaction_matches")
    rows = conn.execute(
        """
        SELECT metadata_entries.value_text, transactions.id, journal_files.role
        FROM metadata_entries
        JOIN transactions ON transactions.id = metadata_entries.owner_id
        JOIN journal_files ON journal_files.id = transactions.journal_file_id
        WHERE metadata_entries.owner_type = 'transaction'
          AND metadata_entries.key IN ('lf_match_id', 'match-id')
        """
    ).fetchall()
    by_match: dict[str, dict[str, str]] = {}
    for match_id, transaction_id, role in rows:
        side = "archived" if role == "archive" else "imported"
        match = by_match.setdefault(match_id, {})
        if side in match:
            continue
        match[side] = transaction_id
    for match_id, sides in by_match.items():
        if set(sides) != {"imported", "archived"}:
            continue
        conn.execute(
            """
            INSERT INTO transaction_matches (
                id, imported_transaction_id, archived_manual_transaction_id
            ) VALUES (?, ?, ?)
            """,
            (match_id, sides["imported"], sides["archived"]),
        )


def rebuild_projection(config: AppConfig) -> dict[str, list[str]]:
    """Recovery path: wipe every projection table and re-project from disk."""
    ensure_database(config)
    with connect(database_path(config)) as conn:
        for table in reversed(PROJECTION_TABLES):
            conn.execute(f"DELETE FROM {table}")
    return refresh_projection(config)


def load_transactions_projected(config: AppConfig) -> list[ParsedTransaction]:
    """Projection-backed replacement for ``journal_query_service.load_transactions``.

    Refreshes the projection (content-hash self-healing), then rebuilds the
    exact legacy ``ParsedTransaction`` contract from stored block text: same
    include-expansion ordering per top-level journal, same stable date sort,
    same ``-1`` sentinel for transactions living in included files.
    """
    refresh_projection(config)
    root = config.root_dir.resolve()

    with connect(database_path(config)) as conn:
        files: dict[str, str] = {
            path: file_id
            for file_id, path in conn.execute(
                "SELECT id, path FROM journal_files"
            ).fetchall()
        }
        items_by_file: dict[str, list[tuple[str, str, int, str | None, str | None]]] = {}
        for file_id, item_type, raw_text, start_line, txn_id, block_hash in conn.execute(
            """
            SELECT journal_items.journal_file_id, journal_items.item_type,
                   journal_items.raw_text, journal_items.source_start_line,
                   transactions.id, transactions.raw_block_hash
            FROM journal_items
            LEFT JOIN transactions ON transactions.id = journal_items.transaction_id
            WHERE journal_items.item_type IN ('transaction', 'include')
            ORDER BY journal_items.journal_file_id, journal_items.item_order
            """
        ).fetchall():
            items_by_file.setdefault(file_id, []).append(
                (item_type, raw_text, start_line, txn_id, block_hash)
            )

    journal_dir_rel = _rel_path(config, config.journal_dir)
    tops = sorted(
        rel
        for rel in files
        if rel.startswith(f"{journal_dir_rel}/")
        and "/" not in rel[len(journal_dir_rel) + 1 :]
        and rel.endswith(".journal")
        and Path(rel).name != ARCHIVED_MANUAL_JOURNAL_NAME
    )

    transactions: list[ParsedTransaction] = []

    def walk(rel: str, top_rel: str, source_journal: str, stack: tuple[str, ...]) -> None:
        for item_type, raw_text, start_line, txn_id, block_hash in items_by_file.get(
            files[rel], []
        ):
            if item_type == "transaction":
                transaction = _parse_transaction(raw_text.splitlines())
                if transaction is None:
                    continue
                line_number = start_line - 1 if rel == top_rel else -1
                transactions.append(
                    replace(
                        transaction,
                        source_journal=source_journal,
                        header_line_number=line_number,
                        txn_id=txn_id,
                        block_hash=block_hash,
                    )
                )
                continue
            include_match = INCLUDE_RE.match(raw_text.rstrip("\n"))
            if not include_match:
                continue
            target = _normalize_include_target(include_match.group(1))
            base_dir = (root / rel).parent
            for include_path in _resolve_include_paths(base_dir, target):
                include_rel = _rel_path(config, include_path)
                if include_rel in files and include_rel not in stack:
                    walk(include_rel, top_rel, source_journal, (*stack, include_rel))

    for top_rel in tops:
        source_journal = str(config.journal_dir / Path(top_rel).name)
        walk(top_rel, top_rel, source_journal, (top_rel,))

    return sorted(transactions, key=lambda txn: txn.posted_on)


def load_projected_transaction_rows(config: AppConfig, journal_path: Path) -> list[dict]:
    """Load scan-oriented transaction rows from the projection.

    Unlike the legacy scanners this never walks or reparses the journal.  It
    exposes the stored source coordinates and raw posting presentation needed
    by staging flows whose eventual writes still preserve the original line.
    """
    refresh_projection(config)
    rel_path = _rel_path(config, journal_path)
    with connect(database_path(config)) as conn:
        transaction_rows = conn.execute(
            """
            SELECT transactions.id, transactions.date, transactions.payee,
                   transactions.raw_block_hash, transactions.source_start_line,
                   transactions.source_end_line
            FROM transactions
            JOIN journal_files ON journal_files.id = transactions.journal_file_id
            WHERE journal_files.path = ?
            ORDER BY transactions.txn_order
            """,
            (rel_path,),
        ).fetchall()
        result: list[dict] = []
        for txn_id, posted_on, payee, block_hash, start_line, end_line in transaction_rows:
            metadata = dict(conn.execute(
                """
                SELECT key, value_text FROM metadata_entries
                WHERE owner_type = 'transaction' AND owner_id = ?
                ORDER BY source_order
                """,
                (txn_id,),
            ).fetchall())
            postings = []
            for account, raw_line, source_line in conn.execute(
                """
                SELECT account, raw_line, source_line FROM postings
                WHERE transaction_id = ? ORDER BY posting_order
                """,
                (txn_id,),
            ).fetchall():
                match = ACCOUNT_LINE_RE.match(raw_line)
                if match:
                    indent, sep, amount = match.group(1), match.group(3), match.group(4).strip()
                else:
                    match = ACCOUNT_ONLY_RE.match(raw_line)
                    indent, sep, amount = (match.group(1), "", "") if match else ("", "", "")
                postings.append({
                    "lineNo": source_line,
                    "indent": indent,
                    "account": account,
                    "sep": sep,
                    "amount": amount,
                    "line": raw_line,
                })
            result.append({
                "id": txn_id,
                "date": posted_on,
                "payee": payee or "(no payee)",
                "blockHash": block_hash,
                "transactionStartLine": start_line,
                "transactionEndLine": end_line,
                "metadata": metadata,
                "postings": postings,
            })
    return result


@dataclass(frozen=True)
class ProjectedTransactionRef:
    """The projected identity a mutation endpoint needs to locate and guard
    one transaction block: where it lives, what its header says, and the
    block hash that detects staleness."""

    id: str
    journal_path: str  # workspace-relative POSIX path
    journal_file_id: str
    txn_order: int
    raw_header: str
    raw_block_hash: str
    status: str
    source_start_line: int


@dataclass(frozen=True)
class ProjectedTransactionMatch:
    id: str
    imported_transaction_id: str
    archived_manual_transaction_id: str


@dataclass(frozen=True)
class ProjectedManualEntry:
    id: str
    date: str
    status: str
    payee: str
    source_start_line: int
    source_end_line: int
    destination_account: str
    amount: Decimal | None


def projected_manual_entries(
    config: AppConfig, journal_path: Path, tracked_ledger_account: str
) -> list[ProjectedManualEntry]:
    """Return manual-entry match inputs from the projection, not journal text."""
    refresh_projection(config)
    try:
        rel = journal_path.resolve().relative_to(config.root_dir.resolve()).as_posix()
    except ValueError:
        return []
    with connect(database_path(config)) as conn:
        rows = conn.execute(
            """
            SELECT transactions.id, transactions.date, transactions.status,
                   transactions.payee, transactions.source_start_line,
                   transactions.source_end_line,
                   postings.account, postings.amount_nano
            FROM transactions
            JOIN journal_files ON journal_files.id = transactions.journal_file_id
            JOIN comments manual_tag
              ON manual_tag.owner_type = 'transaction'
             AND manual_tag.owner_id = transactions.id
             AND manual_tag.parse_status = 'tag'
             AND lower(manual_tag.parsed_key) = 'manual'
            JOIN postings ON postings.transaction_id = transactions.id
            WHERE journal_files.path = ?
              AND postings.account <> ?
              AND postings.account NOT LIKE '%Unknown%'
            ORDER BY transactions.txn_order, postings.posting_order
            """,
            (rel, tracked_ledger_account),
        ).fetchall()
    seen: set[str] = set()
    entries: list[ProjectedManualEntry] = []
    for row in rows:
        if row[0] in seen:
            continue
        seen.add(row[0])
        amount = Decimal(row[7]) / Decimal(1_000_000_000) if row[7] is not None else None
        entries.append(ProjectedManualEntry(*row[:7], amount))
    return entries


def find_projected_transaction_match(
    config: AppConfig, match_id: str
) -> ProjectedTransactionMatch | None:
    refresh_projection(config)
    with connect(database_path(config)) as conn:
        row = conn.execute(
            """
            SELECT id, imported_transaction_id, archived_manual_transaction_id
            FROM transaction_matches WHERE id = ?
            """,
            (match_id,),
        ).fetchone()
    return ProjectedTransactionMatch(*row) if row is not None else None


def projected_transaction_block(config: AppConfig, txn_id: str) -> str | None:
    """Return one transaction's canonical raw block through the projection."""
    with connect(database_path(config)) as conn:
        row = conn.execute(
            """
            SELECT journal_items.raw_text
            FROM journal_items
            WHERE journal_items.transaction_id = ?
            """,
            (txn_id,),
        ).fetchone()
    return row[0] if row is not None else None


_TXN_REF_SQL = """
    SELECT transactions.id, journal_files.path, transactions.journal_file_id,
           transactions.txn_order, transactions.raw_header,
           transactions.raw_block_hash, transactions.status,
           transactions.source_start_line
    FROM transactions
    JOIN journal_files ON journal_files.id = transactions.journal_file_id
"""


def find_projected_transaction(
    config: AppConfig, txn_id: str
) -> ProjectedTransactionRef | None:
    with connect(database_path(config)) as conn:
        row = conn.execute(
            f"{_TXN_REF_SQL} WHERE transactions.id = ?", (txn_id,)
        ).fetchone()
    return ProjectedTransactionRef(*row) if row is not None else None


def find_projected_transaction_at(
    config: AppConfig, journal_file_id: str, txn_order: int
) -> ProjectedTransactionRef | None:
    """Re-fetch a transaction after its file was re-projected. ``txn_order``
    is stable across in-place block edits, so this recovers the row even when
    the block carried no ``lf_txn_id`` and its hash-derived id changed."""
    with connect(database_path(config)) as conn:
        row = conn.execute(
            f"{_TXN_REF_SQL} WHERE transactions.journal_file_id = ? AND transactions.txn_order = ?",
            (journal_file_id, txn_order),
        ).fetchone()
    return ProjectedTransactionRef(*row) if row is not None else None


def render_file(config: AppConfig, rel_path: str) -> str:
    """Render a projected file from its items — byte-identical for untouched files."""
    with connect(database_path(config)) as conn:
        rows = conn.execute(
            """
            SELECT journal_items.raw_text
            FROM journal_items
            JOIN journal_files ON journal_files.id = journal_items.journal_file_id
            WHERE journal_files.path = ?
            ORDER BY journal_items.item_order
            """,
            (rel_path,),
        ).fetchall()
    return "".join(raw_text for (raw_text,) in rows)
