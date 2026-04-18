from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from services.parsers import registry
from services.parsers.implementations.bank_of_america import (
    BankOfAmericaAdapter,
)


@pytest.fixture(scope="module", autouse=True)
def _discover_adapters() -> None:
    registry.discover()


def test_adapter_is_registered_under_canonical_slug():
    adapter = registry.get_adapter("bank_of_america")
    assert isinstance(adapter, BankOfAmericaAdapter)
    assert adapter.translator_name == "generic.checking"
    assert adapter.institution == "bank_of_america"
    assert adapter.formats == ("csv",)


def test_adapter_declares_task_06_metadata():
    a = BankOfAmericaAdapter()
    assert a.display_name == "Bank of America"
    assert set(a.aliases) == {"bofa", "bank-of-america", "bankofamerica", "boa"}
    assert a.encoding == "utf-8"
    assert a.head == 6
    assert a.tail == 0


HEADER = "Date,Description,Amount,Running Bal.\r\n"


def _parse(body: str):
    return list(BankOfAmericaAdapter().parse(HEADER + body))


def test_parses_simple_credit_row():
    rows = _parse('01/31/2025,"Interest Earned",0.42,"6,787.53"\r\n')
    assert len(rows) == 1
    r = rows[0]
    assert r.date == date(2025, 1, 31)
    assert r.description == "Interest Earned"
    assert r.amount == Decimal("0.42")
    assert r.balance == Decimal("6787.53")
    assert r.currency == "$"
    assert r.code is None
    assert r.note is None


def test_parses_debit_row_with_negative_amount():
    rows = _parse('01/22/2025,"CHECKCARD 0121 SAMPLE GROCERY",-48.73,"3,012.11"\r\n')
    assert rows[0].amount == Decimal("-48.73")
    assert rows[0].balance == Decimal("3012.11")


def test_strips_thousand_separator_from_quoted_amount():
    rows = _parse('01/10/2025,"LARGE PURCHASE","-1,234.56","3,158.10"\r\n')
    assert rows[0].amount == Decimal("-1234.56")
    assert rows[0].balance == Decimal("3158.10")


def test_preserves_comma_inside_quoted_description():
    rows = _parse(
        '01/30/2025,"Zelle Transfer Conf# aa11bb22, SAMPLE PAYEE A",-150.00,"6,787.11"\r\n'
    )
    assert rows[0].description == "Zelle Transfer Conf# aa11bb22, SAMPLE PAYEE A"


def test_running_balance_captured_raw_for_debugging():
    rows = _parse('01/05/2025,"MOBILE DEPOSIT",850.00,"4,517.66"\r\n')
    assert rows[0].raw["running_balance_raw"] == "4,517.66"


def test_emits_usd_dollar_sign_currency():
    rows = _parse('01/05/2025,"MOBILE DEPOSIT",850.00,"4,517.66"\r\n')
    assert rows[0].currency == "$"


def test_code_is_none_for_v1_even_on_check_row():
    rows = _parse('01/27/2025,"CHECK 1042",-75.00,"6,437.11"\r\n')
    assert rows[0].code is None
    assert "CHECK 1042" in rows[0].description


def test_blank_trailing_row_is_tolerated():
    rows = _parse('01/05/2025,"MOBILE DEPOSIT",850.00,"4,517.66"\r\n\r\n')
    assert len(rows) == 1


def test_rejects_unexpected_header_loudly():
    bogus = "Posted Date,Payee,Amount\r\n01/01/2025,X,1.00\r\n"
    with pytest.raises(ValueError, match="Unexpected Bank of America CSV header"):
        list(BankOfAmericaAdapter().parse(bogus))


def test_order_preserved_newest_first():
    body = (
        '01/31/2025,"B",1.00,"2.00"\r\n'
        '01/30/2025,"A",1.00,"1.00"\r\n'
    )
    rows = _parse(body)
    assert [r.description for r in rows] == ["B", "A"]


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "csv_snapshots" / "bank_of_america"


def test_end_to_end_matches_golden_intermediate(tmp_path):
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
            "bank_of_america": {"encoding": "utf-8", "head": 6, "tail": 0},
        },
        import_accounts={},
    )
    account_cfg = {
        "institution": "bank_of_america",
        "ledger_account": "Assets:Bank:Bank of America:Checking",
    }
    actual = normalize_csv_to_intermediate(
        config, input_path, account_cfg,
    )
    expected = expected_path.read_bytes()
    assert actual == expected.decode("utf-8")
