from __future__ import annotations
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from services.parsers import registry


@pytest.fixture(autouse=True)
def _discover_adapters():
    registry.discover()


@pytest.fixture
def adapter():
    return registry.get_adapter("chase")


HEADER = (
    "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\r\n"
)


def _one_row(row: str) -> str:
    return HEADER + row + "\r\n"


def test_protocol_and_metadata(adapter):
    assert adapter.name == "chase"
    assert adapter.institution == "chase"
    assert adapter.formats == ("csv",)
    assert adapter.translator_name == "generic.checking"
    assert adapter.display_name == "Chase Bank"
    assert adapter.csv_date_format == "%m/%d/%Y"
    assert adapter.suggested_ledger_prefix == "Assets:Bank:Chase"
    assert "jpmorgan_chase" in adapter.aliases
    assert adapter.head == 0
    assert adapter.tail == 0
    assert adapter.encoding == "utf-8"


def test_parse_debit_row_is_negative(adapter):
    text = _one_row(
        "DEBIT,04/14/2026,PAYEE_001 PURCHASE    04/13 #000001234,-42.17,DEBIT_CARD,3812.44,"
    )
    [rec] = list(adapter.parse(text))
    assert rec.date == date(2026, 4, 14)
    assert rec.amount == Decimal("-42.17")
    assert rec.currency == "$"
    assert rec.description == "PAYEE_001 PURCHASE    04/13 #000001234"
    assert rec.code is None
    assert rec.balance == Decimal("3812.44")
    assert rec.note is None
    assert rec.raw == {"Details": "DEBIT", "Type": "DEBIT_CARD"}


def test_parse_credit_row_is_positive(adapter):
    text = _one_row(
        "CREDIT,04/12/2026,DEPOSIT ACH CREDIT PAYEE_002 PAYROLL PPD ID: REF_000001,2450.00,ACH_CREDIT,3854.61,"
    )
    [rec] = list(adapter.parse(text))
    assert rec.amount == Decimal("2450.00")
    assert rec.balance == Decimal("3854.61")
    assert rec.code is None


def test_parse_check_row_populates_code(adapter):
    text = _one_row(
        "CHECK,04/10/2026,CHECK # REF_001087,-240.00,CHECK_PAID,1529.61,REF_001087"
    )
    [rec] = list(adapter.parse(text))
    assert rec.code == "REF_001087"
    assert rec.amount == Decimal("-240.00")
    assert rec.raw["Details"] == "CHECK"


def test_parse_dslip_row_populates_code(adapter):
    text = _one_row(
        "DSLIP,04/03/2026,DEPOSIT ID REF_000006,500.00,DEPOSIT,1897.18,REF_000006"
    )
    [rec] = list(adapter.parse(text))
    assert rec.code == "REF_000006"
    assert rec.amount == Decimal("500.00")


def test_parse_empty_balance_becomes_none(adapter):
    text = _one_row(
        "DEBIT,04/02/2026,PAYEE_009 ONLINE PMT,-89.50,ACH_DEBIT,,"
    )
    [rec] = list(adapter.parse(text))
    assert rec.balance is None


def test_parse_empty_amount_becomes_none(adapter):
    text = _one_row(
        "DEBIT,04/02/2026,PAYEE_009 PENDING,,ACH_DEBIT,1000.00,"
    )
    [rec] = list(adapter.parse(text))
    assert rec.amount is None


def test_parse_missing_header_raises(adapter):
    with pytest.raises(ValueError, match="missing expected columns"):
        list(adapter.parse("Foo,Bar,Baz\r\n1,2,3\r\n"))


def test_parse_empty_input_raises(adapter):
    with pytest.raises(ValueError, match="empty or missing header"):
        list(adapter.parse(""))


def test_parse_multiple_rows_preserves_order(adapter):
    text = (
        HEADER
        + "DEBIT,04/14/2026,PAYEE_001,-10.00,DEBIT_CARD,100.00,\r\n"
        + "CREDIT,04/13/2026,PAYEE_002,20.00,ACH_CREDIT,110.00,\r\n"
        + "DEBIT,04/12/2026,PAYEE_003,-5.00,DEBIT_CARD,90.00,\r\n"
    )
    records = list(adapter.parse(text))
    assert [r.date for r in records] == [
        date(2026, 4, 14),
        date(2026, 4, 13),
        date(2026, 4, 12),
    ]
    assert [r.amount for r in records] == [
        Decimal("-10.00"),
        Decimal("20.00"),
        Decimal("-5.00"),
    ]


FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "csv_snapshots" / "chase"
)


def test_end_to_end_byte_exact(tmp_path):
    from services.config_service import AppConfig
    from services.csv_normalizer import normalize_csv_to_intermediate

    input_path = FIXTURE_DIR / "input.csv"
    expected_path = FIXTURE_DIR / "expected_intermediate.csv"

    assert input_path.exists(), f"Missing fixture: {input_path}"
    assert expected_path.exists(), f"Missing golden: {expected_path}"

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
            "chase": {
                "encoding": "utf-8",
                "head": 0,
                "tail": 0,
            }
        },
        import_accounts={},
    )
    account_cfg = {
        "institution": "chase",
        "ledger_account": "Assets:Bank:Chase:Checking",
    }

    actual = normalize_csv_to_intermediate(config, input_path, account_cfg)
    expected = expected_path.read_bytes().decode("utf-8")
    assert actual == expected
