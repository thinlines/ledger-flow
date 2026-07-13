"""Account declaration lifecycle edits: subtype, close/reopen, delete.

Implements the Account Lifecycle section of
docs/ledger-flow-projection-schema.md (issue #19). Subtype and close date are
app-owned ``lf_`` metadata comment lines inside the ``account`` directive
block:

    account Liabilities:Credit Card
        ; lf_subtype: credit_card
        ; lf_closed:: [2026-05-31]

Edits locate the declaring directive file via the projection
(``accounts.journal_file_id``), rewrite only the target block's metadata
lines, and re-project, so every other byte of the file is preserved.
Undeclared accounts are auto-declared into ``10-accounts.dat`` first (the
same write path the create-account flow uses).

Deletion removes the whole block and is allowed only when the projection
proves no posting — in any file role, archives included — references the
account or a descendant, and no tracked/import account is configured on it.
Nothing foreign-keys into ``accounts``; the reference rebuild re-derives
used-only and ancestor rows, so usage rows never orphan.

Directive-only writes deliberately do not run through
``journal_writer.mutate`` (it requires a ``*.journal`` path); they follow the
``create_account`` precedent of direct write + re-projection. Event-log
coverage for declaration edits arrives with the operations spine (#22).
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .config_service import AppConfig, infer_account_kind
from .projection_db import connect, database_path
from .projection_service import refresh_projection

SUBTYPE_KEY = "lf_subtype"
CLOSED_KEY = "lf_closed"


def load_known_accounts(accounts_dat: Path) -> set[str]:
    """Account names declared in one directive file (header lines only)."""
    known = set()
    if not accounts_dat.exists():
        return known
    for line in accounts_dat.read_text(encoding="utf-8").splitlines():
        if line.startswith("account "):
            known.add(line[len("account "):].strip())
    return known


def create_account(
    accounts_dat: Path,
    account: str,
    account_type: str | None = None,
    description: str | None = None,
) -> tuple[bool, str | None]:
    """Append an ``account`` declaration block. ``(added, warning)``."""
    account_clean = account.strip()
    if not account_clean:
        raise ValueError("Account is required")
    if ":" not in account_clean:
        raise ValueError("Account must be fully qualified, e.g. Expenses:Food")

    known = load_known_accounts(accounts_dat)
    if account_clean in known:
        return False, None

    account_type_clean = (account_type or "").strip() or infer_account_kind(account_clean).title()
    description_clean = re.sub(r"\s*[\r\n]+\s*", " ", description or "").strip()
    if accounts_dat.exists():
        lines = accounts_dat.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"account {account_clean}")
    lines.append(f"    ; type: {account_type_clean}")
    if description_clean:
        lines.append(f"    ; description: {description_clean}")
    accounts_dat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True, None


class AccountNotDeclared(Exception):
    """The account has no declaration to operate on."""

    def __init__(self, account: str) -> None:
        super().__init__(f"Account is not declared: {account}")
        self.account = account


class DeclarationInUse(Exception):
    """Deletion refused: postings or app config still reference the account."""

    def __init__(self, account: str, reason: str, posting_count: int = 0) -> None:
        super().__init__(reason)
        self.account = account
        self.reason = reason
        self.posting_count = posting_count


def _default_declarations_file(config: AppConfig) -> Path:
    return config.init_dir / "10-accounts.dat"


def _declaring_file(config: AppConfig, account: str) -> Path | None:
    """Path of the directive file declaring ``account``, from the projection."""
    with closing(connect(database_path(config))) as conn:
        row = conn.execute(
            """
            SELECT journal_files.path
            FROM accounts
            JOIN journal_files ON journal_files.id = accounts.journal_file_id
            WHERE accounts.name = ? AND accounts.declared = TRUE
            """,
            (account,),
        ).fetchone()
    return config.root_dir / row[0] if row else None


def _metadata_line_re(key: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*;\s*{re.escape(key)}::?\s")


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _block_range(lines: list[str], account: str) -> tuple[int, int] | None:
    """(header_index, end_index) of the ``account <name>`` block, half-open.

    A block is the header line plus the following non-blank indented lines
    (metadata comments, ``note``/``alias`` subdirectives, rule ``payee``
    lines).
    """
    for index, raw in enumerate(lines):
        content = raw[: len(raw) - len(_line_ending(raw))]
        if not content.startswith("account "):
            continue
        if content[len("account "):].strip() != account:
            continue
        end = index + 1
        while end < len(lines):
            body = lines[end][: len(lines[end]) - len(_line_ending(lines[end]))]
            if not body.strip() or not body[:1].isspace():
                break
            end += 1
        return index, end
    return None


def _write_metadata(
    config: AppConfig, account: str, key: str, rendered: str | None
) -> None:
    """Set/replace (``rendered``) or remove (``None``) one metadata line in
    the account's declaration block, auto-declaring the account if needed."""
    refresh_projection(config)
    path = _declaring_file(config, account)
    if path is None:
        if rendered is None:
            return  # nothing declared, nothing to clear
        create_account(_default_declarations_file(config), account)
        path = _default_declarations_file(config)

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    block = _block_range(lines, account)
    if block is None:  # pragma: no cover — projection and file disagree
        raise AccountNotDeclared(account)
    header, end = block

    line_re = _metadata_line_re(key)
    existing = next(
        (i for i in range(header + 1, end) if line_re.match(lines[i])), None
    )

    if rendered is None:
        if existing is None:
            return
        removed_ending = _line_ending(lines[existing])
        del lines[existing]
        if not removed_ending and lines:
            # The removed line was the file's last; keep the file
            # newline-terminated exactly as far as it was before.
            lines[-1] = lines[-1][: len(lines[-1]) - len(_line_ending(lines[-1]))]
    elif existing is not None:
        ending = _line_ending(lines[existing]) or "\n"
        lines[existing] = f"    ; {rendered}{ending}"
    else:
        header_ending = _line_ending(lines[header])
        if not header_ending:
            lines[header] = f"{lines[header]}\n"
        lines.insert(header + 1, f"    ; {rendered}{header_ending or chr(10)}")

    path.write_text("".join(lines), encoding="utf-8")
    refresh_projection(config)


