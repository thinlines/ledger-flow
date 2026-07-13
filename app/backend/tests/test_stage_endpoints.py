"""Staged workflows against the DB-backed stage store (issue #21).

Import preview/apply, unknowns autosave/resume/apply/discard, and
rule-history scan/apply must create, resume, and finalize stage rows in the
SQLite ``stages`` table — and never write ``.workflow/stages/*.json`` files.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from models import (
    ImportPreviewRequest,
    RuleHistoryApplyRequest,
    RuleHistoryScanRequest,
    StageApplyRequest,
    UnknownScanRequest,
    UnknownSelection,
    UnknownStageRequest,
)
from services import event_log_service
from services.config_service import AppConfig
from services.projection_db import database_path


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2026, "base_currency": "USD"},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={
            "wells_fargo": {
                "display_name": "Wells Fargo",
                "parser": "wfchk",
                "CSV_date_format": "%Y/%m/%d",
            }
        },
        import_accounts={
            "wf_checking": {
                "display_name": "Wells Fargo Checking",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
                "tracked_account_id": "checking",
            }
        },
        tracked_accounts={
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Bank:Checking",
                "import_account_id": "wf_checking",
            }
        },
    )


def _stage_row(config: AppConfig, stage_id: str) -> tuple | None:
    with sqlite3.connect(database_path(config)) as conn:
        return conn.execute(
            """
            SELECT kind, status, summary_json, base_file_hashes_json, payload_json,
                   applied_operation_id
            FROM stages WHERE id = ?
            """,
            (stage_id,),
        ).fetchone()


def _assert_no_json_stage_files(config: AppConfig) -> None:
    assert not (config.root_dir / ".workflow" / "stages").exists()


def _prepared_txn(*, date: str, payee: str, source_identity: str, amount: str) -> dict:
    return {
        "matchStatus": "new",
        "annotatedRaw": (
            f"{date} {payee}\n"
            f"    ; lf_source_identity: {source_identity}\n"
            f"    ; source_payload_hash: payload-{source_identity}\n"
            "    ; source_file_sha256: abc123def4567890\n"
            "    ; importer_version: mvp2\n"
            f"    Assets:Bank:Checking  {amount}\n"
            "    Expenses:Unknown\n"
        ),
        "sourceIdentity": source_identity,
        "sourcePayloadHash": f"payload-{source_identity}",
        "date": date,
        "payee": payee,
    }


def _canned_preview_data(config: AppConfig) -> dict:
    return {
        "summary": {"count": 1, "duplicateCount": 0, "fenceCount": 0, "newCount": 1, "unknownCount": 1},
        "conflicts": [],
        "preview": [{"date": "2026/03/01", "payee": "Coffee Shop", "matchStatus": "new"}],
        "targetJournalPath": str(config.journal_dir / "2026.journal"),
        "preparedTransactions": [
            _prepared_txn(date="2026/03/01", payee="Coffee Shop", source_identity="txn-1", amount="$-7.50")
        ],
        "sourceFileSha256": "abc123def4567890",
        "destinationAccount": "Assets:Bank:Checking",
        "importAccountDisplayName": "Wells Fargo Checking",
        "importMode": "csv",
    }


def _import_preview(config: AppConfig, monkeypatch: pytest.MonkeyPatch) -> dict:
    inbox_csv = config.csv_dir / "2026__wf_checking__statement.csv"
    inbox_csv.write_text("date,amount\n2026-03-01,-7.50\n", encoding="utf-8")
    monkeypatch.setattr(
        main, "preview_import_safely", lambda *a, **k: _canned_preview_data(config)
    )
    return main.import_preview(
        ImportPreviewRequest(csvPath=str(inbox_csv), year="2026", importAccountId="wf_checking")
    )


# ---------------------------------------------------------------------------
# Import preview / apply
# ---------------------------------------------------------------------------


def test_import_preview_creates_stage_row(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.journal_dir / "2026.journal").write_text("", encoding="utf-8")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    payload = _import_preview(config, monkeypatch)

    assert payload["stageId"]
    row = _stage_row(config, payload["stageId"])
    assert row is not None
    kind, status, summary_json, hashes_json, payload_json, applied_op = row
    assert kind == "import"
    assert status == "ready"
    assert json.loads(summary_json) == payload["summary"]
    assert json.loads(payload_json) == payload
    assert applied_op is None
    hashes = json.loads(hashes_json)
    assert set(hashes) == {payload["targetJournalPath"]}
    assert hashes[payload["targetJournalPath"]].startswith("sha256:")

    # Resume: the stage endpoint returns the same payload.
    assert main.get_stage(payload["stageId"]) == payload
    _assert_no_json_stage_files(config)


def test_import_apply_marks_stage_applied_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    payload = _import_preview(config, monkeypatch)
    stage_id = payload["stageId"]

    applied = main.import_apply(StageApplyRequest(stageId=stage_id))

    assert applied["status"] == "applied"
    assert applied["result"]["applied"] is True
    assert applied["result"]["appendedTxnCount"] == 1
    assert applied["result"]["historyId"]

    row = _stage_row(config, stage_id)
    assert row is not None
    _, status, _, _, payload_json, _ = row
    assert status == "applied"
    assert json.loads(payload_json)["result"]["historyId"] == applied["result"]["historyId"]

    # Re-apply returns the stored stage unchanged instead of re-importing.
    again = main.import_apply(StageApplyRequest(stageId=stage_id))
    assert again["result"]["historyId"] == applied["result"]["historyId"]
    journal_text = Path(applied["result"]["journalPath"]).read_text(encoding="utf-8")
    assert journal_text.count("Coffee Shop") == 1
    _assert_no_json_stage_files(config)


def test_unknown_apply_rejects_import_stage(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    payload = _import_preview(config, monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        main.unknown_apply(StageApplyRequest(stageId=payload["stageId"]))
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Generic stage endpoints
# ---------------------------------------------------------------------------


def test_get_stage_unknown_id_is_404(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    with pytest.raises(HTTPException) as exc_info:
        main.get_stage("nope")
    assert exc_info.value.status_code == 404


def test_delete_stage_discards_row(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    payload = _import_preview(config, monkeypatch)
    stage_id = payload["stageId"]

    result = main.delete_stage(stage_id)

    assert result == {"deleted": True, "stageId": stage_id}
    assert _stage_row(config, stage_id) is None
    with pytest.raises(HTTPException):
        main.get_stage(stage_id)
    # Discard is idempotent.
    assert main.delete_stage(stage_id)["deleted"] is True


# ---------------------------------------------------------------------------
# Unknowns (Review) autosave / resume / apply / discard
# ---------------------------------------------------------------------------


def _seed_unknown_journal(config: AppConfig) -> Path:
    journal = config.journal_dir / "2026.journal"
    journal.write_text(
        """
