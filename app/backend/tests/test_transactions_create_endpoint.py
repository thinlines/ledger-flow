"""Source account resolution on the manual transaction create route (#29).

The route accepts either the internal tracked account id (existing UI payload)
or a user-facing source account selector — a fully-qualified Ledger account
name. Resolution happens on the server so the web UI, CLI, and future
integrations share one interpretation. Selectors that match zero or multiple
tracked accounts fail with a clear validation error instead of guessing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from models import ManualTransactionRequest
from services import event_log_service
from services.config_service import AppConfig
from services.projection_service import refresh_projection


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


JOURNAL = """\
include ../rules/11-payees.dat

2026-03-15 * Whole Foods
    ; lf_txn_id: txn_wf
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00

2026-03-16 * Farmers Market
    ; lf_txn_id: txn_market
    Assets:Bank:Checking  -$12.00
    Expenses:Seasonal  $12.00
"""

PAYEES_DAT = """\
account Expenses:Seasonal

payee Burger King
    ; lf_default_account: Expenses:Eating Out

payee Bad Default Cafe
    ; lf_default_account: Expenses:Unlisted
"""


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    (workspace / "rules" / "10-accounts.dat").write_text(
        "account Expenses:Groceries\n"
        "account Expenses:Eating Out\n"
        "account Assets:Bank:Checking\n"
        "account Assets:Bank:Savings\n"
        "account Liabilities:Credit Card\n",
        encoding="utf-8",
    )
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "start_year": 2026, "base_currency": "USD"},
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
                "display_name": "Checking",
                "ledger_account": "Assets:Bank:Checking",
            },
            "savings": {
                "display_name": "Savings",
                "ledger_account": "Assets:Bank:Savings",
            },
        },
    )


def _workspace(tmp_path: Path, monkeypatch) -> AppConfig:
    config = _make_config(tmp_path / "workspace")
    (config.init_dir / "11-payees.dat").write_text(PAYEES_DAT, encoding="utf-8")
    (config.journal_dir / "2026.journal").write_text(JOURNAL, encoding="utf-8")
    (config.journal_dir / "main.journal").write_text(
        "include ../rules/10-accounts.dat\n"
        "include ../rules/11-payees.dat\n"
        "include 2026.journal\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    refresh_projection(config)
    return config


def _request(**overrides) -> ManualTransactionRequest:
    payload = {
        "trackedAccountId": "checking",
        "date": "2026-03-18",
        "payee": "Burger King",
        "amount": "20.00",
        "destinationAccount": "Expenses:Groceries",
    }
    payload.update(overrides)
    return ManualTransactionRequest(**payload)


def test_source_account_ledger_name_creates_transaction(tmp_path, monkeypatch):
    """A fully-qualified Ledger account name selects the tracked account."""
    config = _workspace(tmp_path, monkeypatch)

    result = main.transactions_create(
        _request(trackedAccountId=None, sourceAccount="Assets:Bank:Savings")
    )

    assert result["created"] is True
    assert result["trackedLedgerAccount"] == "Assets:Bank:Savings"
    journal_text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-03-18 Burger King" in journal_text
    assert "Assets:Bank:Savings" in journal_text


def test_source_account_with_no_match_is_rejected(tmp_path, monkeypatch):
    """Unknown names — including alias shorthand while aliases are not yet
    projected — fail with a clear validation error, never a guess."""
    config = _workspace(tmp_path, monkeypatch)
    journal_before = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_create(
            _request(trackedAccountId=None, sourceAccount="checking-alias")
        )

    assert exc_info.value.status_code == 400
    assert "checking-alias" in exc_info.value.detail
    assert (
        journal_before
        == (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    )


def test_ambiguous_source_account_is_rejected(tmp_path, monkeypatch):
    """Two tracked accounts on the same Ledger account: refuse to guess."""
    config = _workspace(tmp_path, monkeypatch)
    config.tracked_accounts["checking_joint"] = {
        "display_name": "Joint Checking",
        "ledger_account": "Assets:Bank:Checking",
    }

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_create(
            _request(trackedAccountId=None, sourceAccount="Assets:Bank:Checking")
        )

    assert exc_info.value.status_code == 400
    assert "ambiguous" in exc_info.value.detail.lower()
    assert "Assets:Bank:Checking" in exc_info.value.detail


def test_missing_source_selector_is_rejected(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_create(_request(trackedAccountId=None))

    assert exc_info.value.status_code == 400
    assert "trackedAccountId" in exc_info.value.detail
    assert "sourceAccount" in exc_info.value.detail


def test_conflicting_source_selectors_are_rejected(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_create(_request(sourceAccount="Assets:Bank:Savings"))

    assert exc_info.value.status_code == 400
    assert "trackedAccountId" in exc_info.value.detail
    assert "sourceAccount" in exc_info.value.detail


def test_tracked_account_id_payload_creates_transaction(tmp_path, monkeypatch):
    """The existing UI-shaped payload keeps working unchanged."""
    config = _workspace(tmp_path, monkeypatch)

    result = main.transactions_create(_request())

    assert result["created"] is True
    assert result["trackedLedgerAccount"] == "Assets:Bank:Checking"
    journal_text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-03-18 Burger King" in journal_text
    assert "Assets:Bank:Checking" in journal_text


def test_projection_known_undeclared_destination_creates_transaction(
    tmp_path, monkeypatch
):
    """An account offered by projection-backed pickers is a valid destination."""
    config = _workspace(tmp_path, monkeypatch)

    result = main.transactions_create(
        _request(destinationAccount="Expenses:Seasonal")
    )

    assert result["created"] is True
    assert result["destinationAccount"] == "Expenses:Seasonal"
    journal_text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-03-18 Burger King" in journal_text
    assert "Expenses:Seasonal" in journal_text


def test_omitted_destination_uses_payee_default_account(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)

    result = main.transactions_create(_request(destinationAccount=None))

    assert result["created"] is True
    assert result["destinationAccount"] == "Expenses:Eating Out"
    journal_text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-03-18 Burger King" in journal_text
    assert "Expenses:Eating Out" in journal_text
    assert "Expenses:Unknown" not in journal_text


@pytest.mark.parametrize(
    "destination_account",
    ["Assets:Bank:Savings", "Liabilities:Credit Card"],
)
def test_explicit_asset_or_liability_destination_creates_normal_manual_transaction(
    tmp_path, monkeypatch, destination_account
):
    config = _workspace(tmp_path, monkeypatch)

    result = main.transactions_create(
        _request(
            trackedAccountId=None,
            sourceAccount="Assets:Bank:Checking",
            destinationAccount=destination_account,
            payee="Move to savings",
            notes="monthly sweep",
        )
    )

    assert result["created"] is True
    assert result["destinationAccount"] == destination_account
    journal_text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-03-18 Move to savings" in journal_text
    assert "    ; notes: monthly sweep" in journal_text
    assert "    ; :manual:" in journal_text
    assert f"    {destination_account}  $20.00" in journal_text
    assert "    Assets:Bank:Checking" in journal_text
    assert "transfer_id" not in journal_text
    assert "transfer_match_state" not in journal_text


def test_invalid_explicit_destination_account_is_rejected(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)
    journal_before = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_create(_request(destinationAccount="Assets:Bank:Vacation"))

    assert exc_info.value.status_code == 400
    assert "Assets:Bank:Vacation" in exc_info.value.detail
    assert "destination account" in exc_info.value.detail
    assert (
        journal_before
        == (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    )


def test_unknown_explicit_and_payee_default_destinations_are_rejected_identically(
    tmp_path, monkeypatch
):
    config = _workspace(tmp_path, monkeypatch)

    errors = []
    for request in (
        _request(destinationAccount="Expenses:Unlisted"),
        _request(payee="Bad Default Cafe", destinationAccount=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            main.transactions_create(request)
        errors.append(exc_info.value)

    assert [error.status_code for error in errors] == [400, 400]
    assert errors[0].detail == errors[1].detail
    assert "Expenses:Unlisted" in errors[0].detail
    journal_text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "Bad Default Cafe" not in journal_text


def test_missing_accounts_dat_does_not_disable_destination_validation(
    tmp_path, monkeypatch
):
    config = _workspace(tmp_path, monkeypatch)
    (config.init_dir / "10-accounts.dat").unlink()

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_create(_request(destinationAccount="Expenses:Unlisted"))

    assert exc_info.value.status_code == 400
    assert "Expenses:Unlisted" in exc_info.value.detail


def test_omitted_destination_without_payee_default_is_rejected(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)
    journal_before = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_create(
            _request(payee="One-Off Plumber", destinationAccount=None)
        )

    assert exc_info.value.status_code == 400
    assert "No default destination account" in exc_info.value.detail
    assert "One-Off Plumber" in exc_info.value.detail
    assert (
        journal_before
        == (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    )


def test_omitted_destination_with_unavailable_payee_default_lookup_is_rejected(
    tmp_path, monkeypatch
):
    config = _workspace(tmp_path, monkeypatch)
    journal_before = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")

    def unavailable(_config):
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(main, "load_merchants", unavailable)

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_create(_request(destinationAccount=None))

    assert exc_info.value.status_code == 400
    assert "Payee default account lookup is unavailable" in exc_info.value.detail
    assert (
        journal_before
        == (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    )


def test_notes_payload_creates_normal_notes_metadata(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)

    result = main.transactions_create(_request(notes="receipt saved"))

    assert result["created"] is True
    journal_text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-03-18 Burger King" in journal_text
    assert "    ; notes: receipt saved" in journal_text
