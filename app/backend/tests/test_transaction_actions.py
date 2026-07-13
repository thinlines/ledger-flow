"""Tests for stable-ID transaction block location."""

from services.journal_block_service import locate_block_by_id


SAMPLE_JOURNAL = """\
2026-03-10 * Opening balance
    ; lf_txn_id: txn_opening
    Assets:Bank:Checking  $1000.00
    Equity:Opening-Balances

2026-03-15 * Whole Foods
    ; lf_txn_id: txn_groceries
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00

2026-03-20 * Target
    ; lf_txn_id: txn_target
    Assets:Bank:Checking  -$30.00
    Expenses:Unknown  $30.00
"""


def test_locates_middle_block_by_id() -> None:
    lines = SAMPLE_JOURNAL.splitlines()

    located = locate_block_by_id(lines, "txn_groceries")

    assert located is not None
    start, end = located
    block = "\n".join(lines[start:end])
    assert "Whole Foods" in block
    assert "Target" not in block


def test_locates_last_block_by_id() -> None:
    lines = SAMPLE_JOURNAL.splitlines()

    located = locate_block_by_id(lines, "txn_target")

    assert located is not None
    start, end = located
    assert "Target" in "\n".join(lines[start:end])


def test_trims_trailing_blank_lines() -> None:
    lines = SAMPLE_JOURNAL.splitlines() + ["", ""]

    located = locate_block_by_id(lines, "txn_target")

    assert located is not None
    _, end = located
    assert lines[end - 1] == "    Expenses:Unknown  $30.00"
