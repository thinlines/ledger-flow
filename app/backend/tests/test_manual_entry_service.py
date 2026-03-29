from decimal import Decimal
from pathlib import Path

from services.manual_entry_service import (
    build_manual_transaction_block,
    create_manual_transaction,
    find_match_candidates,
    has_manual_tag,
    populate_match_candidates,
)
from services.unknowns_service import apply_unknown_mappings, scan_unknowns

from datetime import date


def _tracked_accounts() -> dict[str, dict]:
    return {
        "checking": {
            "display_name": "Checking",
            "ledger_account": "Assets:Bank:Checking",
            "import_account_id": "checking_import",
        },
        "savings": {
            "display_name": "Savings",
            "ledger_account": "Assets:Bank:Savings",
            "import_account_id": "savings_import",
        },
        "vehicle": {
            "display_name": "Vehicle",
            "ledger_account": "Assets:Vehicle:Subaru",
            "import_account_id": None,
        },
    }


def _import_accounts() -> dict[str, dict]:
    return {
        "checking_import": {
            "display_name": "Checking Import",
            "ledger_account": "Assets:Bank:Checking",
            "tracked_account_id": "checking",
        },
        "savings_import": {
            "display_name": "Savings Import",
            "ledger_account": "Assets:Bank:Savings",
            "tracked_account_id": "savings",
        },
    }


# ---------------------------------------------------------------------------
# Creation tests
# ---------------------------------------------------------------------------


def test_build_manual_transaction_block_has_manual_tag() -> None:
    block = build_manual_transaction_block(
        txn_date="2026-03-28",
        payee="Uber",
        amount=Decimal("45.95"),
        destination_account="Expenses:Transportation:Rides",
        tracked_ledger_account="Assets:Bank:Checking",
    )
    assert block[0] == "2026/03/28 Uber"
    assert block[1] == "    ; :manual:"
    assert "Expenses:Transportation:Rides" in block[2]
    assert "$45.95" in block[2]
    assert "Assets:Bank:Checking" in block[3]


def test_create_manual_transaction_writes_to_journal(tmp_path: Path) -> None:
    journal = tmp_path / "2026.journal"
    accounts = tmp_path / "10-accounts.dat"
    journal.write_text("", encoding="utf-8")
    accounts.write_text("account Expenses:Food\n    ; type: Expense\n", encoding="utf-8")

    result = create_manual_transaction(
        journal_path=journal,
        accounts_dat=accounts,
        tracked_account_cfg={"ledger_account": "Assets:Bank:Checking"},
        txn_date="2026-03-28",
        payee="Coffee Shop",
        amount_str="5.00",
        destination_account="Expenses:Food",
    )

    assert result["created"] is True
    assert result["warning"] is None

    content = journal.read_text(encoding="utf-8")
    assert "2026/03/28 Coffee Shop" in content
    assert "; :manual:" in content
    assert "Expenses:Food" in content
    assert "$5.00" in content
    assert "Assets:Bank:Checking" in content


