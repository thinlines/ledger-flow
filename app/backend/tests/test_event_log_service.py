"""Unit tests for event_log_service — event writing, hashing, drift detection, cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import event_log_service
from services.event_log_service import (
    EVENTS_FILENAME,
    check_drift,
    check_startup_drift,
    emit_event,
    get_last_known_hash,
    hash_file,
    rel_path,
)


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    """Reset the module-level hash cache between tests."""
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


def _read_events(workspace: Path) -> list[dict]:
    events_file = workspace / EVENTS_FILENAME
    if not events_file.exists():
        return []
    return [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]


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
    def test_creates_file_on_first_event(self, tmp_path: Path) -> None:
        events_file = tmp_path / EVENTS_FILENAME
        assert not events_file.exists()
        emit_event(
            tmp_path,
            event_type="test.v1",
            summary="first event",
            payload={"key": "value"},
            journal_refs=[],
        )
        assert events_file.exists()
        events = _read_events(tmp_path)
        assert len(events) == 1
        assert events[0]["type"] == "test.v1"

    def test_appends_to_existing_file(self, tmp_path: Path) -> None:
        emit_event(tmp_path, event_type="e1.v1", summary="one", payload={}, journal_refs=[])
        emit_event(tmp_path, event_type="e2.v1", summary="two", payload={}, journal_refs=[])
        events = _read_events(tmp_path)
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
        events = _read_events(tmp_path)
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

    def test_compact_json_no_pretty_print(self, tmp_path: Path) -> None:
        emit_event(tmp_path, event_type="t.v1", summary="s", payload={}, journal_refs=[])
        raw = (tmp_path / EVENTS_FILENAME).read_text()
        # Compact JSON uses no spaces after separators
        assert '"type":"t.v1"' in raw

    def test_updates_hash_cache(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        journal.parent.mkdir(parents=True)
        journal.write_text("data", encoding="utf-8")
        emit_event(
            tmp_path,
            event_type="t.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:old", "hash_after": "sha256:new"}],
        )
        assert event_log_service._hash_cache[str(journal.resolve())] == "sha256:new"


# ---------------------------------------------------------------------------
# get_last_known_hash
# ---------------------------------------------------------------------------


class TestGetLastKnownHash:
    def test_returns_none_when_no_events_file(self, tmp_path: Path) -> None:
        assert get_last_known_hash(tmp_path / EVENTS_FILENAME, "journals/2026.journal") is None

    def test_returns_none_when_path_not_in_events(self, tmp_path: Path) -> None:
        emit_event(
            tmp_path,
            event_type="t.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2025.journal", "hash_before": "sha256:a", "hash_after": "sha256:b"}],
        )
        assert get_last_known_hash(tmp_path / EVENTS_FILENAME, "journals/2026.journal") is None

    def test_returns_most_recent_hash_after(self, tmp_path: Path) -> None:
        emit_event(
            tmp_path,
            event_type="e1.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:a", "hash_after": "sha256:b"}],
        )
        emit_event(
            tmp_path,
            event_type="e2.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:b", "hash_after": "sha256:c"}],
        )
        assert get_last_known_hash(tmp_path / EVENTS_FILENAME, "journals/2026.journal") == "sha256:c"

    def test_handles_corrupt_jsonl_line_gracefully(self, tmp_path: Path) -> None:
        events_file = tmp_path / EVENTS_FILENAME
        # Write a valid event, then a corrupt line, then another valid event
        emit_event(
            tmp_path,
            event_type="e1.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:a", "hash_after": "sha256:b"}],
        )
        with open(events_file, "a") as f:
            f.write("NOT VALID JSON\n")
        # Should skip the corrupt line and still find the valid event
        assert get_last_known_hash(events_file, "journals/2026.journal") == "sha256:b"


# ---------------------------------------------------------------------------
# check_drift
# ---------------------------------------------------------------------------


class TestCheckDrift:
    def test_returns_current_hash(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        journal.parent.mkdir(parents=True)
        journal.write_text("content", encoding="utf-8")
        result = check_drift(tmp_path, journal)
        assert result == hash_file(journal)

    def test_no_drift_event_when_no_baseline(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        journal.parent.mkdir(parents=True)
        journal.write_text("content", encoding="utf-8")
        check_drift(tmp_path, journal)
        events = _read_events(tmp_path)
        assert len(events) == 0

    def test_no_drift_event_when_hash_matches(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        journal.parent.mkdir(parents=True)
        journal.write_text("content", encoding="utf-8")
        h = hash_file(journal)
        # Seed the cache with the correct hash
        event_log_service._hash_cache[str(journal.resolve())] = h
        check_drift(tmp_path, journal)
        events = _read_events(tmp_path)
        assert len(events) == 0

    def test_emits_drift_event_when_hash_mismatches(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        journal.parent.mkdir(parents=True)
        journal.write_text("original", encoding="utf-8")
        # Seed cache with a stale hash
        event_log_service._hash_cache[str(journal.resolve())] = "sha256:stale"
        check_drift(tmp_path, journal)
        events = _read_events(tmp_path)
        assert len(events) == 1
        assert events[0]["type"] == "journal.external_edit_detected.v1"
        assert events[0]["payload"]["trigger"] == "pre_mutation"
        assert events[0]["actor"] == "system"

    def test_updates_cache_after_check(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        journal.parent.mkdir(parents=True)
        journal.write_text("data", encoding="utf-8")
        expected_hash = hash_file(journal)
        check_drift(tmp_path, journal)
        assert event_log_service._hash_cache[str(journal.resolve())] == expected_hash

    def test_falls_back_to_event_log_scan_when_cache_misses(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        journal.parent.mkdir(parents=True)
        journal.write_text("original", encoding="utf-8")
        original_hash = hash_file(journal)

        # Write an event with hash_after for this journal
        emit_event(
            tmp_path,
            event_type="e.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:x", "hash_after": original_hash}],
        )
        # Clear cache to force fallback to log scan
        event_log_service._hash_cache.clear()

        # No drift — file unchanged
        check_drift(tmp_path, journal)
        events = _read_events(tmp_path)
        assert not any(e["type"] == "journal.external_edit_detected.v1" for e in events)

    def test_drift_detected_via_event_log_fallback(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026.journal"
        journal.parent.mkdir(parents=True)
        journal.write_text("original", encoding="utf-8")

        # Write an event with a different hash_after
        emit_event(
            tmp_path,
            event_type="e.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:x", "hash_after": "sha256:old_hash"}],
        )
        # Clear cache to force fallback
        event_log_service._hash_cache.clear()

        check_drift(tmp_path, journal)
        events = _read_events(tmp_path)
        drift_events = [e for e in events if e["type"] == "journal.external_edit_detected.v1"]
        assert len(drift_events) == 1


# ---------------------------------------------------------------------------
# check_startup_drift
# ---------------------------------------------------------------------------


class TestCheckStartupDrift:
    def test_populates_cache_for_all_journals(self, tmp_path: Path) -> None:
        journals = tmp_path / "journals"
        journals.mkdir()
        (journals / "2025.journal").write_text("a", encoding="utf-8")
        (journals / "2026.journal").write_text("b", encoding="utf-8")
        # No events.jsonl → no drift check, but cache should be populated
        check_startup_drift(tmp_path)
        assert str((journals / "2025.journal").resolve()) in event_log_service._hash_cache
        assert str((journals / "2026.journal").resolve()) in event_log_service._hash_cache

    def test_skips_when_no_events_file(self, tmp_path: Path) -> None:
        journals = tmp_path / "journals"
        journals.mkdir()
        (journals / "2026.journal").write_text("data", encoding="utf-8")
        check_startup_drift(tmp_path)
        events = _read_events(tmp_path)
        assert len(events) == 0

    def test_skips_when_no_journals_dir(self, tmp_path: Path) -> None:
        # No journals directory — should not crash
        check_startup_drift(tmp_path)

    def test_detects_drift_at_startup(self, tmp_path: Path) -> None:
        journals = tmp_path / "journals"
        journals.mkdir()
        journal = journals / "2026.journal"
        journal.write_text("original", encoding="utf-8")

        # Create an event with a different hash_after
        emit_event(
            tmp_path,
            event_type="e.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:x", "hash_after": "sha256:different"}],
        )
        event_log_service._hash_cache.clear()

        check_startup_drift(tmp_path)

        events = _read_events(tmp_path)
        drift_events = [e for e in events if e["type"] == "journal.external_edit_detected.v1"]
        assert len(drift_events) == 1
        assert drift_events[0]["payload"]["trigger"] == "startup"

    def test_no_drift_when_hash_matches(self, tmp_path: Path) -> None:
        journals = tmp_path / "journals"
        journals.mkdir()
        journal = journals / "2026.journal"
        journal.write_text("data", encoding="utf-8")
        current_hash = hash_file(journal)

        emit_event(
            tmp_path,
            event_type="e.v1",
            summary="s",
            payload={},
            journal_refs=[{"path": "journals/2026.journal", "hash_before": "sha256:x", "hash_after": current_hash}],
        )
        event_log_service._hash_cache.clear()

        check_startup_drift(tmp_path)

        events = _read_events(tmp_path)
        drift_events = [e for e in events if e["type"] == "journal.external_edit_detected.v1"]
        assert len(drift_events) == 0


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
