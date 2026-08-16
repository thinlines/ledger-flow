"""Integration tests — verify operation-backed event emission patterns.

These tests exercise the event emission logic as wired in main.py by calling the
same service functions and event_log_service functions used by the route handlers.
"""

from __future__ import annotations

from pathlib import Path

from services.event_log_service import (
    EVENTS_FILENAME,
    emit_event,
    hash_file,
    rel_path,
)
from conftest import read_operation_events
from services.manual_entry_service import create_manual_transaction


def _read_operation_events(workspace: Path) -> list[dict]:
    return read_operation_events(workspace)


def _setup_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace directory."""
    workspace = tmp_path / "workspace"
    for d in ["journals", "rules", "inbox"]:
        (workspace / d).mkdir(parents=True)
    accounts_dat = workspace / "rules" / "10-accounts.dat"
    accounts_dat.write_text(
        "account Expenses:Groceries\naccount Assets:Bank:Checking\n",
        encoding="utf-8",
    )
    return workspace


# ---------------------------------------------------------------------------
# Endpoint 1: transactions_create pattern
# ---------------------------------------------------------------------------


class TestManualEntryCreatedEvent:
    def test_event_emitted_after_manual_entry(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal_path = workspace / "journals" / "2026.journal"

        hash_before = hash_file(journal_path)

        tracked_account_cfg = {
            "display_name": "Checking",
            "ledger_account": "Assets:Bank:Checking",
            "name": "Assets:Bank:Checking",
        }
        create_manual_transaction(
            journal_path=journal_path,
            accounts_dat=workspace / "rules" / "10-accounts.dat",
            tracked_account_cfg=tracked_account_cfg,
            txn_date="2026-03-15",
            payee="Whole Foods",
            amount_str="50.00",
            destination_account="Expenses:Groceries",
            currency="USD",
        )

        hash_after = hash_file(journal_path)
        emit_event(
            workspace,
            event_type="manual_entry.created.v1",
            summary="Created manual entry: Whole Foods 50.00 USD",
            payload={
                "date": "2026-03-15",
                "payee": "Whole Foods",
                "amount": "50.00",
                "currency": "USD",
                "destination_account": "Expenses:Groceries",
                "source_account": "Assets:Bank:Checking",
            },
            journal_refs=[{
                "path": rel_path(journal_path, workspace),
                "hash_before": hash_before,
                "hash_after": hash_after,
            }],
        )

        events = _read_operation_events(workspace)
        assert len(events) == 1
        e = events[0]
        assert e["type"] == "manual_entry.created.v1"
        assert e["actor"] == "user"
        assert e["payload"]["payee"] == "Whole Foods"
        assert e["payload"]["amount"] == "50.00"
        assert len(e["journal_refs"]) == 1
        ref = e["journal_refs"][0]
        assert ref["path"] == "journals/2026.journal"
        assert ref["hash_before"] == hash_before
        assert ref["hash_after"] == hash_after
        assert ref["hash_before"] != ref["hash_after"]  # file was created

    def test_hash_before_is_none_sentinel_for_new_file(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal_path = workspace / "journals" / "2026.journal"
        # Journal doesn't exist yet
        assert hash_file(journal_path) == "sha256:none"


# ---------------------------------------------------------------------------
# Event emission failure resilience
# ---------------------------------------------------------------------------


class TestEmissionFailureResilience:
    def test_emit_event_ignores_events_jsonl_path(self, tmp_path: Path) -> None:
        """A stale events.jsonl directory does not affect operation-backed writes."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / EVENTS_FILENAME).mkdir()

        emit_event(workspace, event_type="t.v1", summary="s", payload={}, journal_refs=[])

        events = _read_operation_events(workspace)
        assert [event["type"] for event in events] == ["t.v1"]


# ---------------------------------------------------------------------------
# Hash chain correctness
# ---------------------------------------------------------------------------


class TestHashChain:
    def test_hash_after_equals_next_hash_before(self, tmp_path: Path) -> None:
        """hash_after of event N == hash_before of event N+1 for the same file."""
        workspace = _setup_workspace(tmp_path)
        journal_path = workspace / "journals" / "2026.journal"
        journal_path.write_text("v1\n", encoding="utf-8")

        # First mutation
        hash_before_1 = hash_file(journal_path)
        journal_path.write_text("v2\n", encoding="utf-8")
        hash_after_1 = hash_file(journal_path)
        emit_event(
            workspace,
            event_type="e1.v1",
            summary="s",
            payload={},
            journal_refs=[{
                "path": "journals/2026.journal",
                "hash_before": hash_before_1,
                "hash_after": hash_after_1,
            }],
        )

        # Second mutation
        hash_before_2 = hash_file(journal_path)
        journal_path.write_text("v3\n", encoding="utf-8")
        hash_after_2 = hash_file(journal_path)
        emit_event(
            workspace,
            event_type="e2.v1",
            summary="s",
            payload={},
            journal_refs=[{
                "path": "journals/2026.journal",
                "hash_before": hash_before_2,
                "hash_after": hash_after_2,
            }],
        )

        assert hash_after_1 == hash_before_2

    def test_all_emitted_events_have_envelope_fields(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        for i in range(5):
            emit_event(
                workspace,
                event_type=f"e{i}.v1",
                summary=f"event {i}",
                payload={"i": i},
                journal_refs=[],
            )
        assert not (workspace / EVENTS_FILENAME).exists()
        for event in _read_operation_events(workspace):
            assert "id" in event
            assert "ts" in event
            assert "type" in event
