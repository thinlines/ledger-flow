import json
from pathlib import Path

import pytest

import services.import_service as import_service
from services.config_service import AppConfig
from services.event_log_service import EVENTS_FILENAME
from services.import_identity_service import ImportIdentityStore
from services.import_history_service import record_applied_import, undo_import
from services.import_service import (
    _build_existing_map,
    ImportPreviewBlockedError,
    apply_import,
    archive_inbox_csv,
    preview_import_safely,
    remove_inbox_csv,
)
from services.operations_service import list_operations


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
    )


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


def test_apply_import_can_archive_inbox_csv_after_success(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    inbox_csv = config.csv_dir / "2026__wf_checking__statement.csv"
    original_csv = "date,amount\n2026-03-01,-7.50\n"
    inbox_csv.write_text(original_csv, encoding="utf-8")

    stage = {
        "targetJournalPath": str(config.journal_dir / "2026.journal"),
        "preparedTransactions": [
            {
                "matchStatus": "new",
                "annotatedRaw": (
                    "2026/03/01 Coffee Shop\n"
                    "    ; lf_source_identity: txn-1\n"
                    "    ; source_payload_hash: payload-1\n"
                    "    ; source_file_sha256: abc123def4567890\n"
                    "    ; importer_version: mvp2\n"
                    "    Assets:Bank:Checking  $-7.50\n"
                    "    Expenses:Unknown\n"
                ),
                "sourceIdentity": "txn-1",
                "sourcePayloadHash": "payload-1",
                "date": "2026/03/01",
                "payee": "Coffee Shop",
            }
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "abc123def4567890",
    }

    journal_path, appended_count, skipped_duplicate_count, conflicts = apply_import(config, stage)
    archived_csv_path = archive_inbox_csv(
        config,
        inbox_csv,
        year="2026",
        import_account_id="wf_checking",
        source_file_sha256="abc123def4567890",
    )

    assert appended_count == 1
    assert skipped_duplicate_count == 0
    assert conflicts == []
    assert Path(journal_path).exists()
    assert "Coffee Shop" in Path(journal_path).read_text(encoding="utf-8")

    assert archived_csv_path is not None
    archived_csv = Path(archived_csv_path)
    assert archived_csv.exists()
    assert archived_csv.read_text(encoding="utf-8") == original_csv
    assert not inbox_csv.exists()
    assert archived_csv.parent == config.imports_dir / "processed" / "2026" / "wf_checking"


def test_apply_import_records_active_import_identities(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")

    stage = {
        "targetJournalPath": str(config.journal_dir / "2026.journal"),
        "csvPath": str(config.csv_dir / "2026__wf_checking__statement.csv"),
        "preparedTransactions": [
            _prepared_txn(date="2026/03/01", payee="Coffee", source_identity="txn-1", amount="$-4.00"),
            {
                "matchStatus": "duplicate",
                "sourceIdentity": "txn-duplicate",
                "sourcePayloadHash": "payload-duplicate",
                "date": "2026/03/02",
                "payee": "Already Imported",
                "annotatedRaw": "2026/03/02 Already Imported\n",
            },
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "deadbeef",
    }

    apply_import(config, stage)

    store = ImportIdentityStore(config)
    assert store.get_active_identity_map("wf_checking") == {"txn-1": "payload-txn-1"}


def test_import_undo_reimport_loop_reactivates_identity_without_double_booking(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    csv_path = config.csv_dir / "2026__wf_checking__statement.csv"
    stage = {
        "stageId": "stage-first",
        "targetJournalPath": str(journal_path),
        "csvPath": str(csv_path),
        "preparedTransactions": [
            _prepared_txn(date="2026/03/01", payee="Coffee", source_identity="txn-1", amount="$-4.00"),
        ],
        "importAccountId": "wf_checking",
        "importAccountDisplayName": "Wells Fargo Checking",
        "destinationAccount": "Assets:Bank:Checking",
        "importSourceDisplayName": "Wells Fargo",
        "year": "2026",
        "sourceFileSha256": "deadbeef-first",
        "summary": {"count": 1, "unknownCount": 1, "newCount": 1, "duplicateCount": 0, "fenceCount": 0},
    }

    journal_abs, appended_count, skipped_count, conflicts = apply_import(config, stage)
    stage["result"] = {
        "applied": True,
        "backupPath": None,
        "journalPath": journal_abs,
        "appendedTxnCount": appended_count,
        "skippedDuplicateCount": skipped_count,
        "conflicts": conflicts,
        "archivedCsvPath": None,
        "sourceCsvWarning": None,
    }
    history = record_applied_import(config, stage)

    undo_import(config, history["id"])

    assert _build_existing_map(config, "wf_checking", journal_path) == {}
    assert journal_path.read_text(encoding="utf-8") == ""

    second_stage = {
        **stage,
        "stageId": "stage-second",
        "sourceFileSha256": "deadbeef-second",
        "preparedTransactions": [
            _prepared_txn(date="2026/03/01", payee="Coffee", source_identity="txn-1", amount="$-4.00"),
        ],
    }
    _, second_appended_count, second_skipped_count, second_conflicts = apply_import(config, second_stage)

    text = journal_path.read_text(encoding="utf-8")
    assert second_appended_count == 1
    assert second_skipped_count == 0
    assert second_conflicts == []
    assert text.count("Coffee") == 1
    assert ImportIdentityStore(config).get_active_identity_map("wf_checking") == {"txn-1": "payload-txn-1"}


def test_archive_inbox_csv_leaves_external_files_untouched(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    external_csv = tmp_path / "downloads" / "statement.csv"
    external_csv.parent.mkdir(parents=True, exist_ok=True)
    external_csv.write_text("date,amount\n2026-03-01,-7.50\n", encoding="utf-8")

    archived_csv_path = archive_inbox_csv(
        config,
        external_csv,
        year="2026",
        import_account_id="wf_checking",
        source_file_sha256="abc123def4567890",
    )

    assert archived_csv_path is None
    assert external_csv.exists()


def test_preview_import_safely_removes_failed_upload_before_inbox_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_config(tmp_path / "workspace")
    inbox_csv = config.csv_dir / "2026__wf_checking__statement.csv"
    inbox_csv.write_text("date,amount\n2026-03-01,-7.50\n", encoding="utf-8")

    def blocked_preview(*_args, **_kwargs):
        raise ValueError("wrong account")

    monkeypatch.setattr(import_service, "preview_import", blocked_preview)

    with pytest.raises(ImportPreviewBlockedError) as exc_info:
        preview_import_safely(
            config,
            inbox_csv,
            year="2026",
            import_account_id="wf_checking",
            keep_file_on_failure=False,
        )

    assert not inbox_csv.exists()
    assert exc_info.value.file_kept_in_inbox is False
    assert "Nothing was added to the inbox." in str(exc_info.value)


def test_preview_import_safely_keeps_existing_inbox_file_for_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_config(tmp_path / "workspace")
    inbox_csv = config.csv_dir / "2026__wf_checking__statement.csv"
    inbox_csv.write_text("date,amount\n2026-03-01,-7.50\n", encoding="utf-8")

    def blocked_preview(*_args, **_kwargs):
        raise ValueError("wrong account")

    monkeypatch.setattr(import_service, "preview_import", blocked_preview)

    with pytest.raises(ImportPreviewBlockedError) as exc_info:
        preview_import_safely(
            config,
            inbox_csv,
            year="2026",
            import_account_id="wf_checking",
            keep_file_on_failure=True,
        )

    assert inbox_csv.exists()
    assert exc_info.value.file_kept_in_inbox is True
    assert "remove this file from the inbox" in str(exc_info.value)


def test_remove_inbox_csv_deletes_waiting_statement(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    inbox_csv = config.csv_dir / "2026__wf_checking__statement.csv"
    inbox_csv.write_text("date,amount\n2026-03-01,-7.50\n", encoding="utf-8")

    removed_path = remove_inbox_csv(config, inbox_csv)

    assert removed_path == str(inbox_csv.resolve())
    assert not inbox_csv.exists()


def test_remove_inbox_csv_rejects_external_file(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    external_csv = tmp_path / "downloads" / "statement.csv"
    external_csv.parent.mkdir(parents=True, exist_ok=True)
    external_csv.write_text("date,amount\n2026-03-01,-7.50\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Only statements waiting in the inbox can be removed here."):
        remove_inbox_csv(config, external_csv)

    assert external_csv.exists()


def test_apply_import_preserves_same_day_prepared_transaction_order(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"

    stage = {
        "targetJournalPath": str(journal_path),
        "preparedTransactions": [
            _prepared_txn(
                date="2026/03/12",
                payee="AMAZON MKTPL*BP9TA8360 Amzn.com/billWA",
                source_identity="txn-1",
                amount="$-98.56",
            ),
            _prepared_txn(
                date="2026/03/12",
                payee="TC @ ALBERTSONS CORPORAT BOISE ID",
                source_identity="txn-2",
                amount="$-7.10",
            ),
            _prepared_txn(
                date="2026/03/12",
                payee="ONLINE PAYMENT THANK YOU",
                source_identity="txn-3",
                amount="$1984.86",
            ),
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "abc123def4567890",
    }

    apply_import(config, stage)

    text = journal_path.read_text(encoding="utf-8")
    assert text.index("AMAZON MKTPL*BP9TA8360 Amzn.com/billWA") < text.index("TC @ ALBERTSONS CORPORAT BOISE ID")
    assert text.index("TC @ ALBERTSONS CORPORAT BOISE ID") < text.index("ONLINE PAYMENT THANK YOU")


def test_apply_import_inserts_older_batch_before_later_existing_transactions(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    journal_path = config.journal_dir / "2026.journal"
    journal_path.write_text(
        "\n".join(
            [
                "include ../rules/10-accounts.dat",
                "include ../rules/12-tags.dat",
                "include ../rules/13-commodities.dat",
                "",
                "2026/03/15 Later Transaction",
                "    ; lf_source_identity: existing-txn",
                "    ; source_payload_hash: payload-existing-txn",
                "    Assets:Bank:Checking  $-20.00",
                "    Expenses:Unknown",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    stage = {
        "targetJournalPath": str(journal_path),
        "preparedTransactions": [
            _prepared_txn(
                date="2026/03/12",
                payee="AMAZON MKTPL*BP9TA8360 Amzn.com/billWA",
                source_identity="txn-1",
                amount="$-98.56",
            ),
            _prepared_txn(
                date="2026/03/12",
                payee="TC @ ALBERTSONS CORPORAT BOISE ID",
                source_identity="txn-2",
                amount="$-7.10",
            ),
            _prepared_txn(
                date="2026/03/12",
                payee="ONLINE PAYMENT THANK YOU",
                source_identity="txn-3",
                amount="$1984.86",
            ),
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "abc123def4567890",
    }

    apply_import(config, stage)

    text = journal_path.read_text(encoding="utf-8")
    assert text.startswith("include ../rules/10-accounts.dat")
    assert text.index("ONLINE PAYMENT THANK YOU") < text.index("Later Transaction")


# ---------------------------------------------------------------------------
# DECISIONS §21: conflicts list and skipped count must distinguish identity
# collisions (silent, diagnostic-only) from reconciled-date fence rows
# (user-facing). Identity collisions fold into the skipped count alongside
# duplicates; the conflicts list returns only fence rows.
# ---------------------------------------------------------------------------


def _prepared_collision_txn(*, date: str, payee: str, source_identity: str) -> dict:
    """A prepared identity-collision txn — same identity exists in journal but
    payload differs (e.g. rule edit between imports)."""
    return {
        "matchStatus": "conflict",
        "conflictReason": "identity_collision",
        "reconciledThrough": None,
        "storedPayloadHash": f"stored-payload-{source_identity}",
        "annotatedRaw": (
            f"{date} {payee}\n"
            f"    ; lf_source_identity: {source_identity}\n"
            f"    ; source_payload_hash: new-payload-{source_identity}\n"
            "    Assets:Bank:Checking  $-7.50\n"
            "    Expenses:Groceries\n"
        ),
        "sourceIdentity": source_identity,
        "sourcePayloadHash": f"new-payload-{source_identity}",
        "date": date,
        "payee": payee,
    }


def _prepared_fence_txn(
    *,
    date: str,
    payee: str,
    source_identity: str,
    reconciled_through: str,
    amount: str = "$-7.50",
) -> dict:
    return {
        "matchStatus": "conflict",
        "conflictReason": "reconciled_date_fence",
        "reconciledThrough": reconciled_through,
        # postings are read by _build_fence_conflicts to populate the amount
        # field on the user-facing conflict row.
        "postings": [
            {"account": "Assets:Bank:Checking", "amount": amount},
            {"account": "Expenses:Unknown", "amount": ""},
        ],
        "annotatedRaw": (
            f"{date} {payee}\n"
            f"    ; lf_source_identity: {source_identity}\n"
            f"    ; source_payload_hash: payload-{source_identity}\n"
            f"    Assets:Bank:Checking  {amount}\n"
            "    Expenses:Unknown\n"
        ),
        "sourceIdentity": source_identity,
        "sourcePayloadHash": f"payload-{source_identity}",
        "date": date,
        "payee": payee,
    }


def test_apply_import_skipped_count_folds_identity_collisions(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")

    stage = {
        "targetJournalPath": str(config.journal_dir / "2026.journal"),
        "preparedTransactions": [
            _prepared_txn(date="2026/03/01", payee="Coffee", source_identity="new-1", amount="$-4.00"),
            {
                "matchStatus": "duplicate",
                "sourceIdentity": "dup-1",
                "sourcePayloadHash": "payload-dup-1",
                "date": "2026/03/02",
                "payee": "Already Imported",
                "annotatedRaw": "2026/03/02 Already Imported\n",
            },
            _prepared_collision_txn(date="2026/03/03", payee="Rule-Edited Payee", source_identity="coll-1"),
            _prepared_collision_txn(date="2026/03/04", payee="Other Edit", source_identity="coll-2"),
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "deadbeef",
    }

    _, appended_count, skipped_count, conflicts = apply_import(config, stage)

    assert appended_count == 1, "Only the genuine new row should be written"
    # 1 duplicate + 2 identity collisions = 3 silent skips
    assert skipped_count == 3, "Identity collisions must fold into the skipped count"
    # No fence rows in this stage, so the conflicts list is empty
    assert conflicts == [], "Identity collisions must not appear in the conflicts list"


def _read_operation_events(workspace_root: Path) -> list[dict]:
    events_file = workspace_root / EVENTS_FILENAME
    if not events_file.exists():
        config = _make_config(workspace_root)
        return [
            {
                "id": op["id"],
                "type": op["type"],
                "summary": op["summary"],
                "payload": op["payload"],
                "journal_refs": op["files"],
                "actor": op["actor"],
                "compensates": op["compensates"],
            }
            for op in reversed(list_operations(config))
        ]
    return [
        json.loads(line)
        for line in events_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_apply_import_emits_identity_collision_diagnostic_event(tmp_path: Path) -> None:
    """Each identity-collision row produces one import.identity_collision.v1
    event with both the stored and the newly-computed payload hashes, so
    operators can diff the two off-line."""
    config = _make_config(tmp_path / "workspace")

    stage = {
        "targetJournalPath": str(config.journal_dir / "2026.journal"),
        "preparedTransactions": [
            _prepared_txn(date="2026/03/01", payee="Coffee", source_identity="new-1", amount="$-4.00"),
            _prepared_collision_txn(
                date="2026/03/02", payee="Rule-Edited Payee", source_identity="coll-1"
            ),
            _prepared_collision_txn(
                date="2026/03/03", payee="Another Edit", source_identity="coll-2"
            ),
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "deadbeef",
    }

    apply_import(config, stage)

    assert not (config.root_dir / EVENTS_FILENAME).exists()
    events = _read_operation_events(config.root_dir)
    collision_events = [e for e in events if e["type"] == "import.identity_collision.v1"]
    assert len(collision_events) == 2, "One event per identity-collision row"

    by_identity = {e["payload"]["source_identity"]: e for e in collision_events}
    coll_1 = by_identity["coll-1"]
    assert coll_1["payload"]["import_account_id"] == "wf_checking"
    assert coll_1["payload"]["stored_payload_hash"] == "stored-payload-coll-1"
    assert coll_1["payload"]["new_payload_hash"] == "new-payload-coll-1"
    assert coll_1["payload"]["target_journal"] == "journals/2026.journal"
    assert coll_1["payload"]["date"] == "2026/03/02"
    assert coll_1["payload"]["payee"] == "Rule-Edited Payee"
    assert coll_1["actor"] == "system"
    # Diagnostic only — no journal mutation tracking.
    assert coll_1["journal_refs"] == []


def test_apply_import_does_not_emit_events_for_fence_or_duplicate_rows(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")

    stage = {
        "targetJournalPath": str(config.journal_dir / "2026.journal"),
        "preparedTransactions": [
            _prepared_txn(date="2026/05/01", payee="Coffee", source_identity="new-1", amount="$-4.00"),
            {
                "matchStatus": "duplicate",
                "sourceIdentity": "dup-1",
                "sourcePayloadHash": "payload-dup-1",
                "date": "2026/05/02",
                "payee": "Duplicate Row",
                "annotatedRaw": "2026/05/02 Duplicate Row\n",
            },
            _prepared_fence_txn(
                date="2026/04/15",
                payee="Pre-Reconciliation",
                source_identity="fence-1",
                reconciled_through="2026-04-30",
            ),
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "deadbeef",
    }

    apply_import(config, stage)

    events = _read_operation_events(config.root_dir)
    collision_events = [e for e in events if e["type"] == "import.identity_collision.v1"]
    assert collision_events == [], "Only identity_collision conflicts emit diagnostic events"


def test_apply_import_conflicts_list_contains_only_fence_rows(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")

    stage = {
        "targetJournalPath": str(config.journal_dir / "2026.journal"),
        "preparedTransactions": [
            _prepared_txn(date="2026/05/01", payee="Coffee", source_identity="new-1", amount="$-4.00"),
            _prepared_collision_txn(date="2026/05/02", payee="Rule-Edited Payee", source_identity="coll-1"),
            _prepared_fence_txn(
                date="2026/04/15",
                payee="Pre-Reconciliation Activity",
                source_identity="fence-1",
                reconciled_through="2026-04-30",
            ),
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "deadbeef",
    }

    _, appended_count, skipped_count, conflicts = apply_import(config, stage)

    assert appended_count == 1
    # The identity collision counts toward skipped; the fence row does NOT
    # (it surfaces as a conflict instead).
    assert skipped_count == 1, "Only the identity collision folds into skipped; fence rows do not"
    assert len(conflicts) == 1, "Only the fence row appears in conflicts"
    assert conflicts[0]["conflictReason"] == "reconciled_date_fence"
    assert conflicts[0]["sourceIdentity"] == "fence-1"
    assert conflicts[0]["reconciledThrough"] == "2026-04-30"


def test_fence_conflict_row_carries_render_fields(tmp_path: Path) -> None:
    """The conflict-resolution view needs date, payee, and amount per fenced
    row to render in transactions-register style."""
    config = _make_config(tmp_path / "workspace")

    stage = {
        "targetJournalPath": str(config.journal_dir / "2026.journal"),
        # apply_import reads destinationAccount to attribute the institution-
        # side amount. _make_config wires wf_checking → Assets:Bank:Checking.
        "destinationAccount": "Assets:Bank:Checking",
        "preparedTransactions": [
            _prepared_fence_txn(
                date="2026/04/15",
                payee="Pre-Reconciliation Activity",
                source_identity="fence-1",
                reconciled_through="2026-04-30",
                amount="$-42.18",
            ),
        ],
        "importAccountId": "wf_checking",
        "year": "2026",
        "sourceFileSha256": "deadbeef",
    }

    _, _, _, conflicts = apply_import(config, stage)

    assert len(conflicts) == 1
    row = conflicts[0]
    assert row["date"] == "2026/04/15"
    assert row["payee"] == "Pre-Reconciliation Activity"
    assert row["amount"] == "$-42.18"
    assert row["reconciledThrough"] == "2026-04-30"
