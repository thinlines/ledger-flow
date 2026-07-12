"""Slice 2/3: golden projection tests.

Invariants under test (spec: docs/ledger-flow-projection-schema.md):

- Round-trip: rendering any projected file from ``journal_items`` is
  byte-identical to the file on disk.
- Structure: transactions, postings, comments, metadata entries, and file
  roles project as the spec describes, with integer nanounit amounts.
- Rebuild: refresh re-projects only changed files; a full rebuild is
  equivalent; deleted files disappear from the projection.
- Passive rebuild never assigns missing ``lf_`` ids and never writes to
  journal files; an existing ``lf_txn_id`` is adopted as the transaction id.
- Unsupported constructs degrade to preserved-raw blocks plus diagnostics
  instead of blocking the projection.
- Ledger CLI parity: nanounit sums per account agree with ``ledger bal``.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
from decimal import Decimal
from pathlib import Path

from services.config_service import AppConfig
from services.journal_block_service import hash_block_text
from services.projection_db import database_path, ensure_database
from services.projection_service import (
    find_projected_transaction_match,
    refresh_projection,
    rebuild_projection,
    render_file,
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
    note Main checking account
account Expenses:Groceries
account Expenses:Coffee
account Income:Salary
account Equity:Opening Balances

tag manual

commodity USD
    format USD 1,000.00
"""

OPENING_INDEX = """\
include checking.journal
"""

# Deliberately no trailing newline (round-trip must preserve that).
OPENING_CHECKING = """\
2026-01-01 * Opening Balance
    ; tracked_account_id: checking
    Assets:Checking    USD 100.00
    Equity:Opening Balances"""

YEAR_2026 = """\
; Year 2026 journal — file-level comment
include ../rules/10-accounts.dat
include ../opening/_opening_balances.journal

2026-01-05 * Grocery Store 超市
    ; lf_source_identity: abc123
    ; effective_date:: [2026-01-06]
    Expenses:Groceries    USD 45.67
    Assets:Checking
        ; note with trailing spaces

2026-01-10 ! Pending Coffee
    ; :manual:
    Expenses:Coffee    USD 4.50
    Assets:Checking    USD -4.50

2026-02-01 (JAN-PAY) Salary
    Assets:Checking    USD 1,500.00
    Income:Salary
"""

YEAR_2027 = """\
include ../rules/10-accounts.dat

2027-01-15 * Carried Forward
    ; lf_txn_id: txn_existing_id_01
    Expenses:Coffee    USD 2.25
    Assets:Checking
"""

ARCHIVED_MANUAL = """\
2026-01-10 ! Pending Coffee
    ; match-id: m1
    Expenses:Coffee    USD 4.50
    Assets:Checking
"""


def test_matched_transactions_rebuild_as_a_queryable_relationship(tmp_path):
    config = _make_config(tmp_path)
    (tmp_path / "journals" / "2026.journal").write_text(
        """2026-03-15 Whole Foods Imported
    ; lf_txn_id: txn_imported
    ; lf_match_id: match_01JZ0000000000000000000000
    Expenses:Groceries    USD 42.00
    Assets:Checking
""",
        encoding="utf-8",
    )
    (tmp_path / "journals" / "archived-manual.journal").write_text(
        """2026-03-14 Whole Foods Manual
    ; lf_txn_id: txn_manual
    ; lf_match_id: match_01JZ0000000000000000000000
    ; :manual:
    Expenses:Groceries    USD 42.00
    Assets:Checking
""",
        encoding="utf-8",
    )

    refresh_projection(config)

    match = find_projected_transaction_match(
        config, "match_01JZ0000000000000000000000"
    )
    assert match is not None
    assert match.imported_transaction_id == "txn_imported"
    assert match.archived_manual_transaction_id == "txn_manual"