def test_create_manual_transaction_inserts_in_date_order(tmp_path: Path) -> None:
    journal = tmp_path / "2026.journal"
    accounts = tmp_path / "10-accounts.dat"
    journal.write_text(
        """2026/03/01 Earlier
    Expenses:Food  $10.00
    Assets:Bank:Checking

2026/03/30 Later
    Expenses:Food  $20.00
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text("account Expenses:Food\n    ; type: Expense\n", encoding="utf-8")

    create_manual_transaction(
        journal_path=journal,
        accounts_dat=accounts,
        tracked_account_cfg={"ledger_account": "Assets:Bank:Checking"},
        txn_date="2026-03-15",
        payee="Middle Entry",
        amount_str="15.00",
        destination_account="Expenses:Food",
    )

    content = journal.read_text(encoding="utf-8")
    earlier_pos = content.index("Earlier")
    middle_pos = content.index("Middle Entry")
    later_pos = content.index("Later")
    assert earlier_pos < middle_pos < later_pos


def test_create_manual_transaction_warns_on_unknown_account(tmp_path: Path) -> None:
    journal = tmp_path / "2026.journal"
    accounts = tmp_path / "10-accounts.dat"
    journal.write_text("", encoding="utf-8")
    accounts.write_text("account Expenses:Food\n    ; type: Expense\n", encoding="utf-8")

    result = create_manual_transaction(
        journal_path=journal,
        accounts_dat=accounts,
        tracked_account_cfg={"ledger_account": "Assets:Bank:Checking"},
        txn_date="2026-03-28",
        payee="Uber",
        amount_str="45.95",
        destination_account="Expenses:Transport:New",
    )

    assert result["created"] is True
    assert result["warning"] is not None
    assert "not in accounts.dat" in result["warning"]


def test_manual_entry_has_no_import_metadata(tmp_path: Path) -> None:
    journal = tmp_path / "2026.journal"
    accounts = tmp_path / "10-accounts.dat"
    journal.write_text("", encoding="utf-8")
    accounts.write_text("", encoding="utf-8")

    create_manual_transaction(
        journal_path=journal,
        accounts_dat=accounts,
        tracked_account_cfg={"ledger_account": "Assets:Bank:Checking"},
        txn_date="2026-03-28",
        payee="Test",
        amount_str="10",
        destination_account="Expenses:Test",
    )

    content = journal.read_text(encoding="utf-8")
    assert "source_identity" not in content
    assert "import_account_id" not in content
    assert "source_payload_hash" not in content


# ---------------------------------------------------------------------------
# Match detection tests
# ---------------------------------------------------------------------------


def test_find_match_candidates_exact_date_amount(tmp_path: Path) -> None:
    journal_lines = [
        "2026/03/28 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal_lines,
        date(2026, 3, 28),
        Decimal("45.95"),
        "Uber",
        "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchQuality"] == "date_exact_amount"
    assert candidates[0]["matchTier"] == 1
    assert candidates[0]["destinationAccount"] == "Expenses:Rides"


def test_find_match_candidates_close_amount(tmp_path: Path) -> None:
    journal_lines = [
        "2026/03/28 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal_lines,
        date(2026, 3, 28),
        Decimal("47.95"),
        "Uber",
        "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchQuality"] == "date_close_amount"
    assert candidates[0]["matchTier"] == 2


def test_find_match_candidates_outside_date_window() -> None:
    journal_lines = [
        "2026/03/20 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal_lines,
        date(2026, 3, 28),
        Decimal("45.95"),
        "Something Else",
        "Assets:Bank:Checking",
    )
    # Date is 8 days away and payees don't match -> no candidates
    assert len(candidates) == 0


def test_find_match_candidates_payee_only_outside_window() -> None:
    journal_lines = [
        "2026/03/20 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal_lines,
        date(2026, 3, 28),
        Decimal("99.00"),
        "Uber Trip",
        "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchQuality"] == "payee_only"
    assert candidates[0]["matchTier"] == 4


def test_find_match_candidates_ignores_non_manual_entries() -> None:
    journal_lines = [
        "2026/03/28 Uber",
        "    ; import_account_id: checking_import",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal_lines,
        date(2026, 3, 28),
        Decimal("45.95"),
        "Uber",
        "Assets:Bank:Checking",
    )
    assert len(candidates) == 0


def test_find_match_candidates_ignores_unknown_destination() -> None:
    journal_lines = [
        "2026/03/28 Uber",
        "    ; :manual:",
        "    Expenses:Unknown  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal_lines,
        date(2026, 3, 28),
        Decimal("45.95"),
        "Uber",
        "Assets:Bank:Checking",
    )
    assert len(candidates) == 0


def test_match_candidates_not_on_non_import_account(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    Expenses:Rides  $45.95
    Assets:Vehicle:Subaru

2026/03/28 Uber
    Expenses:Unknown  $45.95
    Assets:Vehicle:Subaru
""",
        encoding="utf-8",
    )

    result = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())
    for group in result["groups"]:
        for txn in group["txns"]:
            assert "matchCandidates" not in txn or len(txn.get("matchCandidates", [])) == 0


def test_scan_unknowns_populates_match_candidates(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    Expenses:Transportation:Rides  $45.95
    Assets:Bank:Checking

2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber
    Expenses:Unknown  $45.95
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )

    result = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    txn = group["txns"][0]
    assert "matchCandidates" in txn
    assert len(txn["matchCandidates"]) == 1
    assert txn["matchCandidates"][0]["matchQuality"] == "date_exact_amount"
    assert txn["suggestedMatchId"] is not None


