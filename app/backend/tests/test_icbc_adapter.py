"""Tests for the ICBC adapter.

Unit tests cover currency detection, amount sign branches, description
concatenation edge cases, and balance parsing. The end-to-end test asserts
byte-exact equality with the Task 0 fixture.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "csv_snapshots"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    *,
    date: str = "2025-01-01",
    code: str = "消费",
    detail: str = "",
    location: str = "SHOP_A",
    country: str = "CHN",
    cash_remit: str = "钞",
    txn_income: str = "",
    txn_expense: str = "",
    txn_currency: str = "-",
    book_income: str = "",
    book_expense: str = "",
    book_currency: str = "人民币",
    balance: str = "1000.00",
    counterparty: str = "PAYEE_A",
    counter_acct: str = "",
) -> str:
    """Build a single ICBC CSV data row (no header).

    Values are padded with trailing spaces + tab to mimic the real ICBC
    export format, which the adapter handles via .strip().
    """
    fields = [
        date,
        code,
        detail,
        location,
        country,
        cash_remit,
        txn_income,
        txn_expense,
        txn_currency,
        book_income,
        book_expense,
        book_currency,
        balance,
        counterparty,
        counter_acct,
    ]
    # Mimic ICBC's format: first field unquoted with trailing tab,
    # remaining fields quoted with trailing whitespace+tab.
    parts = [fields[0] + "\t"]
    for f in fields[1:]:
        parts.append('"' + f + "\t" + '"')
    return ",".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------


class TestIcbcAdapterParse:
    """Exercise IcbcAdapter.parse() with constructed CSV text."""

    @pytest.fixture()
    def adapter(self):
        from services.parsers.implementations.icbc import IcbcAdapter
        return IcbcAdapter()

    def test_cny_expense(self, adapter):
        """CNY expense row: amount is negated, currency is CNY."""
        text = _make_row(book_expense="9.90", book_currency="人民币", balance="2568.44")
        records = list(adapter.parse(text))
        assert len(records) == 1
        r = records[0]
        assert r.date == date(2025, 1, 1)
        assert r.amount == Decimal("-9.90")
        assert r.currency == "CNY"
        assert r.code == "消费"
        assert r.balance == Decimal("2568.44")
        assert r.note is None

    def test_usd_expense(self, adapter):
        """USD expense row: currency detected from 美元."""
        text = _make_row(
            book_expense="12.34",
            book_currency="美元",
            balance="500.00",
            location="PAYEE_USD_001",
            counterparty="PAYEE_USD_001",
        )
        records = list(adapter.parse(text))
        r = records[0]
        assert r.amount == Decimal("-12.34")
        assert r.currency == "USD"
        assert r.description == "PAYEE_USD_001 PAYEE_USD_001"
        assert r.balance == Decimal("500.00")

    def test_cny_income(self, adapter):
        """CNY income row: amount is positive."""
        text = _make_row(
            code="退款",
            book_income="25.00",
            book_currency="人民币",
            balance="2558.54",
            location="PAYEE_004",
            counterparty="PAYEE_004",
        )
        records = list(adapter.parse(text))
        r = records[0]
        assert r.amount == Decimal("25.00")
        assert r.currency == "CNY"
        assert r.code == "退款"

    def test_empty_location(self, adapter):
        """When 交易场所 is empty, description is just 对方户名 (stripped)."""
        text = _make_row(location="", counterparty="PAYEE_X")
        records = list(adapter.parse(text))
        assert records[0].description == "PAYEE_X"

    def test_empty_counterparty(self, adapter):
        """When 对方户名 is empty, description is just 交易场所 (stripped)."""
        text = _make_row(location="SHOP_B", counterparty="")
        records = list(adapter.parse(text))
        assert records[0].description == "SHOP_B"

    def test_unknown_currency_falls_to_cny(self, adapter):
        """记账币种 that is neither 美元 nor a standard value → CNY (legacy behavior)."""
        text = _make_row(book_expense="1.00", book_currency="欧元")
        records = list(adapter.parse(text))
        assert records[0].currency == "CNY"

    def test_both_amounts_empty(self, adapter):
        """Both 记账金额 columns empty → amount is None."""
        text = _make_row(book_income="", book_expense="")
        records = list(adapter.parse(text))
        assert records[0].amount is None

    def test_balance_with_thousand_separator(self, adapter):
        """Balance containing a comma thousand separator is parsed correctly."""
        text = _make_row(book_expense="10.00", balance="2,568.44")
        records = list(adapter.parse(text))
        assert records[0].balance == Decimal("2568.44")

    def test_multiple_rows(self, adapter):
        """Multiple rows are emitted in source order."""
        text = (
            _make_row(date="2025-01-03", book_expense="1.00")
            + _make_row(date="2025-01-02", book_expense="2.00")
            + _make_row(date="2025-01-01", book_income="3.00")
        )
        records = list(adapter.parse(text))
        assert len(records) == 3
        assert records[0].date == date(2025, 1, 3)
        assert records[1].date == date(2025, 1, 2)
        assert records[2].date == date(2025, 1, 1)
        assert records[0].amount == Decimal("-1.00")
        assert records[2].amount == Decimal("3.00")

    def test_counterparty_field_populated(self, adapter):
        """Counterparty is extracted from 对方户名."""
        text = _make_row(counterparty="ABC Corp")
        records = list(adapter.parse(text))
        assert records[0].counterparty == "ABC Corp"

    def test_counterparty_empty_is_none(self, adapter):
        """Empty 对方户名 results in counterparty=None."""
        text = _make_row(counterparty="")
        records = list(adapter.parse(text))
        assert records[0].counterparty is None

    def test_empty_code_is_none(self, adapter):
        """Empty 摘要 results in code=None."""
        text = _make_row(code="")
        records = list(adapter.parse(text))
        assert records[0].code is None


# ---------------------------------------------------------------------------
# End-to-end through the dispatch seam
# ---------------------------------------------------------------------------


class TestIcbcEndToEnd:
    """Call normalize_csv_to_intermediate with ICBC fixture and assert
    byte-exact equality with expected_intermediate.csv.
    """

    def test_fixture_through_seam(self, tmp_path):
        from services.config_service import AppConfig
        from services.csv_normalizer import normalize_csv_to_intermediate

        fixture_dir = FIXTURES_DIR / "icbc"
        input_path = fixture_dir / "input.csv"
        expected_path = fixture_dir / "expected_intermediate.csv"

        config = AppConfig(
            root_dir=tmp_path,
            config_toml=tmp_path / "config.toml",
            workspace={"name": "fixture", "start_year": 2026},
            dirs={
                "csv_dir": "inbox",
                "journal_dir": "journals",
                "init_dir": "rules",
                "opening_bal_dir": "opening",
                "imports_dir": "imports",
            },
            institution_templates={
                "icbc": {
                    "display_name": "Industrial and Commercial Bank of China",
                    "parser": "icbc",
                    "CSV_date_format": "%Y-%m-%d",
                    "head": 7,
                    "tail": 2,
                }
            },
            import_accounts={},
        )

        account_cfg = {
            "institution": "icbc",
            "ledger_account": "Assets:Bank:ICBC:Checking",
            "display_name": "Fixture",
        }

        actual = normalize_csv_to_intermediate(config, input_path, account_cfg)
        actual_bytes = actual.encode("utf-8")
        expected_bytes = expected_path.read_bytes()

        assert actual_bytes == expected_bytes, (
            "ICBC intermediate output drifted through new adapter seam"
        )