include ../rules/10-accounts.dat

2026/03/01 Coffee Shop
    ; import_account_id: wf_checking
    Expenses:Unknown  $5.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (config.init_dir / "10-accounts.dat").write_text(
        "account Assets:Bank:Checking\naccount Expenses:Food:Coffee\n", encoding="utf-8"
    )
    return journal


def test_unknowns_autosave_resume_apply_and_discard(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    journal = _seed_unknown_journal(config)
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    scanned = main.unknown_scan(UnknownScanRequest(journalPath=str(journal)))
    stage_id = scanned["stageId"]
    row = _stage_row(config, stage_id)
    assert row is not None
    kind, status, _, hashes_json, _, _ = row
    assert (kind, status) == ("unknowns", "ready")
    assert set(json.loads(hashes_json)) == {str(journal.resolve())}

    txn = scanned["groups"][0]["txns"][0]
    updated = main.unknown_stage_mappings(
        UnknownStageRequest(
            stageId=stage_id,
            selections=[
                UnknownSelection(
                    txnId=txn["txnId"],
                    selectionType="category",
                    categoryAccount="Expenses:Food:Coffee",
                )
            ],
        )
    )
    assert updated["summary"] == {"groupCount": 1, "txnUpdates": 1}
    row = _stage_row(config, stage_id)
    assert row is not None
    assert json.loads(row[2]) == {"groupCount": 1, "txnUpdates": 1}

    # Resume keeps the same stage and selections (route/localStorage path).
    rescanned = main.unknown_scan(UnknownScanRequest(journalPath=str(journal)))
    assert rescanned["stageId"] == stage_id
    assert rescanned["selections"][txn["txnId"]]["categoryAccount"] == "Expenses:Food:Coffee"

    applied = main.unknown_apply(StageApplyRequest(stageId=stage_id))
    assert applied["status"] == "applied"
    assert applied["result"]["updatedTxnCount"] == 1
    row = _stage_row(config, stage_id)
    assert row is not None
    assert row[1] == "applied"
    assert "Expenses:Food:Coffee" in journal.read_text(encoding="utf-8")

    # Applied stages are not resumable: a fresh scan mints a new stage.
    fresh = main.unknown_scan(UnknownScanRequest(journalPath=str(journal)))
    assert fresh["stageId"] != stage_id

    # Discard the fresh stage; the next scan mints yet another id.
    main.delete_stage(fresh["stageId"])
    assert _stage_row(config, fresh["stageId"]) is None
    after_discard = main.unknown_scan(UnknownScanRequest(journalPath=str(journal)))
    assert after_discard["stageId"] not in {stage_id, fresh["stageId"]}
    _assert_no_json_stage_files(config)


# ---------------------------------------------------------------------------
# Rule-history scan / apply from Review
# ---------------------------------------------------------------------------


def test_rule_history_scan_apply_and_cleanup(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    journal = _seed_unknown_journal(config)
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    monkeypatch.setattr(main, "_rule_or_404", lambda path, rule_id: {"id": rule_id, "name": "Coffee"})
    monkeypatch.setattr(
        main,
        "scan_rule_reapply",
        lambda *a, **k: {
            "targetAccount": "Expenses:Food:Coffee",
            "candidates": [
                {
                    "id": "cand-1",
                    "payee": "Coffee Shop",
                    "targetAccount": "Expenses:Food:Coffee",
                }
            ],
            "warnings": [],
            "summary": {"candidateCount": 1},
        },
    )

    scanned = main.rules_history_scan("rule-1", RuleHistoryScanRequest(journalPath=str(journal)))
    stage_id = scanned["stageId"]
    row = _stage_row(config, stage_id)
    assert row is not None
    kind, status, summary_json, hashes_json, _, _ = row
    assert (kind, status) == ("rule_history", "ready")
    assert json.loads(summary_json) == {"candidateCount": 1}
    assert set(json.loads(hashes_json)) == {str(journal.resolve())}

    monkeypatch.setattr(main, "apply_rule_reapply", lambda **k: (1, []))
    applied = main.rules_history_apply(
        RuleHistoryApplyRequest(stageId=stage_id, selectedCandidateIds=["cand-1"])
    )
    assert applied["status"] == "applied"
    assert applied["selectedCandidateIds"] == ["cand-1"]
    assert applied["result"]["updatedTxnCount"] == 1
    row = _stage_row(config, stage_id)
    assert row is not None
    assert row[1] == "applied"

    # The frontend deletes the stage after redirecting back to /rules.
    main.delete_stage(stage_id)
    assert _stage_row(config, stage_id) is None
    _assert_no_json_stage_files(config)
