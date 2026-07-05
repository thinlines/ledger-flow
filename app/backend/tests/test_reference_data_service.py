"""DB-backed account picker and autocomplete (issue #18).

The picker/autocomplete lists and the per-account posting counts are served
from the projected reference tables instead of parsing ``10-accounts.dat``
or shelling out to ``ledger accounts --count``:

- ``list_account_names`` — every projected account (declared, used, and
  synthesized ancestors) minus closed ones, in lexicographic order (=
  depth-first tree order per the spec's Account Hierarchy section).
- ``list_category_account_names`` — same source filtered to expense/income
  kinds excluding the app's transfer accounts (legacy picker semantics).
- ``posting_counts_by_account`` — exact-name posting counts over non-archive
  files, the replacement for the ``ledger accounts --count`` parse.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from services.config_service import AppConfig
from services.reference_data_service import (
    list_account_names,
    list_category_account_names,
    posting_counts_by_account,
)


def _make_config(workspace: Path) -> AppConfig:
    for name in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / name).mkdir(parents=True, exist_ok=True)
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "base_currency": "USD", "start_year": 2026},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
        tracked_accounts={},
    )


ACCOUNTS_DAT = """\
account Assets:Checking
account Assets:Old Savings
    ; lf_closed:: [2026-03-31]
account Assets:Transfers:checking__savings
account Expenses:Groceries
account Income:Salary
"""

YEAR_2026 = """\
include ../rules/10-accounts.dat

2026-01-05 * Grocery Store
    Expenses:Groceries    USD 45.67
    Assets:Checking

2026-01-20 * Corner Cafe
    Expenses:Dining:Coffee    USD 4.50
    Assets:Checking
"""


def _workspace(tmp_path: Path) -> AppConfig:
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(ACCOUNTS_DAT, encoding="utf-8")
    (tmp_path / "journals" / "2026.journal").write_text(YEAR_2026, encoding="utf-8")
    return config


def test_all_accounts_include_used_and_ancestors_exclude_closed(tmp_path):
    config = _workspace(tmp_path)

    names = list_account_names(config)

    assert names == sorted(names)
    assert "Expenses:Dining:Coffee" in names  # used-only
    assert "Expenses:Dining" in names  # synthesized ancestor
    assert "Assets:Checking" in names
    assert "Assets:Old Savings" not in names  # closed
    assert "Income:Salary" in names  # declared-only


def test_category_accounts_filter_kind_and_transfers(tmp_path):
    config = _workspace(tmp_path)

    names = list_category_account_names(config)

    assert "Expenses:Groceries" in names
    assert "Expenses:Dining:Coffee" in names
    assert "Income:Salary" in names
    assert "Assets:Checking" not in names
    assert "Assets:Transfers:checking__savings" not in names


def test_posting_counts_by_exact_account_name(tmp_path):
    config = _workspace(tmp_path)

    counts = posting_counts_by_account(config)

    assert counts["Assets:Checking"] == 2
    assert counts["Expenses:Groceries"] == 1
    assert counts["Expenses:Dining:Coffee"] == 1
    assert "Expenses:Dining" not in counts  # no rollup, same as the CLI list
    assert counts["Assets:Old Savings"] == 0  # declared accounts listed at zero


@pytest.mark.skipif(shutil.which("ledger") is None, reason="ledger CLI not installed")
def test_posting_counts_agree_with_ledger_accounts_count(tmp_path):
    config = _workspace(tmp_path)

    output = subprocess.run(
        [
            "ledger",
            "-f",
            str(tmp_path / "journals" / "2026.journal"),
            "accounts",
            "--count",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={"LEDGER_DATE_FORMAT": "%Y-%m-%d", "PATH": "/usr/bin:/bin"},
    ).stdout
    cli_counts: dict[str, int] = {}
    for line in output.strip().splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            cli_counts[parts[1]] = int(parts[0])

    assert posting_counts_by_account(config) == cli_counts
