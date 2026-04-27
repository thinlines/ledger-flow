"""Tests for GET /api/accounts/{accountId}/reconciliation-context."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from services.config_service import AppConfig


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
        import_accounts={},
        tracked_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "ledger_account": "Assets:Checking:Wells Fargo",
                "import_account_id": None,
            },
            "savings": {
                "display_name": "Savings",
                "ledger_account": "Assets:Savings",
                "import_account_id": None,
            },
            "salary": {
                "display_name": "Salary",
                "ledger_account": "Income:Salary",
                "import_account_id": None,
            },
        },
        payee_aliases="payee_aliases.csv",
    )


def _seed_journal(config: AppConfig, body: str) -> Path:
    journal = config.journal_dir / "2026.journal"
    journal.write_text(body, encoding="utf-8")
    return journal


def _seed_accounts_dat(config: AppConfig) -> None:
    lines = [
        "account Assets:Checking:Wells Fargo",
        "account Assets:Savings",
        "account Income:Salary",
        "account Expenses:Food:Coffee",
        "account Equity:Opening-Balances",
    ]
    (config.init_dir / "10-accounts.dat").write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestContextValidation:
    def test_unknown_account_returns_404(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconciliation_context(
                "ghost", period_start="2026-03-01", period_end="2026-03-31"
            )
        assert exc.value.status_code == 404

    def test_income_account_returns_400(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconciliation_context(
                "salary", period_start="2026-03-01", period_end="2026-03-31"
            )
        assert exc.value.status_code == 400
        assert "asset and liability" in str(exc.value.detail)

    def test_period_start_after_end_returns_400(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconciliation_context(
                "checking", period_start="2026-04-01", period_end="2026-03-31"
            )
        assert exc.value.status_code == 400

    def test_invalid_date_returns_400(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconciliation_context(
                "checking", period_start="not-a-date", period_end="2026-03-31"
            )
        assert exc.value.status_code == 400


class TestContextOpeningBalance:
    def test_opening_balance_is_running_balance_at_period_start_minus_one(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        body = (
            "2026-01-01 * Opening Balance\n"
            "    ; tracked_account_id: checking\n"
            "    Assets:Checking:Wells Fargo  $1000.00\n"
            "    Equity:Opening-Balances\n"
            "\n"
            "2026-02-15 Salary deposit\n"
            "    Assets:Checking:Wells Fargo  $500.00\n"
            "    Income:Salary\n"
            "\n"
            "2026-03-05 Coffee\n"
            "    Assets:Checking:Wells Fargo  $-4.50\n"
            "    Expenses:Food:Coffee\n"
        )
        _seed_journal(config, body)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.accounts_reconciliation_context(
            "checking", period_start="2026-03-01", period_end="2026-03-31"
        )
        assert result["openingBalance"] == "1500.00"
        assert result["currency"] == "USD"
        assert result["lastReconciliationDate"] is None
        assert len(result["transactions"]) == 1
        row = result["transactions"][0]
        assert row["date"] == "2026-03-05"
        assert row["payee"] == "Coffee"
        assert row["category"] == "Expenses:Food:Coffee"
        assert row["signedAmount"] == "-4.50"

    def test_first_reconciliation_with_opening_balance_in_period(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        body = (
            "2026-01-01 * Opening Balance\n"
            "    ; tracked_account_id: checking\n"
            "    Assets:Checking:Wells Fargo  $1000.00\n"
            "    Equity:Opening-Balances\n"
        )
        _seed_journal(config, body)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.accounts_reconciliation_context(
            "checking", period_start="2026-01-01", period_end="2026-01-31"
        )
        assert result["openingBalance"] == "0"
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["payee"] == "Opening balance"
        assert result["transactions"][0]["signedAmount"] == "1000.00"


class TestContextTransfers:
    def test_tracked_to_tracked_transfer_returns_one_row_per_account(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        # Single transaction with both postings — the asserted account sees its
        # own posting amount, never the peer's.
        body = (
            "2026-03-10 Transfer to savings\n"
            "    Assets:Checking:Wells Fargo  $-200.00\n"
            "    Assets:Savings  $200.00\n"
        )
        _seed_journal(config, body)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        checking_ctx = main.accounts_reconciliation_context(
            "checking", period_start="2026-03-01", period_end="2026-03-31"
        )
        assert len(checking_ctx["transactions"]) == 1
        assert checking_ctx["transactions"][0]["signedAmount"] == "-200.00"

        savings_ctx = main.accounts_reconciliation_context(
            "savings", period_start="2026-03-01", period_end="2026-03-31"
        )
        assert len(savings_ctx["transactions"]) == 1
        assert savings_ctx["transactions"][0]["signedAmount"] == "200.00"


class TestContextFiltering:
    def test_only_includes_transactions_in_range(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        body = (
            "2026-02-15 Before period\n"
            "    Assets:Checking:Wells Fargo  $-10.00\n"
            "    Expenses:Food:Coffee\n"
            "\n"
            "2026-03-15 In period\n"
            "    Assets:Checking:Wells Fargo  $-20.00\n"
            "    Expenses:Food:Coffee\n"
            "\n"
            "2026-04-15 After period\n"
            "    Assets:Checking:Wells Fargo  $-30.00\n"
            "    Expenses:Food:Coffee\n"
        )
        _seed_journal(config, body)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.accounts_reconciliation_context(
            "checking", period_start="2026-03-01", period_end="2026-03-31"
        )
        assert [r["payee"] for r in result["transactions"]] == ["In period"]
        assert result["openingBalance"] == "-10.00"

    def test_excludes_postings_on_other_accounts(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        body = (
            "2026-03-15 Coffee from savings\n"
            "    Assets:Savings  $-4.50\n"
            "    Expenses:Food:Coffee\n"
        )
        _seed_journal(config, body)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.accounts_reconciliation_context(
            "checking", period_start="2026-03-01", period_end="2026-03-31"
        )
        assert result["transactions"] == []
        assert result["openingBalance"] == "0"

    def test_skips_reconciliation_assertion_transactions(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        body = (
            "2026-03-05 Coffee\n"
            "    Assets:Checking:Wells Fargo  $-4.50\n"
            "    Expenses:Food:Coffee\n"
            "\n"
            "2026-03-10 * Statement reconciliation · Wells Fargo Checking · ending 2026-03-10\n"
            "    ; reconciliation_event_id: deadbeef-cafe\n"
            "    ; statement_period: 2026-03-01..2026-03-10\n"
            "    Assets:Checking:Wells Fargo  $0 = $-4.50\n"
        )
        _seed_journal(config, body)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.accounts_reconciliation_context(
            "checking", period_start="2026-03-01", period_end="2026-03-31"
        )
        assert [r["payee"] for r in result["transactions"]] == ["Coffee"]
        assert result["lastReconciliationDate"] == "2026-03-10"


class TestContextLastReconciliationDate:
    def test_reports_latest_recon_date(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        body = (
            "2026-02-28 * Statement reconciliation · Wells Fargo Checking · ending 2026-02-28\n"
            "    ; reconciliation_event_id: aaaaaaaa-1\n"
            "    ; statement_period: 2026-02-01..2026-02-28\n"
            "    Assets:Checking:Wells Fargo  $0 = $0.00\n"
        )
        _seed_journal(config, body)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.accounts_reconciliation_context(
            "checking", period_start="2026-03-01", period_end="2026-03-31"
        )
        assert result["lastReconciliationDate"] == "2026-02-28"
