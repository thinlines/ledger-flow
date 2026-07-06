"""Merchant layer: app-side payee alias matching (issue #24).

Implements the Merchant Layer section of docs/ledger-flow-projection-schema.md.
``payees`` doubles as the merchant list: on import the app — not ``ledger
convert`` — matches statement text against ``payee_aliases`` patterns in
``alias_order`` and writes the canonical merchant name on the payee line.
"""
from __future__ import annotations

import hashlib
import re
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from .config_service import AppConfig
from .operations_service import record_operation
from .projection_db import connect, database_path
from .projection_service import refresh_projection
from .rules_service import extract_set_account, find_matching_rule

DEFAULT_ACCOUNT_KEY = "lf_default_account"
PAYEES_FILE_NAME = "11-payees.dat"


@dataclass(frozen=True)
class Merchant:
    name: str
    default_account: str | None = None
    aliases: tuple[str, ...] | list[str] = field(default_factory=tuple)


def load_merchants(config: AppConfig) -> list[Merchant]:
    """Declared payees with their ordered alias patterns, name-sorted.

    Undeclared used payees are excluded: they are the "create merchant from
    this payee?" suggestion surface, not merchants."""
    refresh_projection(config)
    with closing(connect(database_path(config))) as conn:
        payee_rows = conn.execute(
            """
            SELECT id, name, default_account FROM payees
            WHERE declared = TRUE ORDER BY name
            """
        ).fetchall()
        alias_rows = conn.execute(
            "SELECT payee_id, pattern FROM payee_aliases ORDER BY alias_order"
        ).fetchall()

    aliases_by_payee: dict[str, list[str]] = {}
    for payee_id, pattern in alias_rows:
        aliases_by_payee.setdefault(payee_id, []).append(pattern)

    return [
        Merchant(
            name=name,
            default_account=default_account,
            aliases=tuple(aliases_by_payee.get(payee_id, [])),
        )
        for payee_id, name, default_account in payee_rows
    ]


def list_undeclared_payees(config: AppConfig) -> list[str]:
    """Used-but-undeclared payees — the "create merchant from this payee?"
    suggestion surface (spec: allowed by design, not an error)."""
    refresh_projection(config)
    with closing(connect(database_path(config))) as conn:
        rows = conn.execute(
            """
            SELECT name FROM payees
            WHERE used = TRUE AND declared = FALSE
            ORDER BY name
            """
        ).fetchall()
    return [name for (name,) in rows]


def resolve_category(
    context: dict[str, str],
    rules: list[dict],
    merchants: list[Merchant],
) -> tuple[str, str] | None:
    """``(account, source)`` by categorization precedence, or ``None``.

    Precedence is explicit rule → merchant default account → nothing
    (callers fall through to ``Expenses:Unknown``). ``source`` is ``"rule"``
    or ``"merchant"``."""
    rule = find_matching_rule(context, rules)
    if rule is not None:
        account = extract_set_account(rule)
        if account:
            return account, "rule"

    payee = context.get("payee", "").strip()
    merchant = next((m for m in merchants if m.name == payee), None)
    if merchant is not None and merchant.default_account:
        return merchant.default_account, "merchant"
    return None


def match_merchant(statement_text: str, merchants: list[Merchant]) -> Merchant | None:
    """First merchant whose alias pattern matches *statement_text*.

    Patterns are ledger ``alias`` regexes, searched case-insensitively.
    """
    for merchant in merchants:
        for pattern in merchant.aliases:
            try:
                if re.search(pattern, statement_text, re.IGNORECASE):
                    return merchant
            except re.error:
                continue
    return None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _declaring_file(config: AppConfig, name: str) -> Path | None:
    """Path of the directive file declaring payee ``name``, from the
    projection (mirrors account_declaration_service)."""
    with closing(connect(database_path(config))) as conn:
        row = conn.execute(
            """
            SELECT journal_files.path
            FROM payees
            JOIN journal_files ON journal_files.id = payees.journal_file_id
            WHERE payees.name = ? AND payees.declared = TRUE
            """,
            (name,),
        ).fetchone()
    return config.root_dir / row[0] if row else None


