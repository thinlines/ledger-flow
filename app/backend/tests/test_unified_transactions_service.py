from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from services.unified_transactions_service import (
    build_unified_transactions,
    UnifiedTransactionFilters,
)
from services.config_service import AppConfig
from services.workspace_service import ensure_workspace_journal_includes


EMPTY_FILTERS = UnifiedTransactionFilters(
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
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2026, "base_currency": "USD"},
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
                "display_name": "Wells Fargo Checking",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
                "last4": "1234",
                "tracked_account_id": "checking",
            },
            "savings": {
                "display_name": "Savings",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Savings",
                "last4": "4321",
                "tracked_account_id": "savings",
            },
            "visa": {
                "display_name": "Visa Signature",
                "institution": "visa",
                "ledger_account": "Liabilities:Cards:Visa",
                "last4": "5678",
                "tracked_account_id": "visa",
            },
        },
        tracked_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
                "last4": "1234",
                "import_account_id": "checking",
            },
            "visa": {
                "display_name": "Visa Signature",
                "institution": "visa",
                "ledger_account": "Liabilities:Cards:Visa",
                "last4": "5678",
                "import_account_id": "visa",
            },
            "savings": {
                "display_name": "Savings",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Savings",
                "last4": "4321",
                "import_account_id": "savings",
            },
        },
        payee_aliases="payee_aliases.csv",
    )


def _write_year_journal(config: AppConfig, body: str = "", year: int = 2026) -> None:
    (config.journal_dir / f"{year}.journal").write_text(body, encoding="utf-8")
    ensure_workspace_journal_includes(config)


# ---------------------------------------------------------------------------
# 1. Empty workspace
# ---------------------------------------------------------------------------
def test_empty_workspace(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config)

    result = build_unified_transactions(config, EMPTY_FILTERS)

    assert result["rows"] == []
    assert result["totalCount"] == 0
    assert result["summary"] is None


