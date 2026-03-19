from pathlib import Path

import main
from models import UnknownScanRequest, UnknownSelection, UnknownStageRequest
from services.config_service import AppConfig
from services.stage_store import StageStore


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
        institution_templates={},
        import_accounts={
            "checking_import": {
                "display_name": "Checking Import",
                "ledger_account": "Assets:Bank:Checking",
                "tracked_account_id": "checking",
            }
        },
        tracked_accounts={
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Bank:Checking",
                "import_account_id": "checking_import",
            }
        },
        payee_aliases="payee_aliases.csv",
    )


def test_unknown_scan_reuses_existing_stage_and_preserves_selections(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    journal = config.journal_dir / "2026.journal"
    journal.write_text(
        """
2026/03/01 Coffee Shop
    ; import_account_id: checking_import
    Expenses:Unknown  $5.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "stages", StageStore(tmp_path / "stage-root"))
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    scanned = main.unknown_scan(UnknownScanRequest(journalPath=str(journal)))
    assert scanned["stageId"]
    assert scanned["selections"] == {}

    updated = main.unknown_stage_mappings(
        UnknownStageRequest(
            stageId=scanned["stageId"],
            selections=[
                UnknownSelection(
                    groupKey="coffee shop::checking_import",
                    selectionType="category",
                    categoryAccount="Expenses:Food:Coffee",
                )
            ],
        )
    )
    assert updated["summary"] == {"groupCount": 1, "txnUpdates": 1}

    rescanned = main.unknown_scan(UnknownScanRequest(journalPath=str(journal)))
    assert rescanned["stageId"] == scanned["stageId"]
    assert rescanned["selections"] == {
        "coffee shop::checking_import": {
            "groupKey": "coffee shop::checking_import",
            "selectionType": "category",
            "categoryAccount": "Expenses:Food:Coffee",
        }
    }
    assert rescanned["summary"] == {"groupCount": 1, "txnUpdates": 1}


def test_unknown_scan_refreshes_groups_and_drops_stale_selections(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path / "workspace")
    journal = config.journal_dir / "2026.journal"
    journal.write_text(
        """
2026/03/01 Coffee Shop
    ; import_account_id: checking_import
    Expenses:Unknown  $5.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "stages", StageStore(tmp_path / "stage-root"))
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

    scanned = main.unknown_scan(UnknownScanRequest(journalPath=str(journal)))
    main.unknown_stage_mappings(
        UnknownStageRequest(
            stageId=scanned["stageId"],
            selections=[
                UnknownSelection(
                    groupKey="coffee shop::checking_import",
                    selectionType="category",
                    categoryAccount="Expenses:Food:Coffee",
                )
            ],
        )
    )

    journal.write_text(
        """
2026/03/01 Coffee Shop
    ; import_account_id: checking_import
    Expenses:Dining  $5.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )

    rescanned = main.unknown_scan(UnknownScanRequest(journalPath=str(journal)))
    assert rescanned["stageId"] == scanned["stageId"]
    assert rescanned["groups"] == []
    assert rescanned["selections"] == {}
    assert rescanned["summary"] == {"groupCount": 0, "txnUpdates": 0}
