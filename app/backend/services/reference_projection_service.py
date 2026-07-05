"""Reference data projection: accounts, payees, tags, commodities.

Implements the Reference Data section of docs/ledger-flow-projection-schema.md.
Rows are the union of declarations (``journal_items`` directive blocks, any
reachable file) and usage (postings, transaction payees, ``:flag:`` comments,
posting commodities — archive files excluded). Ancestors of declared/used
accounts are synthesized as ``used`` rows so the picker tree is complete.

``used AND NOT declared`` accounts, tags, and commodities are the
``--pedantic`` violations; each gets one ``journal_diagnostics`` row pointing
at its first usage site. Undeclared payees are allowed by design (merchant
suggestion surface, not an error).

Everything here is derived state: ``rebuild_reference_data`` wipes and
re-derives inside the caller's transaction, so it stays consistent with the
file projection it reads from.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date

ACCOUNT_TYPES = {"assets", "liabilities", "income", "expenses", "equity"}

REFERENCE_DIAGNOSTIC_CODES: tuple[str, ...] = (
    "undeclared_account",
    "undeclared_tag",
    "undeclared_commodity",
)

_COMMENT_BODY_RE = re.compile(r"^\s*;\s?(.*)$")
_TYPED_KV_RE = re.compile(r"^([^:\s][^:]*)::\s*(.*)$")
_KV_RE = re.compile(r"^([^:\s][^:]*):\s*(.*)$")
_TYPED_DATE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]$")
_FORMAT_DECIMALS_RE = re.compile(r"\d[\d,]*\.(\d+)")


def _short_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


@dataclass
class _Directive:
    keyword: str
    argument: str
    subdirectives: list[tuple[str, str]] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    typed_metadata: dict[str, str] = field(default_factory=dict)


def _parse_directive(raw_text: str) -> _Directive | None:
    lines = raw_text.splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    keyword, _, argument = first.partition(" ")
    directive = _Directive(keyword=keyword, argument=argument.strip())
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        body_match = _COMMENT_BODY_RE.match(stripped)
        if body_match:
            body = body_match.group(1).strip()
            typed = _TYPED_KV_RE.match(body)
            if typed:
                directive.typed_metadata[typed.group(1).strip()] = typed.group(2).strip()
                continue
            kv = _KV_RE.match(body)
            if kv:
                directive.metadata[kv.group(1).strip()] = kv.group(2).strip()
            continue
        word, _, rest = stripped.partition(" ")
        directive.subdirectives.append((word, rest.strip()))
    return directive


def _sub_values(directive: _Directive, word: str) -> list[str]:
    return [value for key, value in directive.subdirectives if key == word and value]


def _first_sub(directive: _Directive, word: str) -> str | None:
    values = _sub_values(directive, word)
    return values[0] if values else None


def _closed_on(directive: _Directive) -> str | None:
    value = directive.typed_metadata.get("lf_closed")
    if value is None:
        return None
    date_match = _TYPED_DATE_RE.match(value)
    if not date_match:
        return None
    try:
        date.fromisoformat(date_match.group(1))
    except ValueError:
        return None
    return date_match.group(1)


def derive_account_fields(name: str) -> tuple[str, str | None, int]:
    """(account_type, parent_name, depth) — pure functions of the name."""
    segments = name.split(":")
    root = segments[0].strip().lower()
    account_type = root if root in ACCOUNT_TYPES else "other"
    parent_name = ":".join(segments[:-1]) if len(segments) > 1 else None
    return account_type, parent_name, len(segments) - 1


def _display_scale(format_text: str | None) -> int:
    if not format_text:
        return 2
    decimals = _FORMAT_DECIMALS_RE.search(format_text)
    return len(decimals.group(1)) if decimals else 0


@dataclass
class _UsageSite:
    file_id: str
    path: str
    line_number: int | None


def _first_usage_sites(
    conn: sqlite3.Connection, query: str
) -> dict[str, _UsageSite]:
    """Run ``query`` returning (name, file_id, path, line) ordered by site;
    keep the first site per name."""
    sites: dict[str, _UsageSite] = {}
    for name, file_id, path, line_number in conn.execute(query).fetchall():
        if name and name not in sites:
            sites[name] = _UsageSite(file_id, path, line_number)
    return sites


_ACCOUNT_USAGE_SQL = """
    SELECT postings.account, journal_files.id, journal_files.path, postings.source_line
    FROM postings
    JOIN transactions ON transactions.id = postings.transaction_id
    JOIN journal_files ON journal_files.id = transactions.journal_file_id
    WHERE journal_files.role != 'archive'
    ORDER BY journal_files.path, postings.source_line
