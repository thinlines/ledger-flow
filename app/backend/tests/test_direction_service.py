from __future__ import annotations

from datetime import date
from pathlib import Path

from services.config_service import AppConfig
from services.direction_service import build_dashboard_direction
from services.workspace_service import ensure_workspace_journal_includes


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2025, "base_currency": "USD"},
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


def _write_journal(config: AppConfig, filename: str, body: str) -> None:
    (config.journal_dir / filename).write_text(body, encoding="utf-8")
    ensure_workspace_journal_includes(config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_direction_empty_workspace(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config, "2026.journal", "")

    result = build_dashboard_direction(config, today=date(2026, 4, 18))

    assert result["runway"] is None
    assert result["netWorthTrend"] is None
    assert result["recurringVsDiscretionary"]["total"] == 0.0
    assert result["notableSignals"]["largestThisWeek"] is None
    assert result["notableSignals"]["categorySpike"] is None
    assert result["notableSignals"]["spendingStreak"] is None
    assert result["looseEnds"]["reviewQueueCount"] == 0
    assert result["baseCurrency"] == "USD"


def test_runway_gauge_computed_correctly(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    # 6 months of spending at $1000/mo, asset balance of $5000
    journal = ""
    for month_num in range(11, 17):  # Nov 2025 through Apr 2026
        year = 2025 if month_num <= 12 else 2026
        m = month_num if month_num <= 12 else month_num - 12
        journal += f"""
{year:04d}/{m:02d}/15 Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  $2000.00
    Income:Salary

{year:04d}/{m:02d}/20 Rent
    ; import_account_id: checking
    Expenses:Housing:Rent  $1000.00
    Assets:Bank:Checking
"""
    _write_journal(config, "2025.journal", "")
    _write_journal(config, "2026.journal", "")
    # Write all to a single journal to keep it simple
    (config.journal_dir / "2025.journal").write_text(journal, encoding="utf-8")
    ensure_workspace_journal_includes(config)

    result = build_dashboard_direction(config, today=date(2026, 4, 18))

    assert result["runway"] is not None
    # spendable cash = 6 * $2000 - 6 * $1000 = $6000
    assert result["runway"]["spendableCash"] == 6000.0
    assert result["runway"]["avgMonthlySpending"] == 1000.0
    assert result["runway"]["months"] == 6.0


def test_runway_null_when_no_spending(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(
        config,
        "2026.journal",
        """
2026/04/10 Deposit
    ; import_account_id: checking
    Assets:Bank:Checking  $5000.00
    Income:Salary
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    assert result["runway"] is None


def test_net_worth_trend_needs_two_months(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(
        config,
        "2026.journal",
        """
2026/04/10 Deposit
    ; import_account_id: checking
    Assets:Bank:Checking  $3000.00
    Income:Salary
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    # Only 1 month of data, needs 2+
    assert result["netWorthTrend"] is None


def test_net_worth_trend_with_multiple_months(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(
        config,
        "2026.journal",
        """
2026/03/10 Deposit
    ; import_account_id: checking
    Assets:Bank:Checking  $3000.00
    Income:Salary

2026/04/10 Deposit
    ; import_account_id: checking
    Assets:Bank:Checking  $2000.00
    Income:Salary
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    assert result["netWorthTrend"] is not None
    assert len(result["netWorthTrend"]) >= 2
    # March should show $3000, April should show $5000
    by_month = {entry["month"]: entry["value"] for entry in result["netWorthTrend"]}
    assert by_month["2026-03"] == 3000.0
    assert by_month["2026-04"] == 5000.0


def test_recurring_vs_discretionary_split(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    # Rent appears in 5 months (recurring), coffee in 1 month (discretionary)
    journal = ""
    for month_num in range(11, 16):  # Nov 2025 through Mar 2026
        year = 2025 if month_num <= 12 else 2026
        m = month_num if month_num <= 12 else month_num - 12
        journal += f"""
{year:04d}/{m:02d}/15 Rent
    ; import_account_id: checking
    Expenses:Housing:Rent  $1200.00
    Assets:Bank:Checking
"""
    # April: rent + coffee
    journal += """
2026/04/01 Rent
    ; import_account_id: checking
    Expenses:Housing:Rent  $1200.00
    Assets:Bank:Checking

2026/04/05 Coffee Shop
    ; import_account_id: checking
    Expenses:Food:Coffee  $25.00
    Assets:Bank:Checking
"""
    _write_journal(config, "2025.journal", "")
    (config.journal_dir / "2025.journal").write_text(journal, encoding="utf-8")
    ensure_workspace_journal_includes(config)

    result = build_dashboard_direction(config, today=date(2026, 4, 18))

    rvd = result["recurringVsDiscretionary"]
    assert rvd["recurring"] == 1200.0
    assert rvd["discretionary"] == 25.0
    assert rvd["total"] == 1225.0
    assert "Housing / Rent" in rvd["recurringCategories"]


def test_largest_this_week(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(
        config,
        "2026.journal",
        """
2026/04/12 Small Coffee
    ; import_account_id: checking
    Expenses:Food:Coffee  $5.00
    Assets:Bank:Checking

2026/04/14 Big Purchase
    ; import_account_id: checking
    Expenses:Shopping  $412.80
    Assets:Bank:Checking

2026/04/01 Old Transaction
    ; import_account_id: checking
    Expenses:Shopping  $999.00
    Assets:Bank:Checking
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))

    largest = result["notableSignals"]["largestThisWeek"]
    assert largest is not None
    assert largest["payee"] == "Big Purchase"
    assert largest["amount"] == -412.80
    assert largest["date"] == "2026-04-14"


def test_category_spike(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    # Dining usually $100/mo, this month $300 (3x)
    journal = ""
    for month_num in range(11, 16):
        year = 2025 if month_num <= 12 else 2026
        m = month_num if month_num <= 12 else month_num - 12
        journal += f"""
{year:04d}/{m:02d}/15 Restaurant
    ; import_account_id: checking
    Expenses:Food:Dining  $100.00
    Assets:Bank:Checking
"""
    journal += """
2026/04/10 Fancy Dinner
    ; import_account_id: checking
    Expenses:Food:Dining  $300.00
    Assets:Bank:Checking
"""
    _write_journal(config, "2025.journal", "")
    (config.journal_dir / "2025.journal").write_text(journal, encoding="utf-8")
    ensure_workspace_journal_includes(config)

    result = build_dashboard_direction(config, today=date(2026, 4, 18))

    spike = result["notableSignals"]["categorySpike"]
    assert spike is not None
    assert spike["category"] == "Food / Dining"
    assert spike["current"] == 300.0
    # Average over 6 months: (5*100 + 300) / 6 = 133.33
    assert spike["ratio"] >= 2.0


def test_spending_streak(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    # 3 months where spending > income
    journal = ""
    for month_offset in range(2, 5):  # Feb, Mar, Apr 2026
        journal += f"""
2026/{month_offset:02d}/10 Income
    ; import_account_id: checking
    Assets:Bank:Checking  $1000.00
    Income:Salary

2026/{month_offset:02d}/15 Spending
    ; import_account_id: checking
    Expenses:Shopping  $1500.00
    Assets:Bank:Checking
"""
    _write_journal(config, "2026.journal", journal)

    result = build_dashboard_direction(config, today=date(2026, 4, 18))

    streak = result["notableSignals"]["spendingStreak"]
    assert streak is not None
    assert streak["months"] == 3


def test_spending_streak_null_when_one_month(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(
        config,
        "2026.journal",
        """
2026/03/10 Income
    ; import_account_id: checking
    Assets:Bank:Checking  $2000.00
    Income:Salary

2026/03/15 Spending
    ; import_account_id: checking
    Expenses:Shopping  $500.00
    Assets:Bank:Checking

2026/04/10 Income
    ; import_account_id: checking
    Assets:Bank:Checking  $1000.00
    Income:Salary

2026/04/15 Spending
    ; import_account_id: checking
    Expenses:Shopping  $1500.00
    Assets:Bank:Checking
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    # Only 1 month of overspending — streak should be null
    assert result["notableSignals"]["spendingStreak"] is None


def test_loose_ends_review_queue(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(
        config,
        "2026.journal",
        """
2026/04/10 Unknown Merchant
    ; import_account_id: checking
    Assets:Bank:Checking  $-50.00
    Expenses:Unknown

2026/04/12 Another Unknown
    ; import_account_id: checking
    Assets:Bank:Checking  $-30.00
    Expenses:Unknown
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    assert result["looseEnds"]["reviewQueueCount"] == 2


def test_loose_ends_statement_inbox(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config, "2026.journal", "")
    # Put CSVs in the inbox
    (config.csv_dir / "statement1.csv").write_text("header\n", encoding="utf-8")
    (config.csv_dir / "statement2.csv").write_text("header\n", encoding="utf-8")

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    assert result["looseEnds"]["statementInboxCount"] == 2


def test_loose_ends_stale_accounts(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(
        config,
        "2026.journal",
        """
2026/02/10 Old Transaction
    ; import_account_id: checking
    Assets:Bank:Checking  $-100.00
    Expenses:Shopping
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    stale = result["looseEnds"]["staleAccounts"]
    stale_ids = [s["id"] for s in stale]
    assert "checking" in stale_ids
    # Check that daysSinceActivity is correct (Feb 10 to Apr 18 = 67 days)
    checking_stale = next(s for s in stale if s["id"] == "checking")
    assert checking_stale["daysSinceActivity"] == 67


def test_loose_ends_missing_opening_balances(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(
        config,
        "2026.journal",
        """
2026/04/10 Transaction
    ; import_account_id: checking
    Assets:Bank:Checking  $-100.00
    Expenses:Shopping
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    missing = result["looseEnds"]["missingOpeningBalances"]
    missing_ids = [m["id"] for m in missing]
    assert "checking" in missing_ids


def test_missing_opening_balances_not_reported_when_present(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-01-01 Opening balance
    ; tracked_account_id: checking
    Assets:Bank:Checking  USD 1000.00
    Equity:Opening-Balances
""".strip() + "\n",
        encoding="utf-8",
    )
    _write_journal(
        config,
        "2026.journal",
        """
2026/04/10 Transaction
    ; import_account_id: checking
    Assets:Bank:Checking  $-100.00
    Expenses:Shopping
""".strip() + "\n",
    )

    result = build_dashboard_direction(config, today=date(2026, 4, 18))
    missing_ids = [m["id"] for m in result["looseEnds"]["missingOpeningBalances"]]
    assert "checking" not in missing_ids


def test_all_signals_null_gracefully(tmp_path: Path) -> None:
    """Every signal degrades to null when workspace has no data."""
    config = _make_config(tmp_path / "workspace")
    _write_journal(config, "2026.journal", "")

    result = build_dashboard_direction(config, today=date(2026, 4, 18))

    assert result["runway"] is None
    assert result["netWorthTrend"] is None
    assert result["recurringVsDiscretionary"]["total"] == 0.0
    assert result["notableSignals"]["largestThisWeek"] is None
    assert result["notableSignals"]["categorySpike"] is None
    assert result["notableSignals"]["spendingStreak"] is None
