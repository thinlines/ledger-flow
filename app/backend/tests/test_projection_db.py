"""Slice 1: workspace-scoped SQLite created from migrations.

The projection database lives in the same ``.workflow/state.db`` file the
import index already uses, resolved from the workspace config's root — never
from a process-level root. Migrations are versioned, idempotent, and the
projection tables are safe to wipe and rebuild.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from services.config_service import AppConfig
from services.projection_db import (
    PROJECTION_TABLES,
    connect,
    ensure_database,
)


PROJECTION_TABLE_NAMES = {
    "journal_files",
    "journal_items",
    "transactions",
    "postings",
    "comments",
    "metadata_entries",
    "journal_diagnostics",
    "accounts",
    "payees",
    "payee_aliases",
    "tags",
    "commodities",
}


def _make_config(workspace: Path) -> AppConfig:
    for name in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / name).mkdir(parents=True, exist_ok=True)
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "base_currency": "USD", "start_year": 2026},
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


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {name for (name,) in rows}


def test_ensure_database_creates_workspace_scoped_db(tmp_path):
    config = _make_config(tmp_path)

    db_path = ensure_database(config)

    assert db_path == tmp_path / ".workflow" / "state.db"
    assert db_path.exists()
    tables = _table_names(db_path)
    assert "schema_migrations" in tables
    assert PROJECTION_TABLE_NAMES <= tables


def test_projection_tables_constant_matches_created_tables(tmp_path):
    config = _make_config(tmp_path)
    ensure_database(config)
    assert set(PROJECTION_TABLES) == PROJECTION_TABLE_NAMES


def test_ensure_database_is_idempotent_and_records_versions_once(tmp_path):
    config = _make_config(tmp_path)

    db_path = ensure_database(config)
    with sqlite3.connect(db_path) as conn:
        first = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()

    ensure_database(config)
    with sqlite3.connect(db_path) as conn:
        second = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert first == second
    assert len(first) >= 1
    versions = [version for version, _ in first]
    assert versions == sorted(set(versions))


def test_projection_tables_are_wipe_and_rebuild_safe(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO journal_files (id, path, role, content_hash, parsed_at)
            VALUES ('jf1', 'journals/2026.journal', 'journal', 'sha256:x', '2026-07-04T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO transactions (
                id, journal_file_id, txn_order, date, payee,
                raw_header, raw_block_hash, source_start_line, source_end_line
            ) VALUES ('t1', 'jf1', 0, '2026-01-01', 'Payee', 'h', 'sha256:y', 1, 2)
            """
        )
        for table in PROJECTION_TABLES:
            conn.execute(f"DELETE FROM {table}")

    ensure_database(config)
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM journal_files").fetchone()[0]
    assert count == 0