# ---------------------------------------------------------------------------
# 2. Single account basics
# ---------------------------------------------------------------------------
def test_single_account_basic(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/03 * Coffee Shop
    ; import_account_id: checking
    Assets:Bank:Checking    $-5.00
    Expenses:Food:Dining     $5.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 2

    # Newest first
    assert rows[0]["payee"] == "Coffee Shop"
    assert rows[0]["date"] == "2026-02-03"
    assert rows[0]["amount"] == -5.0
    assert rows[0]["account"]["id"] == "checking"
    assert rows[0]["account"]["label"] == "Wells Fargo Checking"
    assert rows[0]["status"] == "cleared"
    assert rows[0]["isTransfer"] is False
    assert rows[0]["isUnknown"] is False
    assert rows[0]["isManual"] is False
    assert rows[0]["isOpeningBalance"] is False

    assert rows[1]["payee"] == "Grocery Store"
    assert rows[1]["date"] == "2026-02-01"
    assert rows[1]["amount"] == -50.0
    assert rows[1]["account"]["id"] == "checking"
    assert rows[1]["account"]["label"] == "Wells Fargo Checking"

    # N-1 rule: 2 postings -> 1 category (the expense side)
    assert len(rows[0]["categories"]) == 1
    assert rows[0]["categories"][0]["account"] == "Expenses:Food:Dining"

    assert len(rows[1]["categories"]) == 1
    assert rows[1]["categories"][0]["account"] == "Expenses:Food:Groceries"

    # Legs should exist
    assert len(rows[0]["legs"]) >= 1
    assert "journalPath" in rows[0]["legs"][0]
    assert "headerLine" in rows[0]["legs"][0]

    # accountMeta should be present for single-account filter
    assert result["accountMeta"] is not None
    assert result["accountMeta"]["accountId"] == "checking"


# ---------------------------------------------------------------------------
# 3. Cross-account, no filter
# ---------------------------------------------------------------------------
def test_cross_account_no_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/02 * Online Purchase
    ; import_account_id: visa
    Liabilities:Cards:Visa  $-30.00
    Expenses:Shopping        $30.00
""".strip()
        + "\n",
    )

    result = build_unified_transactions(config, EMPTY_FILTERS)

    rows = result["rows"]
    assert len(rows) == 2

    # Both accounts present
    account_ids = {r["account"]["id"] for r in rows}
    assert "checking" in account_ids
    assert "visa" in account_ids

    # accountMeta should be None for cross-account view
    assert result["accountMeta"] is None


# ---------------------------------------------------------------------------
# 4. N-1 rule: split transaction
# ---------------------------------------------------------------------------
def test_n1_rule_split_transaction(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/05 * Costco
    ; import_account_id: checking
    Assets:Bank:Checking     $-100.00
    Expenses:Food:Groceries   $60.00
    Expenses:Household        $40.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["amount"] == -100.0

    # 3 postings minus 1 tracked account = 2 categories
    cats = rows[0]["categories"]
    assert len(cats) == 2

    cat_accounts = {c["account"] for c in cats}
    assert "Expenses:Food:Groceries" in cat_accounts
    assert "Expenses:Household" in cat_accounts


# ---------------------------------------------------------------------------
# 5. N-1 rule: tracked account posting excluded from categories
# ---------------------------------------------------------------------------
def test_n1_rule_does_not_include_tracked_account_posting(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/05 * Costco
    ; import_account_id: checking
    Assets:Bank:Checking     $-100.00
    Expenses:Food:Groceries   $60.00
    Expenses:Household        $40.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    row = result["rows"][0]
    cat_accounts = [c["account"] for c in row["categories"]]
    assert "Assets:Bank:Checking" not in cat_accounts


# ---------------------------------------------------------------------------
# 6. Running balance: single account
# ---------------------------------------------------------------------------
def test_running_balance_single_account(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-01-01 Opening Balance
    ; tracked_account_id: checking
    Assets:Bank:Checking      $1000.00
    Equity:Opening-Balances  $-1000.00
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/03 * Coffee Shop
    ; import_account_id: checking
    Assets:Bank:Checking    $-5.00
    Expenses:Food:Dining     $5.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 3

    # Rows are newest first; running balances computed oldest-first
    # Coffee Shop (latest): 1000 - 50 - 5 = 945
    assert rows[0]["payee"] == "Coffee Shop"
    assert rows[0]["runningBalance"] == 945.0

    # Grocery Store: 1000 - 50 = 950
    assert rows[1]["payee"] == "Grocery Store"
    assert rows[1]["runningBalance"] == 950.0

    # Opening Balance: 1000
    assert rows[2]["runningBalance"] == 1000.0


# ---------------------------------------------------------------------------
# 7. Running balance: cross-account
# ---------------------------------------------------------------------------
def test_running_balance_cross_account(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-01-01 Opening Balance
    ; tracked_account_id: checking
    Assets:Bank:Checking      $500.00
    Equity:Opening-Balances  $-500.00
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (config.opening_bal_dir / "savings.journal").write_text(
        """
2026-01-01 Opening Balance
    ; tracked_account_id: savings
    Assets:Bank:Savings       $200.00
    Equity:Opening-Balances  $-200.00
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/02 * Savings Interest
    ; import_account_id: savings
    Assets:Bank:Savings     $10.00
    Income:Interest         $-10.00
""".strip()
        + "\n",
    )

    result = build_unified_transactions(config, EMPTY_FILTERS)

    rows = result["rows"]
    # Should have 4 rows (2 opening + 2 transactions)
    assert len(rows) == 4


# ---------------------------------------------------------------------------
# 8. Period filter: this-month
# ---------------------------------------------------------------------------
def test_period_filter_this_month(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/01/15 * January Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-20.00
    Expenses:Misc            $20.00

2026/02/10 * February Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Misc            $30.00

2026/03/05 * March Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-40.00
    Expenses:Misc            $40.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period="this-month",
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters, today=date(2026, 2, 15))

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["payee"] == "February Expense"
    assert result["summary"] is not None


# ---------------------------------------------------------------------------
# 9. Period filter: last-30
# ---------------------------------------------------------------------------
def test_period_filter_last_30(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/01/01 * Old Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-10.00
    Expenses:Misc            $10.00

2026/01/20 * Recent Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-20.00
    Expenses:Misc            $20.00

2026/02/10 * Latest Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Misc            $30.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period="last-30",
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters, today=date(2026, 2, 15))

    rows = result["rows"]
    # last-30 from 2026-02-15 => from 2026-01-16 to 2026-02-15
    dates = [r["date"] for r in rows]
    assert "2026-01-01" not in dates
    assert "2026-01-20" in dates
    assert "2026-02-10" in dates


# ---------------------------------------------------------------------------
# 10. Period filter: last-3-months
# ---------------------------------------------------------------------------
def test_period_filter_last_3_months(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2025/11/01 * Very Old Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-5.00
    Expenses:Misc            $5.00

2026/01/15 * January Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-20.00
    Expenses:Misc            $20.00

2026/02/10 * February Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Misc            $30.00

2026/03/05 * March Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-40.00
    Expenses:Misc            $40.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period="last-3-months",
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters, today=date(2026, 3, 15))

    rows = result["rows"]
    dates = [r["date"] for r in rows]
    # last-3-months from March 15 should include Jan, Feb, Mar but not Nov
    assert "2025-11-01" not in dates
    assert "2026-01-15" in dates
    assert "2026-02-10" in dates
    assert "2026-03-05" in dates


# ---------------------------------------------------------------------------
# 11. Month filter
# ---------------------------------------------------------------------------
def test_month_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/01/15 * January Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-20.00
    Expenses:Misc            $20.00

2026/02/10 * February Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Misc            $30.00

2026/03/05 * March Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-40.00
    Expenses:Misc            $40.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month="2026-02",
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["payee"] == "February Expense"
    assert rows[0]["date"] == "2026-02-10"


# ---------------------------------------------------------------------------
# 12. Category filter
# ---------------------------------------------------------------------------
def test_category_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/02 * Hardware Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Household       $30.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=["Expenses:Food"],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["payee"] == "Grocery Store"


# ---------------------------------------------------------------------------
# 13. Category filter: prefix match
# ---------------------------------------------------------------------------
def test_category_filter_prefix_match(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/02 * Restaurant
    ; import_account_id: checking
    Assets:Bank:Checking    $-25.00
    Expenses:Food:Dining     $25.00

2026/02/03 * Hardware Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Household       $30.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=["Expenses:Food"],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    # Both Expenses:Food:Groceries and Expenses:Food:Dining match the prefix
    assert len(rows) == 2
    payees = {r["payee"] for r in rows}
    assert "Grocery Store" in payees
    assert "Restaurant" in payees
    assert "Hardware Store" not in payees


# ---------------------------------------------------------------------------
# 14. Status filter: cleared
# ---------------------------------------------------------------------------
def test_status_filter_cleared(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Cleared Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Misc            $50.00

2026/02/02 Unmarked Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Misc            $30.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=["cleared"],
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["payee"] == "Cleared Expense"
    assert rows[0]["status"] == "cleared"


# ---------------------------------------------------------------------------
# 15. Status filter: unmarked
# ---------------------------------------------------------------------------
def test_status_filter_unmarked(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Cleared Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Misc            $50.00

2026/02/02 Unmarked Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Misc            $30.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=["unmarked"],
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["payee"] == "Unmarked Expense"
    assert rows[0]["status"] == "unmarked"


# ---------------------------------------------------------------------------
# 16. Search filter
# ---------------------------------------------------------------------------
def test_search_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/02 * Coffee Shop
    ; import_account_id: checking
    Assets:Bank:Checking    $-5.00
    Expenses:Food:Dining     $5.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search="grocery",
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["payee"] == "Grocery Store"


# ---------------------------------------------------------------------------
# 17. Combined filters
# ---------------------------------------------------------------------------
def test_combined_filters(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/01/15 * January Grocery
    ; import_account_id: checking
    Assets:Bank:Checking    $-40.00
    Expenses:Food:Groceries  $40.00

2026/02/10 * February Grocery
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/12 * February Coffee
    ; import_account_id: checking
    Assets:Bank:Checking    $-5.00
    Expenses:Food:Dining     $5.00

2026/02/14 * February Grocery Visa
    ; import_account_id: visa
    Liabilities:Cards:Visa  $-60.00
    Expenses:Food:Groceries  $60.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=[],
        period="this-month",
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search="grocery",
    )
    result = build_unified_transactions(config, filters, today=date(2026, 2, 15))

    rows = result["rows"]
    # Only the February grocery in checking should match all three filters
    assert len(rows) == 1
    assert rows[0]["payee"] == "February Grocery"
    assert rows[0]["account"]["id"] == "checking"


# ---------------------------------------------------------------------------
# 18. Summary with date filter
# ---------------------------------------------------------------------------
def test_summary_with_date_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/10 * Coffee Shop
    ; import_account_id: checking
    Assets:Bank:Checking    $-5.00
    Expenses:Food:Dining     $5.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period="this-month",
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters, today=date(2026, 2, 15))

    summary = result["summary"]
    assert summary is not None
    assert "periodTotal" in summary
    assert "periodCount" in summary
    assert "averageAmount" in summary


# ---------------------------------------------------------------------------
# 19. Summary without date filter
# ---------------------------------------------------------------------------
def test_summary_without_date_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00
""".strip()
        + "\n",
    )

    result = build_unified_transactions(config, EMPTY_FILTERS)

    assert result["summary"] is None


