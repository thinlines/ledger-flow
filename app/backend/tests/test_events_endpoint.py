"""Tests for the GET /api/events listing endpoint."""

from __future__ import annotations

from pathlib import Path

import main
from services.config_service import AppConfig
from services.event_log_service import emit_event


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "rules", "opening", "imports", "inbox"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "start_year": 2026, "base_currency": "USD"},
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
        payee_aliases="payee_aliases.csv",
    )


def test_returns_empty_list_when_log_missing(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    result = main.events_recent()
    assert result == {"events": []}


def test_returns_events_newest_first_with_undoable_flag(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    # Two forward events: one undoable, one not.
    deletable_id = emit_event(
        config.root_dir,
        event_type="transaction.deleted.v1",
        summary="Removed Coffee Shop",
        payload={"journal_path": "journals/2026.journal", "header_line": "x", "deleted_block": "y"},
        journal_refs=[],
    )
    import_id = emit_event(
        config.root_dir,
        event_type="import.applied.v1",  # No handler — should report undoable=False.
        summary="Imported statement",
        payload={},
        journal_refs=[],
    )

    result = main.events_recent()
    rows = result["events"]
    assert [r["id"] for r in rows] == [import_id, deletable_id]  # newest first

    by_id = {r["id"]: r for r in rows}
    assert by_id[deletable_id]["undoable"] is True
    assert by_id[deletable_id]["compensated"] is False
    assert by_id[deletable_id]["compensatedBy"] is None
    assert by_id[deletable_id]["type"] == "transaction.deleted.v1"
    assert by_id[deletable_id]["summary"] == "Removed Coffee Shop"
    assert by_id[deletable_id]["timestamp"]  # ISO string non-empty.

    assert by_id[import_id]["undoable"] is False


def test_compensated_flag_resolves_via_compensates_link(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    forward_id = emit_event(
        config.root_dir,
        event_type="transaction.deleted.v1",
        summary="Removed Coffee Shop",
        payload={},
        journal_refs=[],
    )
    comp_id = emit_event(
        config.root_dir,
        event_type="transaction.deleted.v1.compensated.v1",
        summary="Undid: Removed Coffee Shop",
        payload={},
        journal_refs=[],
        compensates=forward_id,
    )

    result = main.events_recent()
    by_id = {r["id"]: r for r in result["events"]}

    assert by_id[forward_id]["compensated"] is True
    assert by_id[forward_id]["compensatedBy"] == comp_id
    # The compensating event itself is not undoable (no handler for the .compensated.v1 type).
    assert by_id[comp_id]["undoable"] is False
    assert by_id[comp_id]["compensated"] is False


def test_returns_at_most_twenty_events_newest_first(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    ids: list[str] = []
    for i in range(25):
        ids.append(emit_event(
            config.root_dir,
            event_type="transaction.deleted.v1",
            summary=f"event {i}",
            payload={},
            journal_refs=[],
        ))

    rows = main.events_recent()["events"]
    assert len(rows) == 20
    # Newest 20 of 25, newest first → ids[24], ids[23], ..., ids[5].
    assert [r["id"] for r in rows] == list(reversed(ids[-20:]))
