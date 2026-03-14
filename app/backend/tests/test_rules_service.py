from pathlib import Path

from services.rules_service import (
    create_rule,
    ensure_rules_store,
    find_matching_rule,
    load_rules,
    reorder_rules,
    update_rule,
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
    assert rules[0]["name"] == "Coffee Shop"
    assert rules[0]["conditions"][0]["value"] == "Coffee Shop"
    assert rules[0]["conditions"][0]["operator"] == "exact"
    assert rules[0]["actions"] == [{"type": "set_account", "account": "Expenses:Food"}]


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
        actions=[{"type": "set_account", "account": "Expenses:Coffee"}],
        enabled=True,
    )
    matched = find_matching_rule({"payee": "My Coffee Shop"}, load_rules(path))
    assert matched is not None
    assert matched["id"] == rule["id"]
    assert matched["name"] == 'Contains "coffee"'
    assert matched["conditions"][0]["joiner"] == "and"


def test_rule_supports_or_joiner(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")
    path = ensure_rules_store(rules_dir, accounts)

    rule = create_rule(
        path,
        conditions=[
            {"field": "payee", "operator": "contains", "value": "coffee"},
            {"field": "payee", "operator": "contains", "value": "books", "joiner": "or"},
        ],
        actions=[{"type": "set_account", "account": "Expenses:Mixed"}],
        enabled=True,
    )

    matched = find_matching_rule({"payee": "Neighborhood Books Store"}, load_rules(path))
    assert matched is not None
    assert matched["id"] == rule["id"]


def test_rule_supports_multiple_action_types(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")
    path = ensure_rules_store(rules_dir, accounts)

    created = create_rule(
        path,
        conditions=[{"field": "payee", "operator": "contains", "value": "airline"}],
        actions=[
            {"type": "set_account", "account": "Expenses:Travel"},
            {"type": "add_tag", "tag": "business"},
            {"type": "set_kv", "key": "project", "value": "client-x"},
            {"type": "append_comment", "text": "auto-categorized"},
        ],
        enabled=True,
    )
    loaded = load_rules(path)
    assert loaded[0]["id"] == created["id"]
    assert loaded[0]["actions"] == [
        {"type": "set_account", "account": "Expenses:Travel"},
        {"type": "add_tag", "tag": "business"},
        {"type": "set_kv", "key": "project", "value": "client-x"},
        {"type": "append_comment", "text": "auto-categorized"},
    ]


def test_rule_name_can_be_saved_and_updated(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")
    path = ensure_rules_store(rules_dir, accounts)

    created = create_rule(
        path,
        name="Morning coffee",
        conditions=[{"field": "payee", "operator": "contains", "value": "coffee"}],
        actions=[{"type": "set_account", "account": "Expenses:Coffee"}],
        enabled=True,
    )
    assert created["name"] == "Morning coffee"

    updated = update_rule(
        path,
        created["id"],
        name="Cafe visits",
    )
    assert updated["name"] == "Cafe visits"
    assert load_rules(path)[0]["name"] == "Cafe visits"


def test_rule_name_defaults_from_conditions_when_missing(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    path = rules_dir / "20-match-rules.ndjson"
    path.write_text(
        '{"id":"r1","type":"match","conditions":[{"field":"payee","operator":"exact","value":"Coffee Shop"}],"actions":[{"type":"set_account","account":"Expenses:Coffee"}],"enabled":true,"position":1}\n',
        encoding="utf-8",
    )

    loaded = load_rules(path)
    assert loaded[0]["name"] == "Coffee Shop"
