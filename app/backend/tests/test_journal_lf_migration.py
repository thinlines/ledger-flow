"""One-time journal migration to lf_ house-style metadata (issue #16).

Behavior under test (spec: docs/ledger-flow-projection-schema.md, adoption
step 4):

- Every managed transaction block gains a stable ``lf_txn_id`` directly
  after its header line; existing ids are adopted, never replaced.
- Schema-named metadata keys are renamed in place:
  ``source_identity(_N)`` -> ``lf_source_identity(_N)`` and
  ``reconciliation_event_id`` -> ``lf_operation_id``.
- Every byte outside inserted/renamed lines is preserved, including
  preserved-raw blocks, ``.dat`` directive files, file comments, and a
  missing trailing newline.
- The migration is idempotent, runs through the journal writer ritual
  (backups + event), and refreshes the projection so assigned ids are
  adopted as ``transactions.id``.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from services.config_service import AppConfig
from services.journal_migration_service import migrate_lf_metadata
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
account Expenses:Groceries
account Expenses:Coffee
account Income:Salary
account Equity:Opening Balances

commodity USD
    format USD 1,000.00
"""

# Deliberately no trailing newline (byte preservation must keep that).
OPENING_CHECKING = """\
2026-01-01 * Opening Balance
    ; tracked_account_id: checking
    Assets:Checking    USD 100.00
    Equity:Opening Balances"""

YEAR_2026 = """\
; Year 2026 journal — file-level comment stays byte-identical
include ../rules/10-accounts.dat
include ../opening/checking.journal

2026-01-05 * Grocery Store 超市
    ; source_identity: abc123
    ; source_payload_hash: deadbeef
    Expenses:Groceries    USD 45.67
    Assets:Checking
        ; note with trailing spaces

2026-01-10 ! Reconciled Coffee
    ; reconciliation_event_id: 0197-abc
    ; statement_period: 2026-01-01..2026-01-31
    Expenses:Coffee    USD 4.50
    Assets:Checking    USD -4.50

2026-02-01 * Priced Block Stays Raw
    ; source_identity: keep-me-raw
    Assets:Checking    10 AAPL @ USD 150.00
    Income:Salary

2026-02-02 * Merged Duplicate
    ; source_identity: primary-1
    ; source_identity_1: carried-1
    Expenses:Coffee    USD 2.00
    Assets:Checking
"""

YEAR_2027 = """\
2027-01-15 * Already Has Id
    ; lf_txn_id: txn_existing_id_01
    Expenses:Coffee    USD 2.25
    Assets:Checking
"""


def _workspace(tmp_path: Path) -> AppConfig:
    config = _make_config(tmp_path)
    (tmp_path / "rules" / "10-accounts.dat").write_text(ACCOUNTS_DAT, encoding="utf-8")
    (tmp_path / "opening" / "checking.journal").write_text(
        OPENING_CHECKING, encoding="utf-8"
    )
    (tmp_path / "journals" / "2026.journal").write_text(YEAR_2026, encoding="utf-8")
    (tmp_path / "journals" / "2027.journal").write_text(YEAR_2027, encoding="utf-8")
    return config


def _connect(config: AppConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path(config))
    conn.row_factory = sqlite3.Row
    return conn


def _block_lines(text: str, header_prefix: str) -> list[str]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(header_prefix):
            block = [line]
            for follower in lines[index + 1 :]:
                if not follower[:1] in (" ", "\t") or not follower.strip():
                    break
                block.append(follower)
            return block
    raise AssertionError(f"no block starting with {header_prefix!r}")


ID_LINE_RE = re.compile(r"^    ; lf_txn_id: txn_[0-9a-f]{32}$")


# ---------------------------------------------------------------------------
# Id assignment
# ---------------------------------------------------------------------------


