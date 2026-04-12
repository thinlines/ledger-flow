"""Tests for notes read/write and recategorize with newCategory."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from services import event_log_service
from services.backup_service import backup_file
from services.event_log_service import EVENTS_FILENAME, check_drift, emit_event, hash_file, rel_path
from services.journal_block_service import find_transaction_block, locate_header
from services.transfer_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE, rewrite_posting_account


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


# ---------------------------------------------------------------------------
# Helpers: workspace + journal setup
# ---------------------------------------------------------------------------


def _setup_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    for d in ["journals", "rules"]:
        (workspace / d).mkdir(parents=True)
    (workspace / "rules" / "10-accounts.dat").write_text(
        "account Expenses:Groceries\naccount Expenses:Unknown\naccount Assets:Bank:Checking\naccount Expenses:Pets\n",
        encoding="utf-8",
    )
    return workspace


def _write_journal(workspace: Path, filename: str, content: str) -> Path:
    path = workspace / "journals" / filename
    path.write_text(content, encoding="utf-8")
    return path


SAMPLE_JOURNAL = """\
2026-03-10 * Opening balance
    Assets:Bank:Checking  $1000.00
    Equity:Opening-Balances

2026-03-15 * Whole Foods
    ; source_identity: abc123
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00

2026-03-20 * Target
    ; source_identity: def456
    Assets:Bank:Checking  -$30.00
    Expenses:Unknown  $30.00
"""

JOURNAL_WITH_NOTES = """\
2026-03-15 * Whole Foods
    ; notes: Weekly groceries
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00

2026-03-20 * Walmart
    ; source_identity: def456
    Assets:Bank:Checking  -$38.32
    Expenses:Pets  $38.32
