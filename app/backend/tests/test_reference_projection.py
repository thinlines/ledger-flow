"""Reference data projection (issue #18).

Invariants under test (spec: docs/ledger-flow-projection-schema.md,
Reference Data section):

- Directive files project into ``accounts`` / ``payees`` / ``payee_aliases``
  / ``tags`` / ``commodities`` with ``declared`` flags and directive-block
  ``lf_`` metadata (subtype, close date, merchant default account).
- Usage (postings, transaction payees, ``:flag:`` tags, posting commodities)
  is unioned in with ``used`` flags; ancestors of used accounts are
  synthesized so the account tree is complete.
- ``used AND NOT declared`` accounts/tags/commodities produce
  ``journal_diagnostics`` rows carrying the first usage site's file/line —
  the ``--pedantic`` checks, computed in SQL. Undeclared payees are allowed.
- Reference tables are wiped and re-derived on refresh: external edits and
  deletions never leave stale rows behind.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from services.config_service import AppConfig
from services.projection_db import database_path
from services.projection_service import refresh_projection


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
    note Main checking account
account Liabilities:Credit Card
    ; lf_subtype: credit_card
    ; lf_closed:: [2026-05-31]
account Expenses:Groceries
account Income:Salary
account Equity:Opening Balances

payee Walmart
    alias WAL-?MART
    alias WALMART\\.COM
    ; lf_default_account: Expenses:Groceries

tag manual

commodity USD
    format USD 1,000.00
"""

YEAR_2026 = """\
include ../rules/10-accounts.dat

2026-01-05 * Grocery Store
    ; :manual:
    Expenses:Groceries    USD 45.67
    Assets:Checking

2026-01-20 * Corner Cafe
    ; :coffee-club:
    Expenses:Dining:Coffee    USD 4.50
    Assets:Checking

2026-02-01 * Forex Kiosk
    Expenses:Travel    EUR 20.00
    Assets:Checking    EUR -20.00
"""


def _workspace(tmp_path: Path) -> AppConfig:
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(ACCOUNTS_DAT, encoding="utf-8")
    (tmp_path / "journals" / "2026.journal").write_text(YEAR_2026, encoding="utf-8")
    return config


def _connect(config: AppConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path(config))
    conn.row_factory = sqlite3.Row
    return conn


