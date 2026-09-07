from decimal import Decimal

import pytest

from services.commodity import canonicalize_base_currency_amount, format_currency_amount


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal("1234.5"), "usd", "USD 1234.50"),
        (Decimal("-9.9"), "EUR", "EUR -9.90"),
        (Decimal(0), " GBP ", "GBP 0.00"),
    ],
)
def test_format_currency_amount_uses_canonical_journal_form(
    amount: Decimal, currency: str, expected: str
) -> None:
    assert format_currency_amount(amount, currency) == expected


def test_format_currency_amount_requires_currency() -> None:
    with pytest.raises(ValueError, match="Currency is required"):
        format_currency_amount(Decimal(1), " ")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,200", "USD 1200"),
        ("1200 USD", "USD 1200"),
        ("USD 1200.0", "USD 1200.0"),
        ("USD 1.234567", "USD 1.234567"),
    ],
)
def test_canonicalize_base_currency_amount_uses_shared_renderer(
    raw: str, expected: str
) -> None:
    assert canonicalize_base_currency_amount(raw, "USD") == expected
