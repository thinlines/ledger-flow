"""Merchant layer (issue #24).

Invariants under test (spec: docs/ledger-flow-projection-schema.md,
Merchant Layer section):

- Statement text is matched against ``payee_aliases`` patterns
  (case-insensitive regex search) in ``alias_order``; the first matching
  merchant wins and supplies the canonical payee name.
- ``load_merchants`` reads declared payees with their aliases (in
  ``alias_order``) and default account from the projection.
"""
from __future__ import annotations

from pathlib import Path

from services.config_service import AppConfig
from services.merchant_service import (
    Merchant,
    list_undeclared_payees,
    load_merchants,
    match_merchant,
    upsert_merchant,
)
from services.operations_service import list_operations


def make_config(workspace: Path) -> AppConfig:
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


PAYEES_DAT = """\
payee Walmart
    alias WAL-?MART
    alias WALMART\\.COM
    ; lf_default_account: Expenses:Groceries

payee Corner Cafe
"""

JOURNAL_WITH_UNDECLARED_PAYEE = """\
include ../rules/11-payees.dat

2026-01-05 * One-Off Plumber
    Expenses:Home    USD 45.67
    Assets:Checking
"""


def merchant_workspace(tmp_path: Path) -> AppConfig:
    config = make_config(tmp_path)
    (tmp_path / "rules" / "11-payees.dat").write_text(PAYEES_DAT, encoding="utf-8")
    (tmp_path / "journals" / "2026.journal").write_text(
        JOURNAL_WITH_UNDECLARED_PAYEE, encoding="utf-8"
    )
    return config


def test_alias_pattern_matches_statement_text():
    merchants = [
        Merchant(
            name="Walmart",
            default_account="Expenses:Groceries",
            aliases=["WAL-?MART"],
        )
    ]

    match = match_merchant("WAL-MART #2734 GROCERY", merchants)

    assert match is not None
    assert match.name == "Walmart"


def test_unmatched_statement_text_returns_none():
    merchants = [Merchant(name="Walmart", aliases=["WAL-?MART"])]

    assert match_merchant("SQ *CORNER CAFE", merchants) is None


def test_first_matching_merchant_wins_in_list_order():
    merchants = [
        Merchant(name="Amazon", aliases=["AMZN"]),
        Merchant(name="Amazon Fresh", aliases=["AMZN FRESH", "AMZN"]),
    ]

    match = match_merchant("AMZN FRESH SEATTLE", merchants)

    assert match is not None
    assert match.name == "Amazon"


def test_invalid_alias_pattern_is_skipped_not_fatal():
    merchants = [
        Merchant(name="Broken", aliases=["*("]),
        Merchant(name="Walmart", aliases=["WALMART"]),
    ]

    match = match_merchant("WALMART.COM", merchants)

    assert match is not None
    assert match.name == "Walmart"


def test_upsert_merchant_declares_new_payee_and_records_operation(tmp_path):
    config = merchant_workspace(tmp_path)

    result = upsert_merchant(
        config,
        name="Costco",
        alias="COSTCO WHSE",
        default_account="Expenses:Groceries",
    )

    assert result["created"] is True
    costco = next(m for m in load_merchants(config) if m.name == "Costco")
    assert costco.default_account == "Expenses:Groceries"
    assert list(costco.aliases) == ["COSTCO WHSE"]

    operations = list_operations(config)
    created = [op for op in operations if op["type"] == "reference.merchant.created.v1"]
    assert len(created) == 1
    assert created[0]["payload"]["name"] == "Costco"
    assert created[0]["files"], "operation must reference the payees dat"


def test_upsert_merchant_extends_existing_declaration_in_place(tmp_path):
    config = merchant_workspace(tmp_path)

    result = upsert_merchant(
        config,
        name="Corner Cafe",
        alias="SQ \\*CORNER CAFE",
        default_account="Expenses:Dining:Coffee",
    )

    assert result["created"] is False
    cafe = next(m for m in load_merchants(config) if m.name == "Corner Cafe")
    assert cafe.default_account == "Expenses:Dining:Coffee"
    assert list(cafe.aliases) == ["SQ \\*CORNER CAFE"]
    # The neighbouring declaration is untouched.
    walmart = next(m for m in load_merchants(config) if m.name == "Walmart")
    assert list(walmart.aliases) == ["WAL-?MART", "WALMART\\.COM"]

    operations = list_operations(config)
    assert any(op["type"] == "reference.merchant.updated.v1" for op in operations)


def test_undeclared_used_payees_are_the_suggestion_surface(tmp_path):
    config = merchant_workspace(tmp_path)

    suggestions = list_undeclared_payees(config)

    assert suggestions == ["One-Off Plumber"]


def test_load_merchants_returns_declared_payees_with_ordered_aliases(tmp_path):
    config = merchant_workspace(tmp_path)

    merchants = load_merchants(config)

    by_name = {merchant.name: merchant for merchant in merchants}
    assert set(by_name) == {"Walmart", "Corner Cafe"}
    walmart = by_name["Walmart"]
    assert walmart.default_account == "Expenses:Groceries"
    assert list(walmart.aliases) == ["WAL-?MART", "WALMART\\.COM"]
    cafe = by_name["Corner Cafe"]
    assert cafe.default_account is None
    assert list(cafe.aliases) == []
