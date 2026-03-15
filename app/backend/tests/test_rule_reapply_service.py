from pathlib import Path

from services.rule_reapply_service import apply_rule_reapply, scan_rule_reapply
from services.rules_service import create_rule, ensure_rules_store, load_rules


def test_scan_rule_reapply_finds_safe_historical_candidates(tmp_path: Path) -> None:
    journal = tmp_path / "2026.journal"
    journal.write_text(
        """
2026/01/15 Coffee Shop
    ; import_account_id: checking
    Expenses:Food:Groceries  $5.00
    Assets:Bank:Checking

2026/02/15 Coffee Shop
    ; import_account_id: checking
    Expenses:Food:Groceries  $7.00
    Assets:Bank:Checking

2026/02/20 Coffee Shop
    ; import_account_id: checking
    Expenses:Food:Shopping  $8.00
    Assets:Bank:Checking

2026/02/21 Coffee Shop
    ; import_account_id: checking
    Expenses:Food:Groceries  $4.00
    Expenses:Tips  $1.00
    Assets:Bank:Checking

2026/02/22 Coffee Shop
    ; import_account_id: checking
    Assets:Savings  $10.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text(
        """
account Expenses:Food:Groceries
    ; type: Expense

account Expenses:Food:Shopping
    ; type: Expense

account Expenses:Tips
    ; type: Expense

account Assets:Bank:Checking
    ; type: Asset

account Assets:Savings
    ; type: Asset
""".strip()
        + "\n",
        encoding="utf-8",
    )
    path = ensure_rules_store(rules_dir, accounts)
    create_rule(
        path,
        conditions=[
            {"field": "payee", "operator": "contains", "value": "coffee"},
            {"field": "date", "operator": "on_or_after", "value": "2026-02-01", "joiner": "and"},
        ],
        actions=[{"type": "set_account", "account": "Expenses:Food:Shopping"}],
        enabled=True,
    )
    rule = load_rules(path)[0]

    result = scan_rule_reapply(
        journal,
        rule,
        {
            "checking": {
                "display_name": "Primary Checking",
                "ledger_account": "Assets:Bank:Checking",
            }
        },
    )

    assert result["summary"] == {
        "matchedCount": 4,
        "candidateCount": 1,
        "upToDateCount": 1,
        "skippedCount": 2,
    }
    assert result["candidates"] == [
        {
            "id": "2026.journal:8",
            "date": "2026-02-15",
            "payee": "Coffee Shop",
            "amount": "$7.00",
            "lineNo": 8,
            "currentAccount": "Expenses:Food:Groceries",
            "targetAccount": "Expenses:Food:Shopping",
            "importAccountId": "checking",
            "sourceAccountLabel": "Primary Checking",
            "sourceLedgerAccount": "Assets:Bank:Checking",
        }
    ]
    assert len(result["warnings"]) == 2


def test_apply_rule_reapply_updates_selected_candidates(tmp_path: Path) -> None:
    journal = tmp_path / "2026.journal"
    journal.write_text(
        """
2026/02/15 Coffee Shop
    ; import_account_id: checking
    Expenses:Food:Groceries  $7.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    accounts = tmp_path / "10-accounts.dat"
    accounts.write_text(
        """
account Expenses:Food:Groceries
    ; type: Expense

account Expenses:Food:Shopping
    ; type: Expense
""".strip()
        + "\n",
        encoding="utf-8",
    )

    updated_count, warnings = apply_rule_reapply(
        journal_path=journal,
        accounts_dat=accounts,
        candidates=[
            {
                "id": "2026.journal:3",
                "lineNo": 3,
                "currentAccount": "Expenses:Food:Groceries",
                "targetAccount": "Expenses:Food:Shopping",
            }
        ],
        selected_candidate_ids=["2026.journal:3"],
    )

    assert updated_count == 1
    assert warnings == []
    assert "Expenses:Food:Shopping  $7.00" in journal.read_text(encoding="utf-8")