def _golden_workspace(tmp_path: Path) -> AppConfig:
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(ACCOUNTS_DAT, encoding="utf-8")
    (tmp_path / "opening" / "_opening_balances.journal").write_text(
        OPENING_INDEX, encoding="utf-8"
    )
    (tmp_path / "opening" / "checking.journal").write_text(
        OPENING_CHECKING, encoding="utf-8"
    )
    (tmp_path / "journals" / "2026.journal").write_text(YEAR_2026, encoding="utf-8")
    (tmp_path / "journals" / "2027.journal").write_text(YEAR_2027, encoding="utf-8")
    (tmp_path / "journals" / "archived-manual.journal").write_text(
        ARCHIVED_MANUAL, encoding="utf-8"
    )
    return config


def _connect(config: AppConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path(config))
    conn.row_factory = sqlite3.Row
    return conn


def _file_row(conn: sqlite3.Connection, rel_path: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM journal_files WHERE path = ?", (rel_path,)
    ).fetchone()
    assert row is not None, f"no journal_files row for {rel_path}"
    return row


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip_every_file_byte_identical(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        paths = [
            row["path"]
            for row in conn.execute("SELECT path FROM journal_files").fetchall()
        ]
    assert sorted(paths) == [
        "journals/2026.journal",
        "journals/2027.journal",
        "journals/archived-manual.journal",
        "opening/_opening_balances.journal",
        "opening/checking.journal",
        "rules/10-accounts.dat",
    ]
    for rel_path in paths:
        rendered = render_file(config, rel_path)
        on_disk = (config.root_dir / rel_path).read_text(encoding="utf-8")
        assert rendered == on_disk, f"round-trip mismatch for {rel_path}"


def test_projection_does_not_write_journals(tmp_path):
    config = _golden_workspace(tmp_path)
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.rglob("*")
        if path.is_file() and path.suffix in {".journal", ".dat"}
    }

    refresh_projection(config)

    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in before
    }
    assert before == after


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_file_roles(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        roles = {
            row["path"]: row["role"]
            for row in conn.execute("SELECT path, role FROM journal_files").fetchall()
        }
    assert roles == {
        "journals/2026.journal": "journal",
        "journals/2027.journal": "journal",
        "journals/archived-manual.journal": "archive",
        "opening/_opening_balances.journal": "opening",
        "opening/checking.journal": "opening",
        "rules/10-accounts.dat": "directives",
    }


def test_transactions_and_postings_project_with_nanounits(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        file_id = _file_row(conn, "journals/2026.journal")["id"]
        txns = conn.execute(
            "SELECT * FROM transactions WHERE journal_file_id = ? ORDER BY txn_order",
            (file_id,),
        ).fetchall()
        assert [t["payee"] for t in txns] == [
            "Grocery Store 超市",
            "Pending Coffee",
            "Salary",
        ]
        assert [t["date"] for t in txns] == ["2026-01-05", "2026-01-10", "2026-02-01"]
        assert [t["status"] for t in txns] == ["cleared", "pending", "unmarked"]
        assert [t["parse_status"] for t in txns] == ["ok", "ok", "ok"]
        assert txns[2]["code"] == "(JAN-PAY)"

        grocery = txns[0]
        grocery_raw = conn.execute(
            """
            SELECT raw_text FROM journal_items
            WHERE transaction_id = ?
            """,
            (grocery["id"],),
        ).fetchone()["raw_text"]
        assert grocery["raw_block_hash"] == hash_block_text(grocery_raw)
        postings = conn.execute(
            "SELECT * FROM postings WHERE transaction_id = ? ORDER BY posting_order",
            (grocery["id"],),
        ).fetchall()
        assert [(p["account"], p["amount_nano"], p["commodity"]) for p in postings] == [
            ("Expenses:Groceries", 45_670_000_000, "USD"),
            ("Assets:Checking", -45_670_000_000, "USD"),
        ]
        assert postings[0]["amount_inferred"] == 0
        assert postings[1]["amount_inferred"] == 1

        salary_postings = conn.execute(
            "SELECT amount_nano FROM postings WHERE transaction_id = ? ORDER BY posting_order",
            (txns[2]["id"],),
        ).fetchall()
        assert salary_postings[0]["amount_nano"] == 1_500_000_000_000


def test_comments_and_metadata_project(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        file_id = _file_row(conn, "journals/2026.journal")["id"]
        txns = conn.execute(
            "SELECT * FROM transactions WHERE journal_file_id = ? ORDER BY txn_order",
            (file_id,),
        ).fetchall()
        grocery, coffee = txns[0], txns[1]

        meta = conn.execute(
            """
            SELECT key, value_text, value_type, value_date
            FROM metadata_entries WHERE owner_type = 'transaction' AND owner_id = ?
            ORDER BY source_order
            """,
            (grocery["id"],),
        ).fetchall()
        by_key = {m["key"]: m for m in meta}
        assert by_key["lf_source_identity"]["value_type"] == "string"
        assert by_key["lf_source_identity"]["value_text"] == "abc123"
        assert by_key["effective_date"]["value_type"] == "date"
        assert by_key["effective_date"]["value_date"] == "2026-01-06"

        tag = conn.execute(
            """
            SELECT parse_status, parsed_key FROM comments
            WHERE owner_type = 'transaction' AND owner_id = ? AND parse_status = 'tag'
            """,
            (coffee["id"],),
        ).fetchone()
        assert tag is not None
        assert tag["parsed_key"] == "manual"

        posting_comment = conn.execute(
            """
            SELECT comments.raw_text, comments.source_location
            FROM comments
            JOIN postings ON postings.id = comments.owner_id
            WHERE comments.owner_type = 'posting' AND postings.transaction_id = ?
            """,
            (grocery["id"],),
        ).fetchone()
        assert posting_comment is not None
        assert posting_comment["source_location"] == "posting_comment"
        assert "note with trailing spaces" in posting_comment["raw_text"]


def test_includes_project_each_physical_file_once(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        # The accounts .dat is included by both year journals but projected once.
        count = conn.execute(
            "SELECT COUNT(*) FROM journal_files WHERE path = 'rules/10-accounts.dat'"
        ).fetchone()[0]
        assert count == 1

        opening_id = _file_row(conn, "opening/checking.journal")["id"]
        opening_txns = conn.execute(
            "SELECT payee FROM transactions WHERE journal_file_id = ?",
            (opening_id,),
        ).fetchall()
        assert [t["payee"] for t in opening_txns] == ["Opening Balance"]

        include_items = conn.execute(
            """
            SELECT COUNT(*) FROM journal_items
            WHERE journal_file_id = ? AND item_type = 'include'
            """,
            (_file_row(conn, "journals/2026.journal")["id"],),
        ).fetchone()[0]
        assert include_items == 2

        directive_items = conn.execute(
            """
            SELECT COUNT(*) FROM journal_items
            WHERE journal_file_id = ? AND item_type = 'directive'
            """,
            (_file_row(conn, "rules/10-accounts.dat")["id"],),
        ).fetchone()[0]
        # account x5, tag, commodity
        assert directive_items == 7


def test_existing_lf_txn_id_is_adopted_and_none_are_minted(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)

    with _connect(config) as conn:
        adopted = conn.execute(
            "SELECT id FROM transactions WHERE payee = 'Carried Forward'"
        ).fetchone()
        assert adopted["id"] == "txn_existing_id_01"

    # Journals on disk still contain exactly one lf_txn_id (the pre-existing one).
    occurrences = 0
    for path in (tmp_path / "journals").glob("*.journal"):
        occurrences += path.read_text(encoding="utf-8").count("lf_txn_id")
    for path in (tmp_path / "opening").glob("*.journal"):
        occurrences += path.read_text(encoding="utf-8").count("lf_txn_id")
    assert occurrences == 1


# ---------------------------------------------------------------------------
# Rebuild / refresh
# ---------------------------------------------------------------------------


def test_refresh_projects_only_changed_files(tmp_path):
    config = _golden_workspace(tmp_path)
    first = refresh_projection(config)
    assert sorted(first["projected"]) == [
        "journals/2026.journal",
        "journals/2027.journal",
        "journals/archived-manual.journal",
        "opening/_opening_balances.journal",
        "opening/checking.journal",
        "rules/10-accounts.dat",
    ]

    second = refresh_projection(config)
    assert second["projected"] == []
    assert sorted(second["unchanged"]) == sorted(first["projected"])

    year_path = tmp_path / "journals" / "2026.journal"
    year_path.write_text(
        year_path.read_text(encoding="utf-8")
        + "\n2026-03-01 * Late Addition\n"
        "    Expenses:Coffee    USD 3.00\n"
        "    Assets:Checking\n",
        encoding="utf-8",
    )

    third = refresh_projection(config)
    assert third["projected"] == ["journals/2026.journal"]

    with _connect(config) as conn:
        file_id = _file_row(conn, "journals/2026.journal")["id"]
        count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE journal_file_id = ?",
            (file_id,),
        ).fetchone()[0]
    assert count == 4


def test_full_rebuild_equals_refreshed_state(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)
    year_path = tmp_path / "journals" / "2026.journal"
    year_path.write_text(
        year_path.read_text(encoding="utf-8")
        + "\n2026-03-01 * Late Addition\n"
        "    Expenses:Coffee    USD 3.00\n"
        "    Assets:Checking\n",
        encoding="utf-8",
    )
    refresh_projection(config)

    def _dump(conn: sqlite3.Connection) -> dict:
        tables = [
            "journal_files",
            "journal_items",
            "transactions",
            "postings",
            "comments",
            "metadata_entries",
        ]
        out = {}
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            out[table] = sorted(
                tuple(
                    value
                    for key, value in dict(row).items()
                    if key != "parsed_at"
                )
                for row in rows
            )
        return out

    with _connect(config) as conn:
        incremental = _dump(conn)

    rebuild_projection(config)
    with _connect(config) as conn:
        rebuilt = _dump(conn)

    assert incremental == rebuilt


def test_deleted_file_is_removed_from_projection(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)

    (tmp_path / "journals" / "2027.journal").unlink()
    result = refresh_projection(config)
    assert result["removed"] == ["journals/2027.journal"]

    with _connect(config) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM journal_files WHERE path = 'journals/2027.journal'"
        ).fetchone()[0]
        assert remaining == 0
        orphaned = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE payee = 'Carried Forward'"
        ).fetchone()[0]
        assert orphaned == 0
        orphaned_comments = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE owner_id = 'txn_existing_id_01'"
        ).fetchone()[0]
        assert orphaned_comments == 0