"""

_PAYEE_USAGE_SQL = """
    SELECT transactions.payee, journal_files.id, journal_files.path,
           transactions.source_start_line
    FROM transactions
    JOIN journal_files ON journal_files.id = transactions.journal_file_id
    WHERE journal_files.role != 'archive'
    ORDER BY journal_files.path, transactions.source_start_line
"""

_TAG_USAGE_SQL = """
    SELECT comments.parsed_key, journal_files.id, journal_files.path,
           COALESCE(postings.source_line, transactions.source_start_line)
    FROM comments
    LEFT JOIN postings
        ON comments.owner_type = 'posting' AND postings.id = comments.owner_id
    JOIN transactions ON transactions.id = CASE
        WHEN comments.owner_type = 'posting' THEN postings.transaction_id
        ELSE comments.owner_id
    END
    JOIN journal_files ON journal_files.id = transactions.journal_file_id
    WHERE comments.parse_status = 'tag' AND journal_files.role != 'archive'
    ORDER BY journal_files.path,
             COALESCE(postings.source_line, transactions.source_start_line)
"""

_COMMODITY_USAGE_SQL = """
    SELECT postings.commodity, journal_files.id, journal_files.path,
           postings.source_line
    FROM postings
    JOIN transactions ON transactions.id = postings.transaction_id
    JOIN journal_files ON journal_files.id = transactions.journal_file_id
    WHERE postings.commodity IS NOT NULL AND journal_files.role != 'archive'
    ORDER BY journal_files.path, postings.source_line