def _payee_block_range(lines: list[str], name: str) -> tuple[int, int] | None:
    """(header_index, end_index) of the ``payee <name>`` block, half-open.

    A block is the header plus the following non-blank indented lines
    (``alias`` subdirectives, metadata comments)."""
    for index, line in enumerate(lines):
        if not line.startswith("payee "):
            continue
        if line[len("payee "):].strip() != name:
            continue
        end = index + 1
        while end < len(lines):
            body = lines[end]
            if not body.strip() or not body[:1].isspace():
                break
            end += 1
        return index, end
    return None


def upsert_merchant(
    config: AppConfig,
    *,
    name: str,
    alias: str | None = None,
    default_account: str | None = None,
    actor_type: str = "user",
) -> dict:
    """Declare or extend a merchant (``payee`` directive block).

    Appends a new block to the payees ``.dat`` for undeclared payees, or
    edits the declaring block in place: the alias is appended (if new) and
    the default account set/replaced. The reference-data change is recorded
    as an operation (issue #24)."""
    name_clean = name.strip()
    if not name_clean:
        raise ValueError("Merchant name is required")
    alias_clean = (alias or "").strip()
    default_clean = (default_account or "").strip()

    refresh_projection(config)
    path = _declaring_file(config, name_clean)
    created = path is None
    if path is None:
        path = config.init_dir / PAYEES_FILE_NAME
    hash_before = _sha256_file(path)

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    changed = False
    if created:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"payee {name_clean}")
        if alias_clean:
            lines.append(f"    alias {alias_clean}")
        if default_clean:
            lines.append(f"    ; {DEFAULT_ACCOUNT_KEY}: {default_clean}")
        changed = True
    else:
        block = _payee_block_range(lines, name_clean)
        if block is None:  # pragma: no cover — projection and file disagree
            raise ValueError(f"Payee declaration not found: {name_clean}")
        header, end = block
        alias_exists = any(
            line.strip() == f"alias {alias_clean}" for line in lines[header + 1:end]
        )
        if alias_clean and not alias_exists:
            last_alias = max(
                (i for i in range(header + 1, end) if lines[i].strip().startswith("alias ")),
                default=header,
            )
            lines.insert(last_alias + 1, f"    alias {alias_clean}")
            end += 1
            changed = True
        if default_clean:
            default_re = re.compile(rf"^\s*;\s*{DEFAULT_ACCOUNT_KEY}:\s*(.*)$")
            existing = next(
                (i for i in range(header + 1, end) if default_re.match(lines[i])), None
            )
            rendered = f"    ; {DEFAULT_ACCOUNT_KEY}: {default_clean}"
            if existing is None:
                lines.insert(end, rendered)
                changed = True
            elif lines[existing] != rendered:
                lines[existing] = rendered
                changed = True

    if not changed:
        return {"name": name_clean, "created": False, "changed": False, "operationId": None}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    refresh_projection(config)

    operation_type = (
        "reference.merchant.created.v1" if created else "reference.merchant.updated.v1"
    )
    summary = f"{'Created' if created else 'Updated'} merchant: {name_clean}"
    operation_id = record_operation(
        config,
        operation_type=operation_type,
        summary=summary,
        payload={
            "name": name_clean,
            "alias": alias_clean or None,
            "default_account": default_clean or None,
        },
        files=[
            {
                "path": str(path.relative_to(config.root_dir)),
                "hash_before": hash_before,
                "hash_after": _sha256_file(path),
            }
        ],
        entities=[{"entity_type": "payee", "entity_id": name_clean, "role": "target"}],
        actor_type=actor_type,
    )
    return {
        "name": name_clean,
        "created": created,
        "changed": True,
        "operationId": operation_id,
    }
