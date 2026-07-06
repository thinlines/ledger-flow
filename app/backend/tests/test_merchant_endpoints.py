"""Merchant API endpoints (issue #24).

- ``POST /api/merchants`` creates/extends a merchant declaration in context
  (Review flow) and records the reference-data change as an operation.
- ``GET /api/merchants`` lists declared merchants plus the undeclared-payee
  "create merchant from this payee?" suggestions.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from models import MerchantCreateRequest
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


@pytest.fixture
def config(tmp_path: Path, monkeypatch) -> AppConfig:
    config = _make_config(tmp_path / "workspace")
    (config.init_dir / "10-accounts.dat").write_text(
        "account Expenses:Groceries\n", encoding="utf-8"
    )
    (config.init_dir / "11-payees.dat").write_text("", encoding="utf-8")
    (config.journal_dir / "2026.journal").write_text(
        "include ../rules/10-accounts.dat\n"
        "include ../rules/11-payees.dat\n"
        "\n"
        "2026-01-05 * One-Off Plumber\n"
        "    Expenses:Unknown    USD 45.67\n"
        "    Assets:Checking\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    return config


def test_create_merchant_records_operation_and_projects(config: AppConfig) -> None:
    response = main.merchants_create(
        MerchantCreateRequest(
            name="Costco",
            alias="COSTCO WHSE",
            defaultAccount="Expenses:Groceries",
        )
    )

    assert response["merchant"]["name"] == "Costco"
    assert response["merchant"]["created"] is True

    listed = main.merchants_list()
    costco = next(m for m in listed["merchants"] if m["name"] == "Costco")
    assert costco["defaultAccount"] == "Expenses:Groceries"
    assert costco["aliases"] == ["COSTCO WHSE"]

    with sqlite3.connect(database_path(config)) as conn:
        operation_types = [
            row[0]
            for row in conn.execute("SELECT type FROM operations ORDER BY rowid").fetchall()
        ]
    assert "reference.merchant.created.v1" in operation_types


def test_create_merchant_rejects_unknown_default_account(config: AppConfig) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.merchants_create(
            MerchantCreateRequest(name="Costco", defaultAccount="Expenses:Missing")
        )

    assert excinfo.value.status_code == 400
    assert "Unknown account" in str(excinfo.value.detail)


def test_merchants_list_surfaces_undeclared_payee_suggestions(config: AppConfig) -> None:
    listed = main.merchants_list()

    assert [s["name"] for s in listed["suggestions"]] == ["One-Off Plumber"]

    main.merchants_create(MerchantCreateRequest(name="One-Off Plumber"))
    relisted = main.merchants_list()
    assert relisted["suggestions"] == []
    assert any(m["name"] == "One-Off Plumber" for m in relisted["merchants"])