"""


def _declared_directives(conn: sqlite3.Connection) -> list[tuple[str, str, _Directive]]:
    """(journal_file_id, path, parsed directive) in deterministic file order."""
    declarations = []
    for raw_text, file_id, path in conn.execute(
        """
        SELECT journal_items.raw_text, journal_items.journal_file_id, journal_files.path
        FROM journal_items
        JOIN journal_files ON journal_files.id = journal_items.journal_file_id
        WHERE journal_items.item_type = 'directive'
        ORDER BY journal_files.path, journal_items.item_order
        """
    ).fetchall():
        directive = _parse_directive(raw_text)
        if directive is not None and directive.argument:
            declarations.append((file_id, path, directive))
    return declarations


def _record_diagnostic(
    conn: sqlite3.Connection, code: str, name: str, site: _UsageSite, parsed_at: str
) -> None:
    kind = code.removeprefix("undeclared_")
    conn.execute(
        """
        INSERT INTO journal_diagnostics (
            id, journal_file_id, path, line_number, severity,
            code, message, blocking, created_at
        ) VALUES (?, ?, ?, ?, 'warning', ?, ?, FALSE, ?)
        """,
        (
            _short_id("diag", "reference", code, name),
            site.file_id,
            site.path,
            site.line_number,
            code,
            f"{kind.capitalize()} {name!r} is used but not declared.",
            parsed_at,
        ),
    )


def rebuild_reference_data(conn: sqlite3.Connection, parsed_at: str) -> None:
    """Wipe and re-derive the reference tables and their diagnostics.

    Runs inside the caller's transaction, after the file projection is
    current, so declarations and usage are read from a consistent state.
    """
    for table in ("payee_aliases", "accounts", "payees", "tags", "commodities"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute(
        "DELETE FROM journal_diagnostics WHERE code IN (%s)"
        % ",".join("?" * len(REFERENCE_DIAGNOSTIC_CODES)),
        REFERENCE_DIAGNOSTIC_CODES,
    )

    declared_accounts: dict[str, dict] = {}
    declared_payees: dict[str, dict] = {}
    declared_tags: dict[str, dict] = {}
    declared_commodities: dict[str, dict] = {}

    for file_id, _path, directive in _declared_directives(conn):
        name = directive.argument
        if directive.keyword == "account" and name not in declared_accounts:
            declared_accounts[name] = {
                "journal_file_id": file_id,
                "note": _first_sub(directive, "note")
                or directive.metadata.get("description"),
                "subtype": directive.metadata.get("lf_subtype"),
                "closed_on": _closed_on(directive),
            }
        elif directive.keyword == "payee" and name not in declared_payees:
            declared_payees[name] = {
                "journal_file_id": file_id,
                "default_account": directive.metadata.get("lf_default_account"),
                "aliases": _sub_values(directive, "alias"),
            }
        elif directive.keyword == "tag" and name not in declared_tags:
            declared_tags[name] = {
                "journal_file_id": file_id,
                "note": _first_sub(directive, "note"),
            }
        elif directive.keyword == "commodity" and name not in declared_commodities:
            declared_commodities[name] = {
                "journal_file_id": file_id,
                "format": _first_sub(directive, "format"),
                "note": _first_sub(directive, "note"),
            }

    used_accounts = _first_usage_sites(conn, _ACCOUNT_USAGE_SQL)
    used_payees = _first_usage_sites(conn, _PAYEE_USAGE_SQL)
    used_tags = _first_usage_sites(conn, _TAG_USAGE_SQL)
    used_commodities = _first_usage_sites(conn, _COMMODITY_USAGE_SQL)

    # Ancestors of every declared/used account exist as rows so the tree is
    # complete; undeclared intermediates are synthesized as used (spec
    # Account Hierarchy).
    account_names = set(declared_accounts) | set(used_accounts)
    synthesized: set[str] = set()
    for name in list(account_names):
        segments = name.split(":")
        for end in range(1, len(segments)):
            synthesized.add(":".join(segments[:end]))
    account_names |= synthesized

    for name in sorted(account_names):
        declaration = declared_accounts.get(name)
        account_type, parent_name, depth = derive_account_fields(name)
        used = name in used_accounts or (
            declaration is None and name in synthesized
        )
        conn.execute(
            """
            INSERT INTO accounts (
                id, journal_file_id, name, account_type, subtype, parent_name,
                depth, note, closed_on, declared, used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _short_id("acct", name),
                declaration["journal_file_id"] if declaration else None,
                name,
                account_type,
                declaration["subtype"] if declaration else None,
                parent_name,
                depth,
                declaration["note"] if declaration else None,
                declaration["closed_on"] if declaration else None,
                1 if declaration else 0,
                1 if used else 0,
            ),
        )

    for name in sorted(set(declared_payees) | set(used_payees)):
        declaration = declared_payees.get(name)
        payee_id = _short_id("payee", name)
        conn.execute(
            """
            INSERT INTO payees (
                id, journal_file_id, name, default_account, declared, used
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payee_id,
                declaration["journal_file_id"] if declaration else None,
                name,
                declaration["default_account"] if declaration else None,
                1 if declaration else 0,
                1 if name in used_payees else 0,
            ),
        )
        for alias_order, pattern in enumerate(declaration["aliases"] if declaration else []):
            conn.execute(
                """
                INSERT OR IGNORE INTO payee_aliases (id, payee_id, pattern, alias_order)
                VALUES (?, ?, ?, ?)
                """,
                (_short_id("pal", payee_id, pattern), payee_id, pattern, alias_order),
            )

    for name in sorted(set(declared_tags) | set(used_tags)):
        declaration = declared_tags.get(name)
        conn.execute(
            """
            INSERT INTO tags (id, journal_file_id, name, note, declared, used)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _short_id("tag", name),
                declaration["journal_file_id"] if declaration else None,
                name,
                declaration["note"] if declaration else None,
                1 if declaration else 0,
                1 if name in used_tags else 0,
            ),
        )

    for symbol in sorted(set(declared_commodities) | set(used_commodities)):
        declaration = declared_commodities.get(symbol)
        format_text = declaration["format"] if declaration else None
        conn.execute(
            """
            INSERT INTO commodities (
                id, journal_file_id, symbol, format, display_scale,
                note, declared, used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _short_id("comm", symbol),
                declaration["journal_file_id"] if declaration else None,
                symbol,
                format_text,
                _display_scale(format_text) if declaration else 2,
                declaration["note"] if declaration else None,
                1 if declaration else 0,
                1 if symbol in used_commodities else 0,
            ),
        )

    for name, site in used_accounts.items():
        if name not in declared_accounts:
            _record_diagnostic(conn, "undeclared_account", name, site, parsed_at)
    for name, site in used_tags.items():
        if name not in declared_tags:
            _record_diagnostic(conn, "undeclared_tag", name, site, parsed_at)
    for symbol, site in used_commodities.items():
        if symbol not in declared_commodities:
            _record_diagnostic(conn, "undeclared_commodity", symbol, site, parsed_at)
