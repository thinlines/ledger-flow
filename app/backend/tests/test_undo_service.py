"""Tests for the undo service — dispatcher skeleton and each handler.

#17: undo handlers locate transactions by the ``txn_id`` recorded in the
forward event payload (via the projection) instead of scanning for header
text, and staleness is judged per transaction — an unrelated later edit to
the same file no longer blocks undo. Conflicting edits to the same
transaction fail the handler's semantic precondition instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import event_log_service
from services.config_service import AppConfig
from services.event_log_service import EVENTS_FILENAME, emit_event, hash_file, check_drift, rel_path
from services.operations_service import list_operations, record_operation
from services.undo_service import UndoOutcome, undo_event


def _make_config(workspace: Path) -> AppConfig:
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test"},
        dirs={
            "csv_dir": "csv",
            "journal_dir": "journals",
            "init_dir": "init",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
    )


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


def _read_events(workspace: Path) -> list[dict]:
    config = _make_config(workspace)
    operation_events = [
        {
            "id": op["id"],
            "type": op["type"],
            "summary": op["summary"],
            "payload": op["payload"],
            "journal_refs": op["files"],
            "compensates": op["compensates"],
        }
        for op in reversed(list_operations(config))
    ]
    events_file = workspace / EVENTS_FILENAME
    if not events_file.exists():
        return operation_events
    legacy_events = [
        json.loads(line)
        for line in events_file.read_text().splitlines()
        if line.strip()
    ]
    legacy_ids = {str(event.get("id")) for event in legacy_events}
    return legacy_events + [
        event for event in operation_events if str(event.get("id")) not in legacy_ids
    ]


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


EXTERNAL_INSERT = (
    "2026-03-01 * Inserted Externally\n"
    "    Assets:Bank:Checking  -$1.00\n"
    "    Expenses:Groceries  $1.00\n"
    "\n"
)


# ---------------------------------------------------------------------------
# Dispatcher skeleton
# ---------------------------------------------------------------------------


class TestUndoDispatcher:
    def test_not_found(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        result = undo_event(_make_config(workspace), "nonexistent-id")
        assert result.outcome == UndoOutcome.NOT_FOUND

    def test_unsupported_event_type(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        _write_journal(workspace, "2026.journal", "")
        event_id = record_operation(
            _make_config(workspace),
            operation_type="some.unknown.type.v1",
            summary="test",
            payload={},
            files=[],
        )
        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.UNSUPPORTED

    def test_refuses_when_operation_file_hash_has_drifted(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        config = _make_config(workspace)
        journal = _write_journal(
            workspace,
            "2026.journal",
            "2026-03-15 * Test\n    ; lf_txn_id: txn_test\n    Assets:Bank:Checking  -$10.00\n    Expenses:Groceries  $10.00\n",
        )
        before = hash_file(journal)
        journal.write_text("", encoding="utf-8")
        after = hash_file(journal)
        event_id = record_operation(
            config,
            operation_type="transaction.deleted.v1",
            summary="Deleted: Test",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 * Test",
                "txn_id": "txn_test",
                "deleted_block": "2026-03-15 * Test\n    ; lf_txn_id: txn_test\n    Assets:Bank:Checking  -$10.00\n    Expenses:Groceries  $10.00",
            },
            files=[
                {
                    "path": rel_path(journal, workspace),
                    "hash_before": before,
                    "hash_after": after,
                }
            ],
        )
        journal.write_text("; external edit\n", encoding="utf-8")

        result = undo_event(config, event_id)

        assert result.outcome == UndoOutcome.DRIFT

    def test_already_compensated(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(
            workspace,
            "2026.journal",
            "2026-03-15 * Test\n    ; lf_txn_id: txn_test\n    Assets:Bank:Checking  -$10.00\n    Expenses:Groceries  $10.00\n",
        )
        hash_before = check_drift(workspace, journal)

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
                "txn_id": "txn_test",
                "deleted_block": "\n".join(lines),
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

        # First undo succeeds.
        r1 = undo_event(_make_config(workspace), event_id)
        assert r1.outcome == UndoOutcome.SUCCESS

        # Second undo is idempotent.
        r2 = undo_event(_make_config(workspace), event_id)
        assert r2.outcome == UndoOutcome.ALREADY_COMPENSATED
        assert r2.compensating_event_id == r1.compensating_event_id


# ---------------------------------------------------------------------------
# Handler: transaction.deleted.v1
# ---------------------------------------------------------------------------


class TestUndoDeleted:
    def _delete_and_emit(self, workspace: Path, journal: Path, header: str, txn_id: str) -> str:
        hash_before = check_drift(workspace, journal)
        lines = journal.read_text(encoding="utf-8").splitlines()
        from services.journal_block_service import find_transaction_block

        idx = next(i for i, line in enumerate(lines) if line == header)
        bs, be = find_transaction_block(lines, idx)
        deleted_block = "\n".join(lines[bs:be])

        remove_start = bs
        if remove_start > 0 and lines[remove_start - 1].strip() == "":
            remove_start -= 1
        new_lines = lines[:remove_start] + lines[be:]
        journal.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        hash_after = hash_file(journal)
        return emit_event(
            workspace,
            event_type="transaction.deleted.v1",
            summary="Deleted: Whole Foods",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": header,
                "txn_id": txn_id,
                "deleted_block": deleted_block,
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

    def test_round_trip_delete_and_restore(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        original = (
            "2026-03-10 * Opening\n"
            "    ; lf_txn_id: txn_opening\n"
            "    Assets:Bank:Checking  $1000.00\n"
            "    Equity:Opening-Balances\n"
            "\n"
            "2026-03-15 * Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", original)

        event_id = self._delete_and_emit(workspace, journal, "2026-03-15 * Whole Foods", "txn_wf")
        assert "Whole Foods" not in journal.read_text()

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        restored = journal.read_text()
        assert "Whole Foods" in restored
        assert "Expenses:Groceries" in restored
        assert "Opening" in restored
        # Identity survives delete → undo: the restored block keeps its id.
        assert "; lf_txn_id: txn_wf" in restored

    def test_restore_refuses_after_unrelated_file_edit(self, tmp_path: Path) -> None:
        """#22 restores whole-file drift refusal through operation file hashes."""
        workspace = _setup_workspace(tmp_path)
        original = (
            "2026-03-15 * Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", original)
        event_id = self._delete_and_emit(workspace, journal, "2026-03-15 * Whole Foods", "txn_wf")

        # External edit after the delete.
        journal.write_text(EXTERNAL_INSERT + journal.read_text(encoding="utf-8"), encoding="utf-8")

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.DRIFT
        text = journal.read_text()
        assert "Whole Foods" not in text
        assert "Inserted Externally" in text

    def test_refuses_duplicate_by_id(self, tmp_path: Path) -> None:
        """If a block with the same lf_txn_id still exists, undo refuses."""
        workspace = _setup_workspace(tmp_path)
        content = (
            "2026-03-15 * Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", content)

        hash_after = hash_file(journal)
        event_id = emit_event(
            workspace,
            event_type="transaction.deleted.v1",
            summary="Deleted: Whole Foods",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 * Whole Foods",
                "txn_id": "txn_wf",
                "deleted_block": content.strip(),
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:none", "hash_after": hash_after}],
        )

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.FAILED
        assert "re-created" in result.message


