"""Account declaration lifecycle edits (issue #19).

Invariants under test (spec: docs/ledger-flow-projection-schema.md, Account
Lifecycle section):

- ``set_subtype`` / ``close_account`` / ``reopen_account`` rewrite only the
  target ``account`` block's ``lf_`` metadata lines in the declaring
  directive file; every other byte is preserved.
- Undeclared accounts are auto-declared when subtype/close is set; clearing
  metadata on an undeclared account is a no-op.
- After an edit the projection reflects it without a manual refresh:
  ``accounts.subtype`` / ``accounts.closed_on`` update, closed accounts
  leave the picker lists but keep their postings and posting counts.
- Deletion is allowed only when no posting (any file role, archive included)
  references the account or a descendant and the account is not a
  tracked/import ledger account; allowed deletes remove the block and leave
  used-only/ancestor rows intact.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services.account_declaration_service import (
    AccountNotDeclared,
    DeclarationInUse,
    close_account,
    delete_declaration,
    reopen_account,
    set_subtype,
)
from services.config_service import AppConfig
from services.projection_db import database_path
from services.projection_service import refresh_projection
from services.reference_data_service import (
    list_account_names,
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
; House accounts — hand comment stays put.
account Assets:Checking
    note Main checking account
account Assets:Old Savings
    ; lf_closed:: [2026-03-31]
account Liabilities:Credit Card
    ; lf_subtype: credit_card
account Expenses:Groceries
\tpayee Grocery Store

account Expenses:DVDs
account Income:Salary
"""

EXTRA_DAT = """\
account Assets:Brokerage
    note Held elsewhere
"""

YEAR_2026 = """\
include ../rules/10-accounts.dat
include ../rules/11-extra.dat

2026-01-05 * Grocery Store
    Expenses:Groceries    USD 45.67
    Assets:Checking

2026-01-20 * Corner Cafe
    Expenses:Dining:Coffee    USD 4.50
    Assets:Old Savings
"""

ARCHIVE_2020 = """\
2020-03-03 * Ancient Vendor
    Expenses:Archived Only    USD 9.99
    Assets:Checking
"""


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(ACCOUNTS_DAT, encoding="utf-8")
    (tmp_path / "rules" / "11-extra.dat").write_text(EXTRA_DAT, encoding="utf-8")
    (tmp_path / "journals" / "2026.journal").write_text(YEAR_2026, encoding="utf-8")
    refresh_projection(config)
    return config


def _dat(config: AppConfig, name: str = "10-accounts.dat") -> str:
    return (config.init_dir / name).read_text(encoding="utf-8")


def _account_row(config: AppConfig, name: str) -> sqlite3.Row | None:
    with sqlite3.connect(database_path(config)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM accounts WHERE name = ?", (name,)
        ).fetchone()


# ---------------------------------------------------------------------------
# Subtype


def test_set_subtype_inserts_metadata_line_and_projects(config):
    set_subtype(config, "Assets:Checking", "checking")

    text = _dat(config)
    assert "account Assets:Checking\n    ; lf_subtype: checking\n" in text
    # The note subdirective survives inside the same block.
    assert "    note Main checking account\n" in text

    row = _account_row(config, "Assets:Checking")
    assert row["subtype"] == "checking"


def test_set_subtype_replaces_existing_line(config):
    set_subtype(config, "Liabilities:Credit Card", "loan")

    text = _dat(config)
    assert text.count("lf_subtype") == 1
    assert "account Liabilities:Credit Card\n    ; lf_subtype: loan\n" in text
    assert _account_row(config, "Liabilities:Credit Card")["subtype"] == "loan"


def test_set_subtype_none_removes_line(config):
    set_subtype(config, "Liabilities:Credit Card", None)

    assert "lf_subtype" not in _dat(config)
    assert _account_row(config, "Liabilities:Credit Card")["subtype"] is None


