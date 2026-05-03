from __future__ import annotations

from pathlib import Path

import pytest

import main
from models import (
    ReconciliationDuplicateResolutionRequest,
    ReconciliationDuplicateReviewRequest,
)
from services.config_service import AppConfig
from services.event_log_service import read_events
from services.import_service import _build_existing_map, _classify_transaction
from services import reconciliation_duplicate_service


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
                "display_name": "Checking Import",
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
        },
        payee_aliases="payee_aliases.csv",
    )


def _seed_accounts_dat(config: AppConfig) -> None:
    (config.init_dir / "10-accounts.dat").write_text(
        "\n".join(
            [
                "account Assets:Checking:Wells Fargo",
                "account Expenses:Food:Groceries",
                "account Expenses:Food:Dining",
                "account Equity:Opening-Balances",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_journal(config: AppConfig, body: str) -> Path:
    journal = config.journal_dir / "2026.journal"
    journal.write_text(body, encoding="utf-8")
    return journal


def _context_rows(config: AppConfig, monkeypatch, *, start: str = "2026-03-01", end: str = "2026-03-31") -> list[dict]:
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    context = main.accounts_reconciliation_context("checking", period_start=start, period_end=end)
    return context["transactions"]


def _row_by_payee(rows: list[dict], payee: str) -> dict:
    return next(row for row in rows if row["payee"] == payee)


class TestDuplicateReviewHeuristic:
    def test_review_endpoint_requires_exact_amount_match(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(
            config,
            (
                "2026-03-05 Manual coffee\n"
                "    ; :manual:\n"
                "    Assets:Checking:Wells Fargo  $-25.00\n"
                "    Expenses:Food:Dining\n"
                "\n"
                "2026-03-06 Imported coffee\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: import-coffee\n"
                "    ; source_payload_hash: payload-coffee\n"
                "    Assets:Checking:Wells Fargo  $-24.00\n"
                "    Expenses:Unknown\n"
            ),
        )
        rows = _context_rows(config, monkeypatch)
        manual = _row_by_payee(rows, "Manual coffee")

        review = main.accounts_reconciliation_duplicate_review(
            "checking",
            ReconciliationDuplicateReviewRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKeys=[manual["selectionKey"]],
            ),
        )

        assert review["hasGroups"] is False
        assert review["groups"] == []

    def test_review_endpoint_rejects_dissimilar_same_day_same_amount_pairs(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(
            config,
            (
                "2026-03-05 Starbucks\n"
                "    ; :manual:\n"
                "    Assets:Checking:Wells Fargo  $-15.00\n"
                "    Expenses:Food:Dining\n"
                "\n"
                "2026-03-05 LANDLORD LLC\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: rent-1\n"
                "    ; source_payload_hash: payload-rent-1\n"
                "    Assets:Checking:Wells Fargo  $-15.00\n"
                "    Expenses:Unknown\n"
            ),
        )
        rows = _context_rows(config, monkeypatch)
        checked = _row_by_payee(rows, "Starbucks")

        review = main.accounts_reconciliation_duplicate_review(
            "checking",
            ReconciliationDuplicateReviewRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKeys=[checked["selectionKey"]],
            ),
        )

        assert review["hasGroups"] is False
        assert review["groups"] == []

    def test_review_endpoint_rejects_opposite_sign_same_day_pairs(self, tmp_path: Path, monkeypatch) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(
            config,
            (
                "2026-03-05 ACH Deposit WELLS FARGO IFI - ACCTVERIFY\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: acctverify-in\n"
                "    ; source_payload_hash: payload-in\n"
                "    Assets:Checking:Wells Fargo  $0.12\n"
                "    Expenses:Food:Dining\n"
                "\n"
                "2026-03-05 ACH Withdrawal WELLS FARGO IFI - ACCTVERIFY\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: acctverify-out\n"
                "    ; source_payload_hash: payload-out\n"
                "    Assets:Checking:Wells Fargo  $-0.12\n"
                "    Expenses:Food:Dining\n"
            ),
        )
        rows = _context_rows(config, monkeypatch)
        checked = _row_by_payee(rows, "ACH Deposit WELLS FARGO IFI - ACCTVERIFY")

        review = main.accounts_reconciliation_duplicate_review(
            "checking",
            ReconciliationDuplicateReviewRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKeys=[checked["selectionKey"]],
            ),
        )

        assert review["hasGroups"] is False
        assert review["groups"] == []


class TestDuplicateResolution:
    def test_use_imported_transaction_archives_manual_and_carries_category(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        journal = _seed_journal(
            config,
            (
                "2026-03-01 Manual groceries\n"
                "    ; :manual:\n"
                "    ; notes: remembered later\n"
                "    Assets:Checking:Wells Fargo  $-25.00\n"
                "    Expenses:Food:Groceries\n"
                "\n"
                "2026-03-02 Grocery Store\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: import-1\n"
                "    ; source_payload_hash: payload-1\n"
                "    Assets:Checking:Wells Fargo  $-25.00\n"
                "    Expenses:Unknown\n"
            ),
        )
        rows = _context_rows(config, monkeypatch)
        manual = _row_by_payee(rows, "Manual groceries")
        imported = _row_by_payee(rows, "Grocery Store")

        review = main.accounts_reconciliation_duplicate_review(
            "checking",
            ReconciliationDuplicateReviewRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKeys=[manual["selectionKey"]],
            ),
        )
        assert review["hasGroups"] is True
        assert review["groups"][0]["matches"][0]["action"] == "use_imported_transaction"

        result = main.accounts_reconciliation_duplicate_resolution(
            "checking",
            ReconciliationDuplicateResolutionRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKey=manual["selectionKey"],
                uncheckedSelectionKey=imported["selectionKey"],
                action="use_imported_transaction",
            ),
        )

        updated = journal.read_text(encoding="utf-8")
        archive = (config.journal_dir / "archived-manual.journal").read_text(encoding="utf-8")
        events = read_events(config.root_dir)
        assert result["removedSelectionKeys"] == [manual["selectionKey"]]
        assert result["addedCheckedSelectionKeys"] == [imported["selectionKey"]]
        assert result["eventId"]
        assert "Manual groceries" not in updated
        assert "Expenses:Food:Groceries" in updated
        assert "; notes: remembered later" in updated
        assert "; match-id:" in updated
        assert "Manual groceries" in archive
        assert events[-1]["type"] == "reconciliation.imported_transaction_used.v1"

    def test_remove_manual_duplicate_deletes_unchecked_manual_row(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        journal = _seed_journal(
            config,
            (
                "2026-03-04 Imported rent\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: rent-1\n"
                "    ; source_payload_hash: payload-rent-1\n"
                "    Assets:Checking:Wells Fargo  $-900.00\n"
                "    Expenses:Food:Dining\n"
                "\n"
                "2026-03-05 Manual rent copy\n"
                "    ; :manual:\n"
                "    Assets:Checking:Wells Fargo  $-900.00\n"
                "    Expenses:Food:Dining\n"
            ),
        )
        rows = _context_rows(config, monkeypatch)
        imported = _row_by_payee(rows, "Imported rent")
        manual = _row_by_payee(rows, "Manual rent copy")

        result = main.accounts_reconciliation_duplicate_resolution(
            "checking",
            ReconciliationDuplicateResolutionRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKey=imported["selectionKey"],
                uncheckedSelectionKey=manual["selectionKey"],
                action="remove_manual_duplicate",
            ),
        )

        updated = journal.read_text(encoding="utf-8")
        events = read_events(config.root_dir)
        assert result["removedSelectionKeys"] == [manual["selectionKey"]]
        assert result["eventId"]
        assert "Manual rent copy" not in updated
        assert "Imported rent" in updated
        assert events[-1]["type"] == "reconciliation.duplicate_manual_removed.v1"

    def test_duplicate_resolution_rolls_back_when_event_write_fails(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        journal = _seed_journal(
            config,
            (
                "2026-03-04 Imported rent\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: rent-1\n"
                "    ; source_payload_hash: payload-rent-1\n"
                "    Assets:Checking:Wells Fargo  $-900.00\n"
                "    Expenses:Food:Dining\n"
                "\n"
                "2026-03-05 Manual rent copy\n"
                "    ; :manual:\n"
                "    Assets:Checking:Wells Fargo  $-900.00\n"
                "    Expenses:Food:Dining\n"
            ),
        )
        original = journal.read_text(encoding="utf-8")
        rows = _context_rows(config, monkeypatch)
        imported = _row_by_payee(rows, "Imported rent")
        manual = _row_by_payee(rows, "Manual rent copy")

        monkeypatch.setattr(reconciliation_duplicate_service, "emit_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("event failed")))

        with pytest.raises(RuntimeError):
            main.accounts_reconciliation_duplicate_resolution(
                "checking",
                ReconciliationDuplicateResolutionRequest(
                    periodStart="2026-03-01",
                    periodEnd="2026-03-31",
                    checkedSelectionKey=imported["selectionKey"],
                    uncheckedSelectionKey=manual["selectionKey"],
                    action="remove_manual_duplicate",
                ),
            )

        assert journal.read_text(encoding="utf-8") == original

    def test_merge_imported_duplicates_preserves_alternate_identity_for_future_dedupe(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        journal = _seed_journal(
            config,
            (
                "2026-03-07 Utility bill\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: util-a\n"
                "    ; source_payload_hash: payload-a\n"
                "    Assets:Checking:Wells Fargo  $-120.00\n"
                "    Expenses:Food:Dining\n"
                "\n"
                "2026-03-08 Utility bill online\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: util-b\n"
                "    ; source_payload_hash: payload-b\n"
                "    Assets:Checking:Wells Fargo  $-120.00\n"
                "    Expenses:Food:Dining\n"
            ),
        )
        rows = _context_rows(config, monkeypatch)
        survivor = _row_by_payee(rows, "Utility bill")
        merged = _row_by_payee(rows, "Utility bill online")

        result = main.accounts_reconciliation_duplicate_resolution(
            "checking",
            ReconciliationDuplicateResolutionRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKey=survivor["selectionKey"],
                uncheckedSelectionKey=merged["selectionKey"],
                action="merge_imported_duplicates",
            ),
        )

        updated = journal.read_text(encoding="utf-8")
        existing_map = _build_existing_map(config, "checking", journal)
        events = read_events(config.root_dir)

        assert result["removedSelectionKeys"] == [merged["selectionKey"]]
        assert result["eventId"]
        assert "Utility bill online" not in updated
        assert "; source_identity_2: util-b" in updated
        assert "; source_payload_hash_2: payload-b" in updated
        assert events[-1]["type"] == "reconciliation.imported_duplicates_merged.v1"
        assert existing_map["util-a"] is not None
        assert existing_map["util-a"] != "payload-b"
        assert existing_map["util-b"] == "payload-b"
        assert _classify_transaction(
            {
                "sourceIdentity": "util-b",
                "sourcePayloadHash": "payload-b",
            },
            existing_map,
        ) == "duplicate"

        refreshed_rows = _context_rows(config, monkeypatch)
        refreshed_survivor = _row_by_payee(refreshed_rows, "Utility bill")
        assert refreshed_survivor["selectionKey"] == survivor["selectionKey"]

    def test_use_imported_transaction_rejects_split_manual_duplicate(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        _seed_journal(
            config,
            (
                "2026-03-01 Manual groceries split\n"
                "    ; :manual:\n"
                "    Assets:Checking:Wells Fargo  $-25.00\n"
                "    Expenses:Food:Groceries  $-20.00\n"
                "    Expenses:Food:Dining  $-5.00\n"
                "\n"
                "2026-03-02 Grocery Store\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: import-1\n"
                "    ; source_payload_hash: payload-1\n"
                "    Assets:Checking:Wells Fargo  $-25.00\n"
                "    Expenses:Unknown\n"
            ),
        )

        rows = _context_rows(config, monkeypatch)
        manual = _row_by_payee(rows, "Manual groceries split")
        imported = _row_by_payee(rows, "Grocery Store")

        with pytest.raises(main.HTTPException) as exc_info:
            main.accounts_reconciliation_duplicate_resolution(
                "checking",
                ReconciliationDuplicateResolutionRequest(
                    periodStart="2026-03-01",
                    periodEnd="2026-03-31",
                    checkedSelectionKey=manual["selectionKey"],
                    uncheckedSelectionKey=imported["selectionKey"],
                    action="use_imported_transaction",
                ),
            )

        assert exc_info.value.status_code == 422
        assert "Split manual duplicates" in exc_info.value.detail

    def test_cross_journal_imported_candidates_show_without_merge_action(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        march = config.journal_dir / "2026.journal"
        april = config.journal_dir / "2027.journal"
        march.write_text(
            (
                "2026-03-07 Utility bill\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: util-a\n"
                "    ; source_payload_hash: payload-a\n"
                "    Assets:Checking:Wells Fargo  $-120.00\n"
                "    Expenses:Food:Dining\n"
            ),
            encoding="utf-8",
        )
        april.write_text(
            (
                "2026-03-08 Utility bill online\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: util-b\n"
                "    ; source_payload_hash: payload-b\n"
                "    Assets:Checking:Wells Fargo  $-120.00\n"
                "    Expenses:Food:Dining\n"
            ),
            encoding="utf-8",
        )

        rows = _context_rows(config, monkeypatch)
        survivor = _row_by_payee(rows, "Utility bill")

        review = main.accounts_reconciliation_duplicate_review(
            "checking",
            ReconciliationDuplicateReviewRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKeys=[survivor["selectionKey"]],
            ),
        )

        assert review["hasGroups"] is True
        match = review["groups"][0]["matches"][0]
        assert match["action"] is None
        assert match["actionLabel"] is None
        assert "different journals" in match["actionBlockedReason"]

    def test_chained_imported_merge_preserves_all_carried_identities(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _make_config(tmp_path / "workspace")
        _seed_accounts_dat(config)
        journal = _seed_journal(
            config,
            (
                "2026-03-07 Utility bill\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: util-a\n"
                "    ; source_payload_hash: payload-a\n"
                "    Assets:Checking:Wells Fargo  $-120.00\n"
                "    Expenses:Food:Dining\n"
                "\n"
                "2026-03-08 Utility bill online\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: util-b\n"
                "    ; source_payload_hash: payload-b\n"
                "    Assets:Checking:Wells Fargo  $-120.00\n"
                "    Expenses:Food:Dining\n"
                "\n"
                "2026-03-09 Utility bill mobile\n"
                "    ; import_account_id: checking\n"
                "    ; source_identity: util-c\n"
                "    ; source_payload_hash: payload-c\n"
                "    ; source_identity_2: util-d\n"
                "    ; source_payload_hash_2: payload-d\n"
                "    Assets:Checking:Wells Fargo  $-120.00\n"
                "    Expenses:Food:Dining\n"
            ),
        )

        rows = _context_rows(config, monkeypatch)
        survivor = _row_by_payee(rows, "Utility bill")
        first_merge = _row_by_payee(rows, "Utility bill online")
        second_merge = _row_by_payee(rows, "Utility bill mobile")

        main.accounts_reconciliation_duplicate_resolution(
            "checking",
            ReconciliationDuplicateResolutionRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKey=survivor["selectionKey"],
                uncheckedSelectionKey=first_merge["selectionKey"],
                action="merge_imported_duplicates",
            ),
        )

        refreshed_rows = _context_rows(config, monkeypatch)
        refreshed_survivor = _row_by_payee(refreshed_rows, "Utility bill")
        refreshed_second_merge = _row_by_payee(refreshed_rows, "Utility bill mobile")

        main.accounts_reconciliation_duplicate_resolution(
            "checking",
            ReconciliationDuplicateResolutionRequest(
                periodStart="2026-03-01",
                periodEnd="2026-03-31",
                checkedSelectionKey=refreshed_survivor["selectionKey"],
                uncheckedSelectionKey=refreshed_second_merge["selectionKey"],
                action="merge_imported_duplicates",
            ),
        )

        updated = journal.read_text(encoding="utf-8")
        existing_map = _build_existing_map(config, "checking", journal)

        assert "Utility bill online" not in updated
        assert "Utility bill mobile" not in updated
        assert "; source_identity_2: util-b" in updated
        assert "; source_identity_3: util-c" in updated
        assert "; source_identity_4: util-d" in updated

        expected_payloads = {
            "util-a": existing_map["util-a"],
            "util-b": "payload-b",
            "util-c": "payload-c",
            "util-d": "payload-d",
        }
        assert expected_payloads["util-a"] is not None
        for identity, payload in expected_payloads.items():
            assert _classify_transaction(
                {
                    "sourceIdentity": identity,
                    "sourcePayloadHash": payload,
                },
                existing_map,
            ) == "duplicate"