def test_assigns_lf_txn_id_directly_after_header(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    text = (tmp_path / "journals" / "2026.journal").read_text(encoding="utf-8")
    block = _block_lines(text, "2026-01-05 * Grocery Store")
    assert ID_LINE_RE.match(block[1]), block[1]

    opening = (tmp_path / "opening" / "checking.journal").read_text(encoding="utf-8")
    opening_block = _block_lines(opening, "2026-01-01 * Opening Balance")
    assert ID_LINE_RE.match(opening_block[1]), opening_block[1]


def test_assigned_ids_are_unique(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    ids: list[str] = []
    for rel in ["journals/2026.journal", "journals/2027.journal", "opening/checking.journal"]:
        for line in (tmp_path / rel).read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*; lf_txn_id: (\S+)$", line)
            if match:
                ids.append(match.group(1))
    assert len(ids) == len(set(ids))
    assert len(ids) >= 4


def test_adopts_existing_id_and_leaves_file_untouched(tmp_path):
    config = _workspace(tmp_path)
    before = (tmp_path / "journals" / "2027.journal").read_text(encoding="utf-8")

    report = migrate_lf_metadata(config)

    after = (tmp_path / "journals" / "2027.journal").read_text(encoding="utf-8")
    assert after == before
    assert "journals/2027.journal" not in report["files_changed"]


def test_preserved_raw_block_is_not_touched(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    text = (tmp_path / "journals" / "2026.journal").read_text(encoding="utf-8")
    block = _block_lines(text, "2026-02-01 * Priced Block Stays Raw")
    assert block == [
        "2026-02-01 * Priced Block Stays Raw",
        "    ; source_identity: keep-me-raw",
        "    Assets:Checking    10 AAPL @ USD 150.00",
        "    Income:Salary",
    ]


# ---------------------------------------------------------------------------
# Key renames
# ---------------------------------------------------------------------------


def test_renames_source_identity_family(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    text = (tmp_path / "journals" / "2026.journal").read_text(encoding="utf-8")
    assert "    ; lf_source_identity: abc123" in text
    assert "    ; lf_source_identity_1: carried-1" in text
    assert "    ; lf_source_identity: primary-1" in text
    # Only inside managed blocks; the preserved_raw block keeps the old key.
    assert text.count("; source_identity:") == 1  # the raw block
    # Non-schema-named keys keep their names until their owning issues.
    assert "    ; source_payload_hash: deadbeef" in text
    assert "    ; statement_period: 2026-01-01..2026-01-31" in text


def test_renames_reconciliation_event_id_to_lf_operation_id(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    text = (tmp_path / "journals" / "2026.journal").read_text(encoding="utf-8")
    assert "    ; lf_operation_id: 0197-abc" in text
    assert "reconciliation_event_id" not in text


# ---------------------------------------------------------------------------
# Byte preservation
# ---------------------------------------------------------------------------


def test_untouched_bytes_are_preserved(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    text = (tmp_path / "journals" / "2026.journal").read_text(encoding="utf-8")
    assert text.startswith(
        "; Year 2026 journal — file-level comment stays byte-identical\n"
        "include ../rules/10-accounts.dat\n"
        "include ../opening/checking.journal\n"
        "\n"
    )
    assert "        ; note with trailing spaces" in text

    dat = (tmp_path / "rules" / "10-accounts.dat").read_text(encoding="utf-8")
    assert dat == ACCOUNTS_DAT


def test_missing_trailing_newline_preserved(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    opening = (tmp_path / "opening" / "checking.journal").read_text(encoding="utf-8")
    assert not opening.endswith("\n")
    assert opening.endswith("    Equity:Opening Balances")


def test_migration_is_idempotent(tmp_path):
    config = _workspace(tmp_path)
    first = migrate_lf_metadata(config)
    assert first["ids_assigned"] > 0

    snapshot = {
        rel: (tmp_path / rel).read_text(encoding="utf-8")
        for rel in [
            "journals/2026.journal",
            "journals/2027.journal",
            "opening/checking.journal",
            "rules/10-accounts.dat",
        ]
    }

    second = migrate_lf_metadata(config)

    assert second["ids_assigned"] == 0
    assert second["keys_renamed"] == 0
    assert second["files_changed"] == []
    for rel, before in snapshot.items():
        assert (tmp_path / rel).read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# Config subtype adoption (issue #19: subtype is declaration-canonical)
# ---------------------------------------------------------------------------


def test_migration_copies_config_subtypes_into_declarations(tmp_path):
    config = _workspace(tmp_path)
    config.tracked_accounts["checking"] = {
        "display_name": "Checking",
        "ledger_account": "Assets:Checking",
        "subtype": "checking",
    }

    report = migrate_lf_metadata(config)
    assert report["subtypes_adopted"] == 1

    dat = (tmp_path / "rules" / "10-accounts.dat").read_text(encoding="utf-8")
    assert "account Assets:Checking\n    ; lf_subtype: checking\n" in dat

    second = migrate_lf_metadata(config)
    assert second["subtypes_adopted"] == 0


def test_migration_never_overwrites_declaration_subtype(tmp_path):
    config = _workspace(tmp_path)
    dat_path = tmp_path / "rules" / "10-accounts.dat"
    dat_path.write_text(
        dat_path.read_text(encoding="utf-8").replace(
            "account Assets:Checking\n",
            "account Assets:Checking\n    ; lf_subtype: savings\n",
        ),
        encoding="utf-8",
    )
    config.tracked_accounts["checking"] = {
        "display_name": "Checking",
        "ledger_account": "Assets:Checking",
        "subtype": "checking",
    }

    report = migrate_lf_metadata(config)

    assert report["subtypes_adopted"] == 0
    dat = dat_path.read_text(encoding="utf-8")
    assert "; lf_subtype: savings" in dat
    assert "; lf_subtype: checking" not in dat


# ---------------------------------------------------------------------------
# Writer ritual: backups + event
# ---------------------------------------------------------------------------


def test_backups_written_and_event_emitted(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    backups = list((tmp_path / "journals").glob("2026.journal.lf-migration.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == YEAR_2026

    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["type"] == "journal.lf_metadata_migrated.v1"


# ---------------------------------------------------------------------------
# Projection adoption
# ---------------------------------------------------------------------------


def test_projection_adopts_assigned_ids(tmp_path):
    config = _workspace(tmp_path)

    migrate_lf_metadata(config)

    journal_ids: set[str] = set()
    for rel in ["journals/2026.journal", "journals/2027.journal", "opening/checking.journal"]:
        for line in (tmp_path / rel).read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*; lf_txn_id: (\S+)$", line)
            if match:
                journal_ids.add(match.group(1))

    with _connect(config) as conn:
        projected = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM transactions WHERE parse_status = 'ok'"
            ).fetchall()
        }
    assert journal_ids == projected


def test_duplicate_lf_txn_id_gets_diagnostic_not_crash(tmp_path):
    config = _make_config(tmp_path)
    (tmp_path / "journals" / "2026.journal").write_text(
        "2026-01-05 * First\n"
        "    ; lf_txn_id: txn_dupe\n"
        "    Expenses:Groceries    USD 1.00\n"
        "    Assets:Checking\n"
        "\n"
        "2026-01-06 * Second\n"
        "    ; lf_txn_id: txn_dupe\n"
        "    Expenses:Groceries    USD 2.00\n"
        "    Assets:Checking\n",
        encoding="utf-8",
    )

    refresh_projection(config)

    with _connect(config) as conn:
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM transactions ORDER BY txn_order"
            ).fetchall()
        ]
        diags = conn.execute(
            "SELECT code FROM journal_diagnostics WHERE code = 'duplicate_lf_txn_id'"
        ).fetchall()
    assert ids[0] == "txn_dupe"
    assert ids[1] != "txn_dupe"
    assert len(diags) == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_migrate_subcommand(tmp_path, capsys):
    from ledger_flow_cli import main

    workspace = tmp_path / "workspace"
    (workspace / "settings").mkdir(parents=True)
    for name in ["journals", "inbox", "rules", "opening", "imports"]:
        (workspace / name).mkdir()
    (workspace / "settings" / "workspace.toml").write_text(
        """
[workspace]
name = "Test"
start_year = 2026
base_currency = "USD"

[dirs]
csv_dir = "inbox"
journal_dir = "journals"
init_dir = "rules"
opening_bal_dir = "opening"
imports_dir = "imports"
""".lstrip(),
        encoding="utf-8",
    )
    (workspace / "journals" / "2026.journal").write_text(
        "2026-01-05 * Grocery Store\n"
        "    ; source_identity: abc123\n"
        "    Expenses:Groceries    USD 45.67\n"
        "    Assets:Checking\n",
        encoding="utf-8",
    )

    status = main(
        [
            "--config",
            str(workspace / "settings" / "workspace.toml"),
            "migrate-lf-metadata",
        ]
    )

    assert status == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ids_assigned"] == 1
    assert output["keys_renamed"] == 1
    assert output["files_changed"] == ["journals/2026.journal"]
    text = (workspace / "journals" / "2026.journal").read_text(encoding="utf-8")
    assert "; lf_txn_id: txn_" in text
    assert "; lf_source_identity: abc123" in text