# ---------------------------------------------------------------------------
# 20. accountMeta: single account
# ---------------------------------------------------------------------------
def test_account_meta_single_account(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    meta = result["accountMeta"]
    assert meta is not None
    assert meta["accountId"] == "checking"


# ---------------------------------------------------------------------------
# 21. accountMeta: multi-account
# ---------------------------------------------------------------------------
def test_account_meta_multi_account(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00
""".strip()
        + "\n",
    )

    # Multiple accounts filter
    filters = UnifiedTransactionFilters(
        accounts=["checking", "visa"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)
    assert result["accountMeta"] is None

    # Empty accounts filter (all accounts)
    result2 = build_unified_transactions(config, EMPTY_FILTERS)
    assert result2["accountMeta"] is None


# ---------------------------------------------------------------------------
# 22. Opening balance row
# ---------------------------------------------------------------------------
def test_opening_balance_row(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-01-01 Opening Balance
    ; tracked_account_id: checking
    Assets:Bank:Checking      $1000.00
    Equity:Opening-Balances  $-1000.00
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(config)

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["isOpeningBalance"] is True
    assert rows[0]["amount"] == 1000.0


# ---------------------------------------------------------------------------
# 23. Transfer rows not collapsed
# ---------------------------------------------------------------------------
def test_transfer_rows_not_collapsed(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/10 * Transfer to Savings
    ; import_account_id: checking
    ; transfer_peer_account_id: savings
    ; transfer_type: direct
    Assets:Bank:Checking          $-200.00
    Assets:Transfers:checking__savings  $200.00

2026/02/10 * Transfer from Checking
    ; import_account_id: savings
    ; transfer_peer_account_id: checking
    ; transfer_type: direct
    Assets:Bank:Savings            $200.00
    Assets:Transfers:checking__savings  $-200.00
""".strip()
        + "\n",
    )

    result = build_unified_transactions(config, EMPTY_FILTERS)

    rows = result["rows"]
    # Both sides should appear (no collapse)
    assert len(rows) == 2

    for row in rows:
        assert row["isTransfer"] is True


# ---------------------------------------------------------------------------
# 24. Unknown transaction
# ---------------------------------------------------------------------------
def test_unknown_transaction(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Mystery Charge
    ; import_account_id: checking
    Assets:Bank:Checking    $-15.00
    Expenses:Unknown         $15.00
""".strip()
        + "\n",
    )

    result = build_unified_transactions(config, EMPTY_FILTERS)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["isUnknown"] is True


# ---------------------------------------------------------------------------
# 25. Manual transaction
# ---------------------------------------------------------------------------
def test_manual_transaction(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/15 Manual Payment
    ; :manual:
    Assets:Bank:Checking    $-25.00
    Expenses:Utilities       $25.00
""".strip()
        + "\n",
    )

    result = build_unified_transactions(config, EMPTY_FILTERS)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["isManual"] is True


# ---------------------------------------------------------------------------
# 26. Notes field
# ---------------------------------------------------------------------------
def test_notes_field(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/20 * Some Purchase
    ; import_account_id: checking
    ; notes: Bought this for the office
    Assets:Bank:Checking    $-30.00
    Expenses:Office          $30.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0]["notes"] == "Bought this for the office"


# ---------------------------------------------------------------------------
# 27. Filters echoed back
# ---------------------------------------------------------------------------
def test_filters_echoed_back(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config)

    filters = UnifiedTransactionFilters(
        accounts=["checking"],
        categories=["Expenses:Food"],
        period="this-month",
        from_date=None,
        to_date=None,
        month=None,
        status=["cleared"],
        search="test",
    )
    result = build_unified_transactions(config, filters, today=date(2026, 2, 15))

    assert "filters" in result
    echoed = result["filters"]
    assert echoed["accounts"] == ["checking"]
    assert echoed["categories"] == ["Expenses:Food"]
    assert echoed["period"] == "this-month"
    assert echoed["status"] == ["cleared"]
    assert echoed["search"] == "test"


# ---------------------------------------------------------------------------
# 28. Non-existent account filter
# ---------------------------------------------------------------------------
def test_nonexistent_account_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config)

    filters = UnifiedTransactionFilters(
        accounts=["nonexistent_account_999"],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search=None,
    )

    with pytest.raises(Exception):
        build_unified_transactions(config, filters)


