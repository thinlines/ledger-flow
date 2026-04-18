from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from services.parsers import registry
from services.parsers.implementations.ally import (
    AllyAdapter,
    _parse_amount,
)
from services.parsers.types import Record


FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "csv_snapshots"
    / "ally"
)


def _parse_rows(text: str) -> list[Record]:
    adapter = AllyAdapter()
    return list(adapter.parse(text))


def test_adapter_metadata_is_complete():
    a = AllyAdapter()
    assert a.name == "ally"
    assert a.institution == "ally"
    assert a.formats == ("csv",)
    assert a.translator_name == "generic.checking"
    assert a.display_name == "Ally Bank"
    assert a.csv_date_format == "%m/%d/%Y"
    assert a.suggested_ledger_prefix == "Assets:Bank:Ally"
    assert "ally_bank" in a.aliases
    assert a.head == 1
    assert a.tail == 0
    assert a.encoding == "utf-8-sig"


def test_adapter_registered_under_ally_slug():
    registry.discover()
    assert registry.get_adapter("ally").name == "ally"


def test_parse_deposit_row_is_positive():
    text = "04/13/2026,09:15,2500.00,Deposit,ACH Deposit EMPLOYER INC PAYROLL\n"
    [r] = _parse_rows(text)
    assert r.date == date(2026, 4, 13)
    assert r.amount == Decimal("2500.00")
    assert r.currency == "$"
    assert r.description == "ACH Deposit EMPLOYER INC PAYROLL"
    assert r.code is None
    assert r.raw == {"time": "09:15", "type": "Deposit"}


def test_parse_withdrawal_row_is_negative():
    text = "04/14/2026,14:32,-42.50,Debit Card,TRADER JOES #123 SEATTLE WA\n"
    [r] = _parse_rows(text)
    assert r.amount == Decimal("-42.50")
    assert r.raw["type"] == "Debit Card"


def test_parse_check_row_extracts_check_number():
    text = "04/08/2026,10:22,-350.00,Check,Check # 1042\n"
    [r] = _parse_rows(text)
    assert r.code == "1042"
    assert r.amount == Decimal("-350.00")


def test_parse_check_row_with_narrative_suffix():
    text = "03/31/2026,22:11,-150.00,Check,Check # 1041 - LANDLORD\n"
    [r] = _parse_rows(text)
    assert r.code == "1041"


def test_parse_non_check_description_with_hash_does_not_false_match():
    text = "04/14/2026,14:32,-42.50,Debit Card,TRADER JOES #123 SEATTLE WA\n"
    [r] = _parse_rows(text)
    assert r.code is None


def test_parse_blank_time_row():
    text = "04/09/2026,,0.42,Interest Paid,Interest Paid\n"
    [r] = _parse_rows(text)
    assert r.amount == Decimal("0.42")
    assert r.raw["time"] == ""


def test_parse_skips_trailing_blank_line():
    text = (
        "04/14/2026,14:32,-42.50,Debit Card,TRADER JOES #123 SEATTLE WA\n"
        "\n"
    )
    rows = _parse_rows(text)
    assert len(rows) == 1


def test_parse_rejects_short_row():
    text = "04/14/2026,14:32,-42.50,Debit Card\n"
    with pytest.raises(ValueError, match="expected 5"):
        _parse_rows(text)


def test_parse_rejects_empty_amount():
    text = "04/14/2026,14:32,,Debit Card,FOO\n"
    with pytest.raises(ValueError, match="Amount column is empty"):
        _parse_rows(text)


def test_parse_rejects_malformed_date():
    text = "2026-04-14,14:32,-42.50,Debit Card,FOO\n"
    with pytest.raises(ValueError):
        _parse_rows(text)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("42.50", Decimal("42.50")),
        ("-42.50", Decimal("-42.50")),
        ("1,234.56", Decimal("1234.56")),
        ("-1,234.56", Decimal("-1234.56")),
        ("$42.50", Decimal("42.50")),
        ("-$42.50", Decimal("-42.50")),
        ("$-42.50", Decimal("-42.50")),
        ("  42.50  ", Decimal("42.50")),
    ],
)
def test_parse_amount_variants(raw: str, expected: Decimal):
    assert _parse_amount(raw) == expected


def test_end_to_end_byte_exact(tmp_path: Path):
    from services.config_service import AppConfig
    from services.csv_normalizer import normalize_csv_to_intermediate

    input_path = FIXTURE_DIR / "input.csv"
    expected_path = FIXTURE_DIR / "expected_intermediate.csv"
    assert input_path.exists(), f"Missing fixture: {input_path}"
    assert expected_path.exists(), f"Missing fixture: {expected_path}"

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
            "ally": {
                "encoding": "utf-8-sig",
                "head": 1,
                "tail": 0,
            }
        },
        import_accounts={},
    )
    account_cfg = {
        "institution": "ally",
        "ledger_account": "Assets:Bank:Ally:Checking",
    }

    actual = normalize_csv_to_intermediate(config, input_path, account_cfg)
    expected = expected_path.read_bytes().decode("utf-8")
    assert actual == expected
