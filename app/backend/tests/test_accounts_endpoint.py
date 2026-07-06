"""GET /api/accounts and POST /api/accounts on the projected reference data.

The picker endpoint serves the projection (declared ∪ used ∪ synthesized
ancestors, closed hidden) instead of parsing ``10-accounts.dat``; account
creation composes parent + leaf, writes the declaration, and re-projects so
the new account is immediately declared in the same request.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from models import CreateAccountRequest
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
    )


ACCOUNTS_DAT = """\
account Assets:Checking
account Assets:Old Savings
    ; lf_closed:: [2026-03-31]
account Expenses:Groceries
account Income:Salary
"""

YEAR_2026 = """\
include ../rules/10-accounts.dat

2026-01-20 * Corner Cafe
    Expenses:Dining:Coffee    USD 4.50
    Assets:Checking
"""


@pytest.fixture
def config(tmp_path: Path, monkeypatch) -> AppConfig:
    config = _make_config(tmp_path / "workspace")
    (config.init_dir / "10-accounts.dat").write_text(ACCOUNTS_DAT, encoding="utf-8")
    (config.journal_dir / "2026.journal").write_text(YEAR_2026, encoding="utf-8")
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    return config


def test_accounts_endpoint_serves_projected_reference_data(config):
    payload = main.accounts()

    all_accounts = payload["allAccounts"]
    assert "Expenses:Dining:Coffee" in all_accounts  # used-only, absent from .dat
    assert "Expenses:Dining" in all_accounts  # synthesized ancestor
    assert "Assets:Old Savings" not in all_accounts  # closed
    assert all_accounts == sorted(all_accounts)

    assert "Expenses:Groceries" in payload["categoryAccounts"]
    assert "Assets:Checking" not in payload["categoryAccounts"]
    assert payload["accounts"] == payload["categoryAccounts"]


def test_create_account_from_parent_and_leaf(config):
    result = main.accounts_create(
        CreateAccountRequest(parent="Expenses:Dining", leaf="Tea")
    )

    assert result["added"] is True
    assert result["account"] == "Expenses:Dining:Tea"

    dat_text = (config.init_dir / "10-accounts.dat").read_text(encoding="utf-8")
    assert "account Expenses:Dining:Tea" in dat_text

    # Re-projection happened inside the request: the account is declared.
    with sqlite3.connect(database_path(config)) as conn:
        declared = conn.execute(
            "SELECT declared FROM accounts WHERE name = 'Expenses:Dining:Tea'"
        ).fetchone()
    assert declared == (1,)

    assert "Expenses:Dining:Tea" in main.accounts()["allAccounts"]


def test_create_account_duplicate_is_a_noop(config):
    first = main.accounts_create(
        CreateAccountRequest(parent="Expenses", leaf="Groceries")
    )
    assert first["added"] is False


def test_create_account_rejects_bad_leaf(config):
    with pytest.raises(HTTPException) as excinfo:
        main.accounts_create(CreateAccountRequest(parent="Expenses", leaf="A:B"))
    assert excinfo.value.status_code == 400

    with pytest.raises(HTTPException) as excinfo:
        main.accounts_create(CreateAccountRequest(parent="Expenses", leaf="   "))
    assert excinfo.value.status_code == 400


def test_create_account_legacy_fully_qualified_field_still_works(config):
    result = main.accounts_create(
        CreateAccountRequest(account="Liabilities:New Card", accountType="Liability")
    )
    assert result["added"] is True
    assert result["account"] == "Liabilities:New Card"
