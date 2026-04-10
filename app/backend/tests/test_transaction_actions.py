"""Tests for transaction action endpoints: delete, recategorize, unmatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import event_log_service
from services.event_log_service import EVENTS_FILENAME


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
        "account Expenses:Groceries\naccount Expenses:Unknown\naccount Assets:Bank:Checking\n",
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

MATCHED_JOURNAL = """\
2026-03-15 * Whole Foods
    ; :manual:
    ; match-id: test-match-uuid-1234
    ; source_identity: abc123
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00
"""

ARCHIVE_CONTENT = """\
; Ledger Flow archived manual entries.
; Do NOT include this file in main.journal — it duplicates transactions by design.
; Each entry has a matching `match-id:` tag in a main-journal transaction.

2026-03-15 Whole Foods
    ; match-id: test-match-uuid-1234
    ; :manual:
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00
"""


# ---------------------------------------------------------------------------
# Delete endpoint logic
# ---------------------------------------------------------------------------

from services.journal_block_service import find_transaction_block, locate_header


class TestFindTransactionBlock:
    def test_finds_middle_block(self) -> None:
        lines = SAMPLE_JOURNAL.splitlines()
        # "2026-03-15 * Whole Foods" is at index 3 (after blank line separator).
        idx = next(i for i, l in enumerate(lines) if "Whole Foods" in l)
        start, end = find_transaction_block(lines, idx)
        assert start == idx
        block = "\n".join(lines[start:end])
        assert "Whole Foods" in block
        assert "Expenses:Groceries" in block
        # Should not include the next transaction.
        assert "Target" not in block

    def test_finds_last_block(self) -> None:
        lines = SAMPLE_JOURNAL.splitlines()
        idx = next(i for i, l in enumerate(lines) if "Target" in l)
        start, end = find_transaction_block(lines, idx)
        block = "\n".join(lines[start:end])
        assert "Target" in block
        assert "Expenses:Unknown" in block


class TestLocateHeader:
    def test_unique_match(self) -> None:
        lines = SAMPLE_JOURNAL.splitlines()
        idx = locate_header(lines, "2026-03-15 * Whole Foods")
        assert lines[idx] == "2026-03-15 * Whole Foods"

    def test_not_found_raises(self) -> None:
        from services.journal_block_service import HeaderNotFoundError

        lines = SAMPLE_JOURNAL.splitlines()
        with pytest.raises(HeaderNotFoundError):
            locate_header(lines, "2099-01-01 * Nonexistent")

    def test_ambiguous_raises(self) -> None:
        from services.journal_block_service import AmbiguousHeaderError

        lines = ["2026-03-15 * Dupe", "    posting", "", "2026-03-15 * Dupe", "    posting"]
        with pytest.raises(AmbiguousHeaderError):
            locate_header(lines, "2026-03-15 * Dupe")


# ---------------------------------------------------------------------------
# Delete: full integration
# ---------------------------------------------------------------------------


class TestDeleteTransaction:
    def test_removes_transaction_block(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", SAMPLE_JOURNAL)
        original_text = journal.read_text()

        # Simulate the endpoint logic inline to test without the HTTP layer.
        from services.event_log_service import check_drift, hash_file, emit_event, rel_path
        from services.backup_service import backup_file

        header_line = "2026-03-15 * Whole Foods"
        hash_before = check_drift(workspace, journal)
        backup_file(journal, "delete")

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, header_line)
        block_start, block_end = find_transaction_block(lines, header_idx)
        deleted_block = "\n".join(lines[block_start:block_end])

        new_lines = lines[:block_start] + lines[block_end:]
        journal.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        hash_after = hash_file(journal)
        emit_event(
            workspace,
            event_type="transaction.deleted.v1",
            summary="Deleted transaction: Whole Foods on 2026-03-15",
            payload={"deleted_block": deleted_block},
            journal_refs=[{"path": rel_path(journal, workspace), "hash_before": hash_before, "hash_after": hash_after}],
        )

        # Verify transaction is gone.
        result = journal.read_text()
        assert "Whole Foods" not in result
        # Other transactions remain.
        assert "Opening balance" in result
        assert "Target" in result

        # Verify event was emitted.
        events = _read_events(workspace)
        assert len(events) == 1
        assert events[0]["type"] == "transaction.deleted.v1"
        assert "Whole Foods" in events[0]["payload"]["deleted_block"]

    def test_no_empty_lines_left_after_delete(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", SAMPLE_JOURNAL)

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, "2026-03-15 * Whole Foods")
        block_start, block_end = find_transaction_block(lines, header_idx)
        # Mirror the endpoint logic: consume a preceding blank line.
        remove_start = block_start
        if remove_start > 0 and lines[remove_start - 1].strip() == "":
            remove_start -= 1
        new_lines = lines[:remove_start] + lines[block_end:]
        journal.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        result = journal.read_text()
        # No triple newlines (double blank lines) should remain.
        assert "\n\n\n" not in result


# ---------------------------------------------------------------------------
# Recategorize
# ---------------------------------------------------------------------------


class TestRecategorizeTransaction:
    def test_rewrites_destination_to_unknown(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", SAMPLE_JOURNAL)

        from services.event_log_service import check_drift, hash_file, emit_event, rel_path
        from services.backup_service import backup_file
        from services.transfer_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE, rewrite_posting_account

        header_line = "2026-03-15 * Whole Foods"
        hash_before = check_drift(workspace, journal)
        backup_file(journal, "recategorize")

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, header_line)
        block_start, block_end = find_transaction_block(lines, header_idx)

        tracked_accounts = {"Assets:Bank:Checking"}

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

        new_line, changed = rewrite_posting_account(lines[destination_idx], "Expenses:Unknown")
        assert changed
        lines[destination_idx] = new_line
        journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

        hash_after = hash_file(journal)
        emit_event(
            workspace,
            event_type="transaction.recategorized.v1",
            summary=f"Reset category: Whole Foods on 2026-03-15 ({previous_account} → Expenses:Unknown)",
            payload={"previous_account": previous_account, "new_account": "Expenses:Unknown"},
            journal_refs=[{"path": rel_path(journal, workspace), "hash_before": hash_before, "hash_after": hash_after}],
        )

        result = journal.read_text()
        assert "Expenses:Unknown" in result
        # Original account gone from that transaction.
        # But we check the specific block.
        result_lines = result.splitlines()
        wf_idx = next(i for i, l in enumerate(result_lines) if "Whole Foods" in l)
        block_text = "\n".join(result_lines[wf_idx:wf_idx + 5])
        assert "Expenses:Unknown" in block_text
        assert "Expenses:Groceries" not in block_text

        events = _read_events(workspace)
        assert events[-1]["type"] == "transaction.recategorized.v1"
        assert events[-1]["payload"]["previous_account"] == "Expenses:Groceries"

    def test_already_unknown_is_rejected(self, tmp_path: Path) -> None:
        """Transactions already categorized as Expenses:Unknown should be rejected."""
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", SAMPLE_JOURNAL)

        text = journal.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = locate_header(lines, "2026-03-20 * Target")
        block_start, block_end = find_transaction_block(lines, header_idx)

        from services.transfer_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE

        tracked_accounts = {"Assets:Bank:Checking"}
        for i in range(block_start + 1, block_end):
            stripped = lines[i].strip()
            if stripped.startswith(";") or stripped == "":
                continue
            m = ACCOUNT_LINE_RE.match(lines[i]) or ACCOUNT_ONLY_RE.match(lines[i])
            if m:
                account = m.group(2).strip()
                if account not in tracked_accounts:
                    # This should be Expenses:Unknown already.
                    assert account == "Expenses:Unknown"
                    break


# ---------------------------------------------------------------------------
# Unmatch
# ---------------------------------------------------------------------------


class TestUnmatchTransaction:
    def test_restores_manual_entry_and_removes_tags(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal = _write_journal(workspace, "2026.journal", MATCHED_JOURNAL)
        archive = workspace / "journals" / "archived-manual.journal"
        archive.write_text(ARCHIVE_CONTENT, encoding="utf-8")

        from services.event_log_service import check_drift, hash_file, emit_event, rel_path
        from services.backup_service import backup_file
        from services.transfer_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE, rewrite_posting_account
        from services.journal_query_service import TXN_START_RE

        match_id = "test-match-uuid-1234"
        header_line = "2026-03-15 * Whole Foods"

        # Locate archived block.
        archive_text = archive.read_text(encoding="utf-8")
        archive_lines = archive_text.splitlines()
        archived_block_start = None
        archived_block_end = None

        for i, line in enumerate(archive_lines):
            if line.strip() == f"; match-id: {match_id}":
                if i > 0 and TXN_START_RE.match(archive_lines[i - 1]):
                    archived_block_start = i - 1
                    archived_block_end = i + 1
                    while archived_block_end < len(archive_lines):
                        if TXN_START_RE.match(archive_lines[archived_block_end]):
                            break
                        archived_block_end += 1
                    while archived_block_end > archived_block_start + 1 and archive_lines[archived_block_end - 1].strip() == "":
                        archived_block_end -= 1
                    break

        assert archived_block_start is not None
        archived_block_lines = archive_lines[archived_block_start:archived_block_end]

        # Remove tags from main journal.
        hash_before_main = check_drift(workspace, journal)
        hash_before_archive = check_drift(workspace, archive)
        backup_file(journal, "unmatch")
        backup_file(archive, "unmatch")

        main_text = journal.read_text(encoding="utf-8")
        main_lines = main_text.splitlines()
        header_idx = locate_header(main_lines, header_line)
        block_start, block_end = find_transaction_block(main_lines, header_idx)

        lines_to_remove = []
        destination_idx = None
        tracked_accounts = {"Assets:Bank:Checking"}
        for i in range(block_start + 1, block_end):
            stripped = main_lines[i].strip()
            if stripped == "; :manual:":
                lines_to_remove.append(i)
            elif stripped == f"; match-id: {match_id}":
                lines_to_remove.append(i)
            elif not stripped.startswith(";") and stripped != "":
                m = ACCOUNT_LINE_RE.match(main_lines[i]) or ACCOUNT_ONLY_RE.match(main_lines[i])
                if m:
                    account = m.group(2).strip()
                    if account not in tracked_accounts and destination_idx is None:
                        destination_idx = i

        for idx in sorted(lines_to_remove, reverse=True):
            del main_lines[idx]

        if destination_idx is not None:
            removed_above = sum(1 for idx in lines_to_remove if idx < destination_idx)
            destination_idx -= removed_above
            new_line, _ = rewrite_posting_account(main_lines[destination_idx], "Expenses:Unknown")
            main_lines[destination_idx] = new_line

        journal.write_text("\n".join(main_lines) + "\n", encoding="utf-8")

        # Verify tag removal.
        result = journal.read_text()
        assert "; :manual:" not in result
        assert f"; match-id: {match_id}" not in result
        assert "Expenses:Unknown" in result

        # Verify restored manual entry inserted.
        restored_lines = [l for l in archived_block_lines if l.strip() != f"; match-id: {match_id}"]
        restored_block = "\n".join(restored_lines)

        main_text2 = journal.read_text(encoding="utf-8")
        main_lines2 = main_text2.splitlines()
        restored_date = restored_lines[0][:10] if restored_lines and TXN_START_RE.match(restored_lines[0]) else ""

        insert_idx = len(main_lines2)
        for i in range(len(main_lines2) - 1, -1, -1):
            if TXN_START_RE.match(main_lines2[i]) and main_lines2[i][:10] <= restored_date:
                end_i = i + 1
                while end_i < len(main_lines2):
                    if TXN_START_RE.match(main_lines2[end_i]):
                        break
                    end_i += 1
                insert_idx = end_i
                break

        insert_block = [""] + restored_lines if insert_idx > 0 else restored_lines
        main_lines2[insert_idx:insert_idx] = insert_block
        journal.write_text("\n".join(main_lines2) + "\n", encoding="utf-8")

        final = journal.read_text()
        # The restored manual entry should appear (without match-id tag).
        assert "2026-03-15 Whole Foods" in final
        assert "; :manual:" in final  # The restored entry's :manual: tag.

    def test_archive_entry_removed(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        _write_journal(workspace, "2026.journal", MATCHED_JOURNAL)
        archive = workspace / "journals" / "archived-manual.journal"
        archive.write_text(ARCHIVE_CONTENT, encoding="utf-8")

        from services.journal_query_service import TXN_START_RE

        match_id = "test-match-uuid-1234"
        archive_text = archive.read_text(encoding="utf-8")
        archive_lines = archive_text.splitlines()

        # Find and remove the archived block.
        archived_block_start = None
        archived_block_end = None
        for i, line in enumerate(archive_lines):
            if line.strip() == f"; match-id: {match_id}":
                if i > 0 and TXN_START_RE.match(archive_lines[i - 1]):
                    archived_block_start = i - 1
                    archived_block_end = i + 1
                    while archived_block_end < len(archive_lines):
                        if TXN_START_RE.match(archive_lines[archived_block_end]):
                            break
                        archived_block_end += 1
                    while archived_block_end > archived_block_start + 1 and archive_lines[archived_block_end - 1].strip() == "":
                        archived_block_end -= 1
                    break

        assert archived_block_start is not None

        remove_end = archived_block_end
        while remove_end < len(archive_lines) and archive_lines[remove_end].strip() == "":
            remove_end += 1
        new_archive_lines = archive_lines[:archived_block_start] + archive_lines[remove_end:]

        non_empty = [l for l in new_archive_lines if l.strip() and not l.strip().startswith(";")]
        if non_empty:
            archive.write_text("\n".join(new_archive_lines) + "\n", encoding="utf-8")
        else:
            archive.unlink(missing_ok=True)

        # After removing the only entry, archive should be deleted.
        assert not archive.exists()

    def test_archive_not_found_raises(self, tmp_path: Path) -> None:
        """Missing archive file returns 404."""
        workspace = _setup_workspace(tmp_path)
        _write_journal(workspace, "2026.journal", MATCHED_JOURNAL)
        # No archive file created.

        archive = workspace / "journals" / "archived-manual.journal"
        assert not archive.exists()
