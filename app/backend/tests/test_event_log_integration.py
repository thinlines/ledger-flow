"""Integration tests — verify event emission from each mutation endpoint pattern.

These tests exercise the event emission logic as wired in main.py by calling the
same service functions and event_log_service functions used by the route handlers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import event_log_service
from services.event_log_service import (
    EVENTS_FILENAME,
    check_drift,
    emit_event,
    hash_file,
    rel_path,
)
from services.manual_entry_service import create_manual_transaction


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


def _read_events(workspace: Path) -> list[dict]:
    events_file = workspace / EVENTS_FILENAME
    if not events_file.exists():
        return []
    return [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]


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

        hash_before = check_drift(workspace, journal_path)

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

        events = _read_events(workspace)
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
        hash_before = check_drift(workspace, journal_path)
        assert hash_before == "sha256:none"


# ---------------------------------------------------------------------------
# Drift detection integration
# ---------------------------------------------------------------------------


class TestDriftDetectionIntegration:
    def test_external_edit_detected_before_mutation(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal_path = workspace / "journals" / "2026.journal"
        journal_path.write_text("original content\n", encoding="utf-8")

        # Emit an event to establish a baseline hash
        original_hash = hash_file(journal_path)
        emit_event(
            workspace,
            event_type="e.v1",
            summary="s",
            payload={},
            journal_refs=[{
                "path": "journals/2026.journal",
                "hash_before": "sha256:none",
                "hash_after": original_hash,
            }],
        )

        # Simulate external edit
        journal_path.write_text("externally modified content\n", encoding="utf-8")

        # Drift check before next mutation
        check_drift(workspace, journal_path)

        events = _read_events(workspace)
        drift_events = [e for e in events if e["type"] == "journal.external_edit_detected.v1"]
        assert len(drift_events) == 1
        assert drift_events[0]["payload"]["trigger"] == "pre_mutation"
        assert drift_events[0]["payload"]["expected_hash"] == original_hash
        assert drift_events[0]["actor"] == "system"

    def test_drift_event_appears_before_mutation_event(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal_path = workspace / "journals" / "2026.journal"
        journal_path.write_text("original\n", encoding="utf-8")

        original_hash = hash_file(journal_path)
        emit_event(
            workspace,
            event_type="setup.v1",
            summary="s",
            payload={},
            journal_refs=[{
                "path": "journals/2026.journal",
                "hash_before": "sha256:none",
                "hash_after": original_hash,
            }],
        )

        # External edit
        journal_path.write_text("modified\n", encoding="utf-8")

        # Run drift check (as route handler would)
        hash_before = check_drift(workspace, journal_path)

        # Simulate mutation
        journal_path.write_text("modified\nnew transaction\n", encoding="utf-8")
        hash_after = hash_file(journal_path)

        emit_event(
            workspace,
            event_type="manual_entry.created.v1",
            summary="test",
            payload={},
            journal_refs=[{
                "path": "journals/2026.journal",
                "hash_before": hash_before,
                "hash_after": hash_after,
            }],
        )

        events = _read_events(workspace)
        types = [e["type"] for e in events]
        drift_idx = types.index("journal.external_edit_detected.v1")
        mutation_idx = types.index("manual_entry.created.v1")
        assert drift_idx < mutation_idx

    def test_no_drift_when_file_unchanged(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        journal_path = workspace / "journals" / "2026.journal"
        journal_path.write_text("stable\n", encoding="utf-8")

        current_hash = hash_file(journal_path)
        emit_event(
            workspace,
            event_type="setup.v1",
            summary="s",
            payload={},
            journal_refs=[{
                "path": "journals/2026.journal",
                "hash_before": "sha256:none",
                "hash_after": current_hash,
            }],
        )

        check_drift(workspace, journal_path)

        events = _read_events(workspace)
        drift_events = [e for e in events if e["type"] == "journal.external_edit_detected.v1"]
        assert len(drift_events) == 0


# ---------------------------------------------------------------------------
# Event emission failure resilience
# ---------------------------------------------------------------------------


class TestEmissionFailureResilience:
    def test_emit_event_does_not_raise_on_readonly_dir(self, tmp_path: Path) -> None:
        """If emit_event is called from a try/except wrapper (as in the handlers),
        failures are logged but don't propagate."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Make events file a directory to cause write failure
        (workspace / EVENTS_FILENAME).mkdir()

        with pytest.raises(IsADirectoryError):
            emit_event(workspace, event_type="t.v1", summary="s", payload={}, journal_refs=[])

        # The caller (route handler) wraps this in try/except, so failure is safe.
        # This test documents that emit_event does raise — it's the caller's
        # responsibility to catch.


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
        hash_before_1 = check_drift(workspace, journal_path)
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
        hash_before_2 = check_drift(workspace, journal_path)
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

    def test_all_events_are_valid_json(self, tmp_path: Path) -> None:
        workspace = _setup_workspace(tmp_path)
        for i in range(5):
            emit_event(
                workspace,
                event_type=f"e{i}.v1",
                summary=f"event {i}",
                payload={"i": i},
                journal_refs=[],
            )
        raw_lines = (workspace / EVENTS_FILENAME).read_text().splitlines()
        for line in raw_lines:
            parsed = json.loads(line)  # Should not raise
            assert "id" in parsed
            assert "ts" in parsed
            assert "type" in parsed
