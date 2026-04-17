"""Tests for the Wells Fargo adapter, GenericCheckingTranslator, and
dispatch seam integration.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "csv_snapshots"


# ---------------------------------------------------------------------------
# _extract_code unit tests
# ---------------------------------------------------------------------------

class TestExtractCode:
    """Exercise every branch of WellsFargoAdapter._extract_code against
    the same logic as WellsFargoCSV.code() in Scripts/BankCSV.py.
    """

    @pytest.fixture()
    def adapter(self):
        from services.parsers.implementations.wells_fargo import WellsFargoAdapter
        return WellsFargoAdapter()

    def test_ref_in_description(self, adapter):
        """REF # match in description, empty note column."""
        code = adapter._extract_code(
            "", "ONLINE TRANSFER REF #IB0WD9SHT2 TO CREDIT CARD"
        )
        assert code == "IB0WD9SHT2"

    def test_check_in_description_empty_note(self, adapter):
        """CHECK # match in description with empty note column."""
        code = adapter._extract_code("", "CHECK # 283")
        assert code == "283"

    def test_check_in_description_note_populated(self, adapter):
        """Note column populated takes precedence over CHECK # in description."""
        code = adapter._extract_code("283", "CHECK # 283")
        assert code == "283"

    def test_note_takes_precedence_over_ref(self, adapter):
        """Note column populated takes precedence over REF # in description."""
        code = adapter._extract_code("CUSTOM_NOTE", "TRANSFER REF #ABC123")
        assert code == "CUSTOM_NOTE"

    def test_neither_match_empty_note(self, adapter):
        """No REF/CHECK match and empty note column returns None."""
        code = adapter._extract_code("", "DEPOSIT FROM PAYEE_001")
        assert code is None

    def test_neither_match_no_ref_no_check(self, adapter):
        """Description with no REF/CHECK keywords, empty note."""
        code = adapter._extract_code("", "PURCHASE AUTHORIZED ON 03/16 PAYEE")
        assert code is None

    def test_check_without_space_after_hash(self, adapter):
        """CHECK #<digits> (no space) still matches per the regex."""
        code = adapter._extract_code("", "CHECK #100")
        assert code == "100"


# ---------------------------------------------------------------------------
# Adapter parse() unit tests
# ---------------------------------------------------------------------------

class TestWellsFargoAdapterParse:
    """Construct small WF CSV text, parse it, assert Record contents."""

    @pytest.fixture()
    def adapter(self):
        from services.parsers.implementations.wells_fargo import WellsFargoAdapter
        return WellsFargoAdapter()

    def test_basic_row(self, adapter):
        text = '"03/19/2026","827.31","*","","DEPOSIT FROM PAYEE_001"\n'
        records = list(adapter.parse(text))
        assert len(records) == 1
        r = records[0]
        assert r.date == date(2026, 3, 19)
        assert r.amount == Decimal("827.31")
        assert r.description == "DEPOSIT FROM PAYEE_001"
        assert r.code is None
        assert r.note is None
        assert r.balance is None
        assert r.currency == "$"
        assert r.raw == {"cleared": "*"}

    def test_ref_code_extraction(self, adapter):
        text = (
            '"03/16/2026","-25.00","*","","RECURRING TRANSFER TO SAVINGS '
            'REF #OP0X8Q6GPB XXXXXX0000"\n'
        )
        records = list(adapter.parse(text))
        assert records[0].code == "OP0X8Q6GPB"

    def test_check_code_with_note(self, adapter):
        text = '"02/18/2026","-1000.00","*","283","CHECK # 283"\n'
        records = list(adapter.parse(text))
        r = records[0]
        assert r.code == "283"
        assert r.note is None

    def test_multiple_rows(self, adapter):
        text = (
            '"03/19/2026","827.31","*","","DEPOSIT FROM PAYEE_001"\n'
            '"03/17/2026","-41.01","*","","PURCHASE AUTHORIZED ON 03/16 PAYEE_002"\n'
        )
        records = list(adapter.parse(text))
        assert len(records) == 2
        assert records[0].date == date(2026, 3, 19)
        assert records[1].date == date(2026, 3, 17)
        assert records[1].amount == Decimal("-41.01")


# ---------------------------------------------------------------------------
# GenericCheckingTranslator unit tests
# ---------------------------------------------------------------------------

class TestGenericCheckingTranslator:
    """Translate Records into LedgerTransactions with various field combos."""

    @pytest.fixture()
    def translator(self):
        from services.parsers.implementations.wells_fargo import (
            GenericCheckingTranslator,
        )
        return GenericCheckingTranslator()

    def _make_record(self, **overrides):
        from services.parsers.types import Record
        defaults = dict(
            date=date(2026, 3, 19),
            description="Test Payee",
            amount=Decimal("100.00"),
            currency="$",
            code=None,
            note=None,
            balance=None,
        )
        defaults.update(overrides)
        return Record(**defaults)

    def test_basic_translate(self, translator):
        record = self._make_record()
        txn = translator.translate(record, "Assets:Bank:WF:Checking")
        assert txn.date == date(2026, 3, 19)
        assert txn.payee == "Test Payee"
        assert txn.code is None
        assert txn.note is None
        assert txn.balance is None
        assert len(txn.postings) == 1
        assert txn.postings[0].account == "Assets:Bank:WF:Checking"
        assert txn.postings[0].amount == Decimal("100.00")
        assert txn.postings[0].commodity == "$"

    def test_with_balance(self, translator):
        record = self._make_record(balance=Decimal("5000.00"))
        txn = translator.translate(record, "Assets:Bank:WF:Checking")
        assert txn.balance == Decimal("5000.00")

    def test_with_note(self, translator):
        record = self._make_record(note="some note")
        txn = translator.translate(record, "Assets:Bank:WF:Checking")
        assert txn.note == "some note"

    def test_with_usd_commodity(self, translator):
        record = self._make_record(currency="USD")
        txn = translator.translate(record, "Assets:Bank:WF:Checking")
        assert txn.postings[0].commodity == "USD"

    def test_with_code(self, translator):
        record = self._make_record(code="ABC123")
        txn = translator.translate(record, "Assets:Bank:WF:Checking")
        assert txn.code == "ABC123"


# ---------------------------------------------------------------------------
# End-to-end through the dispatch seam
# ---------------------------------------------------------------------------

class TestWellsFargoEndToEnd:
    """Call normalize_csv_to_intermediate with WF fixture input and assert
    byte-exact equality with expected_intermediate.csv.
    """

    def test_fixture_through_seam(self, tmp_path):
        from services.config_service import AppConfig
        from services.csv_normalizer import normalize_csv_to_intermediate

        fixture_dir = FIXTURES_DIR / "wells_fargo"
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
                "wells_fargo": {
                    "display_name": "Wells Fargo",
                    "parser": "wfchk",
                    "CSV_date_format": "%m/%d/%Y",
                }
            },
            import_accounts={},
        )

        account_cfg = {
            "institution": "wells_fargo",
            "ledger_account": "Assets:Bank:Wells Fargo:Checking",
            "display_name": "Fixture",
        }

        actual = normalize_csv_to_intermediate(config, input_path, account_cfg)
        actual_bytes = actual.encode("utf-8")
        expected_bytes = expected_path.read_bytes()

        assert actual_bytes == expected_bytes, (
            "Wells Fargo intermediate output drifted through new adapter seam"
        )
