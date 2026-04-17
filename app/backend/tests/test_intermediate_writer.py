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


# ===========================================================================
# Fixture cross-checks
#
# Hand-constructed LedgerTransactions derived from the first 2-3 rows of each
# Task 0 golden fixture. The writer must reproduce those exact bytes.
# ===========================================================================


class TestWellsFargoFixtureCrossCheck:
    """Cross-check against wells_fargo/expected_intermediate.csv rows 1-3.

    Wells Fargo: 1-char commodity ``$``, prefix format, balance is always None
    (no running balance in the WF source CSV).
    """

    def test_wf_row1_purchase(self):
        """Row 1: PURCHASE AUTHORIZED ... $-1000.00, no code, no total."""
        txn = LedgerTransaction(
            date=date(2026, 1, 2),
            payee="PURCHASE AUTHORIZED ON 12/31 PAYEE_002 P000000000000000 CARD 0000",
            postings=[Posting(account="Assets:WF:Checking", amount=Decimal("-1000.00"), commodity="$")],
            balance=None,
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = b"2026/01/02,,PURCHASE AUTHORIZED ON 12/31 PAYEE_002 P000000000000000 CARD 0000,$-1000.00,,\r\n"
        assert result == HEADER + expected_row

    def test_wf_row2_check(self):
        """Row 2: CHECK # 282, code=282, $-14000.00."""
        txn = LedgerTransaction(
            date=date(2026, 1, 5),
            payee="CHECK # 282",
            postings=[Posting(account="Assets:WF:Checking", amount=Decimal("-14000.00"), commodity="$")],
            code="282",
            balance=None,
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = b"2026/01/05,282,CHECK # 282,$-14000.00,,\r\n"
        assert result == HEADER + expected_row

    def test_wf_row3_transfer(self):
        """Row 3: ONLINE TRANSFER, code=IB0WD9SHT2, $-1351.75."""
        txn = LedgerTransaction(
            date=date(2026, 1, 7),
            payee="ONLINE TRANSFER REF #IB0WD9SHT2 TO CREDIT CARD XXXXXXXXXXXX0000 ON 01/07/26",
            postings=[Posting(account="Assets:WF:Checking", amount=Decimal("-1351.75"), commodity="$")],
            code="IB0WD9SHT2",
            balance=None,
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = b"2026/01/07,IB0WD9SHT2,ONLINE TRANSFER REF #IB0WD9SHT2 TO CREDIT CARD XXXXXXXXXXXX0000 ON 01/07/26,$-1351.75,,\r\n"
        assert result == HEADER + expected_row


class TestAlipayFixtureCrossCheck:
    """Cross-check against alipay/expected_intermediate.csv rows 1-3.

    Alipay: 1-char commodity ``\u00a5`` (yen sign), prefix format, balance is populated.
    """

    def test_alipay_row1(self):
        txn = LedgerTransaction(
            date=date(2024, 12, 21),
            payee="\u652f\u4ed8-PAYEE_005 \u8d2d\u7269",
            postings=[Posting(account="Assets:Alipay", amount=Decimal("-7.80"), commodity="\u00a5")],
            code="ORD_000012",
            balance=Decimal("-332.50"),
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = "2024/12/21,ORD_000012,\u652f\u4ed8-PAYEE_005 \u8d2d\u7269,\u00a5-7.80,\u00a5-332.50,\r\n".encode("utf-8")
        assert result == HEADER + expected_row

    def test_alipay_row2(self):
        txn = LedgerTransaction(
            date=date(2024, 12, 22),
            payee="\u652f\u4ed8-PAYEE_008 \u6d88\u8d39",
            postings=[Posting(account="Assets:Alipay", amount=Decimal("-12.00"), commodity="\u00a5")],
            code="ORD_000011",
            balance=Decimal("-344.50"),
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = "2024/12/22,ORD_000011,\u652f\u4ed8-PAYEE_008 \u6d88\u8d39,\u00a5-12.00,\u00a5-344.50,\r\n".encode("utf-8")
        assert result == HEADER + expected_row

    def test_alipay_row_positive_amount(self):
        """Row 11 (red packet): positive amount, negative balance."""
        txn = LedgerTransaction(
            date=date(2024, 12, 27),
            payee="PAYEE_003 \u7ea2\u5305",
            postings=[Posting(account="Assets:Alipay", amount=Decimal("0.50"), commodity="\u00a5")],
            code="ORD_000003",
            balance=Decimal("-410.00"),
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = "2024/12/27,ORD_000003,PAYEE_003 \u7ea2\u5305,\u00a50.50,\u00a5-410.00,\r\n".encode("utf-8")
        assert result == HEADER + expected_row


class TestICBCFixtureCrossCheck:
    """Cross-check against icbc/expected_intermediate.csv rows 1-3.

    ICBC: multi-char commodity ``CNY`` / ``USD``, suffix format, balance with
    thousand separators and CSV quoting.
    """

    def test_icbc_row1_cny_negative(self):
        """Row 1: -9.90CNY amount, 2,568.44CNY total (quoted)."""
        txn = LedgerTransaction(
            date=date(2025, 1, 1),
            payee="\u652f\u4ed8\u5b9d-PAYEE_005 PAYEE_005",
            postings=[Posting(account="Assets:ICBC", amount=Decimal("-9.90"), commodity="CNY")],
            code="\u6d88\u8d39",
            balance=Decimal("2568.44"),
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = '2025/01/01,\u6d88\u8d39,\u652f\u4ed8\u5b9d-PAYEE_005 PAYEE_005,-9.90CNY,"2,568.44CNY",\r\n'.encode("utf-8")
        assert result == HEADER + expected_row

    def test_icbc_row2_cny_positive(self):
        """Row 2: 25.00CNY refund, 2,558.54CNY total (quoted)."""
        txn = LedgerTransaction(
            date=date(2025, 1, 2),
            payee="PAYEE_004 PAYEE_004",
            postings=[Posting(account="Assets:ICBC", amount=Decimal("25.00"), commodity="CNY")],
            code="\u9000\u6b3e",
            balance=Decimal("2558.54"),
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = '2025/01/02,\u9000\u6b3e,PAYEE_004 PAYEE_004,25.00CNY,"2,558.54CNY",\r\n'.encode("utf-8")
        assert result == HEADER + expected_row

    def test_icbc_row_usd(self):
        """Row 7: USD transaction — suffix format, total below 1000 (no quoting)."""
        txn = LedgerTransaction(
            date=date(2025, 1, 4),
            payee="PAYEE_USD_001 PAYEE_USD_001",
            postings=[Posting(account="Assets:ICBC", amount=Decimal("-12.34"), commodity="USD")],
            code="\u6d88\u8d39",
            balance=Decimal("500.00"),
        )
        result = write_intermediate([txn]).encode("utf-8")
        expected_row = "2025/01/04,\u6d88\u8d39,PAYEE_USD_001 PAYEE_USD_001,-12.34USD,500.00USD,\r\n".encode("utf-8")
        assert result == HEADER + expected_row
