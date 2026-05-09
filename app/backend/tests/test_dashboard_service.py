from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from services.commodity_service import CommodityMismatchError
from services.config_service import AppConfig
from services.dashboard_service import build_dashboard_overview, query_dashboard_transactions
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


def _write_year_journal(config: AppConfig, body: str = "") -> None:
    (config.journal_dir / "2026.journal").write_text(body, encoding="utf-8")
    ensure_workspace_journal_includes(config)


def test_dashboard_overview_summarizes_financial_state(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
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
    assert balances["checking"]["lastTransactionDate"] == "2026-03-08"
    assert balances["visa"]["lastTransactionDate"] == "2026-03-05"

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
    _write_year_journal(config)

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
    _write_year_journal(config)

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    balances = {row["id"]: row for row in overview["balances"]}
    assert balances["cash_wallet"]["balance"] == 250.0
    assert balances["cash_wallet"]["hasOpeningBalance"] is True
    assert balances["cash_wallet"]["hasTransactionActivity"] is False
    assert balances["cash_wallet"]["hasBalanceSource"] is True
    assert balances["cash_wallet"]["lastTransactionDate"] is None
    assert overview["summary"]["trackedBalanceTotal"] == 250.0
    assert overview["summary"]["netWorth"] == 250.0
    assert overview["summary"]["transactionCount"] == 0
    assert overview["recentTransactions"] == []


def test_dashboard_overview_rejects_mixed_commodities_for_account_balance(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-01-15 Opening balance
    ; tracked_account_id: checking
    Assets:Bank:Checking  USD 200.00
    Equity:Opening-Balances
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(
        config,
        """
2026/02/12 Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  $1000.00 = $1200.00
    Income:Salary
""".strip()
        + "\n",
    )

    with pytest.raises(CommodityMismatchError, match="mixes commodities"):
        build_dashboard_overview(config, today=date(2026, 3, 9))


def test_dashboard_overview_reflects_tracked_account_offset_opening_balances_on_both_accounts(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    config.tracked_accounts["loan"] = {
        "display_name": "Car Loan",
        "ledger_account": "Liabilities:Loans:Car",
    }
    (config.opening_bal_dir / "loan.journal").write_text(
        """
2026-01-15 Opening balance
    ; tracked_account_id: loan
    Liabilities:Loans:Car  USD -18500.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(config)

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    balances = {row["id"]: row for row in overview["balances"]}
    assert balances["checking"]["balance"] == 18500.0
    assert balances["checking"]["hasOpeningBalance"] is False
    assert balances["checking"]["hasTransactionActivity"] is False
    assert balances["checking"]["hasBalanceSource"] is True
    assert balances["loan"]["balance"] == -18500.0
    assert balances["loan"]["hasOpeningBalance"] is True
    assert balances["loan"]["hasTransactionActivity"] is False
    assert balances["loan"]["hasBalanceSource"] is True
    assert overview["summary"]["trackedBalanceTotal"] == 0.0
    assert overview["summary"]["netWorth"] == 0.0
    assert overview["summary"]["transactionCount"] == 0


# --- categoryHistory and cashFlowHistory tests ---

_FIXTURE_JOURNAL = """
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
""".strip() + "\n"


def test_category_history_contains_all_month_category_pairs(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config, _FIXTURE_JOURNAL)

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    history = overview["categoryHistory"]
    by_key = {(r["month"], r["category"]): r for r in history}

    assert ("2026-02", "Expenses:Housing:Rent") in by_key
    assert by_key[("2026-02", "Expenses:Housing:Rent")]["amount"] == 1200.0
    assert by_key[("2026-02", "Expenses:Housing:Rent")]["categoryLabel"] == "Housing / Rent"

    assert ("2026-02", "Expenses:Food:Groceries") in by_key
    assert by_key[("2026-02", "Expenses:Food:Groceries")]["amount"] == 140.5

    assert ("2026-03", "Expenses:Food:Groceries") in by_key
    assert by_key[("2026-03", "Expenses:Food:Groceries")]["amount"] == 84.3

    assert ("2026-03", "Expenses:Shopping") in by_key
    assert by_key[("2026-03", "Expenses:Shopping")]["amount"] == 83.21

    assert ("2026-03", "Expenses:Food:Coffee") in by_key
    assert by_key[("2026-03", "Expenses:Food:Coffee")]["amount"] == 7.5

    # Transfers should not appear in categoryHistory
    transfer_keys = [k for k in by_key if "Assets:" in k[1] or "Liabilities:" in k[1]]
    assert transfer_keys == []

    # Sorted by (month, category)
    months_and_cats = [(r["month"], r["category"]) for r in history]
    assert months_and_cats == sorted(months_and_cats)


def test_cash_flow_history_contains_all_months(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config, _FIXTURE_JOURNAL)

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    history = overview["cashFlowHistory"]
    months = [r["month"] for r in history]
    assert "2026-02" in months
    assert "2026-03" in months

    feb = next(r for r in history if r["month"] == "2026-02")
    assert feb["income"] == 2500.0
    assert feb["spending"] == 1340.5
    assert feb["net"] == 2500.0 - 1340.5
    assert feb["label"] == "Feb"

    mar = next(r for r in history if r["month"] == "2026-03")
    assert mar["income"] == 2500.0
    assert mar["spending"] == 200.01

    # Sorted chronologically
    assert months == sorted(months)


def test_empty_journal_returns_empty_history_arrays(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config)

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    assert overview["categoryHistory"] == []
    assert overview["cashFlowHistory"] == []


def test_opening_balance_excluded_from_category_history(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    config.tracked_accounts["cash_wallet"] = {
        "display_name": "Cash Wallet",
        "ledger_account": "Assets:Cash:Wallet",
    }
    (config.opening_bal_dir / "cash_wallet.journal").write_text(
        "2026-01-15 Opening balance\n"
        "    ; tracked_account_id: cash_wallet\n"
        "    Assets:Cash:Wallet  USD 250.00\n"
        "    Equity:Opening-Balances\n",
        encoding="utf-8",
    )
    _write_year_journal(config)

    overview = build_dashboard_overview(config, today=date(2026, 3, 9))

    assert overview["categoryHistory"] == []
    assert overview["cashFlowHistory"] == []


# --- dashboard transactions endpoint tests ---


def test_dashboard_transactions_returns_matching_period(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config, _FIXTURE_JOURNAL)

    result = query_dashboard_transactions(config, period="2026-03")

    assert result["period"] == "2026-03"
    assert result["category"] is None
    # March has: Coffee Shop, Paycheck, Online Shop, CC Payment, Grocery Market, Unknown Merchant
    assert result["total"] == 6
    assert len(result["transactions"]) == 6
    dates = [r["date"] for r in result["transactions"]]
    assert dates == sorted(dates, reverse=True)


def test_dashboard_transactions_filters_by_category(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config, _FIXTURE_JOURNAL)

    result = query_dashboard_transactions(
        config, period="2026-03", category="Expenses:Food:Groceries"
    )

    assert result["total"] == 1
    assert result["transactions"][0]["payee"] == "Grocery Market"
    assert result["category"] == "Expenses:Food:Groceries"


def test_dashboard_transactions_category_prefix_match(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config, _FIXTURE_JOURNAL)

    result = query_dashboard_transactions(
        config, period="2026-03", category="Expenses:Food"
    )

    # Should match both Coffee and Groceries in March
    assert result["total"] == 2
    payees = {r["payee"] for r in result["transactions"]}
    assert payees == {"Coffee Shop", "Grocery Market"}


def test_dashboard_transactions_pagination(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config, _FIXTURE_JOURNAL)

    result = query_dashboard_transactions(config, period="2026-03", limit=2, offset=0)

    assert result["total"] == 6
    assert len(result["transactions"]) == 2

    result2 = query_dashboard_transactions(config, period="2026-03", limit=2, offset=2)
    assert result2["total"] == 6
    assert len(result2["transactions"]) == 2
    assert result2["transactions"][0] != result["transactions"][0]


def test_dashboard_transactions_invalid_period_raises(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config)

    with pytest.raises(ValueError, match="Invalid period format"):
        query_dashboard_transactions(config, period="invalid")

    with pytest.raises(ValueError, match="Invalid period format"):
        query_dashboard_transactions(config, period="2026-13")


def test_dashboard_transactions_empty_period_returns_empty(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(config, _FIXTURE_JOURNAL)

    result = query_dashboard_transactions(config, period="2025-01")

    assert result["total"] == 0
    assert result["transactions"] == []


def test_dashboard_transactions_excludes_opening_balances(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    config.tracked_accounts["cash_wallet"] = {
        "display_name": "Cash Wallet",
        "ledger_account": "Assets:Cash:Wallet",
    }
    (config.opening_bal_dir / "cash_wallet.journal").write_text(
        "2026-01-15 Opening balance\n"
        "    ; tracked_account_id: cash_wallet\n"
        "    Assets:Cash:Wallet  USD 250.00\n"
        "    Equity:Opening-Balances\n",
        encoding="utf-8",
    )
    _write_year_journal(config)

    result = query_dashboard_transactions(config, period="2026-01")

    assert result["total"] == 0
    assert result["transactions"] == []
