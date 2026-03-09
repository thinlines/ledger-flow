from services.import_service import _annotated_raw_txn, _classify_transaction, _parse_transaction


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
        "raw": "2026/03/01 Coffee Shop\n    Assets:Wells Fargo Checking  $-7.50\n    Expenses:Unknown\n",
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
