from __future__ import annotations

from pathlib import Path

from services.config_service import AppConfig
from services.operations_service import (
    list_operations,
    operation_is_compensated,
    record_operation,
)


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


def test_records_operations_with_files_and_lists_newest_first(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")

    first_id = record_operation(
        config,
        operation_type="transaction.deleted.v1",
        summary="Removed Coffee",
        payload={"txn_id": "txn-1"},
        files=[
            {
                "path": "journals/2026.journal",
                "hash_before": "sha256:a",
                "hash_after": "sha256:b",
            }
        ],
        operation_id="op-1",
        created_at="2026-07-05T10:00:00+00:00",
    )
    second_id = record_operation(
        config,
        operation_type="manual_entry.created.v1",
        summary="Created Lunch",
        payload={"txn_id": "txn-2"},
        files=[],
        operation_id="op-2",
        created_at="2026-07-05T11:00:00+00:00",
    )

    rows = list_operations(config)

    assert [row["id"] for row in rows] == [second_id, first_id]
    assert rows[1]["files"] == [
        {
            "path": "journals/2026.journal",
            "hash_before": "sha256:a",
            "hash_after": "sha256:b",
        }
    ]


def test_compensation_link_marks_forward_operation_undone(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    forward_id = record_operation(
        config,
        operation_type="transaction.deleted.v1",
        summary="Removed Coffee",
        payload={},
        files=[],
        operation_id="op-forward",
    )
    compensating_id = record_operation(
        config,
        operation_type="transaction.deleted.v1.compensated.v1",
        summary="Undid: Removed Coffee",
        payload={},
        files=[],
        operation_id="op-comp",
        compensates_operation_id=forward_id,
    )

    assert operation_is_compensated(config, forward_id) == compensating_id