# ---------------------------------------------------------------------------
# Diagnostics / unsupported constructs
# ---------------------------------------------------------------------------

DIAGNOSTICS_JOURNAL = """\
2026-01-01 * Normal
    Expenses:Groceries    USD 10.00
    Assets:Checking

2026-01-02 * Stock Buy
    Assets:Brokerage    10 AAPL @ USD 150.00
    Assets:Checking

2026-01-03 * Too Precise
    Assets:Checking    USD 0.1234567891
    Expenses:Groceries

2026-01-04 * Two Blanks
    Expenses:Groceries
    Expenses:Coffee
    Assets:Checking    USD -10.00

P 2026-01-01 AAPL USD 150.00
"""


def test_unsupported_constructs_preserved_with_diagnostics(tmp_path):
    config = _make_config(tmp_path)
    (tmp_path / "journals" / "2026.journal").write_text(
        DIAGNOSTICS_JOURNAL, encoding="utf-8"
    )
    refresh_projection(config)

    with _connect(config) as conn:
        file_id = _file_row(conn, "journals/2026.journal")["id"]
        txns = conn.execute(
            "SELECT payee, parse_status FROM transactions "
            "WHERE journal_file_id = ? ORDER BY txn_order",
            (file_id,),
        ).fetchall()
        statuses = {t["payee"]: t["parse_status"] for t in txns}
        assert statuses["Normal"] == "ok"
        assert statuses["Stock Buy"] == "preserved_raw"
        assert statuses["Too Precise"] == "preserved_raw"
        assert statuses["Two Blanks"] == "preserved_raw"

        # Preserved-raw blocks contribute no posting rows.
        preserved_ids = [
            t["id"]
            for t in conn.execute(
                "SELECT id FROM transactions WHERE parse_status = 'preserved_raw'"
            ).fetchall()
        ]
        for txn_id in preserved_ids:
            count = conn.execute(
                "SELECT COUNT(*) FROM postings WHERE transaction_id = ?",
                (txn_id,),
            ).fetchone()[0]
            assert count == 0

        codes = {
            row["code"]
            for row in conn.execute(
                "SELECT code FROM journal_diagnostics WHERE journal_file_id = ?",
                (file_id,),
            ).fetchall()
        }
        assert "unsupported_posting" in codes
        assert "amount_precision_exceeded" in codes
        assert "multiple_elided_postings" in codes
        assert "unsupported_construct" in codes  # top-level P price line

        price_item = conn.execute(
            """
            SELECT item_type FROM journal_items
            WHERE journal_file_id = ? AND raw_text LIKE 'P 2026-01-01%'
            """,
            (file_id,),
        ).fetchone()
        assert price_item["item_type"] == "raw"

        diag_lines = {
            row["code"]: row["line_number"]
            for row in conn.execute(
                "SELECT code, line_number FROM journal_diagnostics "
                "WHERE journal_file_id = ?",
                (file_id,),
            ).fetchall()
        }
        assert diag_lines["unsupported_construct"] == 18

    # Round-trip still holds for a file full of unsupported constructs.
    rendered = render_file(config, "journals/2026.journal")
    assert rendered == DIAGNOSTICS_JOURNAL


