"""Golden-fixture characterization tests for the CSV import pipeline.

Each fixture under ``app/backend/tests/fixtures/csv_snapshots/<institution>/``
contains a sanitized real-world ``input.csv`` and the byte-exact
``expected_intermediate.csv`` that today's ``normalize_csv_to_intermediate()``
produces from it. These are regression oracles for Tasks 1-7 of the
CSV parser refactor: any drift in the intermediate output will surface
as a failing test, and the rule is "fix the parser, never the fixture"
once Tasks 2+ start porting institutions to the new adapter package.
"""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "csv_snapshots"

# Per-institution config used to characterize today's pipeline against
# the sanitized fixture. Mirrors the institution_templates the production
# `AppConfig` carries for each bank, but pinned here so the fixture test
# does not depend on a workspace `config.toml` existing on disk.
INSTITUTION_TEMPLATES = {
    "wells_fargo": {
        "display_name": "Wells Fargo",
        "parser": "wfchk",
        "CSV_date_format": "%m/%d/%Y",
    },
    "alipay": {
        "display_name": "Alipay",
        "parser": "alipay",
        "CSV_date_format": "%Y-%m-%d",
        "head": 13,
        "tail": 1,
        "encoding": "GB18030",
    },
    "icbc": {
        "display_name": "Industrial and Commercial Bank of China",
        "parser": "icbc",
        "CSV_date_format": "%Y-%m-%d",
        "head": 7,
        "tail": 2,
    },
}

INSTITUTIONS = ["wells_fargo", "alipay", "icbc"]


def _make_config(tmp_path: Path, institution: str):
    from services.config_service import AppConfig

    return AppConfig(
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
        institution_templates={institution: INSTITUTION_TEMPLATES[institution]},
        import_accounts={},
    )


@pytest.mark.parametrize("institution", INSTITUTIONS)
def test_fixture_reproduces_expected_intermediate(institution: str, tmp_path: Path) -> None:
    from services.csv_normalizer import normalize_csv_to_intermediate

    fixture_dir = FIXTURES_DIR / institution
    input_path = fixture_dir / "input.csv"
    expected_path = fixture_dir / "expected_intermediate.csv"

    config = _make_config(tmp_path, institution)
    account_cfg = {
        "institution": institution,
        "ledger_account": "Assets:Test",
        "display_name": "Fixture",
    }

    actual = normalize_csv_to_intermediate(config, input_path, account_cfg)
    expected = expected_path.read_bytes().decode("utf-8")

    assert actual == expected, (
        f"intermediate output drifted for {institution}; "
        "fix the fixture (sanitization, encoding, line endings) — "
        "never the parser"
    )
