from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from .config_service import AppConfig
from .projection_db import connect, ensure_database


def _json_dumps(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_operation(
    config: AppConfig,
    *,
    operation_type: str,
    summary: str,
    payload: dict,
    files: list[dict],
    entities: list[dict] | None = None,
    operation_id: str | None = None,
    actor_type: str = "user",
    status: str = "applied",
    undo_mode: str = "semantic",
    compensates_operation_id: str | None = None,
    created_at: str | None = None,
    applied_at: str | None = None,
) -> str:
    """Persist a durable operation and its affected files/entities."""
    op_id = operation_id or uuid4().hex
    timestamp = created_at or _now()
    db_path = ensure_database(config)
    with connect(db_path) as conn:
        if compensates_operation_id is not None:
            exists = conn.execute(
                "SELECT 1 FROM operations WHERE id = ?",
                (compensates_operation_id,),
            ).fetchone()
            if exists is None:
                conn.execute(
                    """
                    INSERT INTO operations (
                        id, type, actor_type, status, summary, created_at,
                        applied_at, undo_mode, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        compensates_operation_id,
                        "legacy.event.v1",
                        "user",
                        "applied",
                        "Legacy event",
                        timestamp,
                        timestamp,
                        "semantic",
                        "{}",
                    ),
                )
        conn.execute(
            """
            INSERT INTO operations (
                id, type, actor_type, status, summary, created_at, applied_at,
                undo_mode, compensates_operation_id, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                op_id,
                operation_type,
                actor_type,
                status,
                summary,
                timestamp,
                applied_at or timestamp,
                undo_mode,
                compensates_operation_id,
                _json_dumps(payload),
            ),
        )
        for file_ref in files:
            conn.execute(
                """
                INSERT INTO operation_files (
                    id, operation_id, path, hash_before, hash_after
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    op_id,
                    str(file_ref.get("path") or ""),
                    str(file_ref.get("hash_before") or ""),
                    str(file_ref.get("hash_after") or ""),
                ),
            )
        for entity in entities or []:
            conn.execute(
                """
                INSERT INTO operation_entities (
                    id, operation_id, entity_type, entity_id, role, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    op_id,
                    str(entity.get("entity_type") or ""),
                    str(entity.get("entity_id") or ""),
                    str(entity.get("role") or "affected"),
                    _json_dumps(dict(entity.get("payload") or {})),
                ),
            )
    return op_id


def list_operations(config: AppConfig, *, limit: int | None = None) -> list[dict]:
    db_path = ensure_database(config)
    sql = """
        SELECT id, type, actor_type, status, summary, created_at, applied_at,
               undo_mode, compensates_operation_id, payload_json
        FROM operations
        ORDER BY created_at DESC, id DESC
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)

    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        files_by_op: dict[str, list[dict]] = {row[0]: [] for row in rows}
        if files_by_op:
            placeholders = ",".join("?" for _ in files_by_op)
            for op_id, path, hash_before, hash_after in conn.execute(
                f"""
                SELECT operation_id, path, hash_before, hash_after
                FROM operation_files
                WHERE operation_id IN ({placeholders})
                ORDER BY rowid
                """,
                tuple(files_by_op),
            ).fetchall():
                files_by_op[op_id].append(
                    {
                        "path": path,
                        "hash_before": hash_before,
                        "hash_after": hash_after,
                    }
                )

    operations: list[dict] = []
    for row in rows:
        (
            op_id,
            op_type,
            actor_type,
            status,
            summary,
            created_at,
            applied_at,
            undo_mode,
            compensates_operation_id,
            payload_json,
        ) = row
        operations.append(
            {
                "id": op_id,
                "type": op_type,
                "actor": actor_type,
                "status": status,
                "summary": summary,
                "ts": created_at,
                "applied_at": applied_at,
                "undo_mode": undo_mode,
                "compensates": compensates_operation_id,
                "payload": json.loads(payload_json or "{}"),
                "files": files_by_op.get(op_id, []),
            }
        )
    return operations


def get_operation(config: AppConfig, operation_id: str) -> dict | None:
    return next(
        (operation for operation in list_operations(config) if operation["id"] == operation_id),
        None,
    )


def operation_is_compensated(config: AppConfig, operation_id: str) -> str | None:
    db_path = ensure_database(config)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id FROM operations
            WHERE compensates_operation_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (operation_id,),
        ).fetchone()
    return str(row[0]) if row else None


def list_legacy_event_operations(config: AppConfig) -> list[dict]:
    """Compatibility adapter for legacy JSONL consumers."""
    return list(reversed(list_operations(config)))
