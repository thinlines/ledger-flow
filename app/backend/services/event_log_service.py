"""Append-only event log with drift detection for journal mutations.

Every journal mutation emits a structured event to ``workspace/events.jsonl``.
Events are advisory — they never block or fail a mutation.  Journals remain
the canonical source of truth.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid7

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


# ---------------------------------------------------------------------------
# Backward JSONL scan for last-known hash
# ---------------------------------------------------------------------------


def read_events(workspace_path: Path) -> list[dict]:
    """Return the parsed event log as a list of dicts (oldest → newest).

    Returns an empty list when the file is missing.  Corrupt JSONL lines are
    logged and skipped — they never block readers.
    """
    events_file = workspace_path / EVENTS_FILENAME
    if not events_file.is_file():
        return []
    lines = events_file.read_text(encoding="utf-8").splitlines()
    events: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Corrupt JSONL line — skipping")
    return events


def get_last_known_hash(events_file: Path, journal_rel_path: str) -> str | None:
    """Scan *events_file* backward for the most recent ``hash_after`` for *journal_rel_path*.

    Returns ``None`` if no event references this path (file predates the log).
    """
    if not events_file.is_file():
        return None

    try:
        lines = events_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("Could not read event log %s", events_file)
        return None

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Corrupt JSONL line in %s — skipping", events_file)
            continue
        for ref in event.get("journal_refs", []):
            if ref.get("path") == journal_rel_path:
                return ref.get("hash_after")

    return None


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
    events_file = workspace_path / EVENTS_FILENAME
    journal_rel = rel_path(journal_path, workspace_path)

    expected_hash = _hash_cache.get(abs_key)
    if expected_hash is None:
        expected_hash = get_last_known_hash(events_file, journal_rel)

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
    events_file = workspace_path / EVENTS_FILENAME
    if not events_file.is_file():
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
        expected_hash = get_last_known_hash(events_file, journal_rel)

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
) -> str:
    """Append one structured event to ``workspace/events.jsonl``.

    Returns the event ``id`` (UUIDv7 string).
    """
    event_id = str(uuid7())
    event = {
        "id": event_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "type": event_type,
        "summary": summary,
        "payload": payload,
        "journal_refs": journal_refs,
        "compensates": compensates,
    }

    line = json.dumps(event, separators=(",", ":"))
    events_file = workspace_path / EVENTS_FILENAME
    with open(events_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    # Update hash cache from journal_refs.
    for ref in journal_refs:
        ref_path = ref.get("path")
        hash_after = ref.get("hash_after")
        if ref_path and hash_after:
            abs_ref = str((workspace_path / ref_path).resolve())
            _hash_cache[abs_ref] = hash_after

    return event_id