def set_subtype(config: AppConfig, account: str, subtype: str | None) -> None:
    """Write or clear the ``lf_subtype`` metadata on the declaration."""
    rendered = f"{SUBTYPE_KEY}: {subtype}" if subtype else None
    _write_metadata(config, account, SUBTYPE_KEY, rendered)


def close_account(config: AppConfig, account: str, closed_on: str) -> None:
    """Write ``lf_closed:: [<date>]`` typed metadata on the declaration."""
    _write_metadata(config, account, CLOSED_KEY, f"{CLOSED_KEY}:: [{closed_on}]")


def reopen_account(config: AppConfig, account: str) -> None:
    """Remove the ``lf_closed`` metadata from the declaration, if present."""
    _write_metadata(config, account, CLOSED_KEY, None)


def subtree_posting_count(conn: sqlite3.Connection, account: str) -> int:
    """Postings referencing the account or any descendant, every file role."""
    return conn.execute(
        "SELECT COUNT(*) FROM postings WHERE account = ? OR account LIKE ? || ':%'",
        (account, account),
    ).fetchone()[0]


def delete_block_reason(config: AppConfig, account: str, posting_count: int) -> str | None:
    """Why deletion is refused, or ``None`` when the declaration is unused."""
    if posting_count:
        return (
            f"{posting_count} posting(s) reference {account} or its "
            "sub-accounts. Deletion is only allowed for unused accounts."
        )
    configured = {
        str(cfg.get("ledger_account", "")).strip()
        for cfg in (*config.tracked_accounts.values(), *config.import_accounts.values())
    }
    if account in configured:
        return (
            f"{account} is the ledger account of a tracked or import account. "
            "Remove that account configuration first."
        )
    return None


def delete_declaration(config: AppConfig, account: str) -> None:
    """Remove the declaration block, guarded by the usage anti-join."""
    refresh_projection(config)
    path = _declaring_file(config, account)
    if path is None:
        raise AccountNotDeclared(account)

    with closing(connect(database_path(config))) as conn:
        posting_count = subtree_posting_count(conn, account)
    reason = delete_block_reason(config, account, posting_count)
    if reason is not None:
        raise DeclarationInUse(account, reason, posting_count)

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    block = _block_range(lines, account)
    if block is None:  # pragma: no cover — projection and file disagree
        raise AccountNotDeclared(account)
    header, end = block

    del lines[header:end]
    # Collapse the separator the block owned so blank runs don't double up.
    if header < len(lines) and not lines[header].strip():
        if header == 0 or not lines[header - 1].strip():
            del lines[header]

    path.write_text("".join(lines), encoding="utf-8")
    refresh_projection(config)
