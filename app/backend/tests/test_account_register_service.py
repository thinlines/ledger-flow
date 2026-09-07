from __future__ import annotations

import pytest

from conftest import write_year_journal
from services import account_register_service
from services.account_register_service import build_account_register
from services.commodity import CommodityMismatchError
from services.config_service import AppConfig
from services.transfer_service import transfer_pair_account


def test_account_register_returns_latest_first_rows_with_running_balances(books_config) -> None:
    config = books_config
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
    write_year_journal(
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


def test_account_register_is_served_from_projection(books_config, monkeypatch: pytest.MonkeyPatch) -> None:
    config = books_config
    write_year_journal(
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
""".strip()
        + "\n",
    )

    def fail_legacy_loader(config: AppConfig) -> list:
        raise AssertionError("legacy regex loader should not serve account register")

    if hasattr(account_register_service, "load_transactions"):
        monkeypatch.setattr(account_register_service, "load_transactions", fail_legacy_loader)

    register = build_account_register(config, "checking")

    assert register["currentBalance"] == 80.0
    assert [entry["payee"] for entry in register["entries"]] == ["Paycheck", "Grocer"]


def test_account_register_parses_balance_assertions_for_matching_commodities(books_config) -> None:
    config = books_config
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
    write_year_journal(
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


def test_account_register_rejects_mixed_commodities_in_running_balance(books_config) -> None:
    config = books_config
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
    write_year_journal(
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


def test_account_register_preserves_liability_signs_in_running_balance(books_config) -> None:
    config = books_config
    write_year_journal(
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


def test_account_register_shows_selected_tracked_account_for_opening_balance_detail(books_config) -> None:
    config = books_config
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
    write_year_journal(config)

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


def test_account_register_uses_transfer_peer_metadata_for_pending_transfers(books_config) -> None:
    config = books_config
    write_year_journal(
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
    assert latest["transferState"] is None
    assert latest["transferPeerAccountId"] == "savings"
    assert latest["transferPeerAccountName"] == "Savings"
    assert latest["detailLines"] == [
        {
            "label": "Savings",
            "account": "Assets:Bank:Savings",
            "kind": "asset",
        }
    ]


def test_account_register_shows_pending_transfer_on_peer_account_without_changing_balance(books_config) -> None:
    config = books_config
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
    write_year_journal(
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


def test_account_register_shows_pending_transfer_on_liability_peer_account_without_changing_balance(books_config) -> None:
    config = books_config
    write_year_journal(
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


def test_account_register_treats_balanced_grouped_pending_transfer_rows_as_settled(books_config) -> None:
    config = books_config
    transfer_account = transfer_pair_account("checking", "savings")
    write_year_journal(
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


def test_account_register_leaves_only_grouped_transfer_residue_pending(books_config) -> None:
    config = books_config
    transfer_account = transfer_pair_account("checking", "savings")
    write_year_journal(
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

    settled_entries = [entry for entry in savings_register["entries"] if entry["transferState"] == "settled_grouped"]
    residue_entries = [entry for entry in savings_register["entries"] if entry["transferState"] is None]

    assert len(settled_entries) == 2
    assert sorted(entry["amount"] for entry in settled_entries) == [0.12, 0.34]
    assert len(residue_entries) == 1
    assert residue_entries[0]["amount"] == 0.10
    assert residue_entries[0]["summary"] == "Transfer · Wells Fargo Checking (Pending)"


def test_account_register_fails_closed_for_ambiguous_same_window_grouped_transfers(books_config) -> None:
    config = books_config
    transfer_account = transfer_pair_account("checking", "savings")
    write_year_journal(
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


def test_account_register_preserves_matched_import_transfer_behavior(books_config) -> None:
    config = books_config
    transfer_account = transfer_pair_account("checking", "savings")
    write_year_journal(
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


def test_account_register_shows_direct_transfer_on_manual_destination_without_pending_state(books_config) -> None:
    config = books_config
    write_year_journal(
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


def test_account_register_ignores_legacy_pending_state_for_manual_destination(books_config) -> None:
    config = books_config
    write_year_journal(
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


def test_account_register_treats_manual_destination_transfer_account_entry_as_posted_direct_transfer(books_config) -> None:
    config = books_config
    write_year_journal(
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


def test_account_register_treats_import_match_without_active_state_as_posted_direct_transfer(books_config) -> None:
    config = books_config
    write_year_journal(
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


def test_account_register_reflects_offsetting_tracked_account_opening_balance_on_peer_account(books_config) -> None:
    config = books_config
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
    write_year_journal(config)

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


def test_bilateral_match_excludes_both_from_pending_and_shows_as_posted(books_config) -> None:
    config = books_config
    transfer_account = transfer_pair_account("checking", "savings")
    write_year_journal(
        config,
        f"""
2026/03/02 Transfer out
    ; import_account_id: checking
    ; lf_source_identity: tx-checking
    ; transfer_id: transfer-wf
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $2000.00
    Assets:Bank:Checking

2026/03/04 Transfer in
    ; import_account_id: savings
    ; lf_source_identity: tx-savings
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
    assert "(Pending)" not in checking_entry["summary"]

    savings_register = build_account_register(config, "savings")
    assert savings_register["transactionCount"] == 1
    assert savings_register["entryCount"] == 1
    savings_entry = savings_register["entries"][0]
    assert savings_entry["summary"] == "Transfer · Wells Fargo Checking"
    assert savings_entry["amount"] == 2000.0
    assert savings_entry["transferState"] == "bilateral_match"
    assert savings_entry["transferPeerAccountId"] == "checking"
    assert "(Pending)" not in savings_entry["summary"]


def test_bilateral_match_excludes_pair_from_pending_balance_and_counts(books_config) -> None:
    config = books_config
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
    write_year_journal(
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


def test_bilateral_match_ambiguous_same_amount_remains_pending(books_config) -> None:
    config = books_config
    transfer_account = transfer_pair_account("checking", "savings")
    write_year_journal(
        config,
        f"""
2026/03/01 Transfer out 1
    ; import_account_id: checking
    ; lf_source_identity: tx-c1
    ; transfer_id: transfer-c1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $500.00
    Assets:Bank:Checking

2026/03/01 Transfer out 2
    ; import_account_id: checking
    ; lf_source_identity: tx-c2
    ; transfer_id: transfer-c2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {transfer_account}  $500.00
    Assets:Bank:Checking

2026/03/03 Transfer in 1
    ; import_account_id: savings
    ; lf_source_identity: tx-s1
    ; transfer_id: transfer-s1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {transfer_account}  $-500.00
    Assets:Bank:Savings

2026/03/03 Transfer in 2
    ; import_account_id: savings
    ; lf_source_identity: tx-s2
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
    # All four remain pending: two same-amount pairs are ambiguous.
    # Source-side entries have no transferState; peer-side synthetics keep "pending".
    assert checking_register["entryCount"] == 4
    checking_states = sorted(entry["transferState"] or "" for entry in checking_register["entries"])
    assert checking_states == ["", "", "pending", "pending"]

    savings_register = build_account_register(config, "savings")
    assert savings_register["entryCount"] == 4
    savings_states = sorted(entry["transferState"] or "" for entry in savings_register["entries"])
    assert savings_states == ["", "", "pending", "pending"]


def test_bilateral_match_single_sided_pending_still_shows_synthetic_peer(books_config) -> None:
    config = books_config
    transfer_account = transfer_pair_account("checking", "savings")
    write_year_journal(
        config,
        f"""
2026/03/02 Transfer out
    ; import_account_id: checking
    ; lf_source_identity: tx-c
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
    assert checking_entry["transferState"] is None
    assert "(Pending)" in checking_entry["summary"]

    # Savings register should show the synthetic peer event
    savings_register = build_account_register(config, "savings")
    assert savings_register["entryCount"] == 1
    savings_entry = savings_register["entries"][0]
    assert savings_entry["transferState"] == "pending"
    assert "(Pending)" in savings_entry["summary"]
    assert savings_entry["amount"] == 2000.0  # peer side gets negated source amount


