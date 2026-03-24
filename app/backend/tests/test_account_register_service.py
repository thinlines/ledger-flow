from __future__ import annotations

from pathlib import Path

from services.account_register_service import build_account_register
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
            "vehicle": {
                "display_name": "Vehicle",
                "ledger_account": "Assets:Vehicle:Subaru",
                "import_account_id": None,
            },
        },
        payee_aliases="payee_aliases.csv",
    )


def _write_year_journal(config: AppConfig, body: str = "") -> None:
    (config.journal_dir / "2026.journal").write_text(body, encoding="utf-8")
    ensure_workspace_journal_includes(config)


def test_account_register_returns_latest_first_rows_with_running_balances(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-02-01 Opening balance
    ; tracked_account_id: checking
    Assets:Bank:Checking  USD 500.00
    Equity:Opening-Balances
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(
        config,
        """
2026/02/02 Grocer
    ; import_account_id: checking
    Expenses:Food:Groceries  $20.00
    Assets:Bank:Checking

2026/02/03 Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  $100.00
    Income:Salary

2026/02/04 Transfer to savings
    ; import_account_id: checking
    Assets:Savings  $30.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "checking")

    assert register["currentBalance"] == 550.0
    assert register["transactionCount"] == 3
    assert register["entryCount"] == 4
    assert register["latestActivityDate"] == "2026-02-04"

    latest = register["entries"][0]
    assert latest["date"] == "2026-02-04"
    assert latest["payee"] == "Transfer to savings"
    assert latest["summary"] == "Transfer · Savings"
    assert latest["amount"] == -30.0
    assert latest["runningBalance"] == 550.0

    middle = register["entries"][1]
    assert middle["date"] == "2026-02-03"
    assert middle["summary"] == "Salary"
    assert middle["amount"] == 100.0
    assert middle["runningBalance"] == 580.0

    opening = register["entries"][-1]
    assert opening["date"] == "2026-02-01"
    assert opening["payee"] == "Opening balance"
    assert opening["isOpeningBalance"] is True
    assert opening["amount"] == 500.0
    assert opening["runningBalance"] == 500.0


def test_account_register_preserves_liability_signs_in_running_balance(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/03/04 Online Shop
    ; import_account_id: visa
    Liabilities:Cards:Visa  $-83.21
    Expenses:Shopping

2026/03/05 Credit Card Payment
    ; import_account_id: checking
    Liabilities:Cards:Visa  $50.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "visa")

    assert register["currentBalance"] == -33.21
    assert register["transactionCount"] == 2
    assert register["entryCount"] == 2

    latest = register["entries"][0]
    assert latest["date"] == "2026-03-05"
    assert latest["amount"] == 50.0
    assert latest["runningBalance"] == -33.21

    first_charge = register["entries"][1]
    assert first_charge["date"] == "2026-03-04"
    assert first_charge["amount"] == -83.21
    assert first_charge["runningBalance"] == -83.21


def test_account_register_shows_selected_tracked_account_for_opening_balance_detail(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "visa.journal").write_text(
        """
2026-02-01 Opening balance
    ; tracked_account_id: visa
    Liabilities:Cards:Visa  USD -850.00
    Assets:Bank:Checking
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(config)

    register = build_account_register(config, "visa")

    opening = register["entries"][0]
    assert opening["payee"] == "Opening balance"
    assert opening["detailLines"] == [
        {
            "label": "Wells Fargo Checking",
            "account": "Assets:Bank:Checking",
            "kind": "asset",
        }
    ]


def test_account_register_uses_transfer_peer_metadata_for_pending_transfers(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/04 Transfer to savings
    ; import_account_id: checking
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    Assets:Transfers:checking__savings  $30.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "checking")

    latest = register["entries"][0]
    assert latest["summary"] == "Transfer · Savings (Pending)"
    assert latest["transferState"] == "pending"
    assert latest["transferPeerAccountId"] == "savings"
    assert latest["transferPeerAccountName"] == "Savings"
    assert latest["detailLines"] == [
        {
            "label": "Savings",
            "account": "Assets:Bank:Savings",
            "kind": "asset",
        }
    ]


def test_account_register_shows_pending_transfer_on_peer_account_without_changing_balance(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "savings.journal").write_text(
        """
2026-02-01 Opening balance
    ; tracked_account_id: savings
    Assets:Bank:Savings  USD 125.00
    Equity:Opening-Balances
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(
        config,
        """
2026/02/04 Transfer to savings
    ; import_account_id: checking
    ; transfer_id: transfer-1
    ; transfer_state: pending
    ; transfer_peer_account_id: savings
    Assets:Transfers:checking__savings  $30.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "savings")

    assert register["currentBalance"] == 125.0
    assert register["transactionCount"] == 0
    assert register["entryCount"] == 2
    assert register["latestActivityDate"] == "2026-02-04"

    latest = register["entries"][0]
    assert latest["date"] == "2026-02-04"
    assert latest["payee"] == "Transfer to savings"
    assert latest["summary"] == "Transfer · Wells Fargo Checking (Pending)"
    assert latest["amount"] == 30.0
    assert latest["runningBalance"] == 125.0
    assert latest["transferState"] == "pending"
    assert latest["transferPeerAccountId"] == "checking"
    assert latest["transferPeerAccountName"] == "Wells Fargo Checking"
    assert latest["detailLines"] == [
        {
            "label": "Wells Fargo Checking",
            "account": "Assets:Bank:Checking",
            "kind": "asset",
        }
    ]


def test_account_register_shows_pending_transfer_on_liability_peer_account_without_changing_balance(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/04 Credit card payment
    ; import_account_id: checking
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: visa
    Assets:Transfers:checking__visa  $50.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "visa")

    assert register["currentBalance"] == 0.0
    assert register["transactionCount"] == 0
    assert register["entryCount"] == 1
    assert register["latestActivityDate"] == "2026-02-04"

    latest = register["entries"][0]
    assert latest["date"] == "2026-02-04"
    assert latest["payee"] == "Credit card payment"
    assert latest["summary"] == "Transfer · Wells Fargo Checking (Pending)"
    assert latest["amount"] == 50.0
    assert latest["runningBalance"] == 0.0
    assert latest["transferState"] == "pending"
    assert latest["transferPeerAccountId"] == "checking"
    assert latest["transferPeerAccountName"] == "Wells Fargo Checking"
    assert latest["detailLines"] == [
        {
            "label": "Wells Fargo Checking",
            "account": "Assets:Bank:Checking",
            "kind": "asset",
        }
    ]


def test_account_register_shows_direct_transfer_on_manual_destination_without_pending_state(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/04 Vehicle purchase
    ; import_account_id: checking
    ; transfer_id: transfer-1
    ; transfer_type: direct
    ; transfer_match_state: none
    ; transfer_peer_account_id: vehicle
    Assets:Vehicle:Subaru  $30.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "vehicle")

    assert register["currentBalance"] == 30.0
    assert register["transactionCount"] == 1
    assert register["entryCount"] == 1
    assert register["latestActivityDate"] == "2026-02-04"

    latest = register["entries"][0]
    assert latest["summary"] == "Transfer · Wells Fargo Checking"
    assert latest["amount"] == 30.0
    assert latest["runningBalance"] == 30.0
    assert latest["transferState"] is None
    assert latest["transferPeerAccountId"] == "checking"
    assert latest["transferPeerAccountName"] == "Wells Fargo Checking"
    assert latest["detailLines"] == [
        {
            "label": "Wells Fargo Checking",
            "account": "Assets:Bank:Checking",
            "kind": "asset",
        }
    ]


def test_account_register_ignores_legacy_pending_state_for_manual_destination(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/04 Vehicle purchase
    ; import_account_id: checking
    ; transfer_id: transfer-1
    ; transfer_state: pending
    ; transfer_peer_account_id: vehicle
    Assets:Vehicle:Subaru  $30.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "vehicle")

    assert register["currentBalance"] == 30.0
    assert register["transactionCount"] == 1
    assert register["entryCount"] == 1

    latest = register["entries"][0]
    assert latest["summary"] == "Transfer · Wells Fargo Checking"
    assert latest["transferState"] is None
    assert latest["transferPeerAccountId"] == "checking"
    assert latest["transferPeerAccountName"] == "Wells Fargo Checking"


def test_account_register_treats_manual_destination_transfer_account_entry_as_posted_direct_transfer(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/04 Vehicle purchase
    ; import_account_id: checking
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: vehicle
    Assets:Transfers:checking__vehicle  $30.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "vehicle")

    assert register["currentBalance"] == 30.0
    assert register["transactionCount"] == 1
    assert register["entryCount"] == 1

    latest = register["entries"][0]
    assert latest["summary"] == "Transfer · Wells Fargo Checking"
    assert latest["amount"] == 30.0
    assert latest["runningBalance"] == 30.0
    assert latest["transferState"] is None
    assert latest["transferPeerAccountId"] == "checking"
    assert latest["transferPeerAccountName"] == "Wells Fargo Checking"
    assert latest["detailLines"] == [
        {
            "label": "Wells Fargo Checking",
            "account": "Assets:Bank:Checking",
            "kind": "asset",
        }
    ]


def test_account_register_reflects_offsetting_tracked_account_opening_balance_on_peer_account(tmp_path: Path) -> None:
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

    register = build_account_register(config, "checking")

    assert register["currentBalance"] == 18500.0
    assert register["transactionCount"] == 0
    assert register["hasOpeningBalance"] is False
    assert register["hasTransactionActivity"] is False
    assert register["hasBalanceSource"] is True
    assert register["latestTransactionDate"] is None
    assert register["entryCount"] == 1

    opening_offset = register["entries"][0]
    assert opening_offset["payee"] == "Opening balance"
    assert opening_offset["amount"] == 18500.0
    assert opening_offset["runningBalance"] == 18500.0
    assert opening_offset["isOpeningBalance"] is False
