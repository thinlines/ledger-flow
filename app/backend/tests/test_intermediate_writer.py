"""Unit tests for the intermediate CSV writer.

Every assertion is byte-level: ``write_intermediate(...).encode("utf-8") == b"..."``.
This ensures the writer's output is a stable regression target for the
import-identity SHA-256 hashes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from services.parsers.intermediate_writer import (
    INTERMEDIATE_FIELDNAMES,
    write_intermediate,
)
from services.parsers.types import LedgerTransaction, Posting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HEADER = b"date,code,description,amount,total,note\r\n"


def _txn(
    *,
    dt: date = date(2025, 6, 15),
    payee: str = "Test Payee",
    amount: Decimal = Decimal("-10.00"),
    commodity: str = "$",
    balance: Decimal | None = None,
    code: str | None = None,
    note: str | None = None,
    account: str = "Assets:Checking",
) -> LedgerTransaction:
    """Build a minimal LedgerTransaction for testing."""
    return LedgerTransaction(
        date=dt,
        payee=payee,
        postings=[Posting(account=account, amount=amount, commodity=commodity)],
        code=code,
        note=note,
        balance=balance,
    )


# ---------------------------------------------------------------------------
# INTERMEDIATE_FIELDNAMES sanity
# ---------------------------------------------------------------------------


def test_fieldnames_tuple():
    assert INTERMEDIATE_FIELDNAMES == (
        "date", "code", "description", "amount", "total", "note",
    )


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_iterable_produces_header_only():
    result = write_intermediate([])
    assert result.encode("utf-8") == HEADER


# ---------------------------------------------------------------------------
# Single-char commodity (prefix format): $
# ---------------------------------------------------------------------------


def test_single_char_commodity_negative_amount():
    txn = _txn(amount=Decimal("-1000.00"), commodity="$")
    expected = HEADER + b"2025/06/15,,Test Payee,$-1000.00,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_single_char_commodity_positive_amount():
    txn = _txn(amount=Decimal("50.00"), commodity="$")
    expected = HEADER + b"2025/06/15,,Test Payee,$50.00,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_single_char_commodity_amount_with_cents():
    txn = _txn(amount=Decimal("-1351.75"), commodity="$")
    expected = HEADER + b"2025/06/15,,Test Payee,$-1351.75,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


# ---------------------------------------------------------------------------
# Multi-char commodity (suffix format): CNY, USD
# ---------------------------------------------------------------------------


def test_multi_char_commodity_suffix_cny():
    txn = _txn(amount=Decimal("-9.90"), commodity="CNY")
    expected = HEADER + b"2025/06/15,,Test Payee,-9.90CNY,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_multi_char_commodity_suffix_usd():
    txn = _txn(amount=Decimal("-12.34"), commodity="USD")
    expected = HEADER + b"2025/06/15,,Test Payee,-12.34USD,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


# ---------------------------------------------------------------------------
# Balance / total column
# ---------------------------------------------------------------------------


def test_balance_none_emits_empty_total():
    txn = _txn(balance=None, commodity="$")
    expected = HEADER + b"2025/06/15,,Test Payee,$-10.00,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_balance_with_thousand_separator_prefix():
    """Balance >= 1000 with 1-char commodity → comma thousand sep, CSV-quoted."""
    txn = _txn(
        amount=Decimal("-100.00"),
        commodity="$",
        balance=Decimal("12345.67"),
    )
    expected = HEADER + b'2025/06/15,,Test Payee,$-100.00,"$12,345.67",\r\n'
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_balance_with_thousand_separator_suffix():
    """Balance >= 1000 with multi-char commodity → comma thousand sep, CSV-quoted."""
    txn = _txn(
        amount=Decimal("-9.90"),
        commodity="CNY",
        balance=Decimal("2568.44"),
    )
    expected = HEADER + b'2025/06/15,,Test Payee,-9.90CNY,"2,568.44CNY",\r\n'
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_balance_below_thousand_no_quoting():
    """Balance < 1000 → no comma, no CSV quoting needed."""
    txn = _txn(
        amount=Decimal("-7.80"),
        commodity="\u00a5",  # ¥
        balance=Decimal("-332.50"),
    )
    expected = HEADER + "2025/06/15,,Test Payee,¥-7.80,¥-332.50,\r\n".encode("utf-8")
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_negative_balance():
    """Negative balance renders with sign inside the formatted number."""
    txn = _txn(
        amount=Decimal("-5.00"),
        commodity="CNY",
        balance=Decimal("-2568.44"),
    )
    expected = HEADER + b'2025/06/15,,Test Payee,-5.00CNY,"-2,568.44CNY",\r\n'
    assert write_intermediate([txn]).encode("utf-8") == expected


# ---------------------------------------------------------------------------
# Code and note columns
# ---------------------------------------------------------------------------


def test_code_rendered():
    txn = _txn(code="282", commodity="$", amount=Decimal("-14000.00"))
    expected = HEADER + b"2025/06/15,282,Test Payee,$-14000.00,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_note_none_emits_empty():
    txn = _txn(note=None, commodity="$")
    expected = HEADER + b"2025/06/15,,Test Payee,$-10.00,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


def test_note_rendered():
    txn = _txn(note="CHECK # 281", commodity="$", amount=Decimal("-122.05"))
    expected = HEADER + b"2025/06/15,,Test Payee,$-122.05,,CHECK # 281\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


# ---------------------------------------------------------------------------
# Multiple transactions — ordering preserved
# ---------------------------------------------------------------------------


def test_multiple_transactions_ordering_preserved():
    txns = [
        _txn(dt=date(2025, 1, 1), payee="First", amount=Decimal("100.00")),
        _txn(dt=date(2025, 1, 2), payee="Second", amount=Decimal("-50.00")),
        _txn(dt=date(2025, 1, 3), payee="Third", amount=Decimal("25.50")),
    ]
    expected = (
        HEADER
        + b"2025/01/01,,First,$100.00,,\r\n"
        + b"2025/01/02,,Second,$-50.00,,\r\n"
        + b"2025/01/03,,Third,$25.50,,\r\n"
    )
    assert write_intermediate(txns).encode("utf-8") == expected


# ---------------------------------------------------------------------------
# Amount rounding (sub-cent precision)
# ---------------------------------------------------------------------------


def test_subcent_precision_rounded():
    """Amounts with > 2 decimal places are rounded to 2 via :.2f."""
    txn = _txn(amount=Decimal("10.005"), commodity="$")
    # Python :.2f uses ROUND_HALF_EVEN (banker's rounding): 10.005 → 10.00
    expected = HEADER + b"2025/06/15,,Test Payee,$10.00,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


# ---------------------------------------------------------------------------
# Empty description
# ---------------------------------------------------------------------------


def test_empty_description():
    txn = _txn(payee="")
    expected = HEADER + b"2025/06/15,,,$-10.00,,\r\n"
    assert write_intermediate([txn]).encode("utf-8") == expected


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_empty_commodity_raises():
    txn = LedgerTransaction(
        date=date(2025, 1, 1),
        payee="Bad",
        postings=[Posting(account="A", amount=Decimal("1"), commodity="")],
    )
    with pytest.raises(ValueError, match="commodity is required"):
        write_intermediate([txn])


def test_none_commodity_raises():
    txn = LedgerTransaction(
        date=date(2025, 1, 1),
        payee="Bad",
        postings=[Posting(account="A", amount=Decimal("1"), commodity=None)],
    )
    with pytest.raises(ValueError, match="commodity is required"):
        write_intermediate([txn])


def test_none_amount_raises():
    txn = LedgerTransaction(
        date=date(2025, 1, 1),
        payee="Bad",
        postings=[Posting(account="A", amount=None, commodity="$")],
    )
    with pytest.raises(ValueError, match="amount is required"):
        write_intermediate([txn])


def test_non_decimal_amount_raises():
    txn = LedgerTransaction(
        date=date(2025, 1, 1),
        payee="Bad",
        postings=[Posting(account="A", amount=10.0, commodity="$")],  # type: ignore[arg-type]
    )
    with pytest.raises(TypeError, match="must be Decimal"):
        write_intermediate([txn])


def test_no_postings_raises():
    txn = LedgerTransaction(
        date=date(2025, 1, 1),
        payee="Bad",
        postings=[],
    )
    with pytest.raises(ValueError, match="at least one posting"):
        write_intermediate([txn])


# ---------------------------------------------------------------------------
# No UTF-8 BOM
# ---------------------------------------------------------------------------


def test_no_utf8_bom():
    """Verify that the output does not start with a UTF-8 BOM."""
    result = write_intermediate([]).encode("utf-8")
    assert not result.startswith(b"\xef\xbb\xbf")


# ---------------------------------------------------------------------------
# CRLF line endings
# ---------------------------------------------------------------------------


def test_crlf_line_endings():
    result = write_intermediate([_txn()])
    # Every line ends with \r\n, and there are no bare \n
    assert "\r\n" in result
    # Remove all \r\n and check no stray \n remains
    assert "\n" not in result.replace("\r\n", "")
