"""The (lf_txn_id, raw_block_hash) mutation contract, proven on toggle-status.

Spec (docs/ledger-flow-projection-schema.md, Mutation-Time Projection): the
client submits transaction id + block hash; the backend locates the block by
id, rejects only true block-level staleness (hash mismatch), re-projects the
touched file after a successful write, and returns updated projected data.
Line numbers and header text are no longer part of the request.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from models import ToggleStatusRequest
from services import event_log_service
from services.config_service import AppConfig
from services.projection_db import database_path
from services.projection_service import refresh_projection


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    return AppConfig(
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


JOURNAL = """\
include ../opening/checking.journal

2026-01-05 Grocery Store
    ; lf_txn_id: txn_grocery
    Expenses:Groceries    USD 45.67
    Assets:Checking

2026-01-10 * Coffee
    ; lf_txn_id: txn_coffee
    Expenses:Coffee    USD 4.50
    Assets:Checking
"""

OPENING = """\
2026-01-01 Opening Balance
    ; lf_txn_id: txn_opening
    Assets:Checking    USD 100.00
    Equity:Opening Balances
"""


def _workspace(tmp_path: Path, monkeypatch) -> AppConfig:
    config = _make_config(tmp_path / "workspace")
    (config.journal_dir / "2026.journal").write_text(JOURNAL, encoding="utf-8")
    (config.root_dir / "opening" / "checking.journal").write_text(
        OPENING, encoding="utf-8"
    )
    monkeypatch.setattr(main, "_require_workspace_config", lambda: config)
    refresh_projection(config)
    return config


def _txn_row(config: AppConfig, txn_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(database_path(config))
    conn.row_factory = sqlite3.Row
    with conn:
        row = conn.execute(
            "SELECT id, raw_block_hash, status FROM transactions WHERE id = ?",
            (txn_id,),
        ).fetchone()
    conn.close()
    assert row is not None, f"no projected transaction {txn_id}"
    return row


def test_toggle_by_id_cycles_status_and_returns_projected_data(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)
    before = _txn_row(config, "txn_grocery")
    assert before["status"] == "unmarked"

    result = main.transactions_toggle_status(
        ToggleStatusRequest(txnId="txn_grocery", blockHash=before["raw_block_hash"])
    )

    assert result["newStatus"] == "pending"
    assert result["txnId"] == "txn_grocery"
    assert result["blockHash"] != before["raw_block_hash"]
    assert result["eventId"]
    # The transitional newHeaderLine field is gone (#17): every row action
    # is identity-based now, nothing needs fresh header text.
    assert "newHeaderLine" not in result

    text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-01-05 ! Grocery Store" in text
    # Untouched sibling block is byte-identical.
    assert "2026-01-10 * Coffee" in text

    # The touched file was re-projected as part of the request: the stored
    # row already reflects the edit, no extra refresh needed.
    after = _txn_row(config, "txn_grocery")
    assert after["status"] == "pending"
    assert after["raw_block_hash"] == result["blockHash"]


def test_stale_block_hash_is_rejected_with_409(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)
    before = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_toggle_status(
            ToggleStatusRequest(txnId="txn_grocery", blockHash="sha256:stale")
        )

    assert exc_info.value.status_code == 409
    assert "changed" in exc_info.value.detail
    assert (config.journal_dir / "2026.journal").read_text(encoding="utf-8") == before


def test_unknown_id_is_rejected_with_404(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_toggle_status(
            ToggleStatusRequest(txnId="txn_missing", blockHash="sha256:whatever")
        )

    assert exc_info.value.status_code == 404


def test_external_edit_before_transaction_no_longer_breaks_toggle(tmp_path, monkeypatch):
    """The positional contract's failure case: an earlier edit moves the
    block's line numbers. Identity + hash must not care."""
    config = _workspace(tmp_path, monkeypatch)
    before = _txn_row(config, "txn_coffee")

    journal = config.journal_dir / "2026.journal"
    text = journal.read_text(encoding="utf-8")
    journal.write_text(
        text.replace(
            "2026-01-05 Grocery Store",
            "2026-01-02 Inserted Externally\n"
            "    Expenses:Groceries    USD 1.00\n"
            "    Assets:Checking\n"
            "\n"
            "2026-01-05 Grocery Store",
        ),
        encoding="utf-8",
    )

    result = main.transactions_toggle_status(
        ToggleStatusRequest(txnId="txn_coffee", blockHash=before["raw_block_hash"])
    )

    # txn_coffee was cleared (*) — the cycle continues to unmarked.
    assert result["newStatus"] == "unmarked"
    text = journal.read_text(encoding="utf-8")
    assert "2026-01-10 Coffee" in text
    assert "2026-01-10 * Coffee" not in text
    assert "2026-01-02 Inserted Externally" in text


def test_reprojected_target_content_change_is_rejected(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)
    before = _txn_row(config, "txn_coffee")

    journal = config.journal_dir / "2026.journal"
    journal.write_text(
        journal.read_text(encoding="utf-8").replace("Coffee", "Coffee Roasters"),
        encoding="utf-8",
    )
    refresh_projection(config)

    with pytest.raises(HTTPException) as exc_info:
        main.transactions_toggle_status(
            ToggleStatusRequest(
                txnId="txn_coffee", blockHash=before["raw_block_hash"]
            )
        )

    assert exc_info.value.status_code == 409
    assert "2026-01-10 * Coffee Roasters" in journal.read_text(encoding="utf-8")


def test_repeated_toggles_use_each_returned_hash(tmp_path, monkeypatch):
    config = _workspace(tmp_path, monkeypatch)
    row = _txn_row(config, "txn_grocery")

    statuses = []
    block_hash = row["raw_block_hash"]
    for _ in range(3):
        result = main.transactions_toggle_status(
            ToggleStatusRequest(txnId="txn_grocery", blockHash=block_hash)
        )
        statuses.append(result["newStatus"])
        block_hash = result["blockHash"]

    assert statuses == ["pending", "cleared", "unmarked"]
    text = (config.journal_dir / "2026.journal").read_text(encoding="utf-8")
    assert "2026-01-05 Grocery Store" in text


def test_included_file_transaction_toggles(tmp_path, monkeypatch):
    """Transactions in included files were unreachable under the positional
    contract (-1 line-number sentinel); by id they just work."""
    config = _workspace(tmp_path, monkeypatch)
    row = _txn_row(config, "txn_opening")

    result = main.transactions_toggle_status(
        ToggleStatusRequest(txnId="txn_opening", blockHash=row["raw_block_hash"])
    )

    assert result["newStatus"] == "pending"
    opening = (config.root_dir / "opening" / "checking.journal").read_text(
        encoding="utf-8"
    )
    assert "2026-01-01 ! Opening Balance" in opening
