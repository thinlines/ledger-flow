from pathlib import Path

from services.rules_service import (
    find_matching_rule,
    ensure_rules_store,
    load_rules,
    create_rule,
    reorder_rules,
    upsert_payee_rule,
)


def test_ensure_rules_store_migrates_legacy_payee_rules(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text(
        """
account Expenses:Food
    ; type: Expense
    payee Coffee Shop
""".strip()
        + "\n",
        encoding="utf-8",
    )
    path = ensure_rules_store(rules_dir, accounts)
    rules = load_rules(path)
    assert len(rules) == 1
    assert rules[0]["conditions"][0]["value"] == "Coffee Shop"
    assert rules[0]["conditions"][0]["operator"] == "exact"
    assert rules[0]["account"] == "Expenses:Food"


def test_upsert_and_reorder_rules(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")
    path = ensure_rules_store(rules_dir, accounts)
    rule1, changed1 = upsert_payee_rule(path, "Coffee Shop", "Expenses:Coffee")
    rule2, changed2 = upsert_payee_rule(path, "Book Store", "Expenses:Books")
    assert changed1 is True
    assert changed2 is True

    reordered = reorder_rules(path, [rule2["id"], rule1["id"]])
    assert reordered[0]["id"] == rule2["id"]
    assert reordered[1]["id"] == rule1["id"]


def test_rule_supports_contains_operator(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")
    path = ensure_rules_store(rules_dir, accounts)
    rule = create_rule(
        path,
        conditions=[{"field": "payee", "operator": "contains", "value": "coffee"}],
        account="Expenses:Coffee",
        enabled=True,
    )
    matched = find_matching_rule({"payee": "My Coffee Shop"}, load_rules(path))
    assert matched is not None
    assert matched["id"] == rule["id"]
