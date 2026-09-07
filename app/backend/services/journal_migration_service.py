"""One-time journal migration to ``lf_`` house-style metadata.

Implements adoption step 4 of docs/ledger-flow-projection-schema.md: every
managed transaction block gains a stable ``lf_txn_id`` comment directly
after its header, and the schema-named app metadata keys are renamed in
place (``source_identity(_N)`` -> ``lf_source_identity(_N)``,
``reconciliation_event_id`` -> ``lf_operation_id``).

Only managed blocks are rewritten; preserved-raw blocks, directive files,
file-level comments, blank runs, and trailing-newline state are preserved
byte-for-byte. The write runs through ``journal_writer.mutate`` (backup /
verify / rollback / event), then the projection is refreshed so the
assigned ids become ``transactions.id``.

``lf_posting_id`` is deliberately not minted: no current flow needs stable
posting identity. Future key renames (import bookkeeping, merchant layer)
extend ``_KEY_RENAMES`` in the issue that owns their flow.

Idempotent: a second run finds nothing to assign or rename.
"""
from __future__ import annotations

import re

from . import journal_writer
from .account_declaration_service import set_subtype
from .config_service import AppConfig
from .journal_block_service import lf_txn_id_line, mint_lf_txn_id
from .projection_service import _classify_file, _discover_files, refresh_projection
from .reference_data_service import account_subtypes

_MIGRATED_ROLES = {"journal", "opening", "archive"}

# Schema-named keys only (issue #16: "where covered by the projection
# schema"); suffixed carried identities ride along with their family.
_RENAMABLE_KEY_RE = re.compile(
    r"^(?P<lead>\s*;\s*)(?P<key>source_identity(?:_\d+)?|reconciliation_event_id)(?P<rest>:.*)$"
)
_KEY_RENAMES = {"reconciliation_event_id": "lf_operation_id"}


def _renamed_key(key: str) -> str:
    return _KEY_RENAMES.get(key, f"lf_{key}")


def _line_ending(raw_line: str) -> str:
    if raw_line.endswith("\r\n"):
        return "\r\n"
    if raw_line.endswith("\n"):
        return "\n"
    return ""


def _migrate_block(raw_text: str, has_txn_id: bool) -> tuple[str, int, int]:
    """Rewrite one managed transaction block. Returns (text, ids, renames)."""
    lines = raw_text.splitlines(keepends=True)
    renames = 0
    for index, line in enumerate(lines[1:], start=1):
        ending = _line_ending(line)
        content = line[: len(line) - len(ending)] if ending else line
        match = _RENAMABLE_KEY_RE.match(content)
        if match is None:
            continue
        lines[index] = (
            f"{match.group('lead')}{_renamed_key(match.group('key'))}{match.group('rest')}{ending}"
        )
        renames += 1

    ids_assigned = 0
    if not has_txn_id:
        header_ending = _line_ending(lines[0]) or "\n"
        lines.insert(1, f"{lf_txn_id_line(mint_lf_txn_id())}{header_ending}")
        ids_assigned = 1

    return "".join(lines), ids_assigned, renames


def migrate_lf_metadata(config: AppConfig) -> dict:
    """Assign missing ``lf_txn_id`` metadata and rename schema-named keys.

    Returns a JSON-friendly report:
    ``{"files_changed": [...], "ids_assigned": N, "keys_renamed": N}``.
    """
    discovered = _discover_files(config)

    changed: dict[str, str] = {}
    ids_assigned = 0
    keys_renamed = 0

    for rel, info in sorted(discovered.items()):
        if info["role"] not in _MIGRATED_ROLES:
            continue
        pieces: list[str] = []
        file_changed = False
        for item in _classify_file(info["text"]):
            if item.item_type != "transaction" or item.parse_status != "managed":
                pieces.append(item.raw_text)
                continue
            assert item.block is not None
            new_text, ids, renames = _migrate_block(
                item.raw_text, has_txn_id=item.block.lf_txn_id is not None
            )
            pieces.append(new_text)
            if new_text != item.raw_text:
                file_changed = True
                ids_assigned += ids
                keys_renamed += renames
        if file_changed:
            changed[rel] = "".join(pieces)

    if changed:
        paths = [config.root_dir / rel for rel in sorted(changed)]
        with journal_writer.mutate(
            config=config,
            paths=paths,
            tag="lf-migration",
            event_type="journal.lf_metadata_migrated.v1",
        ) as mut:
            for rel, text in changed.items():
                (config.root_dir / rel).write_text(text, encoding="utf-8")
            mut.summary = (
                f"Migrated journal metadata to lf_ house style "
                f"({ids_assigned} ids assigned, {keys_renamed} keys renamed)"
            )
            mut.payload = {
                "files_changed": sorted(changed),
                "ids_assigned": ids_assigned,
                "keys_renamed": keys_renamed,
            }
    else:
        # Nothing to write — still self-heal so assigned ids are adopted
        # even when a previous run was interrupted between write and refresh.
        refresh_projection(config)

    subtypes_adopted = _adopt_config_subtypes(config)

    return {
        "files_changed": sorted(changed),
        "ids_assigned": ids_assigned,
        "keys_renamed": keys_renamed,
        "subtypes_adopted": subtypes_adopted,
    }


