"""Tests for the Alipay adapter.

Covers adapter-level unit tests with literal CSV text, plus an end-to-end
fixture test through the dispatch seam for byte-exact regression.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "csv_snapshots"


# ---------------------------------------------------------------------------
# Adapter parse() unit tests
# ---------------------------------------------------------------------------

class TestAlipayAdapterParse:
    """Construct small Alipay CSV text (headerless, matching post-slice
    format), parse it, assert Record contents."""

    @pytest.fixture()
    def adapter(self):
        from services.parsers.implementations.alipay import AlipayAdapter
        return AlipayAdapter()

    def test_income_row(self, adapter):
        """Income row: 收入 populated, 支出 empty -> positive amount."""
        text = "ORD_001\t,2024-12-29 20:03:50,PAYEE_001 收款,,10.00,,100.00,支付宝\n"
        records = list(adapter.parse(text))
        assert len(records) == 1
        r = records[0]
        assert r.date == date(2024, 12, 29)
        assert r.amount == Decimal("10.00")
        assert r.currency == "¥"
        assert r.description == "PAYEE_001 收款"
        assert r.code == "ORD_001"
        assert r.balance == Decimal("100.00")
        assert r.note is None

    def test_expense_row(self, adapter):
        """Expense row: 支出 populated with minus sign, 收入 empty -> negative amount."""
        text = "ORD_002\t,2024-12-25 19:18:59,支付-PAYEE_005 购物,,,-9.60,-409.50,支付宝\n"
        records = list(adapter.parse(text))
        assert len(records) == 1
        r = records[0]
        assert r.date == date(2024, 12, 25)
        assert r.amount == Decimal("-9.60")
        assert r.currency == "¥"
        assert r.description == "支付-PAYEE_005 购物"
        assert r.code == "ORD_002"
        assert r.balance == Decimal("-409.50")
        assert r.note is None

    def test_note_always_none_even_with_beizhu(self, adapter):
        """Row with populated 备注 column -> Record.note still None (legacy behavior)."""
        text = "ORD_003\t,2024-12-28 18:03:50,PAYEE_002 转账,备注_01,500.00,,90.00,支付宝\n"
        records = list(adapter.parse(text))
        r = records[0]
        assert r.note is None
        assert r.amount == Decimal("500.00")

    def test_non_ascii_description(self, adapter):
        """Non-ASCII 名称 round-trips exactly through Record.description."""
        text = "ORD_004\t,2024-12-27 12:03:50,PAYEE_003 红包,,0.50,,-410.00,支付宝\n"
        records = list(adapter.parse(text))
        assert records[0].description == "PAYEE_003 红包"

    def test_multiple_rows(self, adapter):
        """Multiple rows parse in source order."""
        text = (
            "ORD_A\t,2024-12-29 20:03:50,收款_A,,10.00,,100.00,支付宝\n"
            "ORD_B\t,2024-12-28 18:03:50,付款_B,,,-5.00,95.00,支付宝\n"
        )
        records = list(adapter.parse(text))
        assert len(records) == 2
        assert records[0].code == "ORD_A"
        assert records[1].code == "ORD_B"
        assert records[0].amount == Decimal("10.00")
        assert records[1].amount == Decimal("-5.00")

    def test_adapter_metadata(self, adapter):
        """Adapter class attributes match registration requirements."""
        assert adapter.name == "alipay"
        assert adapter.institution == "alipay"
        assert adapter.translator_name == "generic.checking"
        assert "csv" in adapter.formats


# ---------------------------------------------------------------------------
# End-to-end through the dispatch seam
# ---------------------------------------------------------------------------

class TestAlipayEndToEnd:
    """Call normalize_csv_to_intermediate with Alipay fixture input and assert
    byte-exact equality with expected_intermediate.csv.
    """

    def test_fixture_through_seam(self, tmp_path):
        from services.config_service import AppConfig
        from services.csv_normalizer import normalize_csv_to_intermediate

        fixture_dir = FIXTURES_DIR / "alipay"
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
                "alipay": {
                    "display_name": "Alipay",
                    "parser": "alipay",
                    "CSV_date_format": "%Y-%m-%d",
                    "head": 13,
                    "tail": 1,
                    "encoding": "GB18030",
                }
            },
            import_accounts={},
        )

        account_cfg = {
            "institution": "alipay",
            "ledger_account": "Assets:Test",
            "display_name": "Fixture",
        }

        actual = normalize_csv_to_intermediate(config, input_path, account_cfg)
        actual_bytes = actual.encode("utf-8")
        expected_bytes = expected_path.read_bytes()

        assert actual_bytes == expected_bytes, (
            "Alipay intermediate output drifted through new adapter seam"
        )
