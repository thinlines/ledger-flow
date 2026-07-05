"""Workspace-scoped, database-backed store for workflow stages.

Stages (import previews, unknowns review, rule-history reapply) are
resumable in-flight workflow state, not durable history. They live in the
``stages`` table of the workspace ``.workflow/state.db`` — resolved from the
workspace config, never a process-level root — and survive projection
rebuilds.

The payload contract matches the retired JSON file store: ``create`` injects
``stageId`` / ``createdAt`` into the payload, ``load`` returns the payload
dict unchanged. ``kind`` / ``status`` / ``summary`` are mirrored into
columns; ``base_file_hashes_json`` records the content hashes of the files
the stage was computed against. ``base_revision`` and
``applied_operation_id`` stay NULL until the operations spine (#22) defines
them.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlite3 import Connection

from .config_service import AppConfig
from .projection_db import connect, ensure_database


class StageNotFoundError(KeyError):
    """No stage row exists for the given id."""


def _file_hashes(base_files: Iterable[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in base_files:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        hashes[str(path)] = f"sha256:{digest}"
    return hashes


@dataclass(frozen=True)
class StageStore:
    config: AppConfig

    def new_stage_id(self) -> str:
        return uuid.uuid4().hex

    def _connect(self) -> Connection:
        return connect(ensure_database(self.config))

    def create(self, payload: dict, base_files: Iterable[Path] = ()) -> str:
        stage_id = self.new_stage_id()
        now = datetime.now(UTC).isoformat()
        payload["stageId"] = stage_id
        payload["createdAt"] = now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stages (
                    id, kind, status, created_at, updated_at,
                    base_file_hashes_json, summary_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stage_id,
                    payload["kind"],
                    payload.get("status", "ready"),
                    now,
                    now,
                    json.dumps(_file_hashes(base_files)),
                    json.dumps(payload.get("summary") or {}),
                    json.dumps(payload),
                ),
            )
        return stage_id

    def load(self, stage_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM stages WHERE id = ?", (stage_id,)
            ).fetchone()
        if row is None:
            raise StageNotFoundError(stage_id)
        return json.loads(row[0])

    def save(self, stage_id: str, payload: dict) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE stages
                SET kind = ?, status = ?, summary_json = ?, payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["kind"],
                    payload.get("status", "ready"),
                    json.dumps(payload.get("summary") or {}),
                    json.dumps(payload),
                    now,
                    stage_id,
                ),
            )
            if cursor.rowcount == 0:
                raise StageNotFoundError(stage_id)

    def delete(self, stage_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM stages WHERE id = ?", (stage_id,))

    def find_latest(self, predicate: Callable[[dict], bool]) -> dict | None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM stages ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        for (payload_json,) in rows:
            payload = json.loads(payload_json)
            if predicate(payload):
                return payload
        return None

    def cleanup_old(self, days: int = 7) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM stages WHERE updated_at < ?", (cutoff,)
            )
            return cursor.rowcount