# ---------------------------------------------------------------------------
# Ledger CLI parity (slice 3)
# ---------------------------------------------------------------------------

_BAL_LINE_RE = re.compile(r"^\s*(?P<amount>.*?[\d.])\s{2,}(?P<account>\S.*)$")


def _ledger_balances(journal: Path) -> dict[str, Decimal]:
    from services.commodity_service import parse_amount

    output = subprocess.run(
        ["ledger", "-f", str(journal), "bal", "--flat", "--no-total"],
        capture_output=True,
        text=True,
        check=True,
        env={"LEDGER_DATE_FORMAT": "%Y-%m-%d", "PATH": "/usr/bin:/bin"},
    ).stdout
    balances: dict[str, Decimal] = {}
    for line in output.splitlines():
        match = _BAL_LINE_RE.match(line)
        if not match:
            continue
        parsed = parse_amount(match.group("amount"))
        assert parsed is not None, f"unparseable ledger bal line: {line!r}"
        account = match.group("account").strip()
        balances[account] = balances.get(account, Decimal("0")) + parsed.value
    return balances


def test_nanounit_sums_match_ledger_bal(tmp_path):
    config = _golden_workspace(tmp_path)
    refresh_projection(config)

    expected: dict[str, Decimal] = {}
    for journal in sorted((tmp_path / "journals").glob("*.journal")):
        if journal.name == "archived-manual.journal":
            continue
        for account, total in _ledger_balances(journal).items():
            expected[account] = expected.get(account, Decimal("0")) + total
    expected = {a: t for a, t in expected.items() if t != 0}

    with _connect(config) as conn:
        rows = conn.execute(
            """
            SELECT postings.account AS account, SUM(postings.amount_nano) AS nano
            FROM postings
            JOIN transactions ON transactions.id = postings.transaction_id
            JOIN journal_files ON journal_files.id = transactions.journal_file_id
            WHERE journal_files.role != 'archive'
            GROUP BY postings.account
            """
        ).fetchall()
    projected = {
        row["account"]: Decimal(row["nano"]).scaleb(-9)
        for row in rows
        if row["nano"]
    }

    assert projected == expected