def _account(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM accounts WHERE name = ?", (name,)).fetchone()
    assert row is not None, f"no accounts row for {name}"
    return row


# ---------------------------------------------------------------------------
# Declarations


def test_declared_accounts_project_with_derived_hierarchy(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        checking = _account(conn, "Assets:Checking")
        assert checking["declared"] == 1
        assert checking["account_type"] == "assets"
        assert checking["parent_name"] == "Assets"
        assert checking["depth"] == 1
        assert checking["note"] == "Main checking account"
        assert checking["closed_on"] is None

        card = _account(conn, "Liabilities:Credit Card")
        assert card["account_type"] == "liabilities"
        assert card["subtype"] == "credit_card"
        assert card["closed_on"] == "2026-05-31"

        # The declaring file is recorded so edits re-point cleanly.
        declared_file = conn.execute(
            """
            SELECT journal_files.path FROM accounts
            JOIN journal_files ON journal_files.id = accounts.journal_file_id
            WHERE accounts.name = 'Assets:Checking'
            """
        ).fetchone()
        assert declared_file["path"] == "rules/10-accounts.dat"


def test_declared_payees_project_with_aliases_in_order(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        payee = conn.execute(
            "SELECT * FROM payees WHERE name = 'Walmart'"
        ).fetchone()
        assert payee is not None
        assert payee["declared"] == 1
        assert payee["default_account"] == "Expenses:Groceries"

        aliases = conn.execute(
            """
            SELECT pattern, alias_order FROM payee_aliases
            WHERE payee_id = ? ORDER BY alias_order
            """,
            (payee["id"],),
        ).fetchall()
        assert [(a["pattern"], a["alias_order"]) for a in aliases] == [
            ("WAL-?MART", 0),
            ("WALMART\\.COM", 1),
        ]


def test_declared_tags_and_commodities_project(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        tag = conn.execute("SELECT * FROM tags WHERE name = 'manual'").fetchone()
        assert tag is not None
        assert tag["declared"] == 1

        usd = conn.execute(
            "SELECT * FROM commodities WHERE symbol = 'USD'"
        ).fetchone()
        assert usd is not None
        assert usd["declared"] == 1
        assert usd["format"] == "USD 1,000.00"
        assert usd["display_scale"] == 2


# ---------------------------------------------------------------------------
# Usage union


def test_used_accounts_union_with_declarations(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        groceries = _account(conn, "Expenses:Groceries")
        assert (groceries["declared"], groceries["used"]) == (1, 1)

        salary = _account(conn, "Income:Salary")
        assert (salary["declared"], salary["used"]) == (1, 0)

        coffee = _account(conn, "Expenses:Dining:Coffee")
        assert (coffee["declared"], coffee["used"]) == (0, 1)


def test_ancestors_of_used_accounts_are_synthesized(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        dining = _account(conn, "Expenses:Dining")
        assert (dining["declared"], dining["used"]) == (0, 1)
        assert dining["parent_name"] == "Expenses"
        assert dining["depth"] == 1

        expenses = _account(conn, "Expenses")
        assert expenses["parent_name"] is None
        assert expenses["depth"] == 0


def test_used_payees_tags_and_commodities_union(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        rows = {
            row["name"]: row
            for row in conn.execute("SELECT * FROM payees").fetchall()
        }
        assert (rows["Walmart"]["declared"], rows["Walmart"]["used"]) == (1, 0)
        grocery = rows["Grocery Store"]
        assert (grocery["declared"], grocery["used"]) == (0, 1)

        manual = conn.execute("SELECT * FROM tags WHERE name = 'manual'").fetchone()
        assert (manual["declared"], manual["used"]) == (1, 1)
        club = conn.execute("SELECT * FROM tags WHERE name = 'coffee-club'").fetchone()
        assert club is not None
        assert (club["declared"], club["used"]) == (0, 1)

        eur = conn.execute("SELECT * FROM commodities WHERE symbol = 'EUR'").fetchone()
        assert eur is not None
        assert (eur["declared"], eur["used"]) == (0, 1)
        assert eur["display_scale"] == 2
        usd = conn.execute("SELECT * FROM commodities WHERE symbol = 'USD'").fetchone()
        assert (usd["declared"], usd["used"]) == (1, 1)


# ---------------------------------------------------------------------------
# Pedantic diagnostics


def _reference_diagnostics(conn: sqlite3.Connection) -> dict[tuple[str, str], sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT * FROM journal_diagnostics
        WHERE code IN ('undeclared_account', 'undeclared_tag', 'undeclared_commodity')
        """
    ).fetchall()
    keyed = {}
    for row in rows:
        name = row["message"].split("'")[1]
        keyed[(row["code"], name)] = row
    return keyed


def test_undeclared_usage_diagnostics_carry_first_usage_site(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        diags = _reference_diagnostics(conn)

    account_diag = diags[("undeclared_account", "Expenses:Dining:Coffee")]
    assert account_diag["path"] == "journals/2026.journal"
    assert account_diag["line_number"] == 10  # the Coffee posting line
    assert account_diag["severity"] == "warning"
    assert account_diag["blocking"] == 0

    tag_diag = diags[("undeclared_tag", "coffee-club")]
    assert tag_diag["path"] == "journals/2026.journal"

    commodity_diag = diags[("undeclared_commodity", "EUR")]
    assert commodity_diag["path"] == "journals/2026.journal"
    assert commodity_diag["line_number"] == 14  # first EUR posting line


def test_synthesized_ancestors_and_payees_do_not_diagnose(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        diags = _reference_diagnostics(conn)
        payee_diag_count = conn.execute(
            "SELECT COUNT(*) FROM journal_diagnostics WHERE code = 'undeclared_payee'"
        ).fetchone()[0]

    assert ("undeclared_account", "Expenses:Dining") not in diags
    assert ("undeclared_account", "Expenses:Travel") in diags
    assert payee_diag_count == 0


def test_declaring_the_account_clears_its_diagnostic(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)

    dat = tmp_path / "rules" / "10-accounts.dat"
    dat.write_text(
        dat.read_text(encoding="utf-8")
        + "account Expenses:Dining:Coffee\naccount Expenses:Travel\ncommodity EUR\ntag coffee-club\n",
        encoding="utf-8",
    )
    refresh_projection(config)

    with _connect(config) as conn:
        diags = _reference_diagnostics(conn)
        coffee = _account(conn, "Expenses:Dining:Coffee")

    assert diags == {}
    assert (coffee["declared"], coffee["used"]) == (1, 1)


def test_refresh_is_idempotent_for_reference_rows_and_diagnostics(tmp_path):
    config = _workspace(tmp_path)
    refresh_projection(config)
    refresh_projection(config)
    refresh_projection(config)

    with _connect(config) as conn:
        account_count = conn.execute(
            "SELECT COUNT(*) FROM accounts GROUP BY name ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()[0]
        diag_count = conn.execute(
            """
            SELECT COUNT(*) FROM journal_diagnostics
            WHERE code = 'undeclared_account'
              AND message LIKE '%Expenses:Dining:Coffee%'
            """
        ).fetchone()[0]

    assert account_count == 1
    assert diag_count == 1
