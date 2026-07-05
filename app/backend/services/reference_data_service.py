"""Read-side queries over the projected reference tables.

The account picker, autocomplete, and per-account posting counts are served
from the database (spec Reference Data: "replaces the ``ledger accounts
--count`` shell-out for account lists and enables pre-write validation and
autocomplete from the database"). Every entry point refreshes the projection
first, so external edits self-heal before the query runs.

Closed accounts (``closed_on`` set via ``; lf_closed::`` metadata) are hidden
from pickers and autocomplete; history and reports elsewhere are untouched.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing

from .config_service import AppConfig, infer_account_kind
from .projection_db import connect, database_path
from .projection_service import refresh_projection
from .transfer_service import is_transfer_account


def _open(config: AppConfig) -> sqlite3.Connection:
    refresh_projection(config)
    return connect(database_path(config))


def list_account_names(config: AppConfig) -> list[str]:
    """Every projected account (declared ∪ used ∪ synthesized ancestors),
    closed accounts hidden, in lexicographic (= depth-first tree) order."""
    with closing(_open(config)) as conn:
        rows = conn.execute(
            "SELECT name FROM accounts WHERE closed_on IS NULL ORDER BY name"
        ).fetchall()
    return [name for (name,) in rows]


def list_category_account_names(config: AppConfig) -> list[str]:
    """Picker list for categorization: expense/income accounts excluding the
    app's transfer accounts (same filter the ``.dat`` parser applied)."""
    return [
        name
        for name in list_account_names(config)
        if infer_account_kind(name) in {"expense", "income"}
        and not is_transfer_account(name)
    ]


def posting_counts_by_account(config: AppConfig) -> dict[str, int]:
    """Exact-name posting counts over non-archive files — the DB-backed
    replacement for parsing ``ledger accounts --count`` output.

    Matches the CLI's account list: declared accounts appear even with zero
    postings; synthesized ancestors appear only when postings name them
    directly."""
    with closing(_open(config)) as conn:
        declared = conn.execute(
            "SELECT name FROM accounts WHERE declared = TRUE"
        ).fetchall()
        used = conn.execute(
            """
            SELECT postings.account, COUNT(*)
            FROM postings
            JOIN transactions ON transactions.id = postings.transaction_id
            JOIN journal_files ON journal_files.id = transactions.journal_file_id
            WHERE journal_files.role != 'archive'
            GROUP BY postings.account
            """
        ).fetchall()
    counts = {name: 0 for (name,) in declared}
    counts.update({account: count for account, count in used})
    return counts
