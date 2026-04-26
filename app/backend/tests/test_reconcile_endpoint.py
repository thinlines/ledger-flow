"""Tests for POST /api/accounts/{accountId}/reconcile and the read-side wiring
through `_tracked_account_ui` consumers."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from models import DeleteTransactionRequest, ReconcileRequest
from services import event_log_service
from services.config_service import AppConfig
from services.event_log_service import EVENTS_FILENAME, read_events
from services.reconciliation_service import latest_reconciliation_date


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


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
                "ledger_account": "Assets:Checking:Wells Fargo",
                "tracked_account_id": "checking",
            },
        },
        tracked_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "ledger_account": "Assets:Checking:Wells Fargo",
                "import_account_id": "checking",
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


def _seed_accounts_dat(config: AppConfig) -> None:
    lines = [
        "account Assets:Checking:Wells Fargo",
        "account Assets:Savings",
        "account Income:Salary",
        "account Equity:Opening-Balances",
    ]
    (config.init_dir / "10-accounts.dat").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_journal(config: AppConfig, body: str) -> Path:
    journal = config.journal_dir / "2026.journal"
    journal.write_text(body, encoding="utf-8")
    return journal


def _opening_block(account: str, amount: str) -> str:
    return (
        "2026-01-01 * Opening Balance\n"
        f"    {account}  {amount}\n"
        "    Equity:Opening-Balances\n"
    )


# ---------------------------------------------------------------------------
# Validation ladder
# ---------------------------------------------------------------------------


class TestReconcileValidation:
    def test_unknown_account_returns_404(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconcile(
                "ghost",
                ReconcileRequest(
                    periodStart="2026-03-18",
                    periodEnd="2026-04-17",
                    closingBalance="100.00",
                    currency="USD",
                ),
            )
        assert exc.value.status_code == 404
        assert "ghost" in str(exc.value.detail)

    def test_income_account_returns_400(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconcile(
                "salary",
                ReconcileRequest(
                    periodStart="2026-03-18",
                    periodEnd="2026-04-17",
                    closingBalance="100.00",
                    currency="USD",
                ),
            )
        assert exc.value.status_code == 400
        assert "asset and liability" in str(exc.value.detail)

    def test_non_base_currency_returns_400(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconcile(
                "checking",
                ReconcileRequest(
                    periodStart="2026-03-18",
                    periodEnd="2026-04-17",
                    closingBalance="100.00",
                    currency="EUR",
                ),
            )
        assert exc.value.status_code == 400
        assert "Multi-currency" in str(exc.value.detail)

    def test_period_start_after_end_returns_400(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconcile(
                "checking",
                ReconcileRequest(
                    periodStart="2026-04-18",
                    periodEnd="2026-04-17",
                    closingBalance="100.00",
                    currency="USD",
                ),
            )
        assert exc.value.status_code == 400
        assert "Invalid period" in str(exc.value.detail)

    def test_invalid_closing_balance_returns_400(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconcile(
                "checking",
                ReconcileRequest(
                    periodStart="2026-03-18",
                    periodEnd="2026-04-17",
                    closingBalance="not-a-number",
                    currency="USD",
                ),
            )
        assert exc.value.status_code == 400
        assert "Invalid closing balance" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestReconcileSuccess:
    def test_writes_journal_emits_event_returns_response(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(config, _opening_block("Assets:Checking:Wells Fargo", "$2500.00"))
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.accounts_reconcile(
            "checking",
            ReconcileRequest(
                periodStart="2026-03-18",
                periodEnd="2026-04-17",
                closingBalance="2500.00",
                currency="USD",
            ),
        )

        assert result["ok"] is True
        assert "eventId" in result
        assert result["assertionTransaction"]["journalPath"].endswith("2026.journal")

        # Journal contains the assertion transaction.
        journal = config.journal_dir / "2026.journal"
        text = journal.read_text(encoding="utf-8")
        assert "2026-04-17 * Statement reconciliation · Wells Fargo Checking · ending 2026-04-17" in text
        assert f"; reconciliation_event_id: {result['eventId']}" in text
        assert "; statement_period: 2026-03-18..2026-04-17" in text
        assert "Assets:Checking:Wells Fargo  $0 = $2,500.00" in text

        # account.reconciled.v1 event exists with matching id.
        events = read_events(config.root_dir)
        recon_events = [e for e in events if e["type"] == "account.reconciled.v1"]
        assert len(recon_events) == 1
        assert recon_events[0]["id"] == result["eventId"]
        assert recon_events[0]["payload"]["tracked_account_id"] == "checking"
        assert recon_events[0]["payload"]["period_end"] == "2026-04-17"
        assert recon_events[0]["payload"]["closing_balance"] == "2500.00"
        assert len(recon_events[0]["journal_refs"]) == 1
        assert recon_events[0]["journal_refs"][0]["hash_before"] != recon_events[0]["journal_refs"][0]["hash_after"]


# ---------------------------------------------------------------------------
# Same-date conflict (409)
# ---------------------------------------------------------------------------


class TestReconcileConflict:
    def test_same_date_returns_409(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(config, _opening_block("Assets:Checking:Wells Fargo", "$2500.00"))
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        # First reconciliation succeeds.
        main.accounts_reconcile(
            "checking",
            ReconcileRequest(
                periodStart="2026-03-18",
                periodEnd="2026-04-17",
                closingBalance="2500.00",
                currency="USD",
            ),
        )

        # Second reconciliation on the same date returns 409.
        with pytest.raises(HTTPException) as exc:
            main.accounts_reconcile(
                "checking",
                ReconcileRequest(
                    periodStart="2026-03-18",
                    periodEnd="2026-04-17",
                    closingBalance="2500.00",
                    currency="USD",
                ),
            )
        assert exc.value.status_code == 409

    def test_earlier_period_end_returns_409(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(config, _opening_block("Assets:Checking:Wells Fargo", "$2500.00"))
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        main.accounts_reconcile(
            "checking",
            ReconcileRequest(
                periodStart="2026-03-18",
                periodEnd="2026-04-17",
                closingBalance="2500.00",
                currency="USD",
            ),
        )

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconcile(
                "checking",
                ReconcileRequest(
                    periodStart="2026-02-18",
                    periodEnd="2026-03-17",
                    closingBalance="2500.00",
                    currency="USD",
                ),
            )
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Assertion failure: rollback + no event
# ---------------------------------------------------------------------------


class TestReconcileFailure:
    def test_wrong_balance_returns_422_rolls_back_byte_equivalent_no_event(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(config, _opening_block("Assets:Checking:Wells Fargo", "$100.00"))
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        journal = config.journal_dir / "2026.journal"
        before_bytes = journal.read_bytes()

        with pytest.raises(HTTPException) as exc:
            main.accounts_reconcile(
                "checking",
                ReconcileRequest(
                    periodStart="2026-03-18",
                    periodEnd="2026-04-17",
                    closingBalance="2500.00",  # wrong on purpose
                    currency="USD",
                ),
            )
        assert exc.value.status_code == 422
        detail = exc.value.detail
        assert detail["outcome"] == "assertion_failed"
        assert detail["expected"] is not None
        assert detail["actual"] is not None
        assert "Balance assertion off by" in detail["rawError"]

        # Journal restored byte-for-byte.
        assert journal.read_bytes() == before_bytes

        # No account.reconciled.v1 event emitted.
        events = read_events(config.root_dir)
        recon_events = [e for e in events if e["type"] == "account.reconciled.v1"]
        assert recon_events == []


# ---------------------------------------------------------------------------
# Round-trip: reconcile + delete via existing transaction.deleted handler
# ---------------------------------------------------------------------------


class TestReconcileDeleteRoundTrip:
    def test_reconcile_then_delete_yields_byte_equivalent_journal(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(config, _opening_block("Assets:Checking:Wells Fargo", "$2500.00"))
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        journal = config.journal_dir / "2026.journal"
        before_bytes = journal.read_bytes()

        result = main.accounts_reconcile(
            "checking",
            ReconcileRequest(
                periodStart="2026-03-18",
                periodEnd="2026-04-17",
                closingBalance="2500.00",
                currency="USD",
            ),
        )
        assert result["ok"] is True

        # Sanity: latest_reconciliation_date now returns 2026-04-17.
        assert latest_reconciliation_date(config, "Assets:Checking:Wells Fargo") == date(2026, 4, 17)

        # Delete the assertion transaction via the existing endpoint.
        delete_req = DeleteTransactionRequest(
            journalPath=str(journal),
            headerLine=result["assertionTransaction"]["headerLine"],
            lineNumber=result["assertionTransaction"]["lineNumber"],
        )
        main.transactions_delete(delete_req)

        # Journal back to byte-equivalent state.
        assert journal.read_bytes() == before_bytes

        # latest_reconciliation_date now None — fence is cleared.
        assert latest_reconciliation_date(config, "Assets:Checking:Wells Fargo") is None


# ---------------------------------------------------------------------------
# Read-side wiring: reconciliationStatus on _tracked_account_ui consumers
# ---------------------------------------------------------------------------


class TestApplyImportRefusesFenceConflict:
    def test_apply_import_does_not_write_fence_conflict_rows(self, tmp_path: Path) -> None:
        """Apply must skip rows with matchStatus == 'conflict' regardless of reason —
        prove that a fence-triggered conflict is not written."""
        from services.import_service import apply_import

        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(config, _opening_block("Assets:Checking:Wells Fargo", "$2500.00"))

        target = config.journal_dir / "2026.journal"
        before = target.read_text(encoding="utf-8")

        stage = {
            "targetJournalPath": str(target),
            "importAccountId": "checking",
            "year": "2026",
            "sourceFileSha256": "deadbeef",
            "preparedTransactions": [
                {
                    "matchStatus": "conflict",
                    "conflictReason": "reconciled_date_fence",
                    "reconciledThrough": "2026-04-17",
                    "annotatedRaw": (
                        "2026/04/17 Old Coffee\n"
                        "    ; source_identity: txn-fenced\n"
                        "    ; source_payload_hash: payload-fenced\n"
                        "    Assets:Checking:Wells Fargo  $-7.50\n"
                        "    Expenses:Unknown\n"
                    ),
                    "sourceIdentity": "txn-fenced",
                    "sourcePayloadHash": "payload-fenced",
                    "date": "2026/04/17",
                    "payee": "Old Coffee",
                },
            ],
        }

        _, appended_count, _, conflicts = apply_import(config, stage)
        assert appended_count == 0
        assert len(conflicts) == 1
        assert conflicts[0]["conflictReason"] == "reconciled_date_fence"
        assert conflicts[0]["reconciledThrough"] == "2026-04-17"
        # Journal unchanged.
        assert target.read_text(encoding="utf-8") == before


class TestReconciliationStatusOnTrackedAccountUi:
    def test_tracked_accounts_endpoint_returns_status_field(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(config, _opening_block("Assets:Checking:Wells Fargo", "$2500.00"))
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.tracked_accounts_list()
        rows = result["trackedAccounts"]
        assert all("reconciliationStatus" in r for r in rows)
        assert all(r["reconciliationStatus"] == {"ok": True} for r in rows)

    def test_broken_assertion_surfaces_on_account_list(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        # Reconciliation that will FAIL because the account balance is $100 not $200.
        _seed_journal(
            config,
            _opening_block("Assets:Checking:Wells Fargo", "$100.00")
            + "\n"
            + "2026-04-17 * Statement reconciliation · Wells Fargo · ending 2026-04-17\n"
            "    ; reconciliation_event_id: e1\n"
            "    ; statement_period: 2026-03-18..2026-04-17\n"
            "    Assets:Checking:Wells Fargo  $0 = $200.00\n",
        )
        monkeypatch.setattr(main, "_require_workspace_config", lambda: config)

        result = main.tracked_accounts_list()
        rows = {r["id"]: r for r in result["trackedAccounts"]}
        assert rows["checking"]["reconciliationStatus"]["ok"] is False
        broken = rows["checking"]["reconciliationStatus"]["broken"]
        assert "200" in (broken["expected"] or "").replace(",", "")
        assert "100" in (broken["actual"] or "").replace(",", "")
        assert broken["date"] == "2026-04-17"
        assert "Balance assertion off by" in broken["rawError"]

        # Other tracked accounts continue to report ok.
        assert rows["savings"]["reconciliationStatus"] == {"ok": True}
        assert rows["salary"]["reconciliationStatus"] == {"ok": True}
