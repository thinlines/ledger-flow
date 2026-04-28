"""Behavioural tests for the one-shot date-format migration script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "Scripts"
    / "migrate_journal_dates_to_iso.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("migrate_journal_dates_to_iso", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "journals").mkdir(parents=True)
    (workspace / "opening").mkdir(parents=True)
    return workspace


def test_migrates_slash_headers_to_iso(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    journal = workspace / "journals" / "2026.journal"
    journal.write_text(
        "; pre-existing comment with 2026/01/02 date inline\n"
        "2026/01/02 Starbucks\n"
        "    ; CSV: 2026/01/02,Starbucks,4.50\n"
        "    Expenses:Coffee  $4.50\n"
        "    Assets:Bank:Checking\n"
        "\n"
        "2026/01/05 * Whole Foods\n"
        "    Expenses:Groceries  $50.00\n"
        "    Assets:Bank:Checking\n",
        encoding="utf-8",
    )

    module = _load_module()
    rc = module.main([str(SCRIPT_PATH), str(workspace)])

    assert rc == 0
    text = journal.read_text(encoding="utf-8")
    assert "2026-01-02 Starbucks" in text
    assert "2026-01-05 * Whole Foods" in text
    # Inline metadata comments untouched.
    assert "; pre-existing comment with 2026/01/02 date inline" in text
    assert "    ; CSV: 2026/01/02,Starbucks,4.50" in text


def test_writes_backup_before_mutation(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    journal = workspace / "journals" / "2026.journal"
    original = "2026/01/02 Starbucks\n    Expenses:Coffee  $4.50\n    Assets:Bank:Checking\n"
    journal.write_text(original, encoding="utf-8")

    module = _load_module()
    rc = module.main([str(SCRIPT_PATH), str(workspace)])

    assert rc == 0
    backups = list((workspace / "journals").glob("2026.journal.iso-migration.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original


def test_idempotent_second_run(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    journal = workspace / "journals" / "2026.journal"
    journal.write_text(
        "2026/01/02 Starbucks\n"
        "    Expenses:Coffee  $4.50\n"
        "    Assets:Bank:Checking\n",
        encoding="utf-8",
    )

    module = _load_module()
    assert module.main([str(SCRIPT_PATH), str(workspace)]) == 0
    first_pass = journal.read_text(encoding="utf-8")
    backups_after_first = sorted((workspace / "journals").glob("*.iso-migration.bak.*"))

    # Second run should be a no-op: no new backup, no rewrite.
    assert module.main([str(SCRIPT_PATH), str(workspace)]) == 0
    second_pass = journal.read_text(encoding="utf-8")
    backups_after_second = sorted((workspace / "journals").glob("*.iso-migration.bak.*"))

    assert first_pass == second_pass
    assert backups_after_first == backups_after_second


def test_skips_bak_files(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    bak = workspace / "journals" / "2026.journal.import.bak.20260101000000"
    bak.write_text(
        "2026/01/02 Starbucks\n    Expenses:Coffee  $4.50\n    Assets:Bank:Checking\n",
        encoding="utf-8",
    )
    original_bytes = bak.read_bytes()
    original_mtime = bak.stat().st_mtime

    module = _load_module()
    rc = module.main([str(SCRIPT_PATH), str(workspace)])

    assert rc == 0
    assert bak.read_bytes() == original_bytes
    assert bak.stat().st_mtime == pytest.approx(original_mtime, abs=1)


def test_migrates_opening_journals(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    target = workspace / "opening" / "checking.journal"
    target.write_text(
        "2026/01/01 Opening balance\n    Assets:Bank:Checking  $1000.00\n    Equity:Opening-Balances\n",
        encoding="utf-8",
    )

    module = _load_module()
    rc = module.main([str(SCRIPT_PATH), str(workspace)])

    assert rc == 0
    assert target.read_text(encoding="utf-8").startswith("2026-01-01 Opening balance")


def test_anchors_match_to_line_start(tmp_path: Path) -> None:
    """Mid-line slash dates inside a metadata comment must be untouched."""
    workspace = _make_workspace(tmp_path)
    journal = workspace / "journals" / "2026.journal"
    journal.write_text(
        "2026/01/02 Header\n"
        "    ; metadata: see 2026/01/02 in CSV\n"
        "    ; CSV: 2026/01/02,foo,bar\n"
        "    Expenses:Coffee  $4.50\n"
        "    Assets:Bank:Checking\n",
        encoding="utf-8",
    )

    module = _load_module()
    module.main([str(SCRIPT_PATH), str(workspace)])

    text = journal.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "2026-01-02 Header"
    assert "; metadata: see 2026/01/02 in CSV" in text
    assert "; CSV: 2026/01/02,foo,bar" in text
