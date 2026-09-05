import pytest

from services.commodity_service import canonicalize_base_currency_amount


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
