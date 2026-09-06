"""Domain predicates over parsed transactions."""
from datetime import date
from decimal import Decimal

import pytest

from services.journal_query_service import ParsedTransaction, Posting, is_uncategorized


def _txn(*accounts: str) -> ParsedTransaction:
    return ParsedTransaction(
        posted_on=date(2026, 1, 1),
        payee='Somewhere',
        postings=[Posting(account=account, amount=Decimal(10)) for account in accounts],
        metadata={},
    )


@pytest.mark.parametrize('accounts', [
    ('Expenses:Unknown', 'Assets:Bank'),
    ('Assets:Bank', 'Expenses:Unknown'),
    ('Expenses:Rent', 'Expenses:Unknown'),
    # Placeholders are matched case-insensitively and under any parent.
    ('expenses:unknown', 'Assets:Bank'),
    ('Income:Unknown', 'Assets:Bank'),
])
def test_transactions_awaiting_a_category_are_uncategorized(accounts):
    assert is_uncategorized(_txn(*accounts))


@pytest.mark.parametrize('accounts', [
    ('Expenses:Food', 'Assets:Bank'),
    ('Assets:Bank', 'Assets:Savings'),
    # A real account merely containing the word is categorized.
    ('Expenses:Unknown Subscriptions', 'Assets:Bank'),
    ('Expenses:Unknowns', 'Assets:Bank'),
])
def test_fully_categorized_transactions_are_not_uncategorized(accounts):
    assert not is_uncategorized(_txn(*accounts))


def test_a_transaction_without_postings_is_not_uncategorized():
    assert not is_uncategorized(_txn())
