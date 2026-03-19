from pathlib import Path

from services.config_service import AppConfig
from services.import_service import apply_import, archive_inbox_csv


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
        payee_aliases="payee_aliases.csv",
    )


def _prepared_txn(*, date: str, payee: str, source_identity: str, amount: str) -> dict:
    return {
        "matchStatus": "new",
        "annotatedRaw": (
            f"{date} {payee}\n"
            f"    ; source_identity: {source_identity}\n"
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
                    "    ; source_identity: txn-1\n"
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
                "    ; source_identity: existing-txn",
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
