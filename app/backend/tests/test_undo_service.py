"""Tests for the undo service — dispatcher skeleton and each handler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import event_log_service
from services.event_log_service import EVENTS_FILENAME, emit_event, hash_file, check_drift
from services.undo_service import UndoOutcome, undo_event


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


def _read_events(workspace: Path) -> list[dict]:
    events_file = workspace / EVENTS_FILENAME
    if not events_file.exists():
        return []
    return [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]


def _setup_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    for d in ["journals", "rules"]:
        (workspace / d).mkdir(parents=True)
    (workspace / "rules" / "10-accounts.dat").write_text(
        "account Expenses:Groceries\naccount Expenses:Unknown\naccount Assets:Bank:Checking\n",
        encoding="utf-8",
    )
    return workspace


def _write_journal(workspace: Path, filename: str, content: str) -> Path:
    path = workspace / "journals" / filename
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Dispatcher skeleton
# ---------------------------------------------------------------------------


class TestUndoDispatcher:
    def test_not_found(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        result = undo_event(workspace, "nonexistent-id")
        assert result.outcome == UndoOutcome.NOT_FOUND

    def test_unsupported_event_type(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", "")
        emit_event(
            workspace,
            event_type="some.unknown.type.v1",
            summary="test",
            payload={},
            journal_refs=[],
        )
        events = _read_events(workspace)
        result = undo_event(workspace, events[0]["id"])
        assert result.outcome == UndoOutcome.UNSUPPORTED

    def test_already_compensated(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", "2026-03-15 * Test\n    Assets:Bank:Checking  -$10.00\n    Expenses:Groceries  $10.00\n")
        hash_before = check_drift(workspace, journal)

        from services.backup_service import backup_file
        backup_file(journal, "delete")

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        journal.write_text("", encoding="utf-8")

        hash_after = hash_file(journal)
        event_id = emit_event(
            workspace,
            event_type="transaction.deleted.v1",
            summary="Deleted: Test",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 * Test",
                "deleted_block": "\n".join(lines),
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

        # First undo succeeds.
        r1 = undo_event(workspace, event_id)
        assert r1.outcome == UndoOutcome.SUCCESS

        # Second undo is idempotent.
        r2 = undo_event(workspace, event_id)
        assert r2.outcome == UndoOutcome.ALREADY_COMPENSATED
        assert r2.compensating_event_id == r1.compensating_event_id

    def test_drift_detected(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", "2026-03-15 * Test\n    Assets:Bank:Checking  -$10.00\n    Expenses:Groceries  $10.00\n")
        hash_before = check_drift(workspace, journal)

        from services.backup_service import backup_file
        backup_file(journal, "delete")

        text = journal.read_text(encoding="utf-8")
        journal.write_text("", encoding="utf-8")
        hash_after = hash_file(journal)

        event_id = emit_event(
            workspace,
            event_type="transaction.deleted.v1",
            summary="Deleted: Test",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 * Test",
                "deleted_block": text.strip(),
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

        # Tamper with the file to simulate drift.
        journal.write_text("external edit\n", encoding="utf-8")

        result = undo_event(workspace, event_id)
        assert result.outcome == UndoOutcome.DRIFT


# ---------------------------------------------------------------------------
# Handler: transaction.deleted.v1
# ---------------------------------------------------------------------------


class TestUndoDeleted:
    def test_round_trip_delete_and_restore(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        original = "2026-03-10 * Opening\n    Assets:Bank:Checking  $1000.00\n    Equity:Opening-Balances\n\n2026-03-15 * Whole Foods\n    Assets:Bank:Checking  -$50.00\n    Expenses:Groceries  $50.00\n"
        journal = _write_journal(workspace, "2026.journal", original)

        hash_before = check_drift(workspace, journal)
        from services.backup_service import backup_file
        backup_file(journal, "delete")

        lines = journal.read_text(encoding="utf-8").splitlines()
        from services.journal_block_service import locate_header, find_transaction_block
        idx = locate_header(lines, "2026-03-15 * Whole Foods")
        bs, be = find_transaction_block(lines, idx)
        deleted_block = "\n".join(lines[bs:be])

        remove_start = bs
        if remove_start > 0 and lines[remove_start - 1].strip() == "":
            remove_start -= 1
        new_lines = lines[:remove_start] + lines[be:]
        journal.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        hash_after = hash_file(journal)
        event_id = emit_event(
            workspace,
            event_type="transaction.deleted.v1",
            summary="Deleted: Whole Foods",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 * Whole Foods",
                "deleted_block": deleted_block,
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

        # Verify deleted.
        assert "Whole Foods" not in journal.read_text()

        # Undo.
        result = undo_event(workspace, event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        # Verify restored.
        restored = journal.read_text()
        assert "Whole Foods" in restored
        assert "Expenses:Groceries" in restored
        # Opening balance still present.
        assert "Opening" in restored

    def test_refuses_duplicate(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        content = "2026-03-15 * Whole Foods\n    Assets:Bank:Checking  -$50.00\n    Expenses:Groceries  $50.00\n"
        journal = _write_journal(workspace, "2026.journal", content)

        hash_after = hash_file(journal)
        event_id = emit_event(
            workspace,
            event_type="transaction.deleted.v1",
            summary="Deleted: Whole Foods",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 * Whole Foods",
                "deleted_block": content.strip(),
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:none", "hash_after": hash_after}],
        )

        # The transaction still exists → undo should refuse.
        result = undo_event(workspace, event_id)
        assert result.outcome == UndoOutcome.FAILED
        assert "re-created" in result.message


# ---------------------------------------------------------------------------
# Handler: transaction.recategorized.v1
# ---------------------------------------------------------------------------


class TestUndoRecategorized:
    def test_round_trip_recategorize_and_restore(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        # Start with a categorized transaction.
        original = "2026-03-15 * Whole Foods\n    Assets:Bank:Checking  -$50.00\n    Expenses:Groceries  $50.00\n"
        journal = _write_journal(workspace, "2026.journal", original)

        # Recategorize to Unknown.
        hash_before = check_drift(workspace, journal)
        from services.backup_service import backup_file
        from services.transfer_service import rewrite_posting_account
        backup_file(journal, "recategorize")

        lines = journal.read_text(encoding="utf-8").splitlines()
        from services.journal_block_service import locate_header, find_transaction_block
        idx = locate_header(lines, "2026-03-15 * Whole Foods")
        bs, be = find_transaction_block(lines, idx)

        for i in range(bs + 1, be):
            from services.transfer_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE
            m = ACCOUNT_LINE_RE.match(lines[i]) or ACCOUNT_ONLY_RE.match(lines[i])
            if m and m.group(2).strip() == "Expenses:Groceries":
                new_line, _ = rewrite_posting_account(lines[i], "Expenses:Unknown")
                lines[i] = new_line
                break

        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        hash_after = hash_file(journal)
        event_id = emit_event(
            workspace,
            event_type="transaction.recategorized.v1",
            summary="Reset category: Whole Foods",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 * Whole Foods",
                "previous_account": "Expenses:Groceries",
                "new_account": "Expenses:Unknown",
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

        # Verify recategorized.
        assert "Expenses:Unknown" in journal.read_text()

        # Undo.
        result = undo_event(workspace, event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        # Verify restored.
        restored = journal.read_text()
        assert "Expenses:Groceries" in restored
        assert "Expenses:Unknown" not in restored


# ---------------------------------------------------------------------------
# Handler: transaction.status_toggled.v1
# ---------------------------------------------------------------------------


class TestUndoStatusToggled:
    def test_round_trip_toggle_and_restore(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        # Start with unmarked status.
        original = "2026-03-15 Whole Foods\n    Assets:Bank:Checking  -$50.00\n    Expenses:Groceries  $50.00\n"
        journal = _write_journal(workspace, "2026.journal", original)

        # Toggle to pending.
        hash_before = check_drift(workspace, journal)
        from services.backup_service import backup_file
        from services.header_parser import set_header_status, TransactionStatus
        backup_file(journal, "toggle")

        lines = journal.read_text(encoding="utf-8").splitlines()
        lines[0] = set_header_status(lines[0], TransactionStatus.pending)
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        hash_after = hash_file(journal)
        event_id = emit_event(
            workspace,
            event_type="transaction.status_toggled.v1",
            summary="Toggled to pending",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 Whole Foods",
                "previous_status": "unmarked",
                "new_status": "pending",
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

        # Verify toggled.
        assert "!" in journal.read_text().splitlines()[0]

        # Undo.
        result = undo_event(workspace, event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        # Verify restored — should be unmarked (no flag).
        restored_header = journal.read_text().splitlines()[0]
        assert "!" not in restored_header
        assert "*" not in restored_header
        assert restored_header == "2026-03-15 Whole Foods"


# ---------------------------------------------------------------------------
# Handler: manual_entry.created.v1
# ---------------------------------------------------------------------------


class TestUndoManualEntryCreated:
    def test_round_trip_create_and_delete(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", "")

        from services.manual_entry_service import create_manual_transaction
        hash_before = check_drift(workspace, journal)
        create_manual_transaction(
            journal_path=journal,
            accounts_dat=workspace / "rules" / "10-accounts.dat",
            tracked_account_cfg={"display_name": "Checking", "ledger_account": "Assets:Bank:Checking", "name": "Assets:Bank:Checking"},
            txn_date="2026-03-15",
            payee="Whole Foods",
            amount_str="50.00",
            destination_account="Expenses:Groceries",
            currency="USD",
        )

        hash_after = hash_file(journal)
        event_id = emit_event(
            workspace,
            event_type="manual_entry.created.v1",
            summary="Created manual entry: Whole Foods 50.00 USD",
            payload={
                "date": "2026-03-15",
                "payee": "Whole Foods",
                "amount": "50.00",
                "currency": "USD",
                "destination_account": "Expenses:Groceries",
                "source_account": "Assets:Bank:Checking",
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

        # Verify created.
        assert "Whole Foods" in journal.read_text()

        # Undo.
        result = undo_event(workspace, event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        # Verify deleted.
        assert "Whole Foods" not in journal.read_text()


# ---------------------------------------------------------------------------
# Handler: transaction.unmatched.v1
# ---------------------------------------------------------------------------


class TestUndoUnmatched:
    def _setup_unmatched_state(self, tmp_path: Path):
        """Set up a workspace in post-unmatch state with the event recorded."""
        workspace = _setup_workspace(tmp_path)

        # The imported transaction AFTER unmatch: tags stripped, destination = Unknown.
        main_content = (
            "2026-03-15 * Whole Foods\n"
            "    ; source_identity: abc123\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Unknown  $50.00\n"
            "\n"
            "2026-03-15 Whole Foods\n"
            "    ; :manual:\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", main_content)

        # Archive was cleaned up during unmatch (single entry removed).
        # No archive file exists.

        hash_after_main = hash_file(journal)
        # hash_after for archive is sha256:none since file was removed.

        event_id = emit_event(
            workspace,
            event_type="transaction.unmatched.v1",
            summary="Unmatched: Whole Foods",
            payload={
                "journal_path": "journals/2026.journal",
                "archive_path": "journals/archived-manual.journal",
                "header_line": "2026-03-15 * Whole Foods",
                "match_id": "test-match-uuid",
                "restored_manual_block": "2026-03-15 Whole Foods\n    ; :manual:\n    Assets:Bank:Checking  -$50.00\n    Expenses:Groceries  $50.00",
            },
            journal_refs=[
                {"path": "journals/2026.journal", "hash_before": "sha256:irrelevant", "hash_after": hash_after_main},
            ],
        )

        return workspace, journal, event_id

    def test_round_trip_unmatch_and_rematch(self, tmp_path: Path) -> None:
        workspace, journal, event_id = self._setup_unmatched_state(tmp_path)

        # Undo the unmatch → should re-match.
        result = undo_event(workspace, event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        # Verify: imported transaction has the tags back.
        main_text = journal.read_text()
        assert "; :manual:" in main_text
        assert "; match-id: test-match-uuid" in main_text

        # Verify: the restored manual entry was removed from the main journal.
        # Count occurrences of "Whole Foods" header lines — should be 1 (the imported).
        header_count = sum(1 for line in main_text.splitlines() if line.strip().endswith("Whole Foods"))
        assert header_count == 1

        # Verify: destination was restored from Unknown to Groceries.
        assert "Expenses:Groceries" in main_text
        # Expenses:Unknown should no longer appear.
        assert "Expenses:Unknown" not in main_text

        # Verify: archive file was re-created.
        archive = workspace / "journals" / "archived-manual.journal"
        assert archive.is_file()
        archive_text = archive.read_text()
        assert "match-id: test-match-uuid" in archive_text

    def test_compensating_event_emitted(self, tmp_path: Path) -> None:
        workspace, journal, event_id = self._setup_unmatched_state(tmp_path)
        result = undo_event(workspace, event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        events = _read_events(workspace)
        comp = [e for e in events if e.get("compensates") == event_id]
        assert len(comp) == 1
        assert comp[0]["type"] == "transaction.unmatched.v1.compensated.v1"
