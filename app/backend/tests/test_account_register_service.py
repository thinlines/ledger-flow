from __future__ import annotations

from pathlib import Path

import pytest

from services.account_register_service import build_account_register
from services.commodity_service import CommodityMismatchError
from services.config_service import AppConfig
from services.transfer_service import (
    MANUAL_TRANSFER_RESOLUTION_METADATA_KEY,
    MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE,
    transfer_pair_account,
)
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
    Expenses:Food:Groceries  USD 20.00
    Assets:Bank:Checking

2026/02/03 Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  USD 100.00
    Income:Salary

2026/02/04 Transfer to savings
    ; import_account_id: checking
    Assets:Savings  USD 30.00
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


def test_account_register_parses_balance_assertions_for_matching_commodities(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-02-01 Opening balance
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
2026/02/02 Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  USD 1000.00 = USD 1200.00
    Income:Salary
""".strip()
        + "\n",
    )

    register = build_account_register(config, "checking")

    assert register["currentBalance"] == 1200.0
    latest = register["entries"][0]
    assert latest["amount"] == 1000.0
    assert latest["runningBalance"] == 1200.0


def test_account_register_rejects_mixed_commodities_in_running_balance(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-02-01 Opening balance
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
2026/02/02 Paycheck
    ; import_account_id: checking
    Assets:Bank:Checking  $1000.00 = $1200.00
    Income:Salary
""".strip()
        + "\n",
    )

    with pytest.raises(CommodityMismatchError, match="mixes commodities"):
        build_account_register(config, "checking")


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