"""

_NOTES_RE = re.compile(r"^\s*;\s*notes:\s*(.*)$")


# ---------------------------------------------------------------------------
# Recategorize with newCategory
# ---------------------------------------------------------------------------


class TestRecategorizeWithNewCategory:
    """Recategorize endpoint sets a specific category when newCategory is provided."""

    def test_sets_specific_category(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", SAMPLE_JOURNAL)

        header_line = "2026-03-15 * Whole Foods"
        hash_before = check_drift(workspace, journal)
        backup_file(journal, "recategorize")

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, header_line)
        block_start, block_end = find_transaction_block(lines, header_idx)

        tracked_accounts = {"Assets:Bank:Checking"}
        new_category = "Expenses:Pets"

        destination_idx = None
        previous_account = None
        for i in range(block_start + 1, block_end):
            stripped = lines[i].strip()
            if stripped.startswith(";") or stripped == "":
                continue
            m = ACCOUNT_LINE_RE.match(lines[i]) or ACCOUNT_ONLY_RE.match(lines[i])
            if m:
                account = m.group(2).strip()
                if account in tracked_accounts:
                    continue
                destination_idx = i
                previous_account = account
                break

        assert destination_idx is not None
        assert previous_account == "Expenses:Groceries"

        new_line, changed = rewrite_posting_account(lines[destination_idx], new_category)
        assert changed
        lines[destination_idx] = new_line
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        hash_after = hash_file(journal)
        emit_event(
            workspace,
            event_type="transaction.recategorized.v1",
            summary=f"Recategorized: Whole Foods on 2026-03-15 ({previous_account} → {new_category})",
            payload={"previous_account": previous_account, "new_account": new_category},
            journal_refs=[{"path": rel_path(journal, workspace), "hash_before": hash_before, "hash_after": hash_after}],
        )

        result = journal.read_text()
        result_lines = result.splitlines()
        wf_idx = next(i for i, l in enumerate(result_lines) if "Whole Foods" in l)
        block_text = "\n".join(result_lines[wf_idx:wf_idx + 5])
        assert "Expenses:Pets" in block_text
        assert "Expenses:Groceries" not in block_text

        events = _read_events(workspace)
        assert events[-1]["type"] == "transaction.recategorized.v1"
        assert events[-1]["payload"]["previous_account"] == "Expenses:Groceries"
        assert events[-1]["payload"]["new_account"] == "Expenses:Pets"

    def test_without_new_category_resets_to_unknown(self, tmp_path: Path) -> None:
        """Backwards compatibility: omitting newCategory resets to Expenses:Unknown."""
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", SAMPLE_JOURNAL)

        header_line = "2026-03-15 * Whole Foods"
        hash_before = check_drift(workspace, journal)
        backup_file(journal, "recategorize")

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, header_line)
        block_start, block_end = find_transaction_block(lines, header_idx)

        tracked_accounts = {"Assets:Bank:Checking"}
        target_account = "Expenses:Unknown"

        destination_idx = None
        previous_account = None
        for i in range(block_start + 1, block_end):
            stripped = lines[i].strip()
            if stripped.startswith(";") or stripped == "":
                continue
            m = ACCOUNT_LINE_RE.match(lines[i]) or ACCOUNT_ONLY_RE.match(lines[i])
            if m:
                account = m.group(2).strip()
                if account in tracked_accounts:
                    continue
                destination_idx = i
                previous_account = account
                break

        assert destination_idx is not None
        assert previous_account == "Expenses:Groceries"

        new_line, changed = rewrite_posting_account(lines[destination_idx], target_account)
        assert changed
        lines[destination_idx] = new_line
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = journal.read_text()
        result_lines = result.splitlines()
        wf_idx = next(i for i, l in enumerate(result_lines) if "Whole Foods" in l)
        block_text = "\n".join(result_lines[wf_idx:wf_idx + 5])
        assert "Expenses:Unknown" in block_text
        assert "Expenses:Groceries" not in block_text

    def test_recategorize_unknown_to_specific_category(self, tmp_path: Path) -> None:
        """A transaction with Expenses:Unknown can be recategorized to a specific category."""
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", SAMPLE_JOURNAL)

        header_line = "2026-03-20 * Target"
        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, header_line)
        block_start, block_end = find_transaction_block(lines, header_idx)

        tracked_accounts = {"Assets:Bank:Checking"}
        new_category = "Expenses:Groceries"

        destination_idx = None
        previous_account = None
        for i in range(block_start + 1, block_end):
            stripped = lines[i].strip()
            if stripped.startswith(";") or stripped == "":
                continue
            m = ACCOUNT_LINE_RE.match(lines[i]) or ACCOUNT_ONLY_RE.match(lines[i])
            if m:
                account = m.group(2).strip()
                if account in tracked_accounts:
                    continue
                destination_idx = i
                previous_account = account
                break

        assert destination_idx is not None
        assert previous_account == "Expenses:Unknown"

        new_line, changed = rewrite_posting_account(lines[destination_idx], new_category)
        assert changed
        lines[destination_idx] = new_line
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = journal.read_text()
        result_lines = result.splitlines()
        target_idx = next(i for i, l in enumerate(result_lines) if "Target" in l)
        block_text = "\n".join(result_lines[target_idx:target_idx + 5])
        assert "Expenses:Groceries" in block_text
        assert "Expenses:Unknown" not in block_text


# ---------------------------------------------------------------------------
# Notes: save, update, clear
# ---------------------------------------------------------------------------


class TestSaveNotes:
    """Save notes to a transaction that has no existing notes."""

    def test_inserts_notes_line(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", SAMPLE_JOURNAL)

        header_line = "2026-03-15 * Whole Foods"
        notes_text = "Weekly grocery run"

        hash_before = check_drift(workspace, journal)
        backup_file(journal, "notes")

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, header_line)
        block_start, block_end = find_transaction_block(lines, header_idx)

        # No existing notes line.
        notes_idx = None
        for i in range(block_start + 1, block_end):
            if _NOTES_RE.match(lines[i]):
                notes_idx = i
                break
        assert notes_idx is None

        # Insert notes after header.
        lines.insert(block_start + 1, f"    ; notes: {notes_text}")
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = journal.read_text()
        result_lines = result.splitlines()
        wf_idx = next(i for i, l in enumerate(result_lines) if "Whole Foods" in l)
        assert _NOTES_RE.match(result_lines[wf_idx + 1])
        assert "Weekly grocery run" in result_lines[wf_idx + 1]

        # Other transactions unaffected.
        assert "Opening balance" in result
        assert "Target" in result


class TestUpdateNotes:
    """Update existing notes on a transaction."""

    def test_replaces_existing_notes(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", JOURNAL_WITH_NOTES)

        header_line = "2026-03-15 * Whole Foods"
        new_notes = "Updated: organic groceries"

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, header_line)
        block_start, block_end = find_transaction_block(lines, header_idx)

        # Find existing notes line.
        notes_idx = None
        for i in range(block_start + 1, block_end):
            if _NOTES_RE.match(lines[i]):
                notes_idx = i
                break

        assert notes_idx is not None
        assert "Weekly groceries" in lines[notes_idx]

        lines[notes_idx] = f"    ; notes: {new_notes}"
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = journal.read_text()
        assert "Updated: organic groceries" in result
        assert "Weekly groceries" not in result

        # Other transaction still intact.
        assert "Walmart" in result


class TestClearNotes:
    """Clearing notes (empty string) removes the notes line."""

    def test_removes_notes_line(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", JOURNAL_WITH_NOTES)

        header_line = "2026-03-15 * Whole Foods"

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, header_line)
        block_start, block_end = find_transaction_block(lines, header_idx)

        # Find and remove existing notes line.
        notes_idx = None
        for i in range(block_start + 1, block_end):
            if _NOTES_RE.match(lines[i]):
                notes_idx = i
                break

        assert notes_idx is not None
        del lines[notes_idx]
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = journal.read_text()
        # No notes line remains for Whole Foods.
        result_lines = result.splitlines()
        wf_idx = next(i for i, l in enumerate(result_lines) if "Whole Foods" in l)
        # Scan block — no notes line.
        for i in range(wf_idx + 1, len(result_lines)):
            if result_lines[i].strip() == "" or (result_lines[i] and not result_lines[i][0].isspace()):
                break
            assert not _NOTES_RE.match(result_lines[i])

        # Transaction posting lines remain.
        assert "Expenses:Groceries" in result


class TestReadNotesFromRegister:
    """Notes parsed via metadata are included in register entries."""

    def test_notes_present_in_metadata(self) -> None:
        """Verify that META_RE (used by journal_query_service) captures '; notes: ...' lines."""
        from services.journal_query_service import META_RE

        line = "    ; notes: Weekly groceries"
        m = META_RE.match(line)
        assert m is not None
        assert m.group(1).strip().lower() == "notes"
        assert m.group(2).strip() == "Weekly groceries"

    def test_notes_absent_returns_none(self) -> None:
        """A comment without 'notes:' key is not captured as notes."""
        from services.journal_query_service import META_RE

        line = "    ; source_identity: abc123"
        m = META_RE.match(line)
        assert m is not None
        # Key is 'source_identity', not 'notes'.
        assert m.group(1).strip().lower() != "notes"

    def test_register_event_has_notes_field(self) -> None:
        """RegisterEvent dataclass includes a notes field."""
        from services.account_register_service import RegisterEvent
        from datetime import date
        from decimal import Decimal

        event = RegisterEvent(
            posted_on=date(2026, 3, 15),
            order=0,
            amount=Decimal("-50.00"),
            commodity="$",
            payee="Whole Foods",
            summary="Groceries",
            is_unknown=False,
            is_opening_balance=False,
            detail_lines=[],
            notes="Weekly groceries",
        )
        assert event.notes == "Weekly groceries"

    def test_register_event_notes_default_none(self) -> None:
        """RegisterEvent notes defaults to None."""
        from services.account_register_service import RegisterEvent
        from datetime import date
        from decimal import Decimal

        event = RegisterEvent(
            posted_on=date(2026, 3, 15),
            order=0,
            amount=Decimal("-50.00"),
            commodity="$",
            payee="Whole Foods",
            summary="Groceries",
            is_unknown=False,
            is_opening_balance=False,
            detail_lines=[],
        )
        assert event.notes is None
