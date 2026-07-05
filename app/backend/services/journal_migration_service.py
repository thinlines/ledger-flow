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
from uuid import uuid7

from . import journal_writer
from .config_service import AppConfig
from .projection_service import _classify_file, _discover_files, refresh_projection

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
        lines.insert(1, f"    ; lf_txn_id: txn_{uuid7().hex}{header_ending}")
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

    refresh_projection(config)

    return {
        "files_changed": sorted(changed),
        "ids_assigned": ids_assigned,
        "keys_renamed": keys_renamed,
    }