# ---------------------------------------------------------------------------
# 29. Empty search treated as no filter
# ---------------------------------------------------------------------------
def test_empty_search_is_no_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * Grocery Store
    ; import_account_id: checking
    Assets:Bank:Checking    $-50.00
    Expenses:Food:Groceries  $50.00

2026/02/02 * Coffee Shop
    ; import_account_id: checking
    Assets:Bank:Checking    $-5.00
    Expenses:Food:Dining     $5.00
""".strip()
        + "\n",
    )

    filters = UnifiedTransactionFilters(
        accounts=[],
        categories=[],
        period=None,
        from_date=None,
        to_date=None,
        month=None,
        status=None,
        search="",
    )
    result = build_unified_transactions(config, filters)

    rows = result["rows"]
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# 30. Rows newest first
# ---------------------------------------------------------------------------
def test_rows_newest_first(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/01 * First Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-10.00
    Expenses:Misc            $10.00

2026/02/15 * Middle Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-20.00
    Expenses:Misc            $20.00

2026/03/01 * Last Expense
    ; import_account_id: checking
    Assets:Bank:Checking    $-30.00
    Expenses:Misc            $30.00
""".strip()
        + "\n",
    )

    result = build_unified_transactions(config, EMPTY_FILTERS)

    rows = result["rows"]
    assert len(rows) == 3
    assert rows[0]["date"] == "2026-03-01"
    assert rows[1]["date"] == "2026-02-15"
    assert rows[2]["date"] == "2026-02-01"


