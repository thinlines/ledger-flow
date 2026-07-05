"""Tests for the journal-block helpers behind the transaction actions.

The action endpoints themselves are covered at the endpoint seam in
``test_transaction_actions_by_id.py`` on the ``(lf_txn_id, raw_block_hash)``
contract; the inline reimplementations of the old positional endpoint logic
that used to live here died with it.
"""

from __future__ import annotations

from services.journal_block_service import find_transaction_block


SAMPLE_JOURNAL = """\
2026-03-10 * Opening balance
    Assets:Bank:Checking  $1000.00
    Equity:Opening-Balances

2026-03-15 * Whole Foods
    ; lf_source_identity: abc123
    Assets:Bank:Checking  -$50.00
    Expenses:Groceries  $50.00

2026-03-20 * Target
    ; lf_source_identity: def456
    Assets:Bank:Checking  -$30.00
    Expenses:Unknown  $30.00
"""


class TestFindTransactionBlock:
    def test_finds_middle_block(self) -> None:
        lines = SAMPLE_JOURNAL.splitlines()
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

    def test_trims_trailing_blank_lines(self) -> None:
        lines = ["2026-03-15 * A", "    posting", "", "", "2026-03-20 * B", "    posting"]
        start, end = find_transaction_block(lines, 0)
        assert (start, end) == (0, 2)