# ---------------------------------------------------------------------------
# Handler: transaction.recategorized.v1
# ---------------------------------------------------------------------------


RECAT_POST_FORWARD = (
    "2026-03-15 * Whole Foods\n"
    "    ; lf_txn_id: txn_wf\n"
    "    Assets:Bank:Checking  -$50.00\n"
    "    Expenses:Unknown  $50.00\n"
)


class TestUndoRecategorized:
    def _emit_recat_event(self, workspace: Path, journal: Path) -> str:
        hash_after = hash_file(journal)
        return emit_event(
            workspace,
            event_type="transaction.recategorized.v1",
            summary="Reset category: Whole Foods",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 * Whole Foods",
                "txn_id": "txn_wf",
                "previous_account": "Expenses:Groceries",
                "new_account": "Expenses:Unknown",
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:x", "hash_after": hash_after}],
        )

    def test_round_trip_recategorize_and_restore(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", RECAT_POST_FORWARD)
        event_id = self._emit_recat_event(workspace, journal)

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        restored = journal.read_text()
        assert "Expenses:Groceries" in restored
        assert "Expenses:Unknown" not in restored

    def test_undo_survives_line_shift(self, tmp_path: Path) -> None:
        """An external edit above the block moves its lines; locating by
        txn_id must not care. This was the header-scan's failure case
        (duplicate header text elsewhere also broke it)."""
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", RECAT_POST_FORWARD)
        event_id = self._emit_recat_event(workspace, journal)

        journal.write_text(EXTERNAL_INSERT + journal.read_text(encoding="utf-8"), encoding="utf-8")

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.DRIFT
        restored = journal.read_text()
        assert "Expenses:Unknown  $50.00" in restored
        assert "Inserted Externally" in restored

    def test_conflicting_same_block_edit_fails(self, tmp_path: Path) -> None:
        """A later recategorize of the same transaction removes the account
        this undo would revert — the semantic precondition fails."""
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(
            workspace,
            "2026.journal",
            RECAT_POST_FORWARD.replace("Expenses:Unknown", "Expenses:Coffee"),
        )
        event_id = self._emit_recat_event(workspace, journal)

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.FAILED

    def test_missing_txn_id_fails_closed(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", RECAT_POST_FORWARD)
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
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:x", "hash_after": hash_after}],
        )

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.FAILED
        assert "txn_id" in result.message


# ---------------------------------------------------------------------------
# Handler: transaction.status_toggled.v1
# ---------------------------------------------------------------------------


class TestUndoStatusToggled:
    def _emit_toggle_event(self, workspace: Path, journal: Path) -> str:
        hash_after = hash_file(journal)
        return emit_event(
            workspace,
            event_type="transaction.status_toggled.v1",
            summary="Toggled to pending",
            payload={
                "journal_path": "journals/2026.journal",
                "header_line": "2026-03-15 Whole Foods",
                "txn_id": "txn_wf",
                "previous_status": "unmarked",
                "new_status": "pending",
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:x", "hash_after": hash_after}],
        )

    def test_round_trip_toggle_and_restore(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        post_forward = (
            "2026-03-15 ! Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", post_forward)
        event_id = self._emit_toggle_event(workspace, journal)

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        restored_header = journal.read_text().splitlines()[0]
        assert restored_header == "2026-03-15 Whole Foods"

    def test_later_toggle_of_same_txn_fails(self, tmp_path: Path) -> None:
        """The projected status no longer matches the event's new_status —
        true block-level staleness, rejected."""
        workspace = _setup_workspace(tmp_path)
        post_second_toggle = (
            "2026-03-15 * Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", post_second_toggle)
        event_id = self._emit_toggle_event(workspace, journal)

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.FAILED


# ---------------------------------------------------------------------------
# Handler: manual_entry.created.v1
# ---------------------------------------------------------------------------


class TestUndoManualEntryCreated:
    def test_round_trip_create_and_delete(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", "")

        from services.manual_entry_service import create_manual_transaction
        hash_before = check_drift(workspace, journal)
        created = create_manual_transaction(
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
                "txn_id": created["txnId"],
            },
            journal_refs=[{"path": "journals/2026.journal", "hash_before": hash_before, "hash_after": hash_after}],
        )

        assert "Whole Foods" in journal.read_text()

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS
        assert "Whole Foods" not in journal.read_text()

    def test_undo_survives_line_shift(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", "")

        from services.manual_entry_service import create_manual_transaction
        created = create_manual_transaction(
            journal_path=journal,
            accounts_dat=workspace / "rules" / "10-accounts.dat",
            tracked_account_cfg={"ledger_account": "Assets:Bank:Checking"},
            txn_date="2026-03-15",
            payee="Whole Foods",
            amount_str="50.00",
            destination_account="Expenses:Groceries",
        )
        hash_after = hash_file(journal)
        event_id = emit_event(
            workspace,
            event_type="manual_entry.created.v1",
            summary="Created manual entry",
            payload={"date": "2026-03-15", "payee": "Whole Foods", "txn_id": created["txnId"]},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:none", "hash_after": hash_after}],
        )

        journal.write_text(EXTERNAL_INSERT + journal.read_text(encoding="utf-8"), encoding="utf-8")

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.DRIFT
        text = journal.read_text()
        assert "Whole Foods" in text
        assert "Inserted Externally" in text


# ---------------------------------------------------------------------------
# Handler: transaction.notes_updated.v1
# ---------------------------------------------------------------------------


class TestUndoNotesUpdated:
    def _emit_notes_event(
        self,
        workspace: Path,
        journal: Path,
        header_line: str,
        notes: str,
        previous_notes: str,
        *,
        include_previous: bool = True,
        txn_id: str | None = "txn_wf",
    ) -> str:
        hash_after = hash_file(journal)
        payload: dict = {
            "journal_path": "journals/2026.journal",
            "header_line": header_line,
            "notes": notes,
        }
        if txn_id is not None:
            payload["txn_id"] = txn_id
        if include_previous:
            payload["previous_notes"] = previous_notes
        return emit_event(
            workspace,
            event_type="transaction.notes_updated.v1",
            summary=f"Notes updated: {header_line}",
            payload=payload,
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:none", "hash_after": hash_after}],
        )

    def test_round_trip_set_notes_and_remove(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        post_forward = (
            "2026-03-15 * Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    ; notes: weekly groceries\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", post_forward)

        event_id = self._emit_notes_event(
            workspace, journal,
            header_line="2026-03-15 * Whole Foods",
            notes="weekly groceries",
            previous_notes="",
        )

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        restored = journal.read_text()
        assert "notes:" not in restored
        assert "Expenses:Groceries" in restored

    def test_round_trip_replace_notes(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        post_forward = (
            "2026-03-15 * Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    ; notes: new value\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", post_forward)

        event_id = self._emit_notes_event(
            workspace, journal,
            header_line="2026-03-15 * Whole Foods",
            notes="new value",
            previous_notes="old value",
        )

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        restored = journal.read_text()
        assert "; notes: old value" in restored
        assert "new value" not in restored

    def test_round_trip_restore_after_deletion(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        post_forward = (
            "2026-03-15 * Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", post_forward)

        event_id = self._emit_notes_event(
            workspace, journal,
            header_line="2026-03-15 * Whole Foods",
            notes="",
            previous_notes="receipt #4711",
        )

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        restored = journal.read_text()
        # Restored notes line sits inside the block, after the header.
        lines = restored.splitlines()
        assert "    ; notes: receipt #4711" in lines[1:4]

    def test_pre_migration_event_fails_closed(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        post_forward = (
            "2026-03-15 * Whole Foods\n"
            "    ; lf_txn_id: txn_wf\n"
            "    ; notes: weekly groceries\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", post_forward)

        event_id = self._emit_notes_event(
            workspace, journal,
            header_line="2026-03-15 * Whole Foods",
            notes="weekly groceries",
            previous_notes="",  # ignored — include_previous=False drops the key.
            include_previous=False,
        )

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.FAILED
        assert "previous_notes" in result.message


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
            "    ; lf_txn_id: txn_imported\n"
            "    ; lf_source_identity: abc123\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Unknown  $50.00\n"
            "\n"
            "2026-03-15 Whole Foods\n"
            "    ; lf_txn_id: txn_manual\n"
            "    ; :manual:\n"
            "    Assets:Bank:Checking  -$50.00\n"
            "    Expenses:Groceries  $50.00\n"
        )
        journal = _write_journal(workspace, "2026.journal", main_content)

        hash_after_main = hash_file(journal)

        event_id = emit_event(
            workspace,
            event_type="transaction.unmatched.v1",
            summary="Unmatched: Whole Foods",
            payload={
                "journal_path": "journals/2026.journal",
                "archive_path": "journals/archived-manual.journal",
                "header_line": "2026-03-15 * Whole Foods",
                "txn_id": "txn_imported",
                "match_id": "test-match-uuid",
                "restored_manual_block": (
                    "2026-03-15 Whole Foods\n"
                    "    ; lf_txn_id: txn_manual\n"
                    "    ; :manual:\n"
                    "    Assets:Bank:Checking  -$50.00\n"
                    "    Expenses:Groceries  $50.00"
                ),
            },
            journal_refs=[
                {"path": "journals/2026.journal", "hash_before": "sha256:irrelevant", "hash_after": hash_after_main},
            ],
        )

        return workspace, journal, event_id

    def test_round_trip_unmatch_and_rematch(self, tmp_path: Path) -> None:
        workspace, journal, event_id = self._setup_unmatched_state(tmp_path)

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        main_text = journal.read_text()
        assert "; :manual:" in main_text
        assert "; lf_match_id: test-match-uuid" in main_text

        # The restored manual entry was removed from the main journal.
        header_count = sum(1 for line in main_text.splitlines() if line.strip().endswith("Whole Foods"))
        assert header_count == 1

        # Destination restored from Unknown to Groceries.
        assert "Expenses:Groceries" in main_text
        assert "Expenses:Unknown" not in main_text

        # Archive file re-created.
        archive = workspace / "journals" / "archived-manual.journal"
        assert archive.is_file()
        assert "lf_match_id: test-match-uuid" in archive.read_text()

    def test_rematch_survives_line_shift(self, tmp_path: Path) -> None:
        workspace, journal, event_id = self._setup_unmatched_state(tmp_path)

        journal.write_text(EXTERNAL_INSERT + journal.read_text(encoding="utf-8"), encoding="utf-8")

        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.DRIFT
        main_text = journal.read_text()
        assert "; match-id: test-match-uuid" not in main_text
        assert "Inserted Externally" in main_text

    def test_compensating_event_emitted(self, tmp_path: Path) -> None:
        workspace, journal, event_id = self._setup_unmatched_state(tmp_path)
        result = undo_event(_make_config(workspace), event_id)
        assert result.outcome == UndoOutcome.SUCCESS

        events = _read_events(workspace)
        comp = [e for e in events if e.get("compensates") == event_id]
        assert len(comp) == 1
        assert comp[0]["type"] == "transaction.unmatched.v1.compensated.v1"