# ---------------------------------------------------------------------------
# Line-number plumbing (position-based identity)
# ---------------------------------------------------------------------------


def test_row_legs_carry_line_number_for_top_level_transactions(tmp_path: Path) -> None:
    """Every row's ``legs[0]`` carries the zero-indexed ``lineNumber`` of the
    header line within the physical journal file. The frontend sends this
    back with every mutation so the backend can seek directly and verify
    the text has not drifted."""
    config = _make_config(tmp_path / "workspace")
    journal_body = """\
2026-03-10 * First
    Assets:Bank:Checking  -$10.00
    Expenses:Food  $10.00

2026-03-15 * Second
    Assets:Bank:Checking  -$20.00
    Expenses:Food  $20.00
"""
    _write_year_journal(config, journal_body)

    result = build_unified_transactions(config, EMPTY_FILTERS)
    rows = result["rows"]
    assert len(rows) == 2

    # Verify each row's lineNumber points to a header line in the raw file.
    journal_path = config.journal_dir / "2026.journal"
    raw_lines = journal_path.read_text(encoding="utf-8").splitlines()
    for row in rows:
        leg = row["legs"][0]
        assert leg["journalPath"] == str(journal_path)
        assert leg["lineNumber"] >= 0
        assert raw_lines[leg["lineNumber"]] == leg["headerLine"]