def test_scan_unknowns_preselects_single_tier1_match(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    Expenses:Rides  $45.95
    Assets:Bank:Checking

2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber
    Expenses:Unknown  $45.95
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )

    result = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())
    txn = result["groups"][0]["txns"][0]
    assert txn["suggestedMatchId"] == txn["matchCandidates"][0]["manualTxnId"]


# ---------------------------------------------------------------------------
# Apply match tests
# ---------------------------------------------------------------------------


def test_apply_match_replaces_unknown_and_removes_manual(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    Expenses:Transportation:Rides  $45.95
    Assets:Bank:Checking

2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber
    Expenses:Unknown  $45.95
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text(
        """account Expenses:Transportation:Rides
    ; type: Expense

account Assets:Bank:Checking
    ; type: Cash
""",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    assert len(groups) == 1
    txn = groups[0]["txns"][0]
    assert "matchCandidates" in txn

    candidate = txn["matchCandidates"][0]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            groups[0]["groupKey"]: {
                "selectionType": "match",
                "matchedManualTxnId": candidate["manualTxnId"],
                "matchedManualLineRange": [candidate["lineStart"], candidate["lineEnd"]],
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    assert txn_updates == 1
    # The imported transaction should now have the manual entry's destination account.
    assert "Expenses:Transportation:Rides" in content
    assert "Expenses:Unknown" not in content
    # The :manual: tag should be on the imported transaction.
    assert "; :manual:" in content
    # The original manual entry should be removed (only one transaction left).
    txn_count = content.count("2026/03/28 Uber")
    assert txn_count == 1
    # Import metadata should still be on the remaining transaction.
    assert "; source_identity: tx-uber" in content


def test_apply_match_preserves_import_amount_when_amounts_differ(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    Expenses:Rides  $45.95
    Assets:Bank:Checking

2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber
    Expenses:Unknown  $47.95
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text(
        """account Expenses:Rides
    ; type: Expense

account Assets:Bank:Checking
    ; type: Cash
""",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    candidate = groups[0]["txns"][0]["matchCandidates"][0]

    apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            groups[0]["groupKey"]: {
                "selectionType": "match",
                "matchedManualTxnId": candidate["manualTxnId"],
                "matchedManualLineRange": [candidate["lineStart"], candidate["lineEnd"]],
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    # The imported amount ($47.95) is canonical — it stays.
    assert "$47.95" in content
    # The manual amount ($45.95) is gone.
    assert "$45.95" not in content
    # The destination was carried over.
    assert "Expenses:Rides" in content


def test_apply_match_warns_on_stale_manual_entry(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber
    Expenses:Unknown  $45.95
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text(
        """account Assets:Bank:Checking
    ; type: Cash
""",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    _, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            groups[0]["groupKey"]: {
                "selectionType": "match",
                "matchedManualTxnId": "manual:999",
                "matchedManualLineRange": [999, 1002],
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    assert len(warnings) > 0
    assert any("no longer available" in w.get("warning", "").lower() for w in warnings)


def test_apply_match_carries_user_metadata(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    ; note: business trip
    Expenses:Rides  $45.95
    Assets:Bank:Checking

2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber
    Expenses:Unknown  $45.95
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text(
        """account Expenses:Rides
    ; type: Expense

account Assets:Bank:Checking
    ; type: Cash
""",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    candidate = groups[0]["txns"][0]["matchCandidates"][0]

    apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            groups[0]["groupKey"]: {
                "selectionType": "match",
                "matchedManualTxnId": candidate["manualTxnId"],
                "matchedManualLineRange": [candidate["lineStart"], candidate["lineEnd"]],
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    # User metadata "note: business trip" should be carried over.
    assert "; note: business trip" in content
    # The imported transaction should have both import metadata and carried metadata.
    assert "; source_identity: tx-uber" in content


def test_existing_category_and_transfer_flows_unaffected(tmp_path: Path) -> None:
    """Match candidates should not break existing category assignment flow."""
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """2026/02/01 Coffee Shop
    ; import_account_id: checking_import
    Expenses:Unknown  $5.00
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text(
        """account Expenses:Food
    ; type: Expense

account Assets:Bank:Checking
    ; type: Cash
""",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            groups[0]["groupKey"]: {
                "selectionType": "category",
                "categoryAccount": "Expenses:Food",
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    assert txn_updates == 1
    assert warnings == []
    assert "Expenses:Food" in journal.read_text(encoding="utf-8")
