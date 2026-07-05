from pathlib import Path

from services.config_service import AppConfig
from services.projection_db import connect, ensure_database
from services.rules_service import (
    create_rule,
    delete_rule,
    ensure_rules_store,
    find_matching_rule,
    load_rules,
    reorder_rules,
    update_rule,
    upsert_payee_rule,
)


def _make_config(workspace: Path) -> AppConfig:
    for name in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / name).mkdir(parents=True, exist_ok=True)
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "base_currency": "USD", "start_year": 2026},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
        tracked_accounts={},
    )


def test_ensure_rules_store_seeds_ndjson_into_database_once(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    db_path = ensure_database(config)
    rules_file = config.init_dir / "20-match-rules.ndjson"
    rules_file.write_text(
        "\n".join(
            [
                '{"id":"r1","type":"match","name":"Coffee","conditions":[{"field":"payee","operator":"contains","value":"coffee"},{"field":"date","operator":"on_or_after","value":"2026-01-01","joiner":"and"},{"field":"payee","operator":"contains","value":"cafe","joiner":"or"}],"actions":[{"type":"set_account","account":"Expenses:Coffee"}],"enabled":true,"position":1,"createdAt":"2026-01-02T00:00:00+00:00","updatedAt":"2026-01-02T00:00:00+00:00"}',
                "",
            ]
        ),
        encoding="utf-8",
    )

    store = ensure_rules_store(config.init_dir, config.init_dir / "10-accounts.dat")
    rules = load_rules(store)

    assert not rules_file.exists()
    assert rules[0]["id"] == "r1"
    assert rules[0]["conditions"] == [
        {"field": "payee", "operator": "contains", "value": "coffee", "joiner": "and"},
        {"field": "date", "operator": "on_or_after", "value": "2026-01-01", "joiner": "and"},
        {"field": "payee", "operator": "contains", "value": "cafe", "joiner": "or"},
    ]
    assert find_matching_rule({"payee": "Corner Cafe", "date": "2025-12-31"}, rules)["id"] == "r1"
    assert find_matching_rule({"payee": "Coffee Shop", "date": "2026-02-01"}, rules)["id"] == "r1"
    assert find_matching_rule({"payee": "Coffee Shop", "date": "2025-12-31"}, rules) is None

    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM rule_condition_groups").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM rule_conditions").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM rule_actions").fetchone()[0] == 1

    ensure_rules_store(config.init_dir, config.init_dir / "10-accounts.dat")
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 1


def test_rule_mutations_are_recorded_as_operations(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    store = ensure_rules_store(config.init_dir, config.init_dir / "10-accounts.dat")

    created = create_rule(
        store,
        name="Coffee",
        conditions=[{"field": "payee", "operator": "contains", "value": "coffee"}],
        actions=[{"type": "set_account", "account": "Expenses:Coffee"}],
    )
    update_rule(store, created["id"], enabled=False)
    delete_rule(store, created["id"])

    with connect(ensure_database(config)) as conn:
        rows = conn.execute(
            "SELECT type, summary, payload_json FROM operations ORDER BY rowid"
        ).fetchall()

    assert [row[0] for row in rows] == [
        "rule.created.v1",
        "rule.updated.v1",
        "rule.deleted.v1",
    ]
    assert rows[0][1] == "Created rule: Coffee"
    assert f'"rule_id":"{created["id"]}"' in rows[2][2]


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


def test_rule_or_groups_match_with_and_conditions_inside_each_group(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")
    path = ensure_rules_store(rules_dir, accounts)

    rule = create_rule(
        path,
        conditions=[
            {"field": "payee", "operator": "contains", "value": "coffee"},
            {"field": "date", "operator": "before", "value": "2026-02-01", "joiner": "and"},
            {"field": "payee", "operator": "contains", "value": "books", "joiner": "or"},
            {"field": "date", "operator": "on_or_after", "value": "2026-03-01", "joiner": "and"},
        ],
        actions=[{"type": "set_account", "account": "Expenses:Mixed"}],
        enabled=True,
    )
    rules = load_rules(path)

    assert find_matching_rule({"payee": "Coffee Shop", "date": "2026-01-15"}, rules)["id"] == rule["id"]
    assert find_matching_rule({"payee": "Neighborhood Books", "date": "2026-03-15"}, rules)["id"] == rule["id"]
    assert find_matching_rule({"payee": "Coffee Shop", "date": "2026-03-15"}, rules) is None
    assert find_matching_rule({"payee": "Neighborhood Books", "date": "2026-01-15"}, rules) is None


def test_rule_supports_date_conditions(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    accounts = rules_dir / "10-accounts.dat"
    accounts.write_text("", encoding="utf-8")
    path = ensure_rules_store(rules_dir, accounts)

    rule = create_rule(
        path,
        conditions=[
            {"field": "payee", "operator": "contains", "value": "coffee"},
            {
                "field": "date",
                "operator": "between",
                "value": "2026-01-01",
                "secondaryValue": "2026-12-31",
                "joiner": "and",
            },
        ],
        actions=[{"type": "set_account", "account": "Expenses:Coffee"}],
        enabled=True,
    )

    matched = find_matching_rule(
        {"payee": "Neighborhood Coffee Shop", "date": "2026-06-15"},
        load_rules(path),
    )
    assert matched is not None
    assert matched["id"] == rule["id"]

    not_matched = find_matching_rule(
        {"payee": "Neighborhood Coffee Shop", "date": "2025-12-31"},
        load_rules(path),
    )
    assert not_matched is None


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