def test_rules_tables_survive_projection_wipe(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO rules (id, type, name, enabled, position, created_at, updated_at)
            VALUES ('r1', 'match', 'Coffee', 1, 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """
        )
        for table in PROJECTION_TABLES:
            conn.execute(f"DELETE FROM {table}")

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
    assert count == 1


def test_reference_tables_enforce_entity_uniqueness(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO accounts (id, name, account_type) VALUES ('a1', 'Assets:Checking', 'assets')"
        )
        try:
            conn.execute(
                "INSERT INTO accounts (id, name, account_type) VALUES ('a2', 'Assets:Checking', 'assets')"
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("expected IntegrityError for duplicate account name")


def test_payee_aliases_cascade_with_their_payee(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        conn.execute("INSERT INTO payees (id, name) VALUES ('p1', 'Walmart')")
        conn.execute(
            """
            INSERT INTO payee_aliases (id, payee_id, pattern, alias_order)
            VALUES ('pa1', 'p1', 'WAL-?MART', 0)
            """
        )
        conn.execute("DELETE FROM payees WHERE id = 'p1'")
        remaining = conn.execute("SELECT COUNT(*) FROM payee_aliases").fetchone()[0]
    assert remaining == 0


def test_stages_and_operations_tables_created(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    tables = _table_names(db_path)
    assert "stages" in tables
    assert "operations" in tables

    with sqlite3.connect(db_path) as conn:
        columns = {
            name
            for (_, name, *_rest) in conn.execute("PRAGMA table_info(stages)").fetchall()
        }
    assert columns == {
        "id",
        "kind",
        "status",
        "created_at",
        "updated_at",
        "base_revision",
        "base_file_hashes_json",
        "summary_json",
        "payload_json",
        "applied_operation_id",
    }


def test_import_identity_tables_created(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    tables = _table_names(db_path)
    assert "import_sources" in tables
    assert "import_identities" in tables

    with sqlite3.connect(db_path) as conn:
        identity_columns = {
            name
            for (_, name, *_rest) in conn.execute("PRAGMA table_info(import_identities)").fetchall()
        }
        conn.execute(
            """
            INSERT INTO import_identities (
                id, import_account_id, source_identity, source_payload_hash,
                first_seen_at, last_seen_at, current_status
            ) VALUES (
                'ii1', 'checking', 'source-1', 'payload-1',
                '2026-07-05T00:00:00Z', '2026-07-05T00:00:00Z', 'active'
            )
            """
        )
        try:
            conn.execute(
                """
                INSERT INTO import_identities (
                    id, import_account_id, source_identity,
                    first_seen_at, last_seen_at, current_status
                ) VALUES (
                    'ii2', 'checking', 'source-2',
                    '2026-07-05T00:00:00Z', '2026-07-05T00:00:00Z', 'bogus'
                )
                """
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("expected IntegrityError for unknown import identity status")

    assert identity_columns == {
        "id",
        "import_account_id",
        "source_identity",
        "source_payload_hash",
        "transaction_id",
        "import_source_id",
        "first_seen_at",
        "last_seen_at",
        "current_status",
    }


def test_import_identities_survive_projection_wipe(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO import_identities (
                id, import_account_id, source_identity,
                first_seen_at, last_seen_at
            ) VALUES (
                'ii1', 'checking', 'source-1',
                '2026-07-05T00:00:00Z', '2026-07-05T00:00:00Z'
            )
            """
        )
        assert "import_identities" not in PROJECTION_TABLES
        for table in PROJECTION_TABLES:
            conn.execute(f"DELETE FROM {table}")

    ensure_database(config)
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM import_identities").fetchone()[0]
    assert count == 1


def test_stages_survive_projection_wipe(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO stages (id, kind, status, created_at, updated_at, payload_json)
            VALUES ('s1', 'import', 'ready', '2026-07-04T00:00:00Z', '2026-07-04T00:00:00Z', '{}')
            """
        )
        assert "stages" not in PROJECTION_TABLES
        for table in PROJECTION_TABLES:
            conn.execute(f"DELETE FROM {table}")

    ensure_database(config)
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM stages").fetchone()[0]
    assert count == 1


def test_stages_applied_operation_id_foreign_key(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        # NULL linkage is the pre-#22 steady state.
        conn.execute(
            """
            INSERT INTO stages (id, kind, status, created_at, updated_at, payload_json)
            VALUES ('s1', 'import', 'ready', '2026-07-04T00:00:00Z', '2026-07-04T00:00:00Z', '{}')
            """
        )
        try:
            conn.execute(
                """
                INSERT INTO stages (id, kind, status, created_at, updated_at, payload_json, applied_operation_id)
                VALUES ('s2', 'import', 'applied', '2026-07-04T00:00:00Z', '2026-07-04T00:00:00Z', '{}', 'no-such-op')
                """
            )
        except sqlite3.IntegrityError:
            return
    raise AssertionError("expected IntegrityError for orphan applied_operation_id")


def test_stages_status_check_rejects_unknown_values(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO stages (id, kind, status, created_at, updated_at, payload_json)
                VALUES ('s1', 'import', 'bogus', '2026-07-04T00:00:00Z', '2026-07-04T00:00:00Z', '{}')
                """
            )
        except sqlite3.IntegrityError:
            return
    raise AssertionError("expected IntegrityError for unknown stage status")


def test_foreign_keys_enforced_on_connect(tmp_path):
    config = _make_config(tmp_path)
    db_path = ensure_database(config)

    with connect(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO transactions (
                    id, journal_file_id, txn_order, date, payee,
                    raw_header, raw_block_hash, source_start_line, source_end_line
                ) VALUES ('t1', 'missing-file', 0, '2026-01-01', 'P', 'h', 'sha', 1, 1)
                """
            )
        except sqlite3.IntegrityError:
            return
    raise AssertionError("expected IntegrityError for orphan journal_file_id")
