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


# ---------------------------------------------------------------------------
# Summary block
# ---------------------------------------------------------------------------


def test_summary_is_null_when_no_results(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config, category="Expenses:Nonexistent", today=date(2026, 3, 9)
    )

    assert result["summary"] is None


def test_summary_month_filter_compares_to_prior_month(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, month="2026-03", today=date(2026, 3, 9))
    summary = result["summary"]

    assert summary is not None
    # Mar: Coffee -7.50, Grocery -84.30, Unknown -25.00
    assert summary["periodTotal"] == -116.80
    assert summary["periodCount"] == 3
    assert summary["averageAmount"] == round(-116.80 / 3, 2)
    # Feb: Paycheck +3000, Groceries -140.50
    assert summary["priorPeriodTotal"] == 2859.50
    assert summary["priorPeriodCount"] == 2
    assert summary["deltaAmount"] == round(-116.80 - 2859.50, 2)
    assert summary["deltaPercent"] is not None
    # Top of the March block by absolute value is Grocery Market
    assert summary["topTransaction"] is not None
    assert summary["topTransaction"]["payee"] == "Grocery Market"
    assert summary["topTransaction"]["amount"] == -84.30


def test_summary_month_filter_rolling_average(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, month="2026-03", today=date(2026, 3, 9))
    summary = result["summary"]

    assert summary is not None
    # Rolling window = 2025-09 .. 2026-02. Only Jan and Feb have data.
    # Jan total: 3000 - 120 = 2880; Feb total: 3000 - 140.50 = 2859.50.
    # Average across months with data = (2880 + 2859.50) / 2.
    assert summary["rollingMonths"] == 2
    assert summary["rollingMonthlyAverage"] == round((2880 + 2859.50) / 2, 2)


def test_summary_last_3_months_prior_null_when_no_earlier_data(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, today=date(2026, 3, 9))
    summary = result["summary"]

    assert summary is not None
    assert summary["periodCount"] == 7
    # Nothing exists before 2026-01-01, so prior period is genuinely absent.
    assert summary["priorPeriodTotal"] is None
    assert summary["priorPeriodCount"] is None
    assert summary["deltaAmount"] is None
    assert summary["deltaPercent"] is None
    # Rolling window = 2025-07 .. 2025-12, also empty.
    assert summary["rollingMonths"] == 0
    assert summary["rollingMonthlyAverage"] is None


def test_summary_this_month_prior_zero_when_earlier_data_exists(tmp_path: Path) -> None:
    """Feb 1-9 has no activity but Jan has data — prior should be 0/0, not null."""
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, period="this-month", today=date(2026, 3, 9))
    summary = result["summary"]

    assert summary is not None
    # March 1-9: Coffee, Grocery, Unknown = 3 txns totalling -116.80
    assert summary["periodCount"] == 3
    assert summary["periodTotal"] == -116.80
    # Prior window Feb 1 .. Feb 9: no transactions, but Jan has data → 0/0 not null.
    assert summary["priorPeriodTotal"] == 0
    assert summary["priorPeriodCount"] == 0
    # Delta amount = periodTotal - 0 = periodTotal. Delta percent = null (div by 0).
    assert summary["deltaAmount"] == -116.80
    assert summary["deltaPercent"] is None


def test_summary_category_filter_rolling_uses_category_only(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config,
        category="Expenses:Food:Groceries",
        month="2026-03",
        today=date(2026, 3, 9),
    )
    summary = result["summary"]

    assert summary is not None
    # March groceries: Grocery Market -84.30 (1 txn)
    assert summary["periodCount"] == 1
    assert summary["periodTotal"] == -84.30
    # Prior (Feb) groceries: February Groceries -140.50
    assert summary["priorPeriodTotal"] == -140.50
    assert summary["priorPeriodCount"] == 1
    # Rolling groceries: Jan -120, Feb -140.50 → 2 months with data, avg -130.25
    assert summary["rollingMonths"] == 2
    assert summary["rollingMonthlyAverage"] == -130.25


def test_summary_last_30_prior_window(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    # last-30 from Mar 9 covers Feb 8 .. Mar 9. Prior covers Jan 9 .. Feb 7.
    result = build_activity_view(config, period="last-30", today=date(2026, 3, 9))
    summary = result["summary"]

    assert summary is not None
    # Current window has Feb 12, Feb 18, Mar 1, Mar 7, Mar 8 — 5 transactions.
    assert summary["periodCount"] == 5
    # Prior window (Jan 9 .. Feb 7) has Jan 10 Paycheck and Jan 15 Groceries — 2 transactions.
    assert summary["priorPeriodCount"] == 2
    assert summary["priorPeriodTotal"] == round(3000 - 120, 2)


def test_summary_top_transaction_by_absolute_amount(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, month="2026-01", today=date(2026, 3, 9))
    summary = result["summary"]

    assert summary is not None
    assert summary["topTransaction"] is not None
    # Jan has Paycheck +3000 and Groceries -120. +3000 has the largest |amount|.
    assert summary["topTransaction"]["payee"] == "January Paycheck"
    assert summary["topTransaction"]["amount"] == 3000.00


def test_summary_single_transaction_period_still_returns_top(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config,
        category="Expenses:Food:Coffee",
        month="2026-03",
        today=date(2026, 3, 9),
    )
    summary = result["summary"]

    assert summary is not None
    assert summary["periodCount"] == 1
    assert summary["topTransaction"] is not None
    assert summary["topTransaction"]["payee"] == "Coffee Shop"


def test_summary_rolling_null_when_fewer_than_two_months_with_data(tmp_path: Path) -> None:
    """A category with data in only one rolling-window month should return null rolling avg."""
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    # Coffee only appears in March. Rolling window for month=2026-03 is Sep-Feb — no coffee there.
    result = build_activity_view(
        config,
        category="Expenses:Food:Coffee",
        month="2026-03",
        today=date(2026, 3, 9),
    )
    summary = result["summary"]

    assert summary is not None
    assert summary["rollingMonths"] == 0
    assert summary["rollingMonthlyAverage"] is None


def test_summary_null_prior_when_first_period_of_category(tmp_path: Path) -> None:
    """Category that first appears in the current window has null prior, not 0."""
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(
        config,
        category="Expenses:Food:Coffee",
        month="2026-03",
        today=date(2026, 3, 9),
    )
    summary = result["summary"]

    assert summary is not None
    assert summary["periodCount"] == 1
    # No coffee transactions exist before March at all.
    assert summary["priorPeriodTotal"] is None
    assert summary["priorPeriodCount"] is None
    assert summary["deltaAmount"] is None
    assert summary["deltaPercent"] is None


def test_summary_preserves_existing_response_fields(tmp_path: Path) -> None:
    """The summary field is additive — existing fields must be unchanged."""
    config = _make_config(tmp_path / "workspace")
    _write_journal(config)

    result = build_activity_view(config, today=date(2026, 3, 9))

    assert "baseCurrency" in result
    assert "period" in result
    assert "category" in result
    assert "month" in result
    assert "transactions" in result
    assert "totalCount" in result
    assert "summary" in result
    # Transaction row shape is unchanged — still the same fields as before the refactor.
    first = result["transactions"][0]
    assert set(first.keys()) == {
        "date",
        "payee",
        "accountLabel",
        "importAccountId",
        "category",
        "categoryAccount",
        "amount",
        "isIncome",
        "isUnknown",
    }
