from pathlib import Path

from services.config_service import AppConfig
from services.import_history_service import list_import_history, record_applied_import, undo_import
from services.import_index import ImportIndex


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2026},
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
            }
        },
        tracked_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
                "import_account_id": "wf_checking",
            },
            "savings": {
                "display_name": "Savings",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Savings",
                "import_account_id": "wf_savings",
            },
            "vehicle": {
                "display_name": "Vehicle",
                "ledger_account": "Assets:Vehicle:Subaru",
                "import_account_id": None,
            },
        },
        payee_aliases="payee_aliases.csv",
    )


def _stage(
    config: AppConfig,
    *,
    stage_id: str,
    csv_path: Path,
    backup_path: Path,
    archived_csv_path: Path | None,
    journal_path: Path,
    source_identity: str,
) -> dict:
    return {
        "stageId": stage_id,
        "csvPath": str(csv_path.resolve()),
        "year": "2026",
        "importAccountId": "wf_checking",
        "importAccountDisplayName": "Wells Fargo Checking",
        "destinationAccount": "Assets:Bank:Checking",
        "importSourceDisplayName": "Wells Fargo",
        "targetJournalPath": str(journal_path.resolve()),
        "sourceFileSha256": f"sha-{stage_id}",
        "summary": {
            "count": 1,
            "unknownCount": 0,
            "newCount": 1,
            "duplicateCount": 0,
            "conflictCount": 0,
        },
        "preparedTransactions": [
            {
                "matchStatus": "new",
                "sourceIdentity": source_identity,
                "sourcePayloadHash": f"payload-{stage_id}",
                "date": "2026/03/01",
                "payee": f"Merchant {stage_id}",
            }
        ],
        "result": {
            "applied": True,
            "backupPath": str(backup_path.resolve()),
            "journalPath": str(journal_path.resolve()),
            "appendedTxnCount": 1,
            "skippedDuplicateCount": 0,
            "conflicts": [],
            "archivedCsvPath": str(archived_csv_path.resolve()) if archived_csv_path is not None else None,
            "sourceCsvWarning": None,
        },
    }


def _journal_transaction(stage_id: str, source_identity: str) -> str:
    return "\n".join(
        [
            f"2026/03/01 Merchant {stage_id}",
            "    ; import_account_id: wf_checking",
            f"    ; source_identity: {source_identity}",
            f"    ; source_payload_hash: payload-{stage_id}",
            f"    ; source_file_sha256: sha-{stage_id}",
            "    Assets:Bank:Checking  $10.00",
            "    Expenses:Unknown       $-10.00",
        ]
    )


def _journal_transaction_with_carried_identity(
    stage_id: str,
    *,
    primary_identity: str,
    primary_payload: str,
    carried_identity: str,
    carried_payload: str,
) -> str:
    return "\n".join(
        [
            f"2026/03/01 Merchant {stage_id}",
            "    ; import_account_id: wf_checking",
            f"    ; source_identity: {primary_identity}",
            f"    ; source_payload_hash: {primary_payload}",
            "    ; source_file_sha256: sha-merged",
            f"    ; source_identity_2: {carried_identity}",
            f"    ; source_payload_hash_2: {carried_payload}",
            "    ; source_file_sha256_2: sha-carried",
            "    Assets:Bank:Checking  $10.00",
            "    Expenses:Unknown       $-10.00",
        ]
    )


def _write_journal(path: Path, *transactions: str) -> None:
    text = "\n\n".join(transactions)
    path.write_text(f"{text}\n" if text else "", encoding="utf-8")


