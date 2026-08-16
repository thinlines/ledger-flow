"""Unit tests for event_log_service — event writing, hashing, relative paths."""

from __future__ import annotations

from pathlib import Path

from services.event_log_service import (
    EVENTS_FILENAME,
    emit_event,
    hash_file,
    rel_path,
)
from conftest import read_operation_events


def _read_operation_events(workspace: Path) -> list[dict]:
    return read_operation_events(workspace)


# ---------------------------------------------------------------------------
# hash_file
# ---------------------------------------------------------------------------


class TestHashFile:
    def test_returns_sha256_prefix(self, tmp_path: Path) -> None:
        f = tmp_path / "test.journal"
        f.write_text("hello", encoding="utf-8")
        result = hash_file(f)
        assert result.startswith("sha256:")
        assert len(result) > len("sha256:")

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        a = tmp_path / "a.journal"
        b = tmp_path / "b.journal"
        a.write_text("same content", encoding="utf-8")
        b.write_text("same content", encoding="utf-8")
        assert hash_file(a) == hash_file(b)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        a = tmp_path / "a.journal"
        b = tmp_path / "b.journal"
        a.write_text("content A", encoding="utf-8")
        b.write_text("content B", encoding="utf-8")
        assert hash_file(a) != hash_file(b)

    def test_missing_file_returns_none_sentinel(self, tmp_path: Path) -> None:
        assert hash_file(tmp_path / "nonexistent.journal") == "sha256:none"

    def test_hash_is_stable(self, tmp_path: Path) -> None:
        f = tmp_path / "test.journal"
        f.write_text("stable", encoding="utf-8")
        assert hash_file(f) == hash_file(f)


# ---------------------------------------------------------------------------
# emit_event
# ---------------------------------------------------------------------------


class TestEmitEvent:
    def test_records_operation_without_events_file(self, tmp_path: Path) -> None:
        events_file = tmp_path / EVENTS_FILENAME
        assert not events_file.exists()
        emit_event(
            tmp_path,
            event_type="test.v1",
            summary="first event",
            payload={"key": "value"},
            journal_refs=[],
        )
        assert not events_file.exists()
        events = _read_operation_events(tmp_path)
        assert len(events) == 1
        assert events[0]["type"] == "test.v1"

    def test_records_multiple_operations_in_event_order(self, tmp_path: Path) -> None:
        emit_event(tmp_path, event_type="e1.v1", summary="one", payload={}, journal_refs=[])
        emit_event(tmp_path, event_type="e2.v1", summary="two", payload={}, journal_refs=[])
        events = _read_operation_events(tmp_path)
        assert len(events) == 2
        assert events[0]["type"] == "e1.v1"
        assert events[1]["type"] == "e2.v1"

    def test_event_envelope_fields(self, tmp_path: Path) -> None:
        event_id = emit_event(
            tmp_path,
            event_type="manual_entry.created.v1",
            summary="Created entry",
            payload={"date": "2026-01-01"},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:aaa", "hash_after": "sha256:bbb"}],
            actor="user",
            compensates=None,
        )
        events = _read_operation_events(tmp_path)
        assert len(events) == 1
        e = events[0]
        assert e["id"] == event_id
        assert e["ts"].endswith("+00:00") or e["ts"].endswith("Z")
        assert e["actor"] == "user"
        assert e["type"] == "manual_entry.created.v1"
        assert e["summary"] == "Created entry"
        assert e["payload"] == {"date": "2026-01-01"}
        assert len(e["journal_refs"]) == 1
        assert e["journal_refs"][0]["path"] == "journals/2026.journal"
        assert e["compensates"] is None

    def test_returns_uuid7_string(self, tmp_path: Path) -> None:
        event_id = emit_event(tmp_path, event_type="t.v1", summary="s", payload={}, journal_refs=[])
        # UUIDv7 format: 8-4-4-4-12 hex digits
        parts = event_id.split("-")
        assert len(parts) == 5

    def test_does_not_write_jsonl(self, tmp_path: Path) -> None:
        emit_event(tmp_path, event_type="t.v1", summary="s", payload={}, journal_refs=[])
        assert not (tmp_path / EVENTS_FILENAME).exists()

    def test_leaves_retired_events_file_untouched(self, tmp_path: Path) -> None:
        events_file = tmp_path / EVENTS_FILENAME
        events_file.write_text('{"id":"legacy"}\n', encoding="utf-8")
        emit_event(tmp_path, event_type="t.v1", summary="s", payload={}, journal_refs=[])
        assert events_file.exists()


# ---------------------------------------------------------------------------
# rel_path
# ---------------------------------------------------------------------------


class TestRelPath:
    def test_relative_to_workspace(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        journal = workspace / "journals" / "2026.journal"
        journal.parent.mkdir()
        journal.touch()
        assert rel_path(journal, workspace) == "journals/2026.journal"

    def test_falls_back_to_absolute(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "other" / "file.txt"
        outside.parent.mkdir()
        outside.touch()
        result = rel_path(outside, workspace)
        assert str(outside) in result