def _adopt_config_subtypes(config: AppConfig) -> int:
    """Copy legacy config.toml subtypes into ``lf_subtype`` declaration
    metadata (issue #19: subtype is declaration-canonical).

    A declaration that already carries ``lf_subtype`` wins — the migration
    never overwrites it. Idempotent: adopted values project back, so the
    second run finds nothing to copy. Stale ``subtype =`` keys left in
    config.toml are inert (nothing reads them) and drop off on the next
    config write."""
    config_subtypes: dict[str, str] = {}
    for account_cfg in (
        *config.tracked_accounts.values(),
        *config.import_accounts.values(),
    ):
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        subtype = str(account_cfg.get("subtype") or "").strip()
        if ledger_account and subtype:
            config_subtypes.setdefault(ledger_account, subtype)

    if not config_subtypes:
        return 0

    declared = account_subtypes(config)
    adopted = 0
    for ledger_account, subtype in sorted(config_subtypes.items()):
        if ledger_account in declared:
            continue
        set_subtype(config, ledger_account, subtype)
        adopted += 1
    return adopted


# ---------------------------------------------------------------------------
# Source identity regeneration (issue #007, seam 2)
# ---------------------------------------------------------------------------

_IDENTITY_LINE_RE = re.compile(
    r"^(?P<lead>\s*;\s*lf_source_identity:\s*)(?P<value>\S+)(?P<trail>\s*)$"
)


def _block_metadata_and_postings(raw_text: str) -> tuple[dict[str, str], list[dict]]:
    """Metadata and postings of one written block, in identity terms."""
    from .journal_query_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE, META_RE

    metadata: dict[str, str] = {}
    postings: list[dict] = []
    for line in raw_text.splitlines()[1:]:
        meta_match = META_RE.match(line)
        if meta_match:
            metadata[meta_match.group(1).strip().lower()] = meta_match.group(2).strip()
            continue
        if not line.strip() or line.strip().startswith(";"):
            continue
        account_match = ACCOUNT_LINE_RE.match(line)
        if account_match:
            postings.append(
                {"account": account_match.group(2).strip(), "amount": account_match.group(4).strip()}
            )
            continue
        bare_match = ACCOUNT_ONLY_RE.match(line)
        if bare_match:
            postings.append({"account": bare_match.group(2).strip(), "amount": ""})
    return metadata, postings


def _institution_account(config: AppConfig, import_account_id: str) -> str:
    account = config.import_account(import_account_id) or config.account(import_account_id)
    return account.ledger_account if account else ""


def _rewrite_identity_line(raw_text: str, new_value: str) -> str:
    """Replace the block's ``lf_source_identity`` value, preserving every byte
    around it — indentation, spacing, and line ending."""
    lines = raw_text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        ending = _line_ending(line)
        content = line[: len(line) - len(ending)] if ending else line
        match = _IDENTITY_LINE_RE.match(content)
        if match is None:
            continue
        lines[index] = f"{match.group('lead')}{new_value}{match.group('trail')}{ending}"
        break
    return "".join(lines)


