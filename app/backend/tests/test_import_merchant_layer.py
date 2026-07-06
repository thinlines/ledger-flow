"""Import pipeline merchant layer (issue #24).

Invariants under test (spec: docs/ledger-flow-projection-schema.md,
Merchant Layer section):

- The app — not ``ledger convert`` — matches statement text against
  ``payee_aliases``; the journal's payee line gets the canonical merchant
  name and the raw statement text is preserved as ``statement_payee``
  metadata.
- Dedupe identity is computed from the raw statement payee, so declaring an
  alias after a statement was imported never breaks duplicate detection.
- Categorization precedence at import is rule → merchant default account →
  ``Expenses:Unknown``.
"""
from __future__ import annotations

from pathlib import Path

from services.config_service import AppConfig
from services.import_service import apply_import, preview_import
from services.rules_service import create_rule, ensure_rules_store

PAYEES_DAT = """\
payee Walmart
    alias WAL-?MART
    ; lf_default_account: Expenses:Groceries
"""

CHASE_CSV = """\
Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
DEBIT,04/14/2026,WAL-MART #2734 PURCHASE    04/13 #000001234,-42.17,DEBIT_CARD,3812.44,
CREDIT,04/12/2026,SQ *CORNER CAFE OAKLAND,-8.25,DEBIT_CARD,3854.61,
"""


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2026, "base_currency": "USD"},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={
            "chase": {"encoding": "utf-8", "head": 0, "tail": 0}
        },
        import_accounts={
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Checking",
                "institution": "chase",
            }
        },
        tracked_accounts={},
    )


def _import_workspace(tmp_path: Path, payees_dat: str = PAYEES_DAT) -> tuple[AppConfig, Path]:
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(
        "account Assets:Checking\naccount Expenses:Groceries\n", encoding="utf-8"
    )
    (tmp_path / "rules" / "11-payees.dat").write_text(payees_dat, encoding="utf-8")
    (tmp_path / "rules" / "12-tags.dat").write_text("tag manual\n", encoding="utf-8")
    (tmp_path / "journals" / "2026.journal").write_text("", encoding="utf-8")
    csv_path = tmp_path / "inbox" / "2026__checking__statement.csv"
    csv_path.write_text(CHASE_CSV, encoding="utf-8")
    return config, csv_path


def _txn_by_statement_text(result: dict, fragment: str) -> dict:
    for txn in result["preparedTransactions"]:
        if fragment in txn["annotatedRaw"]:
            return txn
    raise AssertionError(f"no prepared transaction mentioning {fragment!r}")


def test_import_writes_canonical_merchant_name_and_preserves_statement_payee(tmp_path):
    config, csv_path = _import_workspace(tmp_path)

    result = preview_import(config, csv_path, "2026", "checking")

    matched = _txn_by_statement_text(result, "WAL-MART #2734")
    assert matched["payee"] == "Walmart"
    header = matched["annotatedRaw"].splitlines()[0]
    assert "Walmart" in header
    assert "WAL-MART" not in header
    assert "; statement_payee: WAL-MART #2734 PURCHASE    04/13 #000001234" in matched["annotatedRaw"]

    unmatched = _txn_by_statement_text(result, "CORNER CAFE")
    assert unmatched["payee"] == "SQ *CORNER CAFE OAKLAND"
    assert "; statement_payee: SQ *CORNER CAFE OAKLAND" in unmatched["annotatedRaw"]

    # The retired payee-alias CSV/generated-dat path stays retired: import
    # no longer conjures those files.
    assert not (tmp_path / "rules" / "payee_aliases.csv").exists()
    assert not (tmp_path / "rules" / "payee_aliases.dat").exists()


def test_alias_declared_after_import_never_reimports_old_rows(tmp_path):
    """Identity is keyed to the raw statement payee: a re-export of the same
    transaction (different bytes, so ledger's UUID dedupe misses it) still
    dedupes after an alias is declared and the preview payee is rewritten."""
    config, csv_path = _import_workspace(tmp_path, payees_dat="")

    first = preview_import(config, csv_path, "2026", "checking")
    assert all(txn["matchStatus"] == "new" for txn in first["preparedTransactions"])
    apply_import(config, first)

    (tmp_path / "rules" / "11-payees.dat").write_text(PAYEES_DAT, encoding="utf-8")
    # Same transactions, re-exported with drifted description whitespace:
    # different bytes (new UUID) but the same normalized statement payee.
    csv_path.write_text(
        CHASE_CSV.replace("PURCHASE    04/13", "PURCHASE 04/13"), encoding="utf-8"
    )
    second = preview_import(config, csv_path, "2026", "checking")

    walmart = _txn_by_statement_text(second, "WAL-MART #2734")
    assert walmart["payee"] == "Walmart"
    assert walmart["matchStatus"] != "new"
    assert second["summary"]["newCount"] == 0


CATEGORIZE_CSV = """\
Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
DEBIT,04/14/2026,WAL-MART #2734 PURCHASE,-42.17,DEBIT_CARD,3812.44,
DEBIT,04/12/2026,SQ *CORNER CAFE OAKLAND,-8.25,DEBIT_CARD,3854.61,
DEBIT,04/10/2026,MYSTERY VENDOR LLC,-19.99,DEBIT_CARD,3862.86,
"""


def _category_posting(txn: dict) -> str:
    accounts = [
        p["account"] for p in txn["postings"] if p["account"] != "Assets:Checking"
    ]
    assert len(accounts) == 1, txn["postings"]
    return accounts[0]


def test_import_categorizes_rule_then_merchant_default_then_unknown(tmp_path):
    config, csv_path = _import_workspace(tmp_path)
    csv_path.write_text(CATEGORIZE_CSV, encoding="utf-8")
    rules_path = ensure_rules_store(
        config.init_dir, config.init_dir / "10-accounts.dat"
    )
    create_rule(
        rules_path,
        [{"field": "payee", "operator": "contains", "value": "CORNER CAFE"}],
        actions=[{"type": "set_account", "account": "Expenses:Dining:Coffee"}],
    )

    result = preview_import(config, csv_path, "2026", "checking")

    by_rule = _txn_by_statement_text(result, "CORNER CAFE")
    assert _category_posting(by_rule) == "Expenses:Dining:Coffee"

    by_merchant_default = _txn_by_statement_text(result, "WAL-MART")
    assert _category_posting(by_merchant_default) == "Expenses:Groceries"

    uncategorized = _txn_by_statement_text(result, "MYSTERY VENDOR")
    assert _category_posting(uncategorized) == "Expenses:Unknown"
    assert result["summary"]["unknownCount"] == 1


def test_rule_wins_over_merchant_default_account(tmp_path):
    config, csv_path = _import_workspace(tmp_path)
    rules_path = ensure_rules_store(
        config.init_dir, config.init_dir / "10-accounts.dat"
    )
    create_rule(
        rules_path,
        [{"field": "payee", "operator": "exact", "value": "Walmart"}],
        actions=[{"type": "set_account", "account": "Expenses:Household"}],
    )

    result = preview_import(config, csv_path, "2026", "checking")

    walmart = _txn_by_statement_text(result, "WAL-MART")
    assert _category_posting(walmart) == "Expenses:Household"
