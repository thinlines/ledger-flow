"""Slice 4: the Transactions read path served from the projection.

``load_transactions_projected`` returns the public ``ParsedTransaction``
contract from SQLite — stable ordering, top-level line numbers, ``-1``
include sentinel, and self-healing after external edits via the content-hash
check. ``build_unified_transactions`` then runs on the projection payload.
"""
from __future__ import annotations

from pathlib import Path

from services import unified_transactions_service
from services.config_service import AppConfig
from services.projection_db import database_path
from services.projection_service import load_transactions_projected
from services.unified_transactions_service import build_unified_transactions
from services.workspace_service import ensure_workspace_journal_includes


def _filters() -> unified_transactions_service.UnifiedTransactionFilters:
    return unified_transactions_service.UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
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
        import_accounts={
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Checking",
            },
            "visa": {
                "display_name": "Visa",
                "ledger_account": "Liabilities:Visa",
            },
        },
        tracked_accounts={
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Checking",
                "import_account_id": "checking",
            },
            "visa": {
                "display_name": "Visa",
                "ledger_account": "Liabilities:Visa",
                "import_account_id": "visa",
            },
        },
    )


YEAR_2026 = """\
2026-01-05 * Grocery Store
    ; lf_source_identity: abc123
    Expenses:Groceries    USD 45.67
    Assets:Checking

2026-01-08 * Split Purchase
    Expenses:Groceries    USD 30.00
    Expenses:Household    USD 12.50
    Assets:Checking       USD -42.50

2026-01-10 ! Pending Transfer
    Assets:Transfers:Pending    USD 200.00
    Assets:Checking

2026-01-12 Card Payment
    Liabilities:Visa    USD 150.00
    Assets:Checking     USD -150.00

2026-02-01 * Salary
    Assets:Checking    USD 1,500.00
    Income:Salary
"""

OPENING_INDEX = """\
include checking.journal
"""

OPENING_CHECKING = """\
2026-01-01 * Opening Balance
    ; tracked_account_id: checking
    Assets:Checking    USD 100.00
    Equity:Opening Balances
"""


def _workspace(tmp_path: Path) -> AppConfig:
    config = _make_config(tmp_path)
    (tmp_path / "opening" / "_opening_balances.journal").write_text(
        OPENING_INDEX, encoding="utf-8"
    )
    (tmp_path / "opening" / "checking.journal").write_text(
        OPENING_CHECKING, encoding="utf-8"
    )
    year_path = tmp_path / "journals" / "2026.journal"
    year_path.write_text(
        "include ../opening/_opening_balances.journal\n\n" + YEAR_2026,
        encoding="utf-8",
    )
    ensure_workspace_journal_includes(config)
    return config


def test_projected_loader_returns_public_transaction_contract(tmp_path):
    config = _workspace(tmp_path)

    projected = load_transactions_projected(config)

    assert [txn.payee for txn in projected] == [
        "Opening Balance",
        "Grocery Store",
        "Split Purchase",
        "Pending Transfer",
        "Card Payment",
        "Salary",
    ]
    grocery = projected[1]
    assert grocery.posted_on.isoformat() == "2026-01-05"
    assert grocery.header_line == "2026-01-05 * Grocery Store"
    assert grocery.metadata["lf_source_identity"] == "abc123"
    assert [posting.account for posting in grocery.postings] == [
        "Expenses:Groceries",
        "Assets:Checking",
    ]
    assert grocery.postings[1].inferred is True
    for txn in projected:
        assert txn.txn_id is not None
        assert txn.block_hash is not None


def test_projected_loader_include_sentinel_and_line_numbers(tmp_path):
    config = _workspace(tmp_path)

    projected = load_transactions_projected(config)
    by_payee = {txn.payee: txn for txn in projected}

    opening = by_payee["Opening Balance"]
    assert opening.header_line_number == -1
    assert opening.source_journal.endswith("journals/2026.journal")

    top_level_lines = (tmp_path / "journals" / "2026.journal").read_text(
        encoding="utf-8"
    ).splitlines()
    for payee in ["Grocery Store", "Split Purchase", "Salary"]:
        assert by_payee[payee].header_line_number >= 0
        assert top_level_lines[by_payee[payee].header_line_number] == by_payee[payee].header_line


def test_projected_loader_self_heals_after_external_edit(tmp_path):
    config = _workspace(tmp_path)
    assert len(load_transactions_projected(config)) == 6

    year_path = tmp_path / "journals" / "2026.journal"
    year_path.write_text(
        year_path.read_text(encoding="utf-8")
        + "\n2026-03-01 * Late Addition\n"
        "    Expenses:Groceries    USD 3.00\n"
        "    Assets:Checking\n",
        encoding="utf-8",
    )

    reloaded = load_transactions_projected(config)
    assert len(reloaded) == 7
    assert reloaded[-1].payee == "Late Addition"


def test_unified_payload_from_projection_exposes_register_data(tmp_path):
    config = _workspace(tmp_path)

    payload = build_unified_transactions(config, _filters())

    assert payload["totalCount"] == 6
    assert any(row["payee"] == "Salary" and row["amount"] == 1500.0 for row in payload["rows"])
    assert any(row["runningBalance"] is not None for row in payload["rows"])


def test_unified_rows_expose_projected_identity(tmp_path):
    """Every register row leg carries the projected (txnId, blockHash) pair
    the stable-identity mutation contract needs — including rows whose
    transactions live in included files (line-number sentinel -1)."""
    config = _workspace(tmp_path)

    payload = build_unified_transactions(config, _filters())

    assert payload["rows"]
    for row in payload["rows"]:
        leg = row["legs"][0]
        assert leg["txnId"], row["payee"]
        assert leg["blockHash"], row["payee"]

    opening_rows = [row for row in payload["rows"] if row["isOpeningBalance"]]
    assert opening_rows
    assert opening_rows[0]["legs"][0]["txnId"]
    assert opening_rows[0]["legs"][0]["blockHash"]
    assert "lineNumber" not in opening_rows[0]["legs"][0]


def test_unified_transactions_reads_through_projection(tmp_path):
    config = _workspace(tmp_path)

    build_unified_transactions(config, _filters())

    db_path = database_path(config)
    assert db_path.exists()
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM journal_files").fetchone()[0]
    assert count > 0
