"""Posting line primitives agree on recognition and preserve posting text."""

import pytest
from services.journal_syntax import posting_account, rewrite_posting_account


@pytest.mark.parametrize("line", [
    "",
    "    ",
    "2026-03-15 * Whole Foods",
    "    ; a comment",
    "    ; notes: preserve  two spaces",
    "    ; :manual:",
])
def test_non_postings_are_rejected_by_both_primitives(line):
    assert posting_account(line) is None
    with pytest.raises(ValueError, match="non-posting"):
        rewrite_posting_account(line, "Expenses:Groceries")


@pytest.mark.parametrize("line, expected", [
    ("    Expenses:Unknown  USD 30.00 = USD 50.00 ; comment",
     "    Expenses:Groceries  USD 30.00 = USD 50.00 ; comment"),
    ("\tExpenses:Unknown\t$30.00", "\tExpenses:Groceries\t$30.00"),
    ("    Expenses:Unknown", "    Expenses:Groceries"),
])
def test_rewrite_preserves_the_rest_of_the_posting(line, expected):
    assert posting_account(line) == "Expenses:Unknown"
    assert rewrite_posting_account(line, "Expenses:Groceries") == expected
    assert rewrite_posting_account(line, "Expenses:Unknown") == line
