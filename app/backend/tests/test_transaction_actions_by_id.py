"""Row actions on the (lf_txn_id, raw_block_hash) mutation contract (#17).

Delete, recategorize/reset, reassign-account, notes, and unmatch follow the
contract proven on toggle-status in #16: the client submits transaction id +
block hash; the backend locates the block by id, rejects only true
block-level staleness, and the writer re-projects the touched files. Line
numbers, header text, and journal paths are no longer part of any request.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from models import (
    DeleteTransactionRequest,
    ReassignAccountRequest,
    RecategorizeTransactionRequest,
    UnmatchTransactionRequest,
    UpdateNotesRequest,
)
from services import event_log_service
from services.config_service import AppConfig
from services.projection_db import database_path
from services.projection_service import refresh_projection


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


JOURNAL = """\
include ../opening/checking.journal

2026-03-15 * Whole Foods
    ; lf_txn_id: txn_wf
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00

2026-03-20 * Target
    ; lf_txn_id: txn_target
    Assets:Bank:Checking  -$30.00
    Expenses:Unknown  $30.00
"""

OPENING = """\
2026-01-01 Opening Balance
    ; lf_txn_id: txn_opening
    Assets:Bank:Checking    $100.00
    Equity:Opening Balances
"""

MATCHED_JOURNAL = """\
2026-03-15 * Whole Foods
    ; lf_txn_id: txn_matched
    ; :manual:
    ; match-id: test-match-uuid-1234
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00
"""

ARCHIVE_CONTENT = """\
; Ledger Flow archived manual entries.