def test_list_import_history_allows_older_imports_to_be_undone_when_their_transactions_still_exist(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    _write_journal(
        journal_path,
        _journal_transaction("first", "txn-1"),
        _journal_transaction("second", "txn-2"),
    )

    first_csv = config.csv_dir / "2026__wf_checking__first.csv"
    second_csv = config.csv_dir / "2026__wf_checking__second.csv"
    first_backup = config.imports_dir / "2026.first.import.bak"
    second_backup = config.imports_dir / "2026.second.import.bak"
    first_backup.write_text("before first import\n", encoding="utf-8")
    second_backup.write_text("before second import\n", encoding="utf-8")

    first = record_applied_import(
        config,
        _stage(
            config,
            stage_id="first",
            csv_path=first_csv,
            backup_path=first_backup,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-1",
        ),
    )
    second = record_applied_import(
        config,
        _stage(
            config,
            stage_id="second",
            csv_path=second_csv,
            backup_path=second_backup,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-2",
        ),
    )

    history = list_import_history(config)
    latest = next(entry for entry in history if entry["id"] == second["id"])
    older = next(entry for entry in history if entry["id"] == first["id"])

    assert latest["canUndo"] is True
    assert latest["undoBlockedReason"] is None
    assert older["canUndo"] is True
    assert older["undoBlockedReason"] is None


def test_undo_import_removes_transactions_restores_source_csv_and_import_index(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    _write_journal(journal_path, _journal_transaction("undo", "txn-undo"))

    original_csv = config.csv_dir / "2026__wf_checking__statement.csv"
    archived_csv = config.imports_dir / "processed" / "2026" / "wf_checking" / "2026__wf_checking__statement-sha.csv"
    archived_csv.parent.mkdir(parents=True, exist_ok=True)
    archived_csv.write_text("date,amount\n2026-03-01,-7.50\n", encoding="utf-8")

    backup_path = config.imports_dir / "2026.import.bak"
    backup_path.write_text("snapshot not used by transaction undo\n", encoding="utf-8")

    index = ImportIndex(config.root_dir / ".workflow" / "state.db")
    index.upsert_transactions(
        import_account_id="wf_checking",
        year="2026",
        journal_path=journal_path,
        source_file_sha256="sha-stage",
        txns=[{"sourceIdentity": "txn-undo", "sourcePayloadHash": "payload-stage"}],
    )

    recorded = record_applied_import(
        config,
        _stage(
            config,
            stage_id="undo",
            csv_path=original_csv,
            backup_path=backup_path,
            archived_csv_path=archived_csv,
            journal_path=journal_path,
            source_identity="txn-undo",
        ),
    )

    undone = undo_import(config, recorded["id"])

    assert journal_path.read_text(encoding="utf-8") == ""
    assert original_csv.exists()
    assert original_csv.read_text(encoding="utf-8") == "date,amount\n2026-03-01,-7.50\n"
    assert not archived_csv.exists()
    assert undone["status"] == "undone"
    assert undone["canUndo"] is False
    assert "already undone" in undone["undoBlockedReason"].lower()
    assert Path(undone["undo"]["undoBackupPath"]).exists()
    assert "txn-undo" in Path(undone["undo"]["undoBackupPath"]).read_text(encoding="utf-8")
    assert undone["undo"]["removedTxnCount"] == 1
    assert index.get_identity_map("wf_checking") == {}


def test_undo_import_strips_carried_identity_without_deleting_survivor(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    _write_journal(
        journal_path,
        _journal_transaction_with_carried_identity(
            "merged",
            primary_identity="txn-keep",
            primary_payload="payload-keep",
            carried_identity="txn-carried",
            carried_payload="payload-carried",
        ),
    )

    original_csv = config.csv_dir / "2026__wf_checking__carried.csv"
    backup_path = config.imports_dir / "2026.carried.import.bak"
    backup_path.write_text("snapshot\n", encoding="utf-8")

    index = ImportIndex(config.root_dir / ".workflow" / "state.db")
    index.upsert_transactions(
        import_account_id="wf_checking",
        year="2026",
        journal_path=journal_path,
        source_file_sha256="sha-carried",
        txns=[{"sourceIdentity": "txn-carried", "sourcePayloadHash": "payload-carried"}],
    )

    recorded = record_applied_import(
        config,
        _stage(
            config,
            stage_id="carried",
            csv_path=original_csv,
            backup_path=backup_path,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-carried",
        ),
    )

    history = list_import_history(config)
    carried_entry = next(entry for entry in history if entry["id"] == recorded["id"])
    assert carried_entry["canUndo"] is True

    undone = undo_import(config, recorded["id"])
    updated = journal_path.read_text(encoding="utf-8")

    assert "Merchant merged" in updated
    assert "; source_identity: txn-keep" in updated
    assert "; source_identity_2: txn-carried" not in updated
    assert "; source_payload_hash_2: payload-carried" not in updated
    assert undone["undo"]["removedTxnCount"] == 0
    assert undone["undo"]["strippedCarriedIdentityCount"] == 1
    assert index.get_identity_map("wf_checking") == {}


def test_undo_import_downgrades_surviving_transfer_peer_to_pending(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    _write_journal(
        journal_path,
        "\n".join(
            [
                "2026/03/01 Transfer out",
                "    ; import_account_id: wf_checking",
                "    ; source_identity: txn-undo",
                "    ; source_payload_hash: payload-undo",
                "    ; transfer_id: transfer-1",
                "    ; transfer_type: import_match",
                "    ; transfer_match_state: matched",
                "    ; transfer_peer_account_id: savings",
                "    Assets:Transfers:checking__savings  $10.00",
                "    Assets:Bank:Checking",
            ]
        ),
        "\n".join(
            [
                "2026/03/02 Transfer in",
                "    ; import_account_id: wf_checking",
                "    ; source_identity: txn-keep",
                "    ; source_payload_hash: payload-keep",
                "    ; transfer_id: transfer-1",
                "    ; transfer_type: import_match",
                "    ; transfer_match_state: matched",
                "    ; transfer_peer_account_id: checking",
                "    Assets:Transfers:checking__savings  $-10.00",
                "    Assets:Bank:Savings",
            ]
        ),
    )

    backup_path = config.imports_dir / "2026.transfer.import.bak"
    backup_path.write_text("snapshot\n", encoding="utf-8")

    index = ImportIndex(config.root_dir / ".workflow" / "state.db")
    index.upsert_transactions(
        import_account_id="wf_checking",
        year="2026",
        journal_path=journal_path,
        source_file_sha256="sha-transfer",
        txns=[
            {"sourceIdentity": "txn-undo", "sourcePayloadHash": "payload-undo"},
            {"sourceIdentity": "txn-keep", "sourcePayloadHash": "payload-keep"},
        ],
    )

    recorded = record_applied_import(
        config,
        _stage(
            config,
            stage_id="undo",
            csv_path=config.csv_dir / "2026__wf_checking__transfer.csv",
            backup_path=backup_path,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-undo",
        ),
    )

    undone = undo_import(config, recorded["id"])

    content = journal_path.read_text(encoding="utf-8")
    assert "txn-undo" not in content
    assert "txn-keep" in content
    assert "; transfer_type: import_match" in content
    assert "; transfer_match_state: pending" in content
    assert "; transfer_match_state: matched" not in content
    assert "; transfer_state:" not in content
    assert undone["undo"]["removedTxnCount"] == 1


def test_undo_import_rejects_downgrading_surviving_direct_transfer_peer(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    _write_journal(
        journal_path,
        "\n".join(
            [
                "2026/03/01 Vehicle purchase",
                "    ; import_account_id: wf_checking",
                "    ; source_identity: txn-undo",
                "    ; source_payload_hash: payload-undo",
                "    ; transfer_id: transfer-1",
                "    ; transfer_type: direct",
                "    ; transfer_match_state: none",
                "    ; transfer_peer_account_id: vehicle",
                "    Assets:Vehicle:Subaru  $10.00",
                "    Assets:Bank:Checking",
            ]
        ),
        "\n".join(
            [
                "2026/03/02 Vehicle adjustment",
                "    ; import_account_id: wf_checking",
                "    ; source_identity: txn-keep",
                "    ; source_payload_hash: payload-keep",
                "    ; transfer_id: transfer-1",
                "    ; transfer_type: direct",
                "    ; transfer_match_state: none",
                "    ; transfer_peer_account_id: vehicle",
                "    Assets:Vehicle:Subaru  $5.00",
                "    Assets:Bank:Checking",
            ]
        ),
    )

    backup_path = config.imports_dir / "2026.direct-transfer.import.bak"
    backup_path.write_text("snapshot\n", encoding="utf-8")

    index = ImportIndex(config.root_dir / ".workflow" / "state.db")
    index.upsert_transactions(
        import_account_id="wf_checking",
        year="2026",
        journal_path=journal_path,
        source_file_sha256="sha-transfer",
        txns=[
            {"sourceIdentity": "txn-undo", "sourcePayloadHash": "payload-undo"},
            {"sourceIdentity": "txn-keep", "sourcePayloadHash": "payload-keep"},
        ],
    )

    recorded = record_applied_import(
        config,
        _stage(
            config,
            stage_id="undo",
            csv_path=config.csv_dir / "2026__wf_checking__direct-transfer.csv",
            backup_path=backup_path,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-undo",
        ),
    )

    original = journal_path.read_text(encoding="utf-8")
    try:
        undo_import(config, recorded["id"])
    except ValueError as exc:
        assert "counterpart-aware" in str(exc).lower()
    else:
        raise AssertionError("undo_import should reject downgrading a direct transfer survivor")

    assert journal_path.read_text(encoding="utf-8") == original


def test_undo_import_rejects_downgrading_legacy_false_pending_manual_transfer_peer(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    _write_journal(
        journal_path,
        "\n".join(
            [
                "2026/03/01 Vehicle purchase",
                "    ; import_account_id: wf_checking",
                "    ; source_identity: txn-undo",
                "    ; source_payload_hash: payload-undo",
                "    ; transfer_id: transfer-1",
                "    ; transfer_state: matched",
                "    ; transfer_peer_account_id: vehicle",
                "    Assets:Vehicle:Subaru  $10.00",
                "    Assets:Bank:Checking",
            ]
        ),
        "\n".join(
            [
                "2026/03/02 Vehicle adjustment",
                "    ; import_account_id: wf_checking",
                "    ; source_identity: txn-keep",
                "    ; source_payload_hash: payload-keep",
                "    ; transfer_id: transfer-1",
                "    ; transfer_state: matched",
                "    ; transfer_peer_account_id: vehicle",
                "    Assets:Vehicle:Subaru  $5.00",
                "    Assets:Bank:Checking",
            ]
        ),
    )

    backup_path = config.imports_dir / "2026.legacy-direct-transfer.import.bak"
    backup_path.write_text("snapshot\n", encoding="utf-8")

    index = ImportIndex(config.root_dir / ".workflow" / "state.db")
    index.upsert_transactions(
        import_account_id="wf_checking",
        year="2026",
        journal_path=journal_path,
        source_file_sha256="sha-transfer",
        txns=[
            {"sourceIdentity": "txn-undo", "sourcePayloadHash": "payload-undo"},
            {"sourceIdentity": "txn-keep", "sourcePayloadHash": "payload-keep"},
        ],
    )

    recorded = record_applied_import(
        config,
        _stage(
            config,
            stage_id="undo",
            csv_path=config.csv_dir / "2026__wf_checking__legacy-direct-transfer.csv",
            backup_path=backup_path,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-undo",
        ),
    )

    original = journal_path.read_text(encoding="utf-8")
    try:
        undo_import(config, recorded["id"])
    except ValueError as exc:
        assert "counterpart-aware" in str(exc).lower()
    else:
        raise AssertionError("undo_import should reject downgrading a manual legacy transfer survivor")

    assert journal_path.read_text(encoding="utf-8") == original


def test_undo_import_keeps_newer_import_transactions_and_their_undoability(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    _write_journal(
        journal_path,
        _journal_transaction("first", "txn-1"),
        _journal_transaction("second", "txn-2"),
    )

    first_csv = config.csv_dir / "2026__wf_checking__first.csv"
    second_csv = config.csv_dir / "2026__wf_checking__second.csv"
    first_backup = config.imports_dir / "2026.first.import.bak"
    second_backup = config.imports_dir / "2026.second.import.bak"
    first_backup.write_text("before first import\n", encoding="utf-8")
    second_backup.write_text("before second import\n", encoding="utf-8")

    index = ImportIndex(config.root_dir / ".workflow" / "state.db")
    index.upsert_transactions(
        import_account_id="wf_checking",
        year="2026",
        journal_path=journal_path,
        source_file_sha256="sha-both",
        txns=[
            {"sourceIdentity": "txn-1", "sourcePayloadHash": "payload-first"},
            {"sourceIdentity": "txn-2", "sourcePayloadHash": "payload-second"},
        ],
    )

    first = record_applied_import(
        config,
        _stage(
            config,
            stage_id="first",
            csv_path=first_csv,
            backup_path=first_backup,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-1",
        ),
    )
    second = record_applied_import(
        config,
        _stage(
            config,
            stage_id="second",
            csv_path=second_csv,
            backup_path=second_backup,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-2",
        ),
    )

    undo_import(config, first["id"])
    journal_text = journal_path.read_text(encoding="utf-8")
    assert "txn-1" not in journal_text
    assert "txn-2" in journal_text

    history = list_import_history(config)
    first_after = next(entry for entry in history if entry["id"] == first["id"])
    second_after = next(entry for entry in history if entry["id"] == second["id"])

    assert first_after["status"] == "undone"
    assert first_after["canUndo"] is False
    assert "already undone" in first_after["undoBlockedReason"].lower()
    assert second_after["canUndo"] is True
    assert second_after["undoBlockedReason"] is None
    assert index.get_identity_map("wf_checking") == {"txn-2": "payload-second"}


def test_list_import_history_blocks_undo_when_import_transactions_are_missing(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    _write_journal(journal_path, _journal_transaction("other", "txn-other"))

    csv_path = config.csv_dir / "2026__wf_checking__missing.csv"
    backup_path = config.imports_dir / "2026.missing.import.bak"
    backup_path.write_text("before missing import\n", encoding="utf-8")

    recorded = record_applied_import(
        config,
        _stage(
            config,
            stage_id="missing",
            csv_path=csv_path,
            backup_path=backup_path,
            archived_csv_path=None,
            journal_path=journal_path,
            source_identity="txn-missing",
        ),
    )

    history = list_import_history(config)
    entry = next(item for item in history if item["id"] == recorded["id"])

    assert entry["canUndo"] is False
    assert "identified in the journal" in entry["undoBlockedReason"].lower()