def test_account_register_exposes_same_manual_resolution_token_on_source_and_peer_pending_rows(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/04 Transfer to savings
    ; import_account_id: checking
    ; source_identity: tx-checking
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    Assets:Transfers:checking__savings  $30.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    checking_register = build_account_register(config, "checking")
    savings_register = build_account_register(config, "savings")

    checking_entry = checking_register["entries"][0]
    savings_entry = savings_register["entries"][0]

    assert checking_entry["manualResolutionToken"]
    assert savings_entry["manualResolutionToken"] == checking_entry["manualResolutionToken"]


def test_account_register_adds_manual_resolution_note_for_resolved_transfer_rows(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/12 Transfer out
    ; import_account_id: checking
    ; source_identity: tx-checking
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: matched
    ; transfer_peer_account_id: savings
    ; {MANUAL_TRANSFER_RESOLUTION_METADATA_KEY}: {MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE}
    {transfer_account}  $30.00
    Assets:Bank:Checking  $-30.00

2026/03/12 Transfer in
    ; import_account_id: savings
    ; source_identity: tx-savings
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: matched
    ; transfer_peer_account_id: checking
    ; {MANUAL_TRANSFER_RESOLUTION_METADATA_KEY}: {MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE}
    {transfer_account}  $-30.00
    Assets:Bank:Savings  $30.00
""".strip()
        + "\n",
    )

    checking_register = build_account_register(config, "checking")
    savings_register = build_account_register(config, "savings")

    assert checking_register["entries"][0]["manualResolutionNote"] == (
        "The missing side was added manually because no imported counterpart was expected."
    )
    assert savings_register["entries"][0]["manualResolutionNote"] == (
        "The missing side was added manually because no imported counterpart was expected."
    )


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


def test_account_register_treats_balanced_grouped_pending_transfer_rows_as_settled(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/12 ACH verification withdrawal
    ; import_account_id: checking
    ; transfer_id: transfer-checking
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $0.46
    Assets:Bank:Checking

2026/03/12 ACH verification deposit 1
    ; import_account_id: savings
    ; transfer_id: transfer-savings-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.12
    Assets:Bank:Savings

2026/03/12 ACH verification deposit 2
    ; import_account_id: savings
    ; transfer_id: transfer-savings-2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.34
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    savings_register = build_account_register(config, "savings")
    assert savings_register["currentBalance"] == 0.46
    assert savings_register["transactionCount"] == 2
    assert savings_register["entryCount"] == 2
    assert [entry["amount"] for entry in savings_register["entries"]] == [0.34, 0.12]
    assert all(entry["transferState"] == "settled_grouped" for entry in savings_register["entries"])
    assert all("(Pending)" not in entry["summary"] for entry in savings_register["entries"])

    checking_register = build_account_register(config, "checking")
    assert checking_register["currentBalance"] == -0.46
    assert checking_register["transactionCount"] == 1
    assert checking_register["entryCount"] == 1
    latest = checking_register["entries"][0]
    assert latest["summary"] == "Transfer · Savings"
    assert latest["amount"] == -0.46
    assert latest["transferState"] == "settled_grouped"


def test_account_register_leaves_only_grouped_transfer_residue_pending(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/12 ACH verification withdrawal
    ; import_account_id: checking
    ; transfer_id: transfer-checking
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $0.46
    Assets:Bank:Checking

2026/03/12 ACH verification deposit 1
    ; import_account_id: savings
    ; transfer_id: transfer-savings-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.12
    Assets:Bank:Savings

2026/03/12 ACH verification deposit 2
    ; import_account_id: savings
    ; transfer_id: transfer-savings-2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.34
    Assets:Bank:Savings

2026/03/13 ACH verification deposit residue
    ; import_account_id: savings
    ; transfer_id: transfer-savings-3
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.10
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    savings_register = build_account_register(config, "savings")
    assert savings_register["currentBalance"] == 0.56
    assert savings_register["transactionCount"] == 3
    assert savings_register["entryCount"] == 3

    pending_entries = [entry for entry in savings_register["entries"] if entry["transferState"] == "pending"]
    settled_entries = [entry for entry in savings_register["entries"] if entry["transferState"] == "settled_grouped"]

    assert len(pending_entries) == 1
    assert pending_entries[0]["amount"] == 0.10
    assert pending_entries[0]["summary"] == "Transfer · Wells Fargo Checking (Pending)"
    assert len(settled_entries) == 2
    assert sorted(entry["amount"] for entry in settled_entries) == [0.12, 0.34]


def test_account_register_fails_closed_for_ambiguous_same_window_grouped_transfers(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/12 Transfer out 1
    ; import_account_id: checking
    ; transfer_id: transfer-checking-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $0.12
    Assets:Bank:Checking

2026/03/12 Transfer out 2
    ; import_account_id: checking
    ; transfer_id: transfer-checking-2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $0.34
    Assets:Bank:Checking

2026/03/12 Transfer in 1
    ; import_account_id: savings
    ; transfer_id: transfer-savings-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.12
    Assets:Bank:Savings

2026/03/12 Transfer in 2
    ; import_account_id: savings
    ; transfer_id: transfer-savings-2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.34
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    checking_register = build_account_register(config, "checking")
    # The two distinct-amount pairs ($0.12 and $0.34) are each unambiguously
    # bilateral-matched, so synthetic peers are suppressed and only the two
    # source-side entries remain on the checking register.
    assert checking_register["entryCount"] == 2
    assert all(entry["transferState"] == "bilateral_match" for entry in checking_register["entries"])
    assert all("(Pending)" not in entry["summary"] for entry in checking_register["entries"])


def test_account_register_preserves_matched_import_transfer_behavior(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/12 Transfer out
    ; import_account_id: checking
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: matched
    ; transfer_peer_account_id: savings
    {transfer_account}  $0.46
    Assets:Bank:Checking

2026/03/12 Transfer in
    ; import_account_id: savings
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: matched
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.46
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    checking_register = build_account_register(config, "checking")
    latest = checking_register["entries"][0]
    assert latest["summary"] == "Transfer · Savings"
    assert latest["transferState"] == "matched"


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


def test_account_register_treats_import_match_without_active_state_as_posted_direct_transfer(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    _write_year_journal(
        config,
        """
2026/02/04 Transfer to savings
    ; import_account_id: checking
    ; transfer_id: transfer-1
    ; transfer_type: import_match
    ; transfer_match_state: none
    ; transfer_peer_account_id: savings
    Assets:Transfers:checking__savings  $30.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    register = build_account_register(config, "savings")

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


def test_bilateral_match_excludes_both_from_pending_and_shows_as_posted(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/02 Transfer out
    ; import_account_id: checking
    ; source_identity: tx-checking
    ; transfer_id: transfer-wf
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $2000.00
    Assets:Bank:Checking

2026/03/04 Transfer in
    ; import_account_id: savings
    ; source_identity: tx-savings
    ; transfer_id: transfer-iccu
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-2000.00
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    checking_register = build_account_register(config, "checking")
    assert checking_register["transactionCount"] == 1
    assert checking_register["entryCount"] == 1
    checking_entry = checking_register["entries"][0]
    assert checking_entry["summary"] == "Transfer · Savings"
    assert checking_entry["amount"] == -2000.0
    assert checking_entry["transferState"] == "bilateral_match"
    assert checking_entry["transferPeerAccountId"] == "savings"
    assert checking_entry["manualResolutionToken"] is None
    assert "(Pending)" not in checking_entry["summary"]

    savings_register = build_account_register(config, "savings")
    assert savings_register["transactionCount"] == 1
    assert savings_register["entryCount"] == 1
    savings_entry = savings_register["entries"][0]
    assert savings_entry["summary"] == "Transfer · Wells Fargo Checking"
    assert savings_entry["amount"] == 2000.0
    assert savings_entry["transferState"] == "bilateral_match"
    assert savings_entry["transferPeerAccountId"] == "checking"
    assert savings_entry["manualResolutionToken"] is None
    assert "(Pending)" not in savings_entry["summary"]


def test_bilateral_match_excludes_pair_from_pending_balance_and_counts(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    (config.opening_bal_dir / "checking.journal").write_text(
        """
2026-02-01 Opening balance
    ; tracked_account_id: checking
    Assets:Bank:Checking  $5000.00
    Equity:Opening-Balances
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_year_journal(
        config,
        f"""
2026/03/02 Transfer out
    ; import_account_id: checking
    ; transfer_id: transfer-wf
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $2000.00
    Assets:Bank:Checking

2026/03/04 Transfer in
    ; import_account_id: savings
    ; transfer_id: transfer-iccu
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-2000.00
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    register = build_account_register(config, "checking")
    # The bilateral-matched transfer still affects the running balance
    # (it IS a real transaction), but no pending synthetic peer is generated.
    assert register["currentBalance"] == 3000.0
    assert register["transactionCount"] == 1
    assert register["entryCount"] == 2  # opening + the matched transfer
    pending_entries = [e for e in register["entries"] if e["transferState"] == "pending"]
    assert len(pending_entries) == 0


def test_bilateral_match_ambiguous_same_amount_remains_pending(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/01 Transfer out 1
    ; import_account_id: checking
    ; source_identity: tx-c1
    ; transfer_id: transfer-c1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $500.00
    Assets:Bank:Checking

2026/03/01 Transfer out 2
    ; import_account_id: checking
    ; source_identity: tx-c2
    ; transfer_id: transfer-c2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $500.00
    Assets:Bank:Checking

2026/03/03 Transfer in 1
    ; import_account_id: savings
    ; source_identity: tx-s1
    ; transfer_id: transfer-s1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-500.00
    Assets:Bank:Savings

2026/03/03 Transfer in 2
    ; import_account_id: savings
    ; source_identity: tx-s2
    ; transfer_id: transfer-s2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-500.00
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    checking_register = build_account_register(config, "checking")
    # All four remain pending: two same-amount pairs are ambiguous
    assert checking_register["entryCount"] == 4
    assert all(entry["transferState"] == "pending" for entry in checking_register["entries"])

    savings_register = build_account_register(config, "savings")
    assert savings_register["entryCount"] == 4
    assert all(entry["transferState"] == "pending" for entry in savings_register["entries"])


def test_bilateral_match_date_boundary_exact_window_matches(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/01 Transfer out
    ; import_account_id: checking
    ; transfer_id: transfer-c
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $100.00
    Assets:Bank:Checking

2026/03/08 Transfer in
    ; import_account_id: savings
    ; transfer_id: transfer-s
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-100.00
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    # Exactly MAX_TRANSFER_MATCH_DAYS (7) apart → should match
    checking_register = build_account_register(config, "checking")
    assert checking_register["entryCount"] == 1
    assert checking_register["entries"][0]["transferState"] == "bilateral_match"


def test_bilateral_match_date_boundary_exceeds_window_remains_pending(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/01 Transfer out
    ; import_account_id: checking
    ; source_identity: tx-c
    ; transfer_id: transfer-c
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $100.00
    Assets:Bank:Checking

2026/03/09 Transfer in
    ; import_account_id: savings
    ; source_identity: tx-s
    ; transfer_id: transfer-s
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-100.00
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    # MAX_TRANSFER_MATCH_DAYS + 1 (8 days) apart → should NOT match
    checking_register = build_account_register(config, "checking")
    assert checking_register["entryCount"] == 2
    assert all(entry["transferState"] == "pending" for entry in checking_register["entries"])


def test_bilateral_match_single_sided_pending_still_shows_synthetic_peer(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/02 Transfer out
    ; import_account_id: checking
    ; source_identity: tx-c
    ; transfer_id: transfer-c
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $2000.00
    Assets:Bank:Checking
""".strip()
        + "\n",
    )

    # Only WF side imported, no ICCU counterpart
    checking_register = build_account_register(config, "checking")
    assert checking_register["entryCount"] == 1
    checking_entry = checking_register["entries"][0]
    assert checking_entry["transferState"] == "pending"
    assert "(Pending)" in checking_entry["summary"]
    assert checking_entry["manualResolutionToken"] is not None

    # Savings register should show the synthetic peer event
    savings_register = build_account_register(config, "savings")
    assert savings_register["entryCount"] == 1
    savings_entry = savings_register["entries"][0]
    assert savings_entry["transferState"] == "pending"
    assert "(Pending)" in savings_entry["summary"]
    assert savings_entry["amount"] == 2000.0  # peer side gets negated source amount


def test_bilateral_match_does_not_interfere_with_grouped_settlement(tmp_path: Path) -> None:
    config = _make_config(tmp_path / "workspace")
    transfer_account = transfer_pair_account("checking", "savings")
    _write_year_journal(
        config,
        f"""
2026/03/12 ACH verification withdrawal
    ; import_account_id: checking
    ; transfer_id: transfer-checking
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $0.46
    Assets:Bank:Checking

2026/03/12 ACH verification deposit 1
    ; import_account_id: savings
    ; transfer_id: transfer-savings-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.12
    Assets:Bank:Savings

2026/03/12 ACH verification deposit 2
    ; import_account_id: savings
    ; transfer_id: transfer-savings-2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-0.34
    Assets:Bank:Savings
""".strip()
        + "\n",
    )

    # These 3 transactions form a grouped settlement (sum to zero)
    # Bilateral matching should not interfere
    savings_register = build_account_register(config, "savings")
    assert all(entry["transferState"] == "settled_grouped" for entry in savings_register["entries"])
