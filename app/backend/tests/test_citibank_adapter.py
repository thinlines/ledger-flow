from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from services.parsers import registry


def _adapter():
    registry.discover()
    return registry.get_adapter("citibank")


def test_citibank_adapter_is_registered():
    adapter = _adapter()
    assert adapter.name == "citibank"
    assert adapter.institution == "citibank"
    assert adapter.translator_name == "generic.checking"
    assert "csv" in adapter.formats


def test_citibank_aliases_declared():
    adapter = _adapter()
    assert adapter.aliases == ("citi", "citibank", "citi-bank")


def test_citibank_parses_charge_row_as_negative():
    text = (
        "Status,Date,Description,Debit,Credit,Member Name\n"
        "Cleared,04/12/2026,AMAZON.COM*AB12CD34,42.17,,JANE DOE\n"
    )
    records = list(_adapter().parse(text))
    assert len(records) == 1
    r = records[0]
    assert r.date == date(2026, 4, 12)
    assert r.description == "AMAZON.COM*AB12CD34"
    assert r.amount == Decimal("-42.17")
    assert r.currency == "$"
    assert r.code is None
    assert r.balance is None
    assert r.raw["status"] == "Cleared"
    assert r.raw["member_name"] == "JANE DOE"


def test_citibank_parses_payment_row_as_positive():
    text = (
        "Status,Date,Description,Debit,Credit,Member Name\n"
        "Cleared,04/08/2026,PAYMENT THANK YOU-ELECTRONIC,,350.00,JANE DOE\n"
    )
    records = list(_adapter().parse(text))
    assert len(records) == 1
    assert records[0].amount == Decimal("350.00")
    assert records[0].description == "PAYMENT THANK YOU-ELECTRONIC"


def test_citibank_parses_refund_row_as_positive():
    text = (
        "Status,Date,Description,Debit,Credit,Member Name\n"
        "Cleared,04/04/2026,RETURN: AMAZON.COM*XY99ZZ,,18.74,JANE DOE\n"
    )
    records = list(_adapter().parse(text))
    assert records[0].amount == Decimal("18.74")


def test_citibank_skips_pending_rows():
    text = (
        "Status,Date,Description,Debit,Credit,Member Name\n"
        "Cleared,04/12/2026,AMAZON.COM*AB12CD34,42.17,,JANE DOE\n"
        "Pending,04/10/2026,UBER   *TRIP HELP.UBER.COM,24.50,,JANE DOE\n"
        "Cleared,04/09/2026,WHOLEFDS MKT #10234,87.63,,JANE DOE\n"
    )
    records = list(_adapter().parse(text))
    assert len(records) == 2
    descriptions = [r.description for r in records]
    assert "UBER   *TRIP HELP.UBER.COM" not in descriptions
    assert descriptions == ["AMAZON.COM*AB12CD34", "WHOLEFDS MKT #10234"]


def test_citibank_skips_zero_dollar_admin_rows():
    text = (
        "Status,Date,Description,Debit,Credit,Member Name\n"
        "Cleared,04/01/2026,ANNUAL FEE NOTICE,,,JANE DOE\n"
    )
    records = list(_adapter().parse(text))
    assert records == []


def test_citibank_raises_when_both_debit_and_credit_populated():
    text = (
        "Status,Date,Description,Debit,Credit,Member Name\n"
        "Cleared,04/01/2026,UNEXPECTED,10.00,5.00,JANE DOE\n"
    )
    with pytest.raises(ValueError, match="both Debit and Credit"):
        list(_adapter().parse(text))


def test_citibank_tolerates_missing_status_column():
    text = (
        "Date,Description,Debit,Credit,Member Name\n"
        "04/12/2026,AMAZON.COM*AB12CD34,42.17,,JANE DOE\n"
        "04/08/2026,PAYMENT THANK YOU,,100.00,JANE DOE\n"
    )
    records = list(_adapter().parse(text))
    assert len(records) == 2
    assert records[0].amount == Decimal("-42.17")
    assert records[1].amount == Decimal("100.00")


def test_citibank_handles_quoted_description_with_comma():
    text = (
        "Status,Date,Description,Debit,Credit,Member Name\n"
        'Cleared,04/03/2026,"CHIPOTLE 1234, BOSTON MA",14.25,,JANE DOE\n'
    )
    records = list(_adapter().parse(text))
    assert records[0].description == "CHIPOTLE 1234, BOSTON MA"


def test_citibank_full_fixture_counts():
    text = (
        "Status,Date,Description,Debit,Credit,Member Name\n"
        "Cleared,04/12/2026,AMAZON.COM*AB12CD34,42.17,,JANE DOE\n"
        "Cleared,04/11/2026,STARBUCKS STORE #12345,6.85,,JANE DOE\n"
        "Cleared,04/11/2026,NETFLIX.COM,15.49,,JANE DOE\n"
        "Cleared,04/10/2026,SHELL OIL 57412983100,38.00,,JANE DOE\n"
        "Pending,04/10/2026,UBER   *TRIP HELP.UBER.COM,24.50,,JANE DOE\n"
        "Cleared,04/09/2026,WHOLEFDS MKT #10234,87.63,,JANE DOE\n"
        "Cleared,04/08/2026,PAYMENT THANK YOU-ELECTRONIC,,350.00,JANE DOE\n"
        "Cleared,04/07/2026,SPOTIFY USA,11.99,,JANE DOE\n"
        "Cleared,04/06/2026,TRADER JOE'S #456,52.41,,JANE DOE\n"
        "Cleared,04/05/2026,DELTA AIR 0061234567890,412.80,,JANE DOE\n"
        "Cleared,04/04/2026,RETURN: AMAZON.COM*XY99ZZ,,18.74,JANE DOE\n"
        'Cleared,04/03/2026,"CHIPOTLE 1234, BOSTON MA",14.25,,JANE DOE\n'
        "Cleared,04/02/2026,CITI REWARDS REDEMPTION,,25.00,JANE DOE\n"
        "Cleared,04/01/2026,APPLE.COM/BILL,2.99,,JANE DOE\n"
        "Cleared,04/01/2026,ANNUAL FEE NOTICE,,,JANE DOE\n"
    )
    records = list(_adapter().parse(text))
    assert len(records) == 13

    by_desc = {r.description: r for r in records}
    assert by_desc["AMAZON.COM*AB12CD34"].amount == Decimal("-42.17")
    assert by_desc["PAYMENT THANK YOU-ELECTRONIC"].amount == Decimal("350.00")
    assert by_desc["RETURN: AMAZON.COM*XY99ZZ"].amount == Decimal("18.74")
    assert by_desc["CITI REWARDS REDEMPTION"].amount == Decimal("25.00")
    assert by_desc["CHIPOTLE 1234, BOSTON MA"].amount == Decimal("-14.25")


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "csv_snapshots" / "citibank"


def test_end_to_end_byte_exact(tmp_path):
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
            "citibank": {
                "encoding": "utf-8-sig",
                "head": 0,
                "tail": 0,
            }
        },
        import_accounts={},
    )
    account_cfg = {
        "institution": "citibank",
        "ledger_account": "Liabilities:Credit Card:Citibank",
    }

    actual = normalize_csv_to_intermediate(config, input_path, account_cfg)
    expected = expected_path.read_bytes().decode("utf-8")
    assert actual == expected
