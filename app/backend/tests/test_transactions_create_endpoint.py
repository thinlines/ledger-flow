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
2026-03-15 * Whole Foods
    ; lf_txn_id: txn_wf
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00
"""


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    (workspace / "rules" / "10-accounts.dat").write_text(
        "account Expenses:Groceries\n"
        "account Assets:Bank:Checking\naccount Assets:Bank:Savings\n",
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
    (config.journal_dir / "2026.journal").write_text(JOURNAL, encoding="utf-8")
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


def test_notes_payload_creates_normal_notes_metadata(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)

    result = main.transactions_create(_request(notes="receipt saved"))

    assert result["created"] is True
    journal_text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-03-18 Burger King" in journal_text
    assert "    ; notes: receipt saved" in journal_text