def test_set_subtype_auto_declares_undeclared_account(config):
    # Used but undeclared (posting only).
    set_subtype(config, "Expenses:Dining:Coffee", "other_asset")

    text = _dat(config)
    assert "account Expenses:Dining:Coffee" in text
    row = _account_row(config, "Expenses:Dining:Coffee")
    assert row["declared"] == 1
    assert row["subtype"] == "other_asset"


def test_set_subtype_none_on_undeclared_account_is_noop(config):
    before = _dat(config)
    set_subtype(config, "Expenses:Dining:Coffee", None)
    assert _dat(config) == before
    assert _account_row(config, "Expenses:Dining:Coffee")["declared"] == 0


def test_set_subtype_edits_the_declaring_file_not_default_dat(config):
    set_subtype(config, "Assets:Brokerage", "investment")

    assert "lf_subtype: investment" in _dat(config, "11-extra.dat")
    assert "Brokerage" not in _dat(config)
    assert _account_row(config, "Assets:Brokerage")["subtype"] == "investment"


def test_set_subtype_preserves_every_other_byte(config):
    before = _dat(config)
    set_subtype(config, "Expenses:DVDs", "other_asset")
    after = _dat(config)

    inserted = "    ; lf_subtype: other_asset\n"
    assert after.count(inserted) == 1
    assert after.replace(inserted, "", 1) == before


# ---------------------------------------------------------------------------
# Close / reopen


def test_close_account_writes_typed_metadata_and_hides_from_pickers(config):
    assert "Expenses:Groceries" in list_account_names(config)

    close_account(config, "Expenses:Groceries", "2026-06-30")

    text = _dat(config)
    assert "account Expenses:Groceries\n    ; lf_closed:: [2026-06-30]\n" in text
    # The rule payee line inside the block survives.
    assert "\tpayee Grocery Store\n" in text

    row = _account_row(config, "Expenses:Groceries")
    assert row["closed_on"] == "2026-06-30"
    assert "Expenses:Groceries" not in list_account_names(config)


def test_closed_account_keeps_history_and_counts(config):
    close_account(config, "Expenses:Groceries", "2026-06-30")

    counts = posting_counts_by_account(config)
    assert counts["Expenses:Groceries"] == 1

    with sqlite3.connect(database_path(config)) as conn:
        postings = conn.execute(
            "SELECT COUNT(*) FROM postings WHERE account = 'Expenses:Groceries'"
        ).fetchone()[0]
    assert postings == 1


def test_close_account_replaces_existing_close_date(config):
    close_account(config, "Assets:Old Savings", "2026-06-30")

    text = _dat(config)
    assert text.count("lf_closed") == 1
    assert "    ; lf_closed:: [2026-06-30]\n" in text
    assert _account_row(config, "Assets:Old Savings")["closed_on"] == "2026-06-30"


def test_close_auto_declares_undeclared_account(config):
    close_account(config, "Expenses:Dining:Coffee", "2026-06-30")

    row = _account_row(config, "Expenses:Dining:Coffee")
    assert row["declared"] == 1
    assert row["closed_on"] == "2026-06-30"
    assert "Expenses:Dining:Coffee" not in list_account_names(config)


def test_reopen_account_removes_close_line(config):
    assert "Assets:Old Savings" not in list_account_names(config)

    reopen_account(config, "Assets:Old Savings")

    assert "lf_closed" not in _dat(config)
    assert _account_row(config, "Assets:Old Savings")["closed_on"] is None
    assert "Assets:Old Savings" in list_account_names(config)


def test_reopen_account_without_close_is_noop(config):
    before = _dat(config)
    reopen_account(config, "Assets:Checking")
    assert _dat(config) == before


def test_close_then_reopen_round_trip_is_byte_identical(config):
    before = _dat(config)
    close_account(config, "Expenses:DVDs", "2026-06-30")
    reopen_account(config, "Expenses:DVDs")
    assert _dat(config) == before


# ---------------------------------------------------------------------------
# Guarded delete


