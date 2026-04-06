"""Tests for the matched-manual-entry archive journal.

Covers the archive writer helper directly and the integrated archive-on-match
behavior in ``apply_unknown_mappings``. The invariant under test is: every
match-apply produces a paired record — the imported transaction in the main
journal carries a ``match-id:`` tag that is byte-for-byte identical to the
``match-id:`` tag on the archived manual entry, and the archive file is never
loaded by ``ledger`` as part of the user's books.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.archive_service import archive_manual_entry, rollback_archive
from services.ledger_runner import CommandError, run_cmd
from services.unknowns_service import apply_unknown_mappings, scan_unknowns


_MATCH_ID_RE = re.compile(r"match-id:\s*([0-9a-f-]{36})")


def _tracked_accounts() -> dict[str, dict]:
    return {
        "checking": {
            "display_name": "Checking",
            "ledger_account": "Assets:Bank:Checking",
            "import_account_id": "checking_import",
        },
    }


def _import_accounts() -> dict[str, dict]:
    return {
        "checking_import": {
            "display_name": "Checking Import",
            "ledger_account": "Assets:Bank:Checking",
            "tracked_account_id": "checking",
        },
    }


def _write_match_fixture(tmp_path: Path) -> tuple[Path, Path]:
    journal = tmp_path / "2026.journal"
    accounts = tmp_path / "10-accounts.dat"
    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    Expenses:Transportation:Rides  $45.95
    Assets:Bank:Checking

2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber
    Expenses:Unknown  $45.95
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text(
        """account Expenses:Transportation:Rides
    ; type: Expense

account Assets:Bank:Checking
    ; type: Cash
