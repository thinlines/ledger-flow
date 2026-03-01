from pathlib import Path

from services.unknowns_service import add_payee_rule, apply_unknown_mappings, create_account, scan_unknowns


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
        [{"id": "r1", "type": "payee", "pattern": "Coffee Shop", "account": "Expenses:Eating Out", "enabled": True, "position": 1}],
    )
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["payeeDisplay"] == "Coffee Shop"
    assert len(group["txns"]) == 2
    assert group["suggestedAccount"] == "Expenses:Eating Out"
    assert group["matchedRuleId"] == "r1"


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
        [{"id": "r1", "type": "payee", "pattern": "Coffee Shop", "account": "Expenses:Eating Out", "enabled": True, "position": 1}],
    )["groups"]
    txn_updates, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        mappings={"coffee shop": "Expenses:Eating Out"},
        scanned_groups=groups,
    )

    assert txn_updates == 1
    assert warnings == []
    assert "Expenses:Eating Out" in journal.read_text(encoding="utf-8")


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