def test_delete_blocked_by_direct_posting(config):
    before = _dat(config)
    with pytest.raises(DeclarationInUse) as excinfo:
        delete_declaration(config, "Expenses:Groceries")
    assert excinfo.value.posting_count == 1
    assert "Expenses:Groceries" in excinfo.value.reason
    assert _dat(config) == before


def test_delete_blocked_by_descendant_posting(tmp_path):
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(
        "account Expenses:Dining\n", encoding="utf-8"
    )
    (tmp_path / "journals" / "2026.journal").write_text(
        "include ../rules/10-accounts.dat\n\n"
        "2026-01-20 * Corner Cafe\n"
        "    Expenses:Dining:Coffee    USD 4.50\n"
        "    Assets:Checking\n",
        encoding="utf-8",
    )
    refresh_projection(config)

    with pytest.raises(DeclarationInUse) as excinfo:
        delete_declaration(config, "Expenses:Dining")
    assert excinfo.value.posting_count == 1


def test_delete_blocked_by_archive_posting(tmp_path):
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(
        "account Expenses:Archived Only\n", encoding="utf-8"
    )
    (tmp_path / "journals" / "2026.journal").write_text(
        "include ../rules/10-accounts.dat\ninclude archived-manual.journal\n",
        encoding="utf-8",
    )
    (tmp_path / "journals" / "archived-manual.journal").write_text(
        ARCHIVE_2020, encoding="utf-8"
    )
    refresh_projection(config)

    with pytest.raises(DeclarationInUse) as excinfo:
        delete_declaration(config, "Expenses:Archived Only")
    assert excinfo.value.posting_count == 1


def test_delete_blocked_for_tracked_ledger_account(config):
    config.tracked_accounts["dvds"] = {
        "display_name": "DVD fund",
        "ledger_account": "Expenses:DVDs",
    }
    with pytest.raises(DeclarationInUse) as excinfo:
        delete_declaration(config, "Expenses:DVDs")
    assert "tracked" in excinfo.value.reason
    assert excinfo.value.posting_count == 0


def test_delete_undeclared_account_raises_not_found(config):
    with pytest.raises(AccountNotDeclared):
        delete_declaration(config, "Expenses:Dining:Coffee")


def test_delete_unused_declaration_removes_block_and_row(config):
    assert _account_row(config, "Expenses:DVDs")["declared"] == 1

    delete_declaration(config, "Expenses:DVDs")

    text = _dat(config)
    assert "Expenses:DVDs" not in text
    assert _account_row(config, "Expenses:DVDs") is None

    # Usage-derived rows survive the rebuild untouched.
    coffee = _account_row(config, "Expenses:Dining:Coffee")
    assert coffee is not None and coffee["used"] == 1
    assert _account_row(config, "Expenses:Dining")["used"] == 1


def test_delete_removes_only_the_block_bytes(config):
    before = _dat(config)
    delete_declaration(config, "Expenses:DVDs")
    assert _dat(config) == before.replace("account Expenses:DVDs\n", "")


def test_delete_block_with_metadata_removes_whole_block(tmp_path):
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(
        "account Assets:Checking\n"
        "\n"
        "account Assets:Stale\n"
        "    note Old account\n"
        "    ; lf_subtype: savings\n"
        "\n"
        "account Income:Salary\n",
        encoding="utf-8",
    )
    (tmp_path / "journals" / "2026.journal").write_text(
        "include ../rules/10-accounts.dat\n", encoding="utf-8"
    )
    refresh_projection(config)

    delete_declaration(config, "Assets:Stale")

    assert _dat(config) == "account Assets:Checking\n\naccount Income:Salary\n"


def test_edits_preserve_missing_trailing_newline(config):
    path = config.init_dir / "11-extra.dat"
    path.write_text(EXTRA_DAT.rstrip("\n"), encoding="utf-8")
    refresh_projection(config)

    set_subtype(config, "Assets:Brokerage", "investment")

    text = _dat(config, "11-extra.dat")
    assert "account Assets:Brokerage\n    ; lf_subtype: investment\n" in text
    assert text.endswith("    note Held elsewhere")
    assert not text.endswith("\n")
