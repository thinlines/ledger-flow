"""Account lifecycle endpoints (issue #19).

``GET /api/accounts/manage`` serves the configure-page panel from the
projection; ``POST /api/accounts/{subtype,close,reopen,delete}`` perform
declaration writes and re-project in the same request. Delete guards map to
409 (in use) / 404 (not declared) with the reason in ``detail``.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import main
from models import (
    AccountCloseRequest,
    AccountNameRequest,
    AccountSubtypeRequest,
)
from services.config_service import AppConfig


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
    ; lf_subtype: checking
account Assets:Old Savings
    note Legacy passbook
    ; lf_closed:: [2026-03-31]
account Expenses:Groceries
account Expenses:DVDs
account Income:Salary
"""

YEAR_2026 = """\
include ../rules/10-accounts.dat

2026-01-05 * Grocery Store
    Expenses:Groceries    USD 45.67
    Assets:Checking

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


def _row(payload: dict, name: str) -> dict:
    matches = [row for row in payload["accounts"] if row["name"] == name]
    assert matches, f"no manage row for {name}"
    return matches[0]


# ---------------------------------------------------------------------------
# GET /api/accounts/manage


def test_manage_lists_projected_accounts_in_tree_order(config):
    payload = main.accounts_manage()

    names = [row["name"] for row in payload["accounts"]]
    assert names == sorted(names)
    assert "Assets" in names  # synthesized ancestor
    assert "Expenses:Dining:Coffee" in names  # used-only

    checking = _row(payload, "Assets:Checking")
    assert checking["declared"] is True
    assert checking["used"] is True
    assert checking["subtype"] == "checking"
    assert checking["closedOn"] is None
    assert checking["accountType"] == "assets"
    assert checking["depth"] == 1
    assert checking["postingCount"] == 2

    old = _row(payload, "Assets:Old Savings")
    assert old["closedOn"] == "2026-03-31"
    assert old["note"] == "Legacy passbook"


def test_manage_posting_counts_aggregate_subtrees(config):
    payload = main.accounts_manage()

    assert _row(payload, "Expenses")["postingCount"] == 2
    assert _row(payload, "Expenses:Dining")["postingCount"] == 1
    assert _row(payload, "Expenses:DVDs")["postingCount"] == 0


def test_manage_delete_flags(config):
    payload = main.accounts_manage()

    dvds = _row(payload, "Expenses:DVDs")
    assert dvds["deletable"] is True
    assert dvds["deleteBlockedReason"] is None

    groceries = _row(payload, "Expenses:Groceries")
    assert groceries["deletable"] is False
    assert "posting" in groceries["deleteBlockedReason"]

    # Used-only rows have no declaration to delete.
    coffee = _row(payload, "Expenses:Dining:Coffee")
    assert coffee["deletable"] is False
    assert coffee["deleteBlockedReason"] is None


def test_manage_delete_flag_blocks_tracked_ledger_account(config):
    config.tracked_accounts["dvds"] = {
        "display_name": "DVD fund",
        "ledger_account": "Expenses:DVDs",
    }
    payload = main.accounts_manage()
    dvds = _row(payload, "Expenses:DVDs")
    assert dvds["deletable"] is False
    assert "tracked" in dvds["deleteBlockedReason"]


# ---------------------------------------------------------------------------
# POST /api/accounts/subtype


def test_subtype_endpoint_writes_declaration(config):
    result = main.accounts_set_subtype(
        AccountSubtypeRequest(account="Assets:Old Savings", subtype="savings")
    )
    assert result["ok"] is True

    dat = (config.init_dir / "10-accounts.dat").read_text(encoding="utf-8")
    assert "    ; lf_subtype: savings\n" in dat
    assert _row(main.accounts_manage(), "Assets:Old Savings")["subtype"] == "savings"


def test_subtype_endpoint_clears_with_null(config):
    main.accounts_set_subtype(
        AccountSubtypeRequest(account="Assets:Checking", subtype=None)
    )
    dat = (config.init_dir / "10-accounts.dat").read_text(encoding="utf-8")
    assert "lf_subtype" not in dat


def test_subtype_endpoint_rejects_kind_mismatch(config):
    with pytest.raises(HTTPException) as excinfo:
        main.accounts_set_subtype(
            AccountSubtypeRequest(account="Assets:Checking", subtype="credit_card")
        )
    assert excinfo.value.status_code == 400

    with pytest.raises(HTTPException) as excinfo:
        main.accounts_set_subtype(
            AccountSubtypeRequest(account="Expenses:Groceries", subtype="checking")
        )
    assert excinfo.value.status_code == 400


def test_subtype_request_model_rejects_unknown_subtype():
    with pytest.raises(ValidationError):
        AccountSubtypeRequest(account="Assets:Checking", subtype="hedge_fund")


# ---------------------------------------------------------------------------
# POST /api/accounts/close + /reopen


def test_close_and_reopen_round_trip(config):
    assert "Expenses:Groceries" in main.accounts()["allAccounts"]

    closed = main.accounts_close(
        AccountCloseRequest(account="Expenses:Groceries", closedOn="2026-06-30")
    )
    assert closed == {"ok": True, "account": "Expenses:Groceries", "closedOn": "2026-06-30"}
    assert "Expenses:Groceries" not in main.accounts()["allAccounts"]
    assert "Expenses:Groceries" not in main.accounts()["categoryAccounts"]

    reopened = main.accounts_reopen(AccountNameRequest(account="Expenses:Groceries"))
    assert reopened["ok"] is True
    assert "Expenses:Groceries" in main.accounts()["allAccounts"]


def test_close_defaults_to_today(config):
    result = main.accounts_close(AccountCloseRequest(account="Expenses:DVDs"))
    assert result["closedOn"] == date.today().isoformat()


def test_close_rejects_invalid_date(config):
    with pytest.raises(HTTPException) as excinfo:
        main.accounts_close(
            AccountCloseRequest(account="Expenses:DVDs", closedOn="06/30/2026")
        )
    assert excinfo.value.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/accounts/delete


def test_delete_endpoint_removes_unused_declaration(config):
    result = main.accounts_delete(AccountNameRequest(account="Expenses:DVDs"))
    assert result["ok"] is True

    dat = (config.init_dir / "10-accounts.dat").read_text(encoding="utf-8")
    assert "Expenses:DVDs" not in dat
    assert "Expenses:DVDs" not in [
        row["name"] for row in main.accounts_manage()["accounts"]
    ]


def test_delete_endpoint_409_when_in_use(config):
    with pytest.raises(HTTPException) as excinfo:
        main.accounts_delete(AccountNameRequest(account="Expenses:Groceries"))
    assert excinfo.value.status_code == 409
    assert "posting" in excinfo.value.detail


def test_delete_endpoint_404_when_not_declared(config):
    with pytest.raises(HTTPException) as excinfo:
        main.accounts_delete(AccountNameRequest(account="Expenses:Dining:Coffee"))
    assert excinfo.value.status_code == 404
