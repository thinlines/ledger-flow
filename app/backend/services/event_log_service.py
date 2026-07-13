"""Operation-backed event compatibility helpers.

Journal mutations now record durable operations. This module keeps the old
event-shaped helper API for drift detection and legacy callers without writing
``events.jsonl`` for new history.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid7

from .config_service import AppConfig
from .operations_service import record_operation

logger = logging.getLogger(__name__)

EVENTS_FILENAME = "events.jsonl"

# Module-level hash cache: absolute-path-string → last-known SHA-256 hash.
# Populated by startup drift check and updated after each event emission.
_hash_cache: dict[str, str] = {}


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------


def hash_file(path: Path) -> str:
    """Return ``sha256:<hexdigest>`` for *path*, or ``sha256:none`` if missing."""
    try:
        data = path.read_bytes()
    except (FileNotFoundError, OSError):
        return "sha256:none"
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Relative-path helper
# ---------------------------------------------------------------------------


def rel_path(file_path: Path, workspace_root: Path) -> str:
    """Return *file_path* relative to *workspace_root*, or absolute as fallback."""
    try:
        return str(file_path.resolve().relative_to(workspace_root.resolve()))
    except ValueError:
        logger.warning("Path %s is outside workspace %s", file_path, workspace_root)
        return str(file_path)


def get_last_known_hash(workspace_path: Path, journal_rel_path: str) -> str | None:
    """Return the latest operation-backed hash for a journal path."""
    db_path = workspace_path / ".workflow" / "state.db"
    if not db_path.is_file():
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT operation_files.hash_after
                FROM operation_files
                JOIN operations ON operations.id = operation_files.operation_id
                WHERE operation_files.path = ?
                ORDER BY operations.created_at DESC, operations.id DESC
                LIMIT 1
                """,
                (journal_rel_path,),
            ).fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row else None


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def check_drift(workspace_path: Path, journal_path: Path) -> str:
    """Pre-mutation drift check for a single journal file.

    Returns the current hash (to be used as ``hash_before`` in the mutation event).
    Emits a ``journal.external_edit_detected.v1`` event if drift is detected.
    Updates ``_hash_cache`` regardless of drift.
    """
    current_hash = hash_file(journal_path)
    abs_key = str(journal_path.resolve())
    journal_rel = rel_path(journal_path, workspace_path)

    expected_hash = _hash_cache.get(abs_key)
    if expected_hash is None:
        expected_hash = get_last_known_hash(workspace_path, journal_rel)

    if expected_hash is not None and current_hash != expected_hash:
        try:
            emit_event(
                workspace_path,
                event_type="journal.external_edit_detected.v1",
                summary=f"External edit detected on {journal_rel}",
                payload={
                    "journal_path": journal_rel,
                    "expected_hash": expected_hash,
                    "actual_hash": current_hash,
                    "trigger": "pre_mutation",
                },
                journal_refs=[],
                actor="system",
            )
        except Exception:
            logger.error("Failed to emit drift event for %s", journal_path, exc_info=True)

    _hash_cache[abs_key] = current_hash
    return current_hash


def check_startup_drift(workspace_path: Path) -> None:
    """Startup drift check — compare all journal files against the event log.

    Populates ``_hash_cache`` for all discovered journals.
    """
    db_path = workspace_path / ".workflow" / "state.db"
    if not db_path.is_file():
        # No baseline — populate cache only, skip drift checks.
        journal_dir = workspace_path / "journals"
        if journal_dir.is_dir():
            for jf in journal_dir.glob("*.journal"):
                _hash_cache[str(jf.resolve())] = hash_file(jf)
        return

    journal_dir = workspace_path / "journals"
    if not journal_dir.is_dir():
        return

    journal_files = list(journal_dir.glob("*.journal"))

    for jf in journal_files:
        current_hash = hash_file(jf)
        abs_key = str(jf.resolve())
        journal_rel = rel_path(jf, workspace_path)
        expected_hash = get_last_known_hash(workspace_path, journal_rel)

        if expected_hash is not None and current_hash != expected_hash:
            try:
                emit_event(
                    workspace_path,
                    event_type="journal.external_edit_detected.v1",
                    summary=f"External edit detected on {journal_rel} at startup",
                    payload={
                        "journal_path": journal_rel,
                        "expected_hash": expected_hash,
                        "actual_hash": current_hash,
                        "trigger": "startup",
                    },
                    journal_refs=[],
                    actor="system",
                )
            except Exception:
                logger.error("Failed to emit startup drift event for %s", jf, exc_info=True)

        _hash_cache[abs_key] = current_hash


# ---------------------------------------------------------------------------
# Event writer
# ---------------------------------------------------------------------------


def emit_event(
    workspace_path: Path,
    *,
    event_type: str,
    summary: str,
    payload: dict,
    journal_refs: list[dict],
    actor: str = "user",
    compensates: str | None = None,
    event_id: str | None = None,
) -> str:
    """Record one event-shaped operation.

    Returns the event ``id`` (UUIDv7 string). When *event_id* is supplied the
    caller's id is used verbatim instead of generating a new one — this is how
    callers that need to write the same id into journal metadata before the
    event is emitted (e.g. reconciliation) keep the two references in sync.
    """
    if event_id is None:
        event_id = str(uuid7())
    timestamp = datetime.now(timezone.utc).isoformat()
    config = AppConfig(
        root_dir=workspace_path,
        config_toml=workspace_path / "settings" / "workspace.toml",
        workspace={},
        dirs={
            "csv_dir": "csv",
            "journal_dir": "journals",
            "init_dir": "init",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
    )
    record_operation(
        config,
        operation_id=event_id,
        operation_type=event_type,
        summary=summary,
        payload=payload,
        files=journal_refs,
        actor_type=actor,
        compensates_operation_id=compensates,
        created_at=timestamp,
        applied_at=timestamp,
    )
    # Update hash cache from journal_refs.
    for ref in journal_refs:
        ref_path = ref.get("path")
        hash_after = ref.get("hash_after")
        if ref_path and hash_after:
            abs_ref = str((workspace_path / ref_path).resolve())
            _hash_cache[abs_ref] = hash_after

    return event_id
