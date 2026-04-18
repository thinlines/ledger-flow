from __future__ import annotations
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from services.parsers import registry


@pytest.fixture(scope="module", autouse=True)
def _discover():
    registry.discover()


def _adapter():
    return registry.get_adapter("us_bank")


def test_adapter_metadata_attrs_present():
    a = _adapter()
    assert a.name == "us_bank"
    assert a.institution == "us_bank"
    assert a.formats == ("csv",)
    assert a.translator_name == "generic.checking"
    assert a.display_name == "U.S. Bank"
    assert a.csv_date_format == "%m/%d/%Y"
    assert a.suggested_ledger_prefix == "Assets:Bank:US Bank"
    assert a.aliases == ("us_bank", "usbank", "us-bank")
    assert a.head == 0
    assert a.tail == 0
    assert a.encoding == "utf-8"


def test_debit_row_becomes_negative_amount():
    text = (
        '"Date","Transaction","Name","Memo","Amount"\n'
        '"03/17/2026","DEBIT","MOBILE PURCHASE PAYEE_002","PURCHASE AUTHORIZED",58.42\n'
    )
    records = list(_adapter().parse(text))
    assert len(records) == 1
    r = records[0]
    assert r.date == date(2026, 3, 17)
    assert r.amount == Decimal("-58.42")
    assert r.currency == "$"
    assert r.description == "MOBILE PURCHASE PAYEE_002 PURCHASE AUTHORIZED"
    assert r.code is None


def test_credit_row_becomes_positive_amount():
    text = (
        '"Date","Transaction","Name","Memo","Amount"\n'
        '"03/19/2026","CREDIT","DEPOSIT FROM PAYEE_001","PAYROLL DEPOSIT",1842.67\n'
    )
    records = list(_adapter().parse(text))
    assert records[0].amount == Decimal("1842.67")
    assert records[0].date == date(2026, 3, 19)


def test_empty_memo_omits_trailing_space_in_description():
    text = (
        '"Date","Transaction","Name","Memo","Amount"\n'
        '"03/03/2026","DEBIT","CHECK 00281","",87.00\n'
    )
    records = list(_adapter().parse(text))
    assert records[0].description == "CHECK 00281"


def test_unknown_transaction_value_raises():
    text = (
        '"Date","Transaction","Name","Memo","Amount"\n'
        '"03/03/2026","HOLD","FOO","",10.00\n'
    )
    with pytest.raises(ValueError, match="Transaction"):
        list(_adapter().parse(text))


def test_missing_amount_raises():
    text = (
        '"Date","Transaction","Name","Memo","Amount"\n'
        '"03/03/2026","DEBIT","FOO","",\n'
    )
    with pytest.raises(ValueError, match="Amount"):
        list(_adapter().parse(text))


def test_header_bom_is_tolerated():
    text = (
        '\ufeff"Date","Transaction","Name","Memo","Amount"\n'
        '"03/19/2026","CREDIT","PAYEE_001","",1.00\n'
    )
    records = list(_adapter().parse(text))
    assert records[0].amount == Decimal("1.00")


def test_bad_header_raises():
    text = (
        '"Posted","Type","Desc","Note","Amt"\n'
        '"03/19/2026","CREDIT","FOO","",1.00\n'
    )
    with pytest.raises(ValueError, match="header"):
        list(_adapter().parse(text))


def test_blank_rows_are_skipped():
    text = (
        '"Date","Transaction","Name","Memo","Amount"\n'
        '\n'
        '"03/19/2026","CREDIT","FOO","",1.00\n'
        ',,,,\n'
    )
    records = list(_adapter().parse(text))
    assert len(records) == 1


def test_raw_dict_preserves_original_columns():
    text = (
        '"Date","Transaction","Name","Memo","Amount"\n'
        '"03/19/2026","CREDIT","FOO","BAR",1.00\n'
    )
    records = list(_adapter().parse(text))
    assert records[0].raw == {
        "Date": "03/19/2026",
        "Transaction": "CREDIT",
        "Name": "FOO",
        "Memo": "BAR",
        "Amount": "1.00",
    }


def test_fixture_end_to_end_byte_exact(tmp_path: Path):
    from services.config_service import AppConfig
    from services.csv_normalizer import normalize_csv_to_intermediate

    fixture_root = (
        Path(__file__).parent / "fixtures" / "csv_snapshots" / "us_bank"
    )
    input_csv = fixture_root / "input.csv"
    expected = (fixture_root / "expected_intermediate.csv").read_bytes()

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
            "us_bank": {
                "display_name": "U.S. Bank",
                "head": 0,
                "tail": 0,
                "encoding": "utf-8",
            }
        },
        import_accounts={},
    )
    account_cfg = {
        "institution": "us_bank",
        "ledger_account": "Assets:Bank:US Bank:Checking",
    }

    actual = normalize_csv_to_intermediate(config, input_csv, account_cfg)
    assert actual == expected.decode("utf-8")
