"""Operation-backed event compatibility helpers.

Journal mutations record durable operations. This module keeps the old
event-shaped helper API (file hashing, workspace-relative paths, event
emission) for legacy callers without writing ``events.jsonl`` for new
history.

The journal files are the source of truth: external edits are absorbed by
re-projection, not detected or logged. Per-block staleness (HTTP 409) and
the undo drift refusal are the only write guards, and they live with the
write paths, not here.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid7

from .config_service import AppConfig
from .operations_service import record_operation

logger = logging.getLogger(__name__)

EVENTS_FILENAME = "events.jsonl"


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
    return event_id
