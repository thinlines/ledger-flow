"""DB-backed stage store: workflow stages live in the SQLite ``stages`` table.

Stages are resumable workflow state, not durable history — the store keeps
the old JSON store's payload contract (``load`` returns the same dict shape,
``stageId`` / ``createdAt`` injected on create) while mirroring kind, status,
summary, and base file hashes into columns. No JSON files are written.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from services.config_service import AppConfig
from services.projection_db import database_path
from services.stage_store import StageNotFoundError, StageStore


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


def _stage_row(config: AppConfig, stage_id: str) -> tuple:
    with sqlite3.connect(database_path(config)) as conn:
        return conn.execute(
            """
            SELECT kind, status, summary_json, base_file_hashes_json, payload_json,
                   created_at, updated_at, base_revision, applied_operation_id
            FROM stages WHERE id = ?
            """,
            (stage_id,),
        ).fetchone()


def test_create_injects_identity_and_mirrors_columns(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    payload = {"kind": "unknowns", "status": "ready", "summary": {"groupCount": 2}}

    stage_id = store.create(payload)

    assert payload["stageId"] == stage_id
    assert payload["createdAt"]
    kind, status, summary_json, _hashes, payload_json, created_at, updated_at, base_revision, applied_op = _stage_row(config, stage_id)
    assert kind == "unknowns"
    assert status == "ready"
    assert json.loads(summary_json) == {"groupCount": 2}
    assert json.loads(payload_json) == payload
    assert created_at == payload["createdAt"]
    assert updated_at == created_at
    assert base_revision is None
    assert applied_op is None


def test_create_records_base_file_hashes(tmp_path):
    config = _make_config(tmp_path)
    journal = config.root_dir / "journals" / "2026.journal"
    journal.write_text("2026/01/01 Payee\n", encoding="utf-8")
    store = StageStore(config)

    stage_id = store.create({"kind": "import", "status": "ready"}, base_files=[journal])

    _, _, _, hashes_json, *_ = _stage_row(config, stage_id)
    hashes = json.loads(hashes_json)
    assert set(hashes) == {str(journal)}
    assert hashes[str(journal)].startswith("sha256:")

    # Same content elsewhere hashes identically (content, not path, is hashed).
    twin = config.root_dir / "journals" / "twin.journal"
    twin.write_text("2026/01/01 Payee\n", encoding="utf-8")
    twin_id = store.create({"kind": "import", "status": "ready"}, base_files=[twin])
    _, _, _, twin_hashes_json, *_ = _stage_row(config, twin_id)
    assert json.loads(twin_hashes_json)[str(twin)] == hashes[str(journal)]


def test_load_round_trips_payload(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    payload = {
        "kind": "import",
        "status": "ready",
        "summary": {"count": 3},
        "preview": [{"payee": "Coffee"}],
    }
    stage_id = store.create(payload)

    assert store.load(stage_id) == payload


def test_load_missing_stage_raises(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    with pytest.raises(StageNotFoundError):
        store.load("nope")


def test_save_updates_payload_and_mirrors(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    payload = {"kind": "unknowns", "status": "ready", "summary": {"txnUpdates": 0}}
    stage_id = store.create(payload)

    payload["status"] = "applied"
    payload["summary"] = {"txnUpdates": 4}
    payload["result"] = {"applied": True}
    store.save(stage_id, payload)

    kind, status, summary_json, _hashes, payload_json, created_at, updated_at, *_ = _stage_row(config, stage_id)
    assert kind == "unknowns"
    assert status == "applied"
    assert json.loads(summary_json) == {"txnUpdates": 4}
    assert json.loads(payload_json)["result"] == {"applied": True}
    assert updated_at >= created_at
    assert store.load(stage_id) == payload


def test_save_missing_stage_raises(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    with pytest.raises(StageNotFoundError):
        store.save("nope", {"kind": "unknowns", "status": "ready"})


def test_delete_removes_row_and_is_idempotent(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    stage_id = store.create({"kind": "unknowns", "status": "ready"})

    store.delete(stage_id)
    with pytest.raises(StageNotFoundError):
        store.load(stage_id)
    store.delete(stage_id)  # no error


def test_find_latest_returns_most_recently_updated_match(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    first = store.create({"kind": "unknowns", "status": "ready", "journalPath": "/a"})
    second = store.create({"kind": "unknowns", "status": "ready", "journalPath": "/a"})
    store.create({"kind": "import", "status": "ready", "journalPath": "/a"})

    found = store.find_latest(lambda p: p.get("kind") == "unknowns")
    assert found is not None
    assert found["stageId"] == second

    # Saving the older stage makes it the most recently updated.
    older = store.load(first)
    older["selections"] = {"t1": {"groupKey": "g"}}
    store.save(first, older)
    found = store.find_latest(lambda p: p.get("kind") == "unknowns")
    assert found is not None
    assert found["stageId"] == first

    assert store.find_latest(lambda p: p.get("kind") == "rule_history") is None


def test_cleanup_old_deletes_only_stale_rows(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    old_id = store.create({"kind": "unknowns", "status": "ready"})
    fresh_id = store.create({"kind": "unknowns", "status": "ready"})

    with sqlite3.connect(database_path(config)) as conn:
        conn.execute(
            "UPDATE stages SET updated_at = '2026-01-01T00:00:00+00:00' WHERE id = ?",
            (old_id,),
        )

    removed = store.cleanup_old(days=7)

    assert removed == 1
    with pytest.raises(StageNotFoundError):
        store.load(old_id)
    assert store.load(fresh_id)["stageId"] == fresh_id


def test_no_json_stage_files_are_written(tmp_path):
    config = _make_config(tmp_path)
    store = StageStore(config)
    stage_id = store.create({"kind": "import", "status": "ready"})
    payload = store.load(stage_id)
    payload["status"] = "applied"
    store.save(stage_id, payload)

    assert not (config.root_dir / ".workflow" / "stages").exists()
    assert list(config.root_dir.rglob("*.json")) == []
