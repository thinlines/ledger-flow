"""Git-tracked text export for durable operation-class database state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .projection_db import database_path
from .config_service import AppConfig

OPERATION_DUMP_PATH = "operation-history.dump.sql"

_DURABLE_TABLES: tuple[str, ...] = (
    "operations",
    "operation_files",
    "operation_entities",
    "rules",
    "rule_condition_groups",
    "rule_conditions",
    "rule_actions",
)

_ORDER_BY: dict[str, str] = {
    "operations": "created_at, id",
    "operation_files": "operation_id, path, id",
    "operation_entities": "operation_id, entity_type, entity_id, role, id",
    "rules": "position, id",
    "rule_condition_groups": "rule_id, group_order, id",
    "rule_conditions": "group_id, condition_order, id",
    "rule_actions": "rule_id, action_order, id",
}


def export_operation_dump(workspace_path: Path) -> Path | None:
    """Export operation-class tables to stable SQL text under the workspace.

    The SQLite database itself lives under ignored ``.workflow/``. If the
    database is absent, leave any existing dump alone so a snapshot taken after
    database loss does not erase the tracked recovery artifact.
    """
    config = _config_for_workspace(workspace_path)
    db_path = database_path(config)
    if not db_path.exists():
        return None

    dump_path = workspace_path / OPERATION_DUMP_PATH
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            lines = _dump_lines(conn)
    except sqlite3.Error:
        return None
    dump_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dump_path


def check_operation_dump(workspace_path: Path) -> dict:
    """Load the tracked dump into memory and report inspectable history counts."""
    dump_path = workspace_path / OPERATION_DUMP_PATH
    if not dump_path.exists():
        return {"ok": False, "error": "operation dump not found"}

    sql = dump_path.read_text(encoding="utf-8")
    with sqlite3.connect(":memory:") as conn:
        conn.executescript(sql)
        tables = {table: _table_count(conn, table) for table in _DURABLE_TABLES}
    return {
        "ok": True,
        "operation_count": tables["operations"],
        "tables": tables,
    }


def _dump_lines(conn: sqlite3.Connection) -> list[str]:
    lines = [
        "-- Ledger Flow operation history dump",
        "-- Durable operation-class tables only; projection/workflow tables are excluded.",
        "PRAGMA foreign_keys=OFF;",
        "BEGIN TRANSACTION;",
    ]
    for table in _DURABLE_TABLES:
        create_sql = _create_sql(conn, table)
        if create_sql is None:
            continue
        lines.append("")
        lines.append(f"-- table: {table}")
        lines.append(f"DROP TABLE IF EXISTS {_ident(table)};")
        lines.append(f"{create_sql};")
        columns = _columns(conn, table)
        column_sql = ", ".join(_ident(column) for column in columns)
        for row in _rows(conn, table):
            values_sql = ", ".join(_quote(conn, row[column]) for column in columns)
            lines.append(
                f"INSERT INTO {_ident(table)} ({column_sql}) VALUES ({values_sql});"
            )
    lines.extend(["", "COMMIT;", "PRAGMA foreign_keys=ON;"])
    return lines


def _create_sql(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone()
    return str(row["sql"]) if row and row["sql"] else None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({_ident(table)})").fetchall()
    ]


def _rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    order_by = _ORDER_BY[table]
    return conn.execute(f"SELECT * FROM {_ident(table)} ORDER BY {order_by}").fetchall()


def _quote(conn: sqlite3.Connection, value: object) -> str:
    return str(conn.execute("SELECT quote(?)", (value,)).fetchone()[0])


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {_ident(table)}").fetchone()
    return int(row[0])


def _ident(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _config_for_workspace(workspace_path: Path) -> AppConfig:
    return AppConfig(
        root_dir=workspace_path,
        config_toml=workspace_path / "settings" / "workspace.toml",
        workspace={},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
        tracked_accounts={},
    )
