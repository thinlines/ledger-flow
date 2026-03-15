from pathlib import Path

from services.config_service import AppConfig
from services.import_index import ImportIndex
from services.import_service import _annotated_raw_txn, _build_existing_map, _classify_transaction, _parse_transaction


def test_parse_transaction_builds_stable_identity() -> None:
    txn = _parse_transaction(
        [
            "2026/03/01 Coffee Shop",
            "    Assets:Wells Fargo Checking  $-7.50",
            "    Expenses:Unknown",
        ],
        import_account_id="wf_checking",
        institution_account="Assets:Wells Fargo Checking",
    )
    assert txn["sourceIdentity"]
    assert txn["sourcePayloadHash"]
    assert txn["payee"] == "Coffee Shop"


def test_parse_transaction_payload_hash_ignores_import_account_name_changes() -> None:
    before = _parse_transaction(
        [
            "2026/03/01 Coffee Shop",
            "    Assets:Bank:Checking  $-7.50",
            "    Expenses:Unknown",
        ],
        import_account_id="wf_checking",
        institution_account="Assets:Bank:Checking",
    )
    after = _parse_transaction(
        [
            "2026/03/01 Coffee Shop",
            "    Assets:Bank:Primary:Checking  $-7.50",
            "    Expenses:Unknown",
        ],
        import_account_id="wf_checking",
        institution_account="Assets:Bank:Primary:Checking",
    )

    assert before["sourceIdentity"] == after["sourceIdentity"]
    assert before["sourcePayloadHash"] == after["sourcePayloadHash"]


def test_classify_transaction_new_duplicate_conflict() -> None:
    txn = {
        "sourceIdentity": "abc",
        "sourcePayloadHash": "hash1",
    }
    assert _classify_transaction(txn, {}) == "new"
    assert _classify_transaction(txn, {"abc": None}) == "duplicate"
    assert _classify_transaction(txn, {"abc": "hash1"}) == "duplicate"
    assert _classify_transaction(txn, {"abc": "other"}) == "conflict"


def test_annotated_raw_txn_adds_import_metadata() -> None:
    txn = {
        "raw": (
            "2026/03/01 Coffee Shop\n"
            "    Assets:Wells Fargo Checking  1200.00 $\n"
            "    Expenses:Unknown  -7.50 $ = 1192.50 $\n"
        ),
        "sourceIdentity": "identity123",
        "sourcePayloadHash": "payload123",
    }
    out = _annotated_raw_txn(
        txn,
        source_file_sha256="filehash",
        import_account_id="wf_checking",
        institution_template_id="wells_fargo",
    )
    assert "; import_account_id: wf_checking" in out
    assert "; institution_template: wells_fargo" in out
    assert "; source_identity: identity123" in out
    assert "; source_payload_hash: payload123" in out
    assert "; source_file_sha256: filehash" in out
    assert "; importer_version: mvp2" in out
    assert "Assets:Wells Fargo Checking  $1200.00" in out
    assert "Expenses:Unknown  $-7.50 = $1192.50" in out


def test_build_existing_map_prefers_canonical_journal_hash_over_legacy_stored_hash(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    config = AppConfig(
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
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Bank:Primary:Checking",
                "tracked_account_id": "checking",
            }
        },
        tracked_accounts={
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Bank:Primary:Checking",
                "import_account_id": "checking",
            }
        },
        payee_aliases="payee_aliases.csv",
    )

    reparsed = _parse_transaction(
        [
            "2026/03/01 Coffee Shop",
            "    Assets:Bank:Primary:Checking  $-7.50",
            "    Expenses:Food",
        ],
        import_account_id="checking",
        institution_account="Assets:Bank:Primary:Checking",
    )
    legacy_hash = "legacyhash123"
    journal_path = workspace / "journals" / "2026.journal"
    journal_path.write_text(
        "2026/03/01 Coffee Shop\n"
        "    ; import_account_id: checking\n"
        f"    ; source_identity: {reparsed['sourceIdentity']}\n"
        f"    ; source_payload_hash: {legacy_hash}\n"
        "    Assets:Bank:Primary:Checking  $-7.50\n"
        "    Expenses:Food\n",
        encoding="utf-8",
    )
    ImportIndex(workspace / ".workflow" / "state.db").upsert_transactions(
        import_account_id="checking",
        year="2026",
        journal_path=journal_path,
        source_file_sha256="source-file-1",
        txns=[
            {
                "sourceIdentity": reparsed["sourceIdentity"],
                "sourcePayloadHash": legacy_hash,
            }
        ],
    )

    existing_map = _build_existing_map(config, "checking", journal_path)

    assert existing_map[reparsed["sourceIdentity"]] == reparsed["sourcePayloadHash"]
