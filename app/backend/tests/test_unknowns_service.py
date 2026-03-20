from pathlib import Path

from services.unknowns_service import add_payee_rule, apply_unknown_mappings, create_account, scan_unknowns
from services.transfer_service import transfer_pair_account


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
        "visa_import": {
            "display_name": "Visa Import",
            "ledger_account": "Liabilities:Cards:Visa",
            "tracked_account_id": "visa",
        },
    }


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
        "visa": {
            "display_name": "Visa",
            "ledger_account": "Liabilities:Cards:Visa",
            "import_account_id": "visa_import",
        },
        "vehicle": {
            "display_name": "Vehicle",
            "ledger_account": "Assets:Vehicle:Subaru",
        },
        "auto_loan": {
            "display_name": "Auto Loan",
            "ledger_account": "Liabilities:Loans:Auto",
        },
    }


def test_scan_unknowns_groups_by_payee(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """
2026/02/01 Coffee Shop
    Expenses:Unknown  $5.00
    Assets:Wells Fargo Checking

2026/02/02 Coffee Shop
    Expenses:Unknown  $7.00
    Assets:Wells Fargo Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts.write_text(
        """
account Expenses:Eating Out
	payee Burger King
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = scan_unknowns(
        journal,
        [{
            "id": "r1",
            "type": "match",
            "conditions": [{"field": "payee", "operator": "contains", "value": "coffee"}],
            "actions": [{"type": "set_account", "account": "Expenses:Eating Out"}],
            "enabled": True,
            "position": 1,
        }],
    )
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["payeeDisplay"] == "Coffee Shop"
    assert len(group["txns"]) == 2
    assert group["suggestedAccount"] == "Expenses:Eating Out"
    assert group["matchedRuleId"] == "r1"
    assert group["sourceAccountLabel"] == "Assets:Wells Fargo Checking"
    assert group["sourceLedgerAccount"] == "Assets:Wells Fargo Checking"


def test_scan_unknowns_splits_groups_by_import_account(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    journal.write_text(
        """
2026/02/01 Coffee Shop
    ; import_account_id: checking
    Expenses:Unknown  $5.00
    Assets:Bank:Checking

2026/02/02 Coffee Shop
    ; import_account_id: visa
    Expenses:Unknown  $7.00
    Liabilities:Cards:Visa
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = scan_unknowns(
        journal,
        [],
        {
            "checking": {"display_name": "Primary Checking", "ledger_account": "Assets:Bank:Checking"},
            "visa": {"display_name": "Travel Visa", "ledger_account": "Liabilities:Cards:Visa"},
        },
    )

    assert len(result["groups"]) == 2
    groups = {group["groupKey"]: group for group in result["groups"]}
    assert groups["coffee shop::checking"]["sourceAccountLabel"] == "Primary Checking"
    assert groups["coffee shop::checking"]["sourceLedgerAccount"] == "Assets:Bank:Checking"
    assert groups["coffee shop::visa"]["sourceAccountLabel"] == "Travel Visa"
    assert groups["coffee shop::visa"]["sourceLedgerAccount"] == "Liabilities:Cards:Visa"


def test_scan_unknowns_only_suggests_date_rule_when_all_group_transactions_match(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    journal.write_text(
        """
2026/01/10 Coffee Shop
    Expenses:Unknown  $5.00
    Assets:Bank:Checking

2026/03/10 Coffee Shop
    Expenses:Unknown  $7.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = scan_unknowns(
        journal,
        [{
            "id": "r1",
            "type": "match",
            "conditions": [
                {"field": "payee", "operator": "contains", "value": "coffee"},
                {"field": "date", "operator": "before", "value": "2026-02-01", "joiner": "and"},
            ],
            "actions": [{"type": "set_account", "account": "Expenses:Eating Out"}],
            "enabled": True,
            "position": 1,
        }],
    )

    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["suggestedAccount"] is None
    assert group["matchedRuleId"] is None


def test_apply_unknown_mappings_updates_journal_only(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """
2026/02/01 Coffee Shop
    Expenses:Unknown  $5.00
    Assets:Wells Fargo Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts.write_text(
        """
account Expenses:Eating Out
    ; type: Expense

account Assets:Wells Fargo Checking
    ; type: Cash
""".strip()
        + "\n",
        encoding="utf-8",
    )

    groups = scan_unknowns(
        journal,
        [{
            "id": "r1",
            "type": "match",
            "conditions": [{"field": "payee", "operator": "contains", "value": "coffee"}],
            "actions": [{"type": "set_account", "account": "Expenses:Eating Out"}],
            "enabled": True,
            "position": 1,
        }],
    )["groups"]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            "coffee shop": {
                "selectionType": "category",
                "categoryAccount": "Expenses:Eating Out",
            }
        },
        scanned_groups=groups,
        tracked_accounts={},
    )

    assert txn_updates == 1
    assert warnings == []
    assert "Expenses:Eating Out" in journal.read_text(encoding="utf-8")


def test_scan_unknowns_suggests_unique_transfer_match(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    journal.write_text(
        """
2026/02/01 Transfer
    ; import_account_id: checking_import
    Expenses:Unknown  $50.00
    Assets:Bank:Checking

2026/02/03 Transfer
    ; import_account_id: savings_import
    Expenses:Unknown  $-50.00
    Assets:Bank:Savings
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())

    checking_group = next(group for group in result["groups"] if group["groupKey"] == "transfer::checking_import")
    suggestion = checking_group["txns"][0]["transferSuggestion"]
    assert suggestion is not None
    assert suggestion["targetTrackedAccountId"] == "savings"
    assert suggestion["targetTrackedAccountName"] == "Savings"


def test_scan_unknowns_leaves_transfer_unsuggested_when_match_is_ambiguous(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    journal.write_text(
        """
2026/02/01 Transfer
    ; import_account_id: checking_import
    Expenses:Unknown  $50.00
    Assets:Bank:Checking

2026/02/02 Transfer
    ; import_account_id: savings_import
    Expenses:Unknown  $-50.00
    Assets:Bank:Savings

2026/02/03 Transfer
    ; import_account_id: savings_import
    Expenses:Unknown  $-50.00
    Assets:Bank:Savings
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())

    checking_group = next(group for group in result["groups"] if group["groupKey"] == "transfer::checking_import")
    assert checking_group["txns"][0]["transferSuggestion"] is None


def test_apply_unknown_mappings_creates_pending_asset_transfer(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"
    transfer_account = transfer_pair_account("checking", "savings")

    journal.write_text(
        """
2026/02/01 Transfer to savings
    ; import_account_id: checking_import
    ; source_identity: tx-checking
    Expenses:Unknown  $50.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts.write_text(
        """
account Assets:Bank:Checking
    ; type: Cash

account Assets:Bank:Savings
    ; type: Cash
""".strip()
        + "\n",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            "transfer to savings::checking_import": {
                "selectionType": "transfer",
                "targetTrackedAccountId": "savings",
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    assert txn_updates == 1
    assert warnings == []
    assert transfer_account in content
    assert "; transfer_state: pending" in content
    assert "; transfer_peer_account_id: savings" in content
    assert f"account {transfer_account}" in accounts.read_text(encoding="utf-8")


def test_apply_unknown_mappings_matches_both_imported_transfer_sides(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"
    transfer_account = transfer_pair_account("checking", "savings")

    journal.write_text(
        """
2026/02/01 Transfer
    ; import_account_id: checking_import
    ; source_identity: tx-checking
    Expenses:Unknown  $50.00
    Assets:Bank:Checking

2026/02/03 Transfer
    ; import_account_id: savings_import
    ; source_identity: tx-savings
    Expenses:Unknown  $-50.00
    Assets:Bank:Savings
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts.write_text(
        """
account Assets:Bank:Checking
    ; type: Cash

account Assets:Bank:Savings
    ; type: Cash
""".strip()
        + "\n",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            "transfer::checking_import": {
                "selectionType": "transfer",
                "targetTrackedAccountId": "savings",
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    assert txn_updates == 2
    assert warnings == []
    assert content.count(transfer_account) == 2
    assert content.count("; transfer_state: matched") == 2
    assert "; transfer_peer_account_id: savings" in content
    assert "; transfer_peer_account_id: checking" in content

    transfer_ids = {
        line.partition(":")[2].strip()
        for line in content.splitlines()
        if line.strip().startswith("; transfer_id:")
    }
    assert len(transfer_ids) == 1


def test_apply_unknown_mappings_creates_pending_liability_transfer(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"
    transfer_account = transfer_pair_account("checking", "visa")

    journal.write_text(
        """
2026/02/01 Credit card payment
    ; import_account_id: checking_import
    ; source_identity: tx-checking
    Expenses:Unknown  $50.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts.write_text(
        """
account Assets:Bank:Checking
    ; type: Cash

account Liabilities:Cards:Visa
    ; type: Liability
""".strip()
        + "\n",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            "credit card payment::checking_import": {
                "selectionType": "transfer",
                "targetTrackedAccountId": "visa",
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    assert txn_updates == 1
    assert warnings == []
    assert transfer_account in content
    assert "; transfer_state: pending" in content
    assert "; transfer_peer_account_id: visa" in content
    assert f"account {transfer_account}" in accounts.read_text(encoding="utf-8")


def test_apply_unknown_mappings_posts_directly_to_manual_asset_account(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """
2026/02/01 Vehicle purchase
    ; import_account_id: checking_import
    ; source_identity: tx-checking
    Expenses:Unknown  $50.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts.write_text(
        """
account Assets:Bank:Checking
    ; type: Cash

account Assets:Vehicle:Subaru
    ; type: Asset
""".strip()
        + "\n",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            "vehicle purchase::checking_import": {
                "selectionType": "transfer",
                "targetTrackedAccountId": "vehicle",
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    assert txn_updates == 1
    assert warnings == []
    assert "Assets:Vehicle:Subaru" in content
    assert "Expenses:Unknown" not in content
    assert "; transfer_state:" not in content
    assert "; transfer_peer_account_id:" not in content
    assert "Assets:Transfers:" not in content
    assert "Assets:Transfers:" not in accounts.read_text(encoding="utf-8")


def test_apply_unknown_mappings_posts_directly_to_manual_liability_account(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"

    journal.write_text(
        """
2026/02/01 Auto loan payment
    ; import_account_id: checking_import
    ; source_identity: tx-checking
    Expenses:Unknown  $50.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts.write_text(
        """
account Assets:Bank:Checking
    ; type: Cash

account Liabilities:Loans:Auto
    ; type: Liability
""".strip()
        + "\n",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            "auto loan payment::checking_import": {
                "selectionType": "transfer",
                "targetTrackedAccountId": "auto_loan",
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    assert txn_updates == 1
    assert warnings == []
    assert "Liabilities:Loans:Auto" in content
    assert "Expenses:Unknown" not in content
    assert "; transfer_state:" not in content
    assert "; transfer_peer_account_id:" not in content
    assert "Assets:Transfers:" not in content
    assert "Assets:Transfers:" not in accounts.read_text(encoding="utf-8")


def test_apply_unknown_mappings_matches_pending_transfer_when_counterpart_arrives(tmp_path: Path) -> None:
    journal = tmp_path / "sample.journal"
    accounts = tmp_path / "10-accounts.dat"
    transfer_account = transfer_pair_account("checking", "savings")

    journal.write_text(
        f"""
2026/02/01 Transfer
    ; import_account_id: checking_import
    ; source_identity: tx-checking
    ; transfer_id: transfer-1
    ; transfer_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $50.00
    Assets:Bank:Checking

2026/02/03 Transfer
    ; import_account_id: savings_import
    ; source_identity: tx-savings
    Expenses:Unknown  $-50.00
    Assets:Bank:Savings
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts.write_text(
        f"""
account Assets:Bank:Checking
    ; type: Cash

account Assets:Bank:Savings
    ; type: Cash

account {transfer_account}
    ; type: Asset
    ; description: Internal transfer clearing account
""".strip()
        + "\n",
        encoding="utf-8",
    )

    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    savings_group = next(group for group in groups if group["groupKey"] == "transfer::savings_import")
    suggestion = savings_group["txns"][0]["transferSuggestion"]
    assert suggestion is not None
    assert suggestion["candidateState"] == "pending"
    assert suggestion["targetTrackedAccountId"] == "checking"

    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            "transfer::savings_import": {
                "selectionType": "transfer",
                "targetTrackedAccountId": "checking",
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )

    content = journal.read_text(encoding="utf-8")
    assert txn_updates == 2
    assert warnings == []
    assert content.count("; transfer_state: matched") == 2
    assert "; transfer_id: transfer-1" in content


def test_add_payee_rule_adds_mapping(tmp_path: Path) -> None:
    accounts = tmp_path / "10-accounts.dat"
    accounts.write_text(
        """
account Expenses:Eating Out
    ; type: Expense
""".strip()
        + "\n",
        encoding="utf-8",
    )
    added, warning = add_payee_rule(accounts, "Coffee Shop", "Expenses:Eating Out")
    assert added is True
    assert warning is None
    assert "payee Coffee Shop" in accounts.read_text(encoding="utf-8")


def test_add_payee_rule_updates_existing_mapping(tmp_path: Path) -> None:
    accounts = tmp_path / "10-accounts.dat"
    accounts.write_text(
        """
account Expenses:Eating Out
    ; type: Expense
    payee Coffee Shop

account Expenses:Coffee
    ; type: Expense
""".strip()
        + "\n",
        encoding="utf-8",
    )
    added, warning = add_payee_rule(accounts, "Coffee Shop", "Expenses:Coffee")
    assert added is True
    assert warning is None
    content = accounts.read_text(encoding="utf-8")
    assert "payee Coffee Shop" in content
    assert "account Expenses:Eating Out\n    ; type: Expense\n    payee Coffee Shop" not in content


def test_create_account_appends_account_block(tmp_path: Path) -> None:
    accounts = tmp_path / "10-accounts.dat"
    accounts.write_text("account Expenses:Eating Out\n    ; type: Expense\n", encoding="utf-8")
    added, warning = create_account(accounts, "Assets:Transfers")
    assert added is True
    assert warning is None
    content = accounts.read_text(encoding="utf-8")
    assert "account Assets:Transfers" in content
    assert "; type: Asset" in content


def test_create_account_respects_explicit_account_type(tmp_path: Path) -> None:
    accounts = tmp_path / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")
    added, warning = create_account(accounts, "Assets:Cashbox", "Cash")
    assert added is True
    assert warning is None
    assert "; type: Cash" in accounts.read_text(encoding="utf-8")


def test_create_account_writes_description_metadata(tmp_path: Path) -> None:
    accounts = tmp_path / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")

    added, warning = create_account(
        accounts,
        "Assets:Bank:Savings",
        description="Emergency fund",
    )

    assert added is True
    assert warning is None
    assert "; description: Emergency fund" in accounts.read_text(encoding="utf-8")


def test_create_account_omits_blank_description_metadata(tmp_path: Path) -> None:
    accounts = tmp_path / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")

    added, warning = create_account(
        accounts,
        "Assets:Bank:Checking",
        description=" \n  ",
    )

    assert added is True
    assert warning is None
    assert "; description:" not in accounts.read_text(encoding="utf-8")