def test_identical_header_lines_get_distinct_line_numbers(tmp_path: Path) -> None:
    """Two transactions with byte-identical header lines (same date, status,
    payee) each get their own physical line number — the ambiguity that
    motivated this task."""
    config = _make_config(tmp_path / "workspace")
    journal_body = """\
2026-03-15 * Starbucks
    Assets:Bank:Checking  -$5.00
    Expenses:Food  $5.00

2026-03-15 * Starbucks
    Assets:Bank:Checking  -$7.00
    Expenses:Food  $7.00
"""
    _write_year_journal(config, journal_body)

    result = build_unified_transactions(config, EMPTY_FILTERS)
    rows = result["rows"]
    assert len(rows) == 2

    line_numbers = {row["legs"][0]["lineNumber"] for row in rows}
    # Distinct line numbers — not collapsed into one via string matching.
    assert len(line_numbers) == 2

    header_lines = {row["legs"][0]["headerLine"] for row in rows}
    # Both header lines are byte-identical text.
    assert header_lines == {"2026-03-15 * Starbucks"}


def test_include_file_transactions_get_sentinel_line_number(tmp_path: Path) -> None:
    """Transactions hoisted from an ``include`` directive point at a file
    the mutation endpoints do not read, so they get the ``-1`` sentinel.
    The frontend still renders the row; the drift check rejects any
    mutation attempt with a 404."""
    from services.journal_query_service import load_transactions

    config = _make_config(tmp_path / "workspace")
    # Put a transaction in a sibling file and reference it via ``include`` from
    # the top-level year journal. ``load_transactions`` parses the expanded
    # text but the mutation endpoints read only the top-level file's raw text,
    # so the included transaction's ``header_line_number`` must be the ``-1``
    # sentinel.
    sibling = config.journal_dir / "2026_extra.journal"
    # Don't give it a ``.journal`` name that would be picked up as its own
    # top-level file by ``load_transactions``.
    sibling = config.journal_dir / "extra.dat"
    sibling.write_text(
        """\
2026-02-15 * From included file
    Assets:Bank:Checking  -$15.00
    Expenses:Food  $15.00
""",
        encoding="utf-8",
    )
    journal_body = """\
include extra.dat

2026-03-10 * In top-level file
    Assets:Bank:Checking  -$10.00
    Expenses:Food  $10.00
"""
    _write_year_journal(config, journal_body)

    transactions = load_transactions(config)
    by_payee = {t.payee: t for t in transactions}

    assert "In top-level file" in by_payee
    assert by_payee["In top-level file"].header_line_number >= 0

    # Transaction loaded via ``include`` gets the -1 sentinel — mutation
    # endpoints reject with 404 via the drift check.
    assert "From included file" in by_payee
    assert by_payee["From included file"].header_line_number == -1