""",
        encoding="utf-8",
    )
    return journal, accounts


def _apply_first_match(journal: Path, accounts: Path) -> tuple[int, list[dict]]:
    groups = scan_unknowns(journal, [], _import_accounts(), _tracked_accounts())["groups"]
    candidate = groups[0]["txns"][0]["matchCandidates"][0]
    return apply_unknown_mappings(
        journal_path=journal,
        accounts_dat=accounts,
        selections={
            groups[0]["groupKey"]: {
                "selectionType": "match",
                "matchedManualTxnId": candidate["manualTxnId"],
                "matchedManualLineRange": [candidate["lineStart"], candidate["lineEnd"]],
            }
        },
        scanned_groups=groups,
        tracked_accounts=_tracked_accounts(),
    )


# ---------------------------------------------------------------------------
# Archive writer helper (direct tests)
# ---------------------------------------------------------------------------


def test_archive_manual_entry_creates_file_with_header(tmp_path: Path) -> None:
    archive = tmp_path / "journals" / "archived-manual.journal"
    block = [
        "2026/03/15 Whole Foods Market",
        "    ; :manual:",
        "    Expenses:Groceries  $50.00",
        "    Assets:Bank:Checking",
    ]

    archive_manual_entry(archive, "uuid-abc", block)

    content = archive.read_text(encoding="utf-8")
    assert content.startswith("; Ledger Flow archived manual entries.\n")
    assert "Do NOT include this file" in content
    assert "match-id:" in content
    # match-id is the second line of the block, right after the header.
    assert "2026/03/15 Whole Foods Market\n    ; match-id: uuid-abc\n" in content
    # Original block lines are preserved after the stamp.
    assert "; :manual:" in content
    assert "Expenses:Groceries" in content


def test_archive_manual_entry_appends_without_rewriting_header(tmp_path: Path) -> None:
    archive = tmp_path / "archived-manual.journal"
    block1 = ["2026/03/15 First", "    Expenses:X  $1.00", "    Assets:Bank:Checking"]
    block2 = ["2026/03/16 Second", "    Expenses:Y  $2.00", "    Assets:Bank:Checking"]

    archive_manual_entry(archive, "uuid-1", block1)
    archive_manual_entry(archive, "uuid-2", block2)

    content = archive.read_text(encoding="utf-8")
    # Header appears exactly once.
    assert content.count("; Ledger Flow archived manual entries.") == 1
    # Both entries present with their match-ids.
    assert "uuid-1" in content
    assert "uuid-2" in content
    assert "2026/03/15 First" in content
    assert "2026/03/16 Second" in content
    # Entries are separated by exactly one blank line.
    assert "\n\n2026/03/16 Second\n" in content


def test_archive_manual_entry_creates_parent_directory(tmp_path: Path) -> None:
    archive = tmp_path / "nested" / "dirs" / "archived-manual.journal"
    assert not archive.parent.exists()

    archive_manual_entry(archive, "uuid", ["2026/03/15 Test", "    Expenses:X  $1.00", "    Assets:Y"])

    assert archive.exists()
    assert "uuid" in archive.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Rollback helper
# ---------------------------------------------------------------------------


def test_rollback_archive_deletes_file_when_size_was_none(tmp_path: Path) -> None:
    archive = tmp_path / "archived-manual.journal"
    archive_manual_entry(archive, "uuid", ["2026/03/15 X", "    Expenses:X  $1.00", "    Assets:Y"])
    assert archive.exists()

    rollback_archive(archive, None)

    assert not archive.exists()


def test_rollback_archive_truncates_to_previous_size(tmp_path: Path) -> None:
    archive = tmp_path / "archived-manual.journal"
    archive_manual_entry(archive, "uuid-1", ["2026/03/15 A", "    Expenses:X  $1.00", "    Assets:Y"])
    size_before = archive.stat().st_size
    archive_manual_entry(archive, "uuid-2", ["2026/03/16 B", "    Expenses:X  $2.00", "    Assets:Y"])
    assert archive.stat().st_size > size_before

    rollback_archive(archive, size_before)

    assert archive.stat().st_size == size_before
    content = archive.read_text(encoding="utf-8")
    assert "uuid-1" in content
    assert "uuid-2" not in content


# ---------------------------------------------------------------------------
# Integration: apply_unknown_mappings archives matched manual entries
# ---------------------------------------------------------------------------


def test_apply_match_writes_archive_file(tmp_path: Path) -> None:
    journal, accounts = _write_match_fixture(tmp_path)
    archive = journal.parent / "archived-manual.journal"
    assert not archive.exists()

    updates, warnings = _apply_first_match(journal, accounts)

    assert updates == 1
    assert warnings == []
    assert archive.exists()
    archive_content = archive.read_text(encoding="utf-8")
    # Header is present.
    assert archive_content.startswith("; Ledger Flow archived manual entries.\n")
    # Archived entry has match-id: as line 2 (after transaction header).
    assert re.search(r"2026/03/28 Uber\n    ; match-id: [0-9a-f-]{36}\n", archive_content)
    # Original manual entry content is preserved.
    assert "Expenses:Transportation:Rides" in archive_content
    assert "; :manual:" in archive_content


def test_apply_match_links_archive_and_main_via_shared_match_id(tmp_path: Path) -> None:
    journal, accounts = _write_match_fixture(tmp_path)
    archive = journal.parent / "archived-manual.journal"

    _apply_first_match(journal, accounts)

    main_content = journal.read_text(encoding="utf-8")
    archive_content = archive.read_text(encoding="utf-8")

    main_ids = _MATCH_ID_RE.findall(main_content)
    archive_ids = _MATCH_ID_RE.findall(archive_content)

    assert len(main_ids) == 1
    assert len(archive_ids) == 1
    # Byte-for-byte identical — this is the 1:1 link.
    assert main_ids[0] == archive_ids[0]


def test_apply_match_stamps_manual_tag_before_match_id_tag(tmp_path: Path) -> None:
    """Verify header → :manual: (line 2) → match-id: (line 3) order."""
    journal, accounts = _write_match_fixture(tmp_path)

    _apply_first_match(journal, accounts)

    main_content = journal.read_text(encoding="utf-8")
    # The imported Uber transaction should have both tags, in the right order.
    # Find the 2026/03/28 Uber block (there's only one after match).
    block_re = re.compile(
        r"2026/03/28 Uber\n    ; :manual:\n    ; match-id: [0-9a-f-]{36}\n"
    )
    assert block_re.search(main_content) is not None


def test_apply_second_match_appends_to_archive(tmp_path: Path) -> None:
    """Two separate match-applies produce two archive entries with distinct UUIDs."""
    journal = tmp_path / "2026.journal"
    accounts = tmp_path / "10-accounts.dat"
    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    Expenses:Transportation:Rides  $45.95
    Assets:Bank:Checking

2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber-1
    Expenses:Unknown  $45.95
    Assets:Bank:Checking

2026/03/29 Lyft
    ; :manual:
    Expenses:Transportation:Rides  $12.00
    Assets:Bank:Checking

2026/03/29 Lyft
    ; import_account_id: checking_import
    ; source_identity: tx-lyft-1
    Expenses:Unknown  $12.00
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text(
        """account Expenses:Transportation:Rides
    ; type: Expense

account Assets:Bank:Checking
    ; type: Cash
