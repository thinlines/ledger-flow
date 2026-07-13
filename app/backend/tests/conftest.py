from pathlib import Path
import json
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_operation_events(workspace: Path) -> list[dict]:
    """Test adapter for assertions that still use the former event shape."""
    db_path = workspace / ".workflow" / "state.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        operations = conn.execute(
            """SELECT id, type, actor_type, summary, created_at,
                      compensates_operation_id, payload_json
               FROM operations ORDER BY created_at, id"""
        ).fetchall()
        files = conn.execute(
            """SELECT operation_id, path, hash_before, hash_after
               FROM operation_files ORDER BY rowid"""
        ).fetchall()
    files_by_operation: dict[str, list[dict]] = {}
    for operation_id, path, hash_before, hash_after in files:
        files_by_operation.setdefault(operation_id, []).append(
            {"path": path, "hash_before": hash_before, "hash_after": hash_after}
        )
    return [
        {
            "id": operation_id,
            "ts": created_at,
            "actor": actor,
            "type": operation_type,
            "summary": summary,
            "payload": json.loads(payload_json or "{}"),
            "journal_refs": files_by_operation.get(operation_id, []),
            "compensates": compensates,
        }
        for operation_id, operation_type, actor, summary, created_at, compensates, payload_json in operations
    ]
