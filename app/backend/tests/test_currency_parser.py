"""Parity tests for the shared currency-amount parser.

The same fixture (``tests/fixtures/currency_parser_cases.json``) is consumed
by the Vitest parity test on the frontend so the two parsers cannot drift.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from services.currency_parser import parse_amount
from services.manual_entry_service import _parse_amount_str
from services.reconciliation_service import parse_closing_balance


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "currency_parser_cases.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


_FIXTURE = _load_fixture()


@pytest.mark.parametrize(
    "case",
    _FIXTURE["accepted"],
    ids=lambda case: f"accept:{case['input']!r}",
)
def test_parse_amount_accepts_fixture_input(case: dict) -> None:
    expected = Decimal(case["expected"])
    assert parse_amount(case["input"]) == expected


@pytest.mark.parametrize(
    "case",
    _FIXTURE["rejected"],
    ids=lambda case: f"reject:{case['input']!r}",
)
def test_parse_amount_rejects_fixture_input(case: dict) -> None:
    with pytest.raises(ValueError):
        parse_amount(case["input"])


@pytest.mark.parametrize("case", _FIXTURE["accepted"], ids=lambda c: c["input"])
def test_legacy_wrappers_match_shared_parser(case: dict) -> None:
    expected = Decimal(case["expected"])
    assert _parse_amount_str(case["input"]) == expected
    assert parse_closing_balance(case["input"]) == expected


@pytest.mark.parametrize("case", _FIXTURE["rejected"], ids=lambda c: c["input"])
def test_legacy_wrappers_reject_same_inputs(case: dict) -> None:
    with pytest.raises(ValueError):
        _parse_amount_str(case["input"])
    with pytest.raises(ValueError):
        parse_closing_balance(case["input"])
