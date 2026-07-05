"""Writer-transactional projection (spec: Mutation-Time Projection).

``journal_writer.mutate`` re-projects the touched files after a successful
block + verify, so callers never need a post-mutate refresh. When the block,
the verifier, or re-projection itself fails, files and projection revert
together — the PRD atomicity invariant.

These tests exercise the ``mutate(...)`` seam directly with a real projection
database; the mutation op is a trivial header rewrite.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services import event_log_service, journal_writer
from services.config_service import AppConfig
from services.journal_writer import VerifyFailure, WriterRejected, mutate
from services.projection_db import database_path
from services.projection_service import refresh_projection


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


JOURNAL = """\
2026-01-05 Grocery Store
    ; lf_txn_id: txn_grocery
    Expenses:Groceries    USD 45.67
    Assets:Checking

2026-01-10 * Coffee
    ; lf_txn_id: txn_coffee
    Expenses:Coffee    USD 4.50
    Assets:Checking
"""


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    workspace = tmp_path / "workspace"
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True)
    (workspace / "journals" / "2026.journal").write_text(JOURNAL, encoding="utf-8")
    cfg = AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "start_year": 2026, "base_currency": "USD"},
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
    refresh_projection(cfg)
    return cfg


def _txn_row(config: AppConfig, txn_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(database_path(config))
    conn.row_factory = sqlite3.Row
    with conn:
        row = conn.execute(
            "SELECT id, status, raw_header, raw_block_hash FROM transactions WHERE id = ?",
            (txn_id,),
        ).fetchone()
    conn.close()
    return row


def _toggle_grocery_header(journal: Path) -> None:
    text = journal.read_text(encoding="utf-8")
    journal.write_text(
        text.replace("2026-01-05 Grocery Store", "2026-01-05 ! Grocery Store"),
        encoding="utf-8",
    )


def test_successful_mutate_reprojects_touched_file(config: AppConfig) -> None:
    journal = config.journal_dir / "2026.journal"

    with mutate(
        config=config,
        paths=[journal],
        tag="test",
        event_type="test.mutated.v1",
    ) as mut:
        _toggle_grocery_header(journal)
        mut.summary = "test edit"

    # No caller-side refresh: the writer already re-projected the file.
    row = _txn_row(config, "txn_grocery")
    assert row["status"] == "pending"
    assert row["raw_header"] == "2026-01-05 ! Grocery Store"


def test_block_failure_leaves_projection_unchanged(config: AppConfig) -> None:
    journal = config.journal_dir / "2026.journal"
    before = _txn_row(config, "txn_grocery")

    with pytest.raises(RuntimeError, match="boom"):
        with mutate(
            config=config,
            paths=[journal],
            tag="test",
            event_type="test.mutated.v1",
        ):
            _toggle_grocery_header(journal)
            raise RuntimeError("boom")

    assert journal.read_text(encoding="utf-8") == JOURNAL
    after = _txn_row(config, "txn_grocery")
    assert after["status"] == before["status"] == "unmarked"
    assert after["raw_block_hash"] == before["raw_block_hash"]


def test_verifier_rejection_leaves_projection_unchanged(config: AppConfig) -> None:
    journal = config.journal_dir / "2026.journal"
    before = _txn_row(config, "txn_grocery")

    class _Reject(VerifyFailure):
        pass

    with pytest.raises(WriterRejected):
        with mutate(
            config=config,
            paths=[journal],
            tag="test",
            event_type="test.mutated.v1",
            verify=lambda _config, _paths: _Reject(),
        ):
            _toggle_grocery_header(journal)

    assert journal.read_text(encoding="utf-8") == JOURNAL
    after = _txn_row(config, "txn_grocery")
    assert after["status"] == before["status"] == "unmarked"
    assert after["raw_block_hash"] == before["raw_block_hash"]


def test_projection_failure_rolls_back_file_write(config: AppConfig, monkeypatch) -> None:
    """The PRD atomicity invariant: an injected failure between file write and
    projection commit reverts both sides together."""
    journal = config.journal_dir / "2026.journal"

    def _boom(_config: AppConfig):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(journal_writer, "refresh_projection", _boom)

    with pytest.raises(sqlite3.OperationalError):
        with mutate(
            config=config,
            paths=[journal],
            tag="test",
            event_type="test.mutated.v1",
        ):
            _toggle_grocery_header(journal)

    assert journal.read_text(encoding="utf-8") == JOURNAL
    monkeypatch.undo()

    # Projection still agrees with the restored file.
    refresh_projection(config)
    row = _txn_row(config, "txn_grocery")
    assert row["status"] == "unmarked"

    # No event was emitted for the failed mutation.
    events_file = config.root_dir / event_log_service.EVENTS_FILENAME
    if events_file.is_file():
        assert "test.mutated.v1" not in events_file.read_text(encoding="utf-8")
