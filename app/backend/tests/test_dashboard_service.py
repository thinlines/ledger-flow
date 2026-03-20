from __future__ import annotations

from datetime import date
from pathlib import Path

from services.config_service import AppConfig
from services.dashboard_service import build_dashboard_overview


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
            "visa": {
                "display_name": "Visa",
                "parser": "visa",
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
        },
        payee_aliases="payee_aliases.csv",
    )


def test_dashboard_overview_summarizes_financial_state(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.journal_dir / "2026.journal").write_text(
        """
2026/02/12 Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  $2500.00
    Income:Salary

2026/02/14 Rent
    ; import_account_id: checking
    Expenses:Housing:Rent  $1200.00
    Assets:Bank:Checking

2026/02/18 Grocer
    ; import_account_id: checking
    Expenses:Food:Groceries  $140.50
    Assets:Bank:Checking

2026/03/01 Coffee Shop
    ; import_account_id: checking
    Assets:Bank:Checking  $-7.50
    Expenses:Food:Coffee

2026/03/02 Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  $2500.00
    Income:Salary

2026/03/04 Online Shop
    ; import_account_id: visa
    Liabilities:Cards:Visa  $-83.21
    Expenses:Shopping

2026/03/05 Credit Card Payment
    ; import_account_id: checking
    Liabilities:Cards:Visa  $50.00
    Assets:Bank:Checking

2026/03/07 Grocery Market
    ; import_account_id: checking
    Assets:Bank:Checking  $-84.30
    Expenses:Food:Groceries

2026/03/08 Unknown Merchant
    ; import_account_id: checking
    Assets:Bank:Checking  $-25.00
    Expenses:Unknown
""".strip()
        + "\n",
        encoding="utf-8",
    )

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    assert overview["hasData"] is True
    assert overview["lastUpdated"] == "2026-03-08"
    assert overview["summary"]["netWorth"] == 3459.49
    assert overview["summary"]["trackedBalanceTotal"] == 3459.49
    assert overview["summary"]["incomeThisMonth"] == 2500.0
    assert overview["summary"]["spendingThisMonth"] == 200.01
    assert overview["summary"]["savingsThisMonth"] == 2299.99
    assert overview["summary"]["unknownTransactionCount"] == 1

    balances = {row["id"]: row for row in overview["balances"]}
    assert balances["checking"]["balance"] == 3492.7
    assert balances["visa"]["balance"] == -33.21
    assert balances["checking"]["hasOpeningBalance"] is False
    assert balances["checking"]["hasTransactionActivity"] is True
    assert balances["checking"]["hasBalanceSource"] is True
    assert balances["visa"]["hasOpeningBalance"] is False
    assert balances["visa"]["hasTransactionActivity"] is True
    assert balances["visa"]["hasBalanceSource"] is True

    assert overview["cashFlow"]["series"][-1] == {
        "month": "2026-03",
        "label": "Mar",
        "income": 2500.0,
        "spending": 200.01,
        "net": 2299.99,
    }

    category_rows = {row["category"]: row for row in overview["categoryTrends"]}
    assert category_rows["Food / Groceries"]["current"] == 84.3
    assert category_rows["Food / Groceries"]["previous"] == 140.5
    assert category_rows["Food / Groceries"]["delta"] == -56.2
    assert category_rows["Food / Groceries"]["direction"] == "down"

    latest = overview["recentTransactions"][0]
    assert latest["date"] == "2026-03-08"
    assert latest["payee"] == "Unknown Merchant"
    assert latest["accountLabel"] == "Wells Fargo Checking"
    assert latest["category"] == "Unknown"
    assert latest["amount"] == -25.0
    assert latest["isUnknown"] is True


def test_dashboard_overview_handles_empty_journals(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.journal_dir / "2026.journal").write_text("", encoding="utf-8")

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    assert overview["hasData"] is False
    assert overview["lastUpdated"] is None
    assert overview["summary"]["netWorth"] == 0.0
    assert overview["balances"][0]["balance"] == 0.0
    assert overview["balances"][0]["hasBalanceSource"] is False
    assert overview["recentTransactions"] == []


def test_dashboard_overview_includes_opening_balances_without_counting_them_as_activity(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    config.tracked_accounts["cash_wallet"] = {
        "display_name": "Cash Wallet",
        "ledger_account": "Assets:Cash:Wallet",
    }
    (config.opening_bal_dir / "cash_wallet.journal").write_text(
        """
2026-01-15 Opening balance
    ; tracked_account_id: cash_wallet
    Assets:Cash:Wallet  USD 250.00
    Equity:Opening-Balances
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (config.journal_dir / "2026.journal").write_text("", encoding="utf-8")

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    balances = {row["id"]: row for row in overview["balances"]}
    assert balances["cash_wallet"]["balance"] == 250.0
    assert balances["cash_wallet"]["hasOpeningBalance"] is True
    assert balances["cash_wallet"]["hasTransactionActivity"] is False
    assert balances["cash_wallet"]["hasBalanceSource"] is True
    assert overview["summary"]["trackedBalanceTotal"] == 250.0
    assert overview["summary"]["netWorth"] == 250.0
    assert overview["summary"]["transactionCount"] == 0
    assert overview["recentTransactions"] == []