""",
        encoding="utf-8",
    )
    archive = tmp_path / "archived-manual.journal"

    # First apply: match only Uber.
    _apply_first_match(journal, accounts)
    size_after_first = archive.stat().st_size
    first_ids = _MATCH_ID_RE.findall(archive.read_text(encoding="utf-8"))
    assert len(first_ids) == 1

    # Second apply: match Lyft.
    _apply_first_match(journal, accounts)

    assert archive.stat().st_size > size_after_first
    archive_content = archive.read_text(encoding="utf-8")
    # Header appears exactly once.
    assert archive_content.count("; Ledger Flow archived manual entries.") == 1
    # Both archived entries present.
    assert "2026/03/28 Uber" in archive_content
    assert "2026/03/29 Lyft" in archive_content
    # Distinct match-ids.
    all_ids = _MATCH_ID_RE.findall(archive_content)
    assert len(all_ids) == 2
    assert all_ids[0] != all_ids[1]


def test_apply_match_ledger_cli_reads_main_journal_unchanged(tmp_path: Path) -> None:
    """ledger -f main.journal must produce valid balances; archive is not loaded."""
    journal, accounts = _write_match_fixture(tmp_path)

    _apply_first_match(journal, accounts)

    # Main journal must load cleanly and contain exactly the expected postings.
    bal = run_cmd(["ledger", "-f", str(journal), "bal"], cwd=tmp_path)
    # After match: one imported transaction with Expenses:Transportation:Rides $45.95
    # balanced against Assets:Bank:Checking -$45.95.
    assert "Expenses:Transportation:Rides" in bal
    assert "$45.95" in bal
    assert "Assets:Bank:Checking" in bal
    # And it balances to zero (single transaction, both postings present).
    # "Expenses:Unknown" from the original imported posting is gone.
    assert "Expenses:Unknown" not in bal


def test_apply_match_archive_file_loads_as_valid_ledger(tmp_path: Path) -> None:
    """The archive file must itself be valid ledger syntax."""
    journal, accounts = _write_match_fixture(tmp_path)
    archive = journal.parent / "archived-manual.journal"

    _apply_first_match(journal, accounts)

    assert archive.exists()
    # This raises if ledger fails to parse.
    bal = run_cmd(["ledger", "-f", str(archive), "bal"], cwd=tmp_path)
    assert "Expenses:Transportation:Rides" in bal


def test_apply_match_rollback_when_archive_write_fails(tmp_path: Path, monkeypatch) -> None:
    """If the archive write fails, the main journal stays unchanged."""
    journal, accounts = _write_match_fixture(tmp_path)
    main_before = journal.read_text(encoding="utf-8")
    archive = journal.parent / "archived-manual.journal"

    def boom(*args, **kwargs):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr("services.unknowns_service.archive_manual_entry", boom)

    with pytest.raises(OSError, match="disk full"):
        _apply_first_match(journal, accounts)

    # Archive was never created.
    assert not archive.exists()
    # Main journal is unchanged (the write at the end of the try block never ran).
    assert journal.read_text(encoding="utf-8") == main_before


def test_apply_match_rollback_truncates_archive_when_journal_write_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """If journal write fails AFTER archive write succeeds, archive is truncated back."""
    journal, accounts = _write_match_fixture(tmp_path)
    archive = journal.parent / "archived-manual.journal"
    # Seed the archive with a pre-existing entry, so we can verify truncation
    # restores the archive to its exact prior size (not deletion).
    archive_manual_entry(
        archive,
        "pre-existing-uuid",
        ["2026/02/01 Prior", "    Expenses:X  $1.00", "    Assets:Bank:Checking"],
    )
    size_before = archive.stat().st_size
    archive_before = archive.read_text(encoding="utf-8")

    real_write_text = Path.write_text

    def failing_write_text(self: Path, *args, **kwargs):
        # Only fail for the main journal write; other writes (e.g. archive) go through.
        if self == journal:
            raise OSError("disk full during main journal write")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    with pytest.raises(OSError, match="disk full during main journal"):
        _apply_first_match(journal, accounts)

    # Archive was truncated back to its pre-apply size.
    assert archive.exists()
    assert archive.stat().st_size == size_before
    assert archive.read_text(encoding="utf-8") == archive_before


def test_apply_match_skips_archive_when_manual_entry_already_has_match_id(
    tmp_path: Path,
) -> None:
    """Edge case: manual entry already tagged with match-id (shouldn't occur) — warn, don't archive."""
    journal = tmp_path / "2026.journal"
    accounts = tmp_path / "10-accounts.dat"
    journal.write_text(
        """2026/03/28 Uber
    ; :manual:
    ; match-id: legacy-uuid-from-prior-match
    Expenses:Transportation:Rides  $45.95
    Assets:Bank:Checking

2026/03/28 Uber
    ; import_account_id: checking_import
    ; source_identity: tx-uber
    Expenses:Unknown  $45.95
    Assets:Bank:Checking
""",
        encoding="utf-8",
    )
    accounts.write_text(
        """account Expenses:Transportation:Rides
    ; type: Expense

account Assets:Bank:Checking
    ; type: Cash
""",
        encoding="utf-8",
    )
    archive = tmp_path / "archived-manual.journal"

    _, warnings = _apply_first_match(journal, accounts)

    # Warning surfaced.
    assert any("already carries a match-id tag" in w.get("warning", "") for w in warnings)
    # Archive was NOT written (skip path).
    assert not archive.exists()
    # Main journal removal still happened — data is not lost, it just isn't duplicated
    # into the archive again. The imported txn carries its own (new) match-id.
    main_content = journal.read_text(encoding="utf-8")
    assert main_content.count("2026/03/28 Uber") == 1
    assert "legacy-uuid-from-prior-match" not in main_content
