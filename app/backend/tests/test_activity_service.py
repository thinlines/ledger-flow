from __future__ import annotations

from datetime import date
from pathlib import Path

from services.activity_service import build_activity_view
from services.config_service import AppConfig
from services.workspace_service import ensure_workspace_journal_includes


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
        institution_templates={
            "wells_fargo": {
                "display_name": "Wells Fargo",
                "parser": "wfchk",
                "CSV_date_format": "%Y/%m/%d",
            },
        },
        import_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
                "last4": "1234",
                "tracked_account_id": "checking",
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
        },
        payee_aliases="payee_aliases.csv",
    )


JOURNAL_BODY = """
2026/01/10 January Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  $3000.00
    Income:Salary

2026/01/15 January Groceries
    ; import_account_id: checking
    Expenses:Food:Groceries  $120.00
    Assets:Bank:Checking

2026/02/12 February Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  $3000.00
    Income:Salary

2026/02/18 February Groceries
    ; import_account_id: checking
    Expenses:Food:Groceries  $140.50
    Assets:Bank:Checking

2026/03/01 Coffee Shop
    ; import_account_id: checking
    Assets:Bank:Checking  $-7.50
    Expenses:Food:Coffee

2026/03/07 Grocery Market
    ; import_account_id: checking
    Assets:Bank:Checking  $-84.30
    Expenses:Food:Groceries

2026/03/08 Unknown Merchant
    ; import_account_id: checking
    Assets:Bank:Checking  $-25.00
    Expenses:Unknown
""".strip() + "\n"


def _write_journal(config: AppConfig, body: str = JOURNAL_BODY) -> None:
    (config.journal_dir / "2026.journal").write_text(body, encoding="utf-8")
    ensure_workspace_journal_includes(config)


def test_unfiltered_returns_last_3_months(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, today=date(2026, 3, 9))

    assert result["period"] == "last-3-months"
    assert result["category"] is None
    assert result["month"] is None
    # Jan, Feb, Mar transactions should all be included (3-month window)
    assert result["totalCount"] == 7
    # Most recent first
    assert result["transactions"][0]["date"] == "2026-03-08"
    assert result["transactions"][-1]["date"] == "2026-01-10"


def test_month_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, month="2026-02", today=date(2026, 3, 9))

    assert result["month"] == "2026-02"
    assert result["period"] is None
    assert result["totalCount"] == 2
    payees = {tx["payee"] for tx in result["transactions"]}
    assert payees == {"February Paycheck", "February Groceries"}


def test_category_filter(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config, category="Expenses:Food:Groceries", today=date(2026, 3, 9)
    )

    assert result["category"] == "Expenses:Food:Groceries"
    assert result["totalCount"] == 3
    payees = [tx["payee"] for tx in result["transactions"]]
    assert "Grocery Market" in payees
    assert "February Groceries" in payees
    assert "January Groceries" in payees


def test_category_prefix_matching(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config, category="Expenses:Food", today=date(2026, 3, 9)
    )

    # Should match Expenses:Food:Groceries and Expenses:Food:Coffee
    assert result["totalCount"] == 4
    payees = {tx["payee"] for tx in result["transactions"]}
    assert "Coffee Shop" in payees
    assert "Grocery Market" in payees


def test_both_filters(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config, category="Expenses:Food:Groceries", month="2026-03", today=date(2026, 3, 9)
    )

    assert result["totalCount"] == 1
    assert result["transactions"][0]["payee"] == "Grocery Market"
    assert result["transactions"][0]["amount"] == -84.30


def test_empty_result(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config, category="Expenses:Nonexistent", today=date(2026, 3, 9)
    )

    assert result["totalCount"] == 0
    assert result["transactions"] == []


def test_this_month_period(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, period="this-month", today=date(2026, 3, 9))

    assert result["period"] == "this-month"
    assert result["totalCount"] == 3
    dates = {tx["date"] for tx in result["transactions"]}
    assert all(d.startswith("2026-03") for d in dates)


def test_last_30_period(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, period="last-30", today=date(2026, 3, 9))

    assert result["period"] == "last-30"
    # last-30 from Mar 9 = Feb 8 through Mar 9
    for tx in result["transactions"]:
        assert tx["date"] >= "2026-02-08"


def test_opening_balances_excluded(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-01-01 Opening balance
    ; tracked_account_id: checking
    Assets:Bank:Checking  USD 5000.00
    Equity:Opening-Balances
""".strip() + "\n",
        encoding="utf-8",
    )
    _write_journal(config)

    result = build_activity_view(config, today=date(2026, 3, 9))

    payees = {tx["payee"] for tx in result["transactions"]}
    assert "Opening balance" not in payees


def test_transaction_row_shape(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config, category="Expenses:Food:Groceries", month="2026-03", today=date(2026, 3, 9)
    )

    assert result["totalCount"] == 1
    tx = result["transactions"][0]
    assert tx["date"] == "2026-03-07"
    assert tx["payee"] == "Grocery Market"
    assert tx["accountLabel"] == "Wells Fargo Checking"
    assert tx["importAccountId"] == "checking"
    assert tx["category"] == "Food / Groceries"
    assert tx["categoryAccount"] == "Expenses:Food:Groceries"
    assert tx["amount"] == -84.30
    assert tx["isIncome"] is False
    assert tx["isUnknown"] is False
