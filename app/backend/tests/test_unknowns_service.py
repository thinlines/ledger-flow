from pathlib import Path

from services.unknowns_service import apply_unknown_mappings, scan_unknowns


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

    result = scan_unknowns(journal, accounts)
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["payeeDisplay"] == "Coffee Shop"
    assert len(group["txns"]) == 2


def test_apply_unknown_mappings_updates_journal_and_rules(tmp_path: Path) -> None:
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

    groups = scan_unknowns(journal, accounts)["groups"]
    txn_updates, rule_adds, warnings = apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        mappings={"coffee shop": "Expenses:Eating Out"},
        scanned_groups=groups,
    )

    assert txn_updates == 1
    assert rule_adds == 1
    assert warnings == []
    assert "Expenses:Eating Out" in journal.read_text(encoding="utf-8")
    assert "payee Coffee Shop" in accounts.read_text(encoding="utf-8")