def migrate_source_identities(config: AppConfig, *, dry_run: bool = False) -> dict:
    """Recompute every stored ``lf_source_identity`` under the current rules.

    Identities written before the amount fix were derived from bases that
    omitted or inconsistently rendered the amount, so some cannot be reproduced
    by current code at all — meaning a re-import would not recognise those rows
    and would write them a second time. Recomputing them from each block's own
    ``; CSV:`` provenance puts every row on one generation.

    Blocks that cannot be recomputed are left untouched and reported rather
    than guessed at: a block with no provenance row, or whose postings no longer
    include its import account, needs a human decision.

    Returns a report: ``rewritten`` / ``unchanged`` counts, ``skipped`` entries
    with reasons, and ``collisions`` — sets of blocks that resolve to one
    identity, which are genuine same-row duplicates needing triage.
    """
    from . import source_identity

    discovered = _discover_files(config)

    changed: dict[str, str] = {}
    identity_map: dict[str, str] = {}
    rewritten = unchanged = 0
    skipped: list[dict] = []
    by_new_identity: dict[str, list[dict]] = {}

    for rel, info in sorted(discovered.items()):
        if info["role"] not in _MIGRATED_ROLES:
            continue
        pieces: list[str] = []
        file_changed = False
        for item in _classify_file(info["text"]):
            if item.item_type != "transaction" or item.parse_status != "managed":
                pieces.append(item.raw_text)
                continue

            metadata, postings = _block_metadata_and_postings(item.raw_text)
            stored = metadata.get(source_identity.IDENTITY_KEY)
            if not stored:
                pieces.append(item.raw_text)
                continue

            institution = _institution_account(
                config, str(metadata.get("import_account_id") or "")
            )
            try:
                identity = source_identity.of_journal_block(
                    metadata=metadata, postings=postings, institution_account=institution
                )
            except source_identity.IdentityInputError as exc:
                skipped.append({
                    "journal": rel,
                    "line": item.start_line,
                    "header": item.raw_text.splitlines()[0].strip(),
                    "storedIdentity": stored,
                    "reason": str(exc),
                })
                pieces.append(item.raw_text)
                continue

            by_new_identity.setdefault(identity, []).append({
                "journal": rel,
                "line": item.start_line,
                "header": item.raw_text.splitlines()[0].strip(),
            })

            if identity == stored:
                unchanged += 1
                pieces.append(item.raw_text)
                continue

            identity_map[stored] = identity
            new_text = _rewrite_identity_line(item.raw_text, identity)
            pieces.append(new_text)
            if new_text != item.raw_text:
                file_changed = True
                rewritten += 1

        if file_changed:
            changed[rel] = "".join(pieces)

    collisions = [
        {"identity": value, "blocks": blocks}
        for value, blocks in sorted(by_new_identity.items())
        if len(blocks) > 1
    ]

    report = {
        "files_changed": sorted(changed),
        "rewritten": rewritten,
        "unchanged": unchanged,
        "skipped": skipped,
        "collisions": collisions,
        "dry_run": dry_run,
    }
    if dry_run or not changed:
        return report

    paths = [config.root_dir / rel for rel in sorted(changed)]
    with journal_writer.mutate(
        config=config,
        paths=paths,
        tag="identity-migration",
        event_type="journal.source_identities_migrated.v1",
    ) as mut:
        for rel, text in changed.items():
            (config.root_dir / rel).write_text(text, encoding="utf-8")
        mut.summary = (
            f"Recomputed {rewritten} source identities under the current rules"
        )
        mut.payload = {
            "files_changed": sorted(changed),
            "rewritten": rewritten,
            "skipped": len(skipped),
            "collisions": len(collisions),
        }

    report["identities_relinked"] = _relink_import_identities(config, identity_map)
    return report


def _relink_import_identities(config: AppConfig, identity_map: dict[str, str]) -> dict:
    """Move ``import_identities`` rows onto the recomputed identities.

    The table is keyed ``(import_account_id, source_identity)``; a rename that
    would collide with a row already holding the new value is left alone and
    reported, because merging two dedupe records is a decision, not a rename.
    """
    import sqlite3

    from .projection_db import connect, database_path, ensure_database

    if not identity_map:
        return {"updated": 0, "conflicts": []}

    ensure_database(config.root_dir)
    updated = 0
    conflicts: list[str] = []
    with connect(database_path(config.root_dir)) as conn:
        for old_value, new_value in sorted(identity_map.items()):
            try:
                cursor = conn.execute(
                    "UPDATE import_identities SET source_identity = ? WHERE source_identity = ?",
                    (new_value, old_value),
                )
                updated += cursor.rowcount
            except sqlite3.IntegrityError:
                conflicts.append(old_value)
    return {"updated": updated, "conflicts": conflicts}
