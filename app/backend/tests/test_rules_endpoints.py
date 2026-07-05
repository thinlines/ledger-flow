from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from models import RuleAction, RuleCondition, RuleCreateRequest, RuleReorderRequest, RuleUpdateRequest
from services.config_service import AppConfig
from services.projection_db import database_path


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "rules", "opening", "imports", "inbox"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "start_year": 2026, "base_currency": "USD"},
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
        payee_aliases="payee_aliases.csv",
    )


@pytest.fixture
def config(tmp_path: Path, monkeypatch) -> AppConfig:
    config = _make_config(tmp_path / "workspace")
    (config.init_dir / "10-accounts.dat").write_text(
        "account Expenses:Coffee\naccount Expenses:Books\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    return config


def _condition(value: str) -> RuleCondition:
    return RuleCondition(field="payee", operator="contains", value=value)


def _set_account(account: str) -> RuleAction:
    return RuleAction(type="set_account", account=account)


def test_rules_editor_api_uses_database_backed_rules(config: AppConfig) -> None:
    coffee = main.rules_create(
        RuleCreateRequest(
            name="Coffee",
            conditions=[_condition("coffee")],
            actions=[_set_account("Expenses:Coffee")],
        )
    )["rule"]
    books = main.rules_create(
        RuleCreateRequest(
            name="Books",
            conditions=[_condition("books")],
            actions=[_set_account("Expenses:Books")],
        )
    )["rule"]

    updated = main.rules_update(
        coffee["id"],
        RuleUpdateRequest(name="Cafe", enabled=False),
    )["rule"]
    reordered = main.rules_reorder(RuleReorderRequest(orderedIds=[books["id"], coffee["id"]]))["rules"]
    deleted = main.rules_delete(books["id"])
    listed = main.rules_list()["rules"]

    assert updated["name"] == "Cafe"
    assert updated["enabled"] is False
    assert [rule["id"] for rule in reordered] == [books["id"], coffee["id"]]
    assert deleted == {"deleted": True}
    assert [rule["id"] for rule in listed] == [coffee["id"]]
    assert not (config.init_dir / "20-match-rules.ndjson").exists()

    with sqlite3.connect(database_path(config)) as conn:
        operation_types = [
            row[0]
            for row in conn.execute("SELECT type FROM operations ORDER BY rowid").fetchall()
        ]
    assert operation_types == [
        "rule.created.v1",
        "rule.created.v1",
        "rule.updated.v1",
        "rule.reordered.v1",
        "rule.deleted.v1",
    ]


def test_rules_editor_rejects_unknown_action_account(config: AppConfig) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.rules_create(
            RuleCreateRequest(
                conditions=[_condition("coffee")],
                actions=[_set_account("Expenses:Missing")],
            )
        )

    assert excinfo.value.status_code == 400
    assert "Unknown account" in str(excinfo.value.detail)