2026-03-15 Whole Foods
    ; match-id: test-match-uuid-1234
    ; :manual:
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00
"""

EXTERNAL_INSERT = (
    "2026-03-01 * Inserted Externally\n"
    "    Assets:Bank:Checking  -$1.00\n"
    "    Expenses:Groceries  $1.00\n"
    "\n"
)


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    (workspace / "rules" / "10-accounts.dat").write_text(
        "account Expenses:Groceries\naccount Expenses:Unknown\n"
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


def _workspace(tmp_path: Path, monkeypatch, journal: str = JOURNAL) -> AppConfig:
    config = _make_config(tmp_path / "workspace")
    (config.journal_dir / "2026.journal").write_text(journal, encoding="utf-8")
    (config.root_dir / "opening" / "checking.journal").write_text(
        OPENING, encoding="utf-8"
    )
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    refresh_projection(config)
    return config


def _txn_row(config: AppConfig, txn_id: str) -> sqlite3.Row | None:
    conn = sqlite3.connect(database_path(config))
    conn.row_factory = sqlite3.Row
    with conn:
        row = conn.execute(
            "SELECT id, raw_block_hash, status FROM transactions WHERE id = ?",
            (txn_id,),
        ).fetchone()
    conn.close()
    return row


def _block_hash(config: AppConfig, txn_id: str) -> str:
    row = _txn_row(config, txn_id)
    assert row is not None, f"no projected transaction {txn_id}"
    return row["raw_block_hash"]


def _shift_lines_above(config: AppConfig) -> None:
    """Simulate an external edit inserting a transaction before the targets."""
    journal = config.journal_dir / "2026.journal"
    text = journal.read_text(encoding="utf-8")
    journal.write_text(
        text.replace("2026-03-15 * Whole Foods", EXTERNAL_INSERT + "2026-03-15 * Whole Foods"),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDeleteById:
    def test_deletes_block_by_id(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)

        result = main.transactions_delete(
            DeleteTransactionRequest(txnId="txn_wf", blockHash=_block_hash(config, "txn_wf"))
        )

        assert result["success"] is True
        assert result["eventId"]
        text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
        assert "Whole Foods" not in text
        assert "Target" in text
        assert "\n\n\n" not in text
        # Writer re-projected: the row is gone without a manual refresh.
        assert _txn_row(config, "txn_wf") is None

    def test_stale_hash_409_journal_untouched(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)
        before = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_delete(
                DeleteTransactionRequest(txnId="txn_wf", blockHash="sha256:stale")
            )

        assert exc_info.value.status_code == 409
        assert (config.journal_dir / "2026.journal").read_text(encoding="utf-8") == before

    def test_unknown_id_404(self, tmp_path, monkeypatch) -> None:
        _workspace(tmp_path, monkeypatch)

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_delete(
                DeleteTransactionRequest(txnId="txn_missing", blockHash="sha256:x")
            )

        assert exc_info.value.status_code == 404

    def test_line_shift_before_block_does_not_break_delete(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)
        block_hash = _block_hash(config, "txn_target")
        _shift_lines_above(config)

        result = main.transactions_delete(
            DeleteTransactionRequest(txnId="txn_target", blockHash=block_hash)
        )

        assert result["success"] is True
        text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
        assert "Target" not in text
        assert "Inserted Externally" in text

    def test_included_file_transaction_is_deletable(self, tmp_path, monkeypatch) -> None:
        """The -1 line-number sentinel used to reject included-file rows."""
        config = _workspace(tmp_path, monkeypatch)

        result = main.transactions_delete(
            DeleteTransactionRequest(
                txnId="txn_opening", blockHash=_block_hash(config, "txn_opening")
            )
        )

        assert result["success"] is True
        opening = (config.root_dir / "opening" / "checking.journal").read_text(
            encoding="utf-8"
        )
        assert "Opening Balance" not in opening


# ---------------------------------------------------------------------------
# Recategorize / reset category
# ---------------------------------------------------------------------------


class TestRecategorizeById:
    def test_sets_category_and_returns_fresh_identity(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)
        block_hash = _block_hash(config, "txn_target")

        result = main.transactions_recategorize(
            RecategorizeTransactionRequest(
                txnId="txn_target", blockHash=block_hash, newCategory="Expenses:Groceries"
            )
        )

        assert result["previousAccount"] == "Expenses:Unknown"
        assert result["newAccount"] == "Expenses:Groceries"
        assert result["txnId"] == "txn_target"
        assert result["blockHash"] != block_hash
        # Returned hash matches the re-projected row — usable for a follow-up.
        assert result["blockHash"] == _block_hash(config, "txn_target")

    def test_reset_to_unknown(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)

        result = main.transactions_recategorize(
            RecategorizeTransactionRequest(
                txnId="txn_wf", blockHash=_block_hash(config, "txn_wf")
            )
        )

        assert result["newAccount"] == "Expenses:Unknown"
        text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
        assert "Expenses:Groceries  $50.00" not in text

    def test_reset_already_unknown_422(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_recategorize(
                RecategorizeTransactionRequest(
                    txnId="txn_target", blockHash=_block_hash(config, "txn_target")
                )
            )

        assert exc_info.value.status_code == 422

    def test_stale_hash_409(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)
        before = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_recategorize(
                RecategorizeTransactionRequest(
                    txnId="txn_wf", blockHash="sha256:stale", newCategory="Expenses:Unknown"
                )
            )

        assert exc_info.value.status_code == 409
        assert (config.journal_dir / "2026.journal").read_text(encoding="utf-8") == before

    def test_line_shift_before_block_does_not_break(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)
        block_hash = _block_hash(config, "txn_target")
        _shift_lines_above(config)

        result = main.transactions_recategorize(
            RecategorizeTransactionRequest(
                txnId="txn_target", blockHash=block_hash, newCategory="Expenses:Groceries"
            )
        )

        assert result["newAccount"] == "Expenses:Groceries"


# ---------------------------------------------------------------------------
# Reassign account
# ---------------------------------------------------------------------------


class TestReassignAccountById:
    def test_reassigns_source_posting(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)
        block_hash = _block_hash(config, "txn_wf")

        result = main.transactions_reassign_account(
            ReassignAccountRequest(
                txnId="txn_wf",
                blockHash=block_hash,
                newAccountLedgerName="Assets:Bank:Savings",
            )
        )

        assert result["previousAccount"] == "Assets:Bank:Checking"
        assert result["newAccount"] == "Assets:Bank:Savings"
        assert result["txnId"] == "txn_wf"
        assert result["blockHash"] == _block_hash(config, "txn_wf")

    def test_untracked_account_422(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_reassign_account(
                ReassignAccountRequest(
                    txnId="txn_wf",
                    blockHash=_block_hash(config, "txn_wf"),
                    newAccountLedgerName="Assets:Nope",
                )
            )

        assert exc_info.value.status_code == 422

    def test_stale_hash_409(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_reassign_account(
                ReassignAccountRequest(
                    txnId="txn_wf",
                    blockHash="sha256:stale",
                    newAccountLedgerName="Assets:Bank:Savings",
                )
            )

        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


class TestNotesById:
    def test_inserts_updates_and_removes_notes(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)
        journal = config.journal_dir / "2026.journal"

        result = main.transactions_notes(
            UpdateNotesRequest(
                txnId="txn_wf", blockHash=_block_hash(config, "txn_wf"), notes="hello"
            )
        )
        assert "    ; notes: hello" in journal.read_text(encoding="utf-8")
        assert result["txnId"] == "txn_wf"

        # Follow-up edits chain on each response's returned hash.
        result = main.transactions_notes(
            UpdateNotesRequest(txnId="txn_wf", blockHash=result["blockHash"], notes="updated")
        )
        text = journal.read_text(encoding="utf-8")
        assert "    ; notes: updated" in text
        assert "hello" not in text

        result = main.transactions_notes(
            UpdateNotesRequest(txnId="txn_wf", blockHash=result["blockHash"], notes="")
        )
        assert "; notes:" not in journal.read_text(encoding="utf-8")

    def test_line_shift_before_block_does_not_break(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)
        block_hash = _block_hash(config, "txn_target")
        _shift_lines_above(config)

        result = main.transactions_notes(
            UpdateNotesRequest(txnId="txn_target", blockHash=block_hash, notes="still works")
        )

        assert result["success"] is True
        assert "    ; notes: still works" in (
            (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
        )

    def test_stale_hash_409(self, tmp_path, monkeypatch) -> None:
        config = _workspace(tmp_path, monkeypatch)

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_notes(
                UpdateNotesRequest(txnId="txn_wf", blockHash="sha256:stale", notes="x")
            )

        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Unmatch
# ---------------------------------------------------------------------------


def _matched_workspace(tmp_path, monkeypatch) -> AppConfig:
    config = _make_config(tmp_path / "workspace")
    (config.journal_dir / "2026.journal").write_text(MATCHED_JOURNAL, encoding="utf-8")
    (config.root_dir / "opening" / "checking.journal").write_text(OPENING, encoding="utf-8")
    (config.journal_dir / "archived-manual.journal").write_text(
        ARCHIVE_CONTENT, encoding="utf-8"
    )
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    refresh_projection(config)
    return config


class TestUnmatchById:
    def test_unmatches_by_id(self, tmp_path, monkeypatch) -> None:
        config = _matched_workspace(tmp_path, monkeypatch)

        result = main.transactions_unmatch(
            UnmatchTransactionRequest(
                txnId="txn_matched",
                blockHash=_block_hash(config, "txn_matched"),
                matchId="test-match-uuid-1234",
            )
        )

        assert result["success"] is True
        text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
        # Imported txn: tags stripped, destination reset.
        assert "; match-id:" not in text.split("2026-03-15 Whole Foods")[0]
        assert "Expenses:Unknown" in text
        # Restored manual entry re-inserted.
        assert "2026-03-15 Whole Foods" in text
        # Archive emptied → removed.
        assert not (config.journal_dir / "archived-manual.journal").exists()

    def test_stale_hash_409(self, tmp_path, monkeypatch) -> None:
        config = _matched_workspace(tmp_path, monkeypatch)
        before = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_unmatch(
                UnmatchTransactionRequest(
                    txnId="txn_matched",
                    blockHash="sha256:stale",
                    matchId="test-match-uuid-1234",
                )
            )

        assert exc_info.value.status_code == 409
        assert (config.journal_dir / "2026.journal").read_text(encoding="utf-8") == before

    def test_missing_archive_404(self, tmp_path, monkeypatch) -> None:
        config = _matched_workspace(tmp_path, monkeypatch)
        (config.journal_dir / "archived-manual.journal").unlink()
        refresh_projection(config)

        with pytest.raises(HTTPException) as exc_info:
            main.transactions_unmatch(
                UnmatchTransactionRequest(
                    txnId="txn_matched",
                    blockHash=_block_hash(config, "txn_matched"),
                    matchId="test-match-uuid-1234",
                )
            )

        assert exc_info.value.status_code == 404
