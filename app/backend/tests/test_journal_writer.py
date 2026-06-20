"""Unit tests for journal_writer.mutate — the single chokepoint for journal mutations.

The writer is a deep module; these tests exercise observable external behavior
at the ``mutate(...)`` interface and assert against the filesystem and the
event log. They do not mock ``check_drift`` / ``hash_file`` / the writer's
internal backup helper, and they do not exercise any domain code or the real
``ledger`` CLI.

The op passed into the writer in every test is a trivial fake that writes a
known string to a path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from services import event_log_service, journal_writer
from services.config_service import AppConfig
from services.event_log_service import EVENTS_FILENAME, hash_file
from services.journal_writer import (
    JournalMutation,
    VerifyFailure,
    WriterError,
    WriterRejected,
    WriterUnavailable,
    mutate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_hash_cache():
    """Reset the event_log_service hash cache between tests."""
    event_log_service._hash_cache.clear()
    yield
    event_log_service._hash_cache.clear()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "journals").mkdir()
    return tmp_path


@pytest.fixture
def config(workspace: Path) -> AppConfig:
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test"},
        dirs={
            "csv_dir": "csv",
            "journal_dir": "journals",
            "init_dir": "init",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
    )


@pytest.fixture
def journal_path(workspace: Path) -> Path:
    p = workspace / "journals" / "2026.journal"
    p.write_text("; original\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_events(workspace: Path) -> list[dict]:
    events_file = workspace / EVENTS_FILENAME
    if not events_file.is_file():
        return []
    return [
        json.loads(line)
        for line in events_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _emitted(workspace: Path, event_type: str) -> list[dict]:
    return [e for e in _read_events(workspace) if e.get("type") == event_type]


# ---------------------------------------------------------------------------
# 1. Event ID minting
# ---------------------------------------------------------------------------


class TestEventIdMinting:
    def test_mints_non_empty_event_id(self, config: AppConfig, journal_path: Path) -> None:
        with mutate(
            config=config,
            paths=[journal_path],
            tag="t",
            event_type="test.created.v1",
        ) as mut:
            assert mut.event_id
            assert len(mut.event_id) > 10

    def test_event_id_distinct_across_calls(self, config: AppConfig, journal_path: Path) -> None:
        ids: list[str] = []
        for _ in range(3):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="t",
                event_type="test.created.v1",
            ) as mut:
                ids.append(mut.event_id)
                journal_path.write_text(f"; new {mut.event_id}\n", encoding="utf-8")
        assert len(set(ids)) == 3

    def test_event_id_matches_emitted_event(self, config: AppConfig, journal_path: Path) -> None:
        with mutate(
            config=config,
            paths=[journal_path],
            tag="t",
            event_type="test.created.v1",
        ) as mut:
            mutation_id = mut.event_id
            journal_path.write_text("; mutated\n", encoding="utf-8")
        events = _emitted(config.root_dir, "test.created.v1")
        assert len(events) == 1
        assert events[0]["id"] == mutation_id


# ---------------------------------------------------------------------------
# 2. Pre-mutation hashing
# ---------------------------------------------------------------------------


class TestPreMutationHashing:
    def test_hash_before_consistent_with_hash_file(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        expected_before = hash_file(journal_path)
        with mutate(
            config=config,
            paths=[journal_path],
            tag="t",
            event_type="test.v1",
        ):
            journal_path.write_text("; mutated\n", encoding="utf-8")
        event = _emitted(config.root_dir, "test.v1")[0]
        assert event["journal_refs"][0]["hash_before"] == expected_before


# ---------------------------------------------------------------------------
# 3. Backup creation
# ---------------------------------------------------------------------------


class TestBackup:
    def test_backup_created_for_existing_path(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        original_contents = journal_path.read_bytes()
        with mutate(
            config=config,
            paths=[journal_path],
            tag="backup-test",
            event_type="test.v1",
        ):
            journal_path.write_text("; mutated\n", encoding="utf-8")
        # Find the backup file in the journal dir.
        backups = list(journal_path.parent.glob(f"{journal_path.name}.backup-test.bak.*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original_contents

    def test_no_backup_for_missing_path(self, config: AppConfig, journal_path: Path) -> None:
        missing = config.root_dir / "journals" / "2027.journal"
        assert not missing.exists()
        with mutate(
            config=config,
            paths=[journal_path, missing],
            tag="backup-test",
            event_type="test.v1",
        ):
            missing.write_text("; new\n", encoding="utf-8")
        backups = list(missing.parent.glob(f"{missing.name}.backup-test.bak.*"))
        assert backups == []


# ---------------------------------------------------------------------------
# 4. Successful exit: event shape + journal_refs filtering
# ---------------------------------------------------------------------------


class TestSuccessfulExit:
    def test_emits_exactly_one_event_with_set_fields(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with mutate(
            config=config,
            paths=[journal_path],
            tag="t",
            event_type="thing.happened.v1",
        ) as mut:
            journal_path.write_text("; new\n", encoding="utf-8")
            mut.summary = "It happened"
            mut.payload = {"reason": "test"}
            mut.compensates = None
        events = _emitted(config.root_dir, "thing.happened.v1")
        assert len(events) == 1
        event = events[0]
        assert event["summary"] == "It happened"
        assert event["payload"] == {"reason": "test"}
        assert event["compensates"] is None

    def test_compensates_recorded_when_set(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with mutate(
            config=config,
            paths=[journal_path],
            tag="t",
            event_type="thing.compensated.v1",
        ) as mut:
            journal_path.write_text("; new\n", encoding="utf-8")
            mut.compensates = "01900000-0000-7000-8000-000000000000"
        event = _emitted(config.root_dir, "thing.compensated.v1")[0]
        assert event["compensates"] == "01900000-0000-7000-8000-000000000000"

    def test_journal_refs_filtered_to_changed_paths(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        other = config.root_dir / "journals" / "2025.journal"
        other.write_text("; untouched\n", encoding="utf-8")
        with mutate(
            config=config,
            paths=[journal_path, other],
            tag="t",
            event_type="multi.v1",
        ):
            journal_path.write_text("; changed\n", encoding="utf-8")
            # `other` is intentionally not modified.
        event = _emitted(config.root_dir, "multi.v1")[0]
        ref_paths = {ref["path"] for ref in event["journal_refs"]}
        assert "journals/2026.journal" in ref_paths
        assert "journals/2025.journal" not in ref_paths

    def test_journal_refs_includes_newly_created_paths(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        new_journal = config.root_dir / "journals" / "2027.journal"
        with mutate(
            config=config,
            paths=[journal_path, new_journal],
            tag="t",
            event_type="multi.v1",
        ):
            journal_path.write_text("; changed\n", encoding="utf-8")
            new_journal.write_text("; new file\n", encoding="utf-8")
        event = _emitted(config.root_dir, "multi.v1")[0]
        new_ref = next(
            ref for ref in event["journal_refs"] if ref["path"] == "journals/2027.journal"
        )
        assert new_ref["hash_before"] == "sha256:none"
        assert new_ref["hash_after"].startswith("sha256:")
        assert new_ref["hash_after"] != "sha256:none"


# ---------------------------------------------------------------------------
# 5. Exception inside the block
# ---------------------------------------------------------------------------


class TestBlockException:
    def test_restores_existing_path_byte_for_byte(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        original = journal_path.read_bytes()
        with pytest.raises(ValueError, match="boom"):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="t",
                event_type="test.v1",
            ):
                journal_path.write_text("; mid-mutation\n", encoding="utf-8")
                raise ValueError("boom")
        assert journal_path.read_bytes() == original

    def test_deletes_paths_created_during_block(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        new_journal = config.root_dir / "journals" / "2028.journal"
        with pytest.raises(RuntimeError, match="boom"):
            with mutate(
                config=config,
                paths=[journal_path, new_journal],
                tag="t",
                event_type="test.v1",
            ):
                new_journal.write_text("; created\n", encoding="utf-8")
                raise RuntimeError("boom")
        assert not new_journal.exists()

    def test_no_event_emitted_on_block_exception(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with pytest.raises(ValueError):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="t",
                event_type="should.not.appear.v1",
            ):
                journal_path.write_text("; partial\n", encoding="utf-8")
                raise ValueError("nope")
        assert _emitted(config.root_dir, "should.not.appear.v1") == []

    def test_original_exception_propagates(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with pytest.raises(KeyError, match="missing"):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="t",
                event_type="test.v1",
            ):
                raise KeyError("missing")


# ---------------------------------------------------------------------------
# 6. Verifier returning VerifyFailure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReconLikeFailure(VerifyFailure):
    expected: str
    actual: str


def _failing_verifier(_config: AppConfig, _paths: list[Path]) -> VerifyFailure | None:
    return _ReconLikeFailure(expected="$100", actual="$90")


class TestVerifyFailure:
    def test_verify_failure_triggers_writer_rejected(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with pytest.raises(WriterRejected) as excinfo:
            with mutate(
                config=config,
                paths=[journal_path],
                tag="reconcile",
                event_type="recon.v1",
                verify=_failing_verifier,
            ):
                journal_path.write_text("; assertion\n", encoding="utf-8")
        assert isinstance(excinfo.value.failure, _ReconLikeFailure)
        assert excinfo.value.failure.expected == "$100"
        assert excinfo.value.failure.actual == "$90"

    def test_verify_failure_restores_file(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        original = journal_path.read_bytes()
        with pytest.raises(WriterRejected):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="reconcile",
                event_type="recon.v1",
                verify=_failing_verifier,
            ):
                journal_path.write_text("; assertion\n", encoding="utf-8")
        assert journal_path.read_bytes() == original

    def test_no_event_emitted_on_verify_failure(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with pytest.raises(WriterRejected):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="reconcile",
                event_type="recon.v1",
                verify=_failing_verifier,
            ):
                journal_path.write_text("; assertion\n", encoding="utf-8")
        assert _emitted(config.root_dir, "recon.v1") == []


# ---------------------------------------------------------------------------
# 7. Verifier raising RuntimeError
# ---------------------------------------------------------------------------


def _unavailable_verifier(_config: AppConfig, _paths: list[Path]) -> VerifyFailure | None:
    raise RuntimeError("ledger CLI is unavailable")


class TestVerifyUnavailable:
    def test_runtime_error_triggers_writer_unavailable(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with pytest.raises(WriterUnavailable, match="ledger CLI"):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="reconcile",
                event_type="recon.v1",
                verify=_unavailable_verifier,
            ):
                journal_path.write_text("; assertion\n", encoding="utf-8")

    def test_unavailable_restores_file(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        original = journal_path.read_bytes()
        with pytest.raises(WriterUnavailable):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="reconcile",
                event_type="recon.v1",
                verify=_unavailable_verifier,
            ):
                journal_path.write_text("; assertion\n", encoding="utf-8")
        assert journal_path.read_bytes() == original

    def test_no_event_emitted_on_unavailable(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with pytest.raises(WriterUnavailable):
            with mutate(
                config=config,
                paths=[journal_path],
                tag="reconcile",
                event_type="recon.v1",
                verify=_unavailable_verifier,
            ):
                journal_path.write_text("; assertion\n", encoding="utf-8")
        assert _emitted(config.root_dir, "recon.v1") == []


# ---------------------------------------------------------------------------
# 8. Validation: paths must contain at least one *.journal file
# ---------------------------------------------------------------------------


class TestPathValidation:
    def test_rejects_paths_without_journal_file(
        self, config: AppConfig, workspace: Path
    ) -> None:
        accounts_dat = workspace / "init" / "10-accounts.dat"
        accounts_dat.parent.mkdir(parents=True, exist_ok=True)
        accounts_dat.write_text("; accounts\n", encoding="utf-8")
        with pytest.raises(ValueError, match="at least one"):
            with mutate(
                config=config,
                paths=[accounts_dat],
                tag="t",
                event_type="bad.v1",
            ):
                pytest.fail("block should not execute")  # pragma: no cover

    def test_accepts_journal_with_co_candidate(
        self, config: AppConfig, journal_path: Path, workspace: Path
    ) -> None:
        accounts_dat = workspace / "init" / "10-accounts.dat"
        accounts_dat.parent.mkdir(parents=True, exist_ok=True)
        accounts_dat.write_text("; accounts\n", encoding="utf-8")
        with mutate(
            config=config,
            paths=[journal_path, accounts_dat],
            tag="t",
            event_type="multi.v1",
        ):
            journal_path.write_text("; changed\n", encoding="utf-8")
            accounts_dat.write_text("; changed\n", encoding="utf-8")
        events = _emitted(config.root_dir, "multi.v1")
        assert len(events) == 1


# ---------------------------------------------------------------------------
# 9. Partial rollback failure
# ---------------------------------------------------------------------------


class TestPartialRollback:
    def test_partial_restore_failure_raises_writer_error(
        self,
        config: AppConfig,
        journal_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        other = config.root_dir / "journals" / "2025.journal"
        other.write_text("; other original\n", encoding="utf-8")

        from services import journal_writer as jw

        real_copyfile = jw.shutil.copyfile

        def flaky_copyfile(src: str, dst: str) -> None:
            if dst.endswith("2026.journal"):
                raise PermissionError("simulated restore failure")
            real_copyfile(src, dst)

        monkeypatch.setattr(jw.shutil, "copyfile", flaky_copyfile)

        with pytest.raises(WriterError) as excinfo:
            with mutate(
                config=config,
                paths=[journal_path, other],
                tag="t",
                event_type="test.v1",
            ):
                journal_path.write_text("; mid\n", encoding="utf-8")
                other.write_text("; mid other\n", encoding="utf-8")
                raise RuntimeError("trigger rollback")

        failures = excinfo.value.restore_failures
        assert len(failures) == 1
        assert failures[0].path == journal_path
        assert isinstance(failures[0].error, PermissionError)
        # The other path was restored even though the first one failed.
        assert other.read_text(encoding="utf-8") == "; other original\n"

    def test_partial_restore_preserves_triggering_exception_via_context(
        self,
        config: AppConfig,
        journal_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from services import journal_writer as jw

        def always_fail(*_a: object, **_k: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(jw.shutil, "copyfile", always_fail)

        with pytest.raises(WriterError) as excinfo:
            with mutate(
                config=config,
                paths=[journal_path],
                tag="t",
                event_type="test.v1",
            ):
                journal_path.write_text("; mid\n", encoding="utf-8")
                raise ValueError("original cause")

        # Python's standard chaining preserves the original exception.
        assert isinstance(excinfo.value.__context__, ValueError)
        assert str(excinfo.value.__context__) == "original cause"


# ---------------------------------------------------------------------------
# Misc behavioral guarantees
# ---------------------------------------------------------------------------


class TestMisc:
    def test_mutation_object_default_summary_empty(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with mutate(
            config=config,
            paths=[journal_path],
            tag="t",
            event_type="test.v1",
        ):
            journal_path.write_text("; changed\n", encoding="utf-8")
        event = _emitted(config.root_dir, "test.v1")[0]
        assert event["summary"] == ""
        assert event["payload"] == {}

    def test_no_journal_refs_when_no_path_changed(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with mutate(
            config=config,
            paths=[journal_path],
            tag="t",
            event_type="noop.v1",
        ):
            pass  # don't write anything
        event = _emitted(config.root_dir, "noop.v1")[0]
        assert event["journal_refs"] == []

    def test_actor_forwarded_to_event(
        self, config: AppConfig, journal_path: Path
    ) -> None:
        with mutate(
            config=config,
            paths=[journal_path],
            tag="t",
            event_type="test.v1",
            actor="system",
        ):
            journal_path.write_text("; changed\n", encoding="utf-8")
        event = _emitted(config.root_dir, "test.v1")[0]
        assert event["actor"] == "system"

    def test_journal_mutation_dataclass_basic_access(self) -> None:
        m = JournalMutation(event_id="abc")
        m.summary = "x"
        m.payload = {"k": "v"}
        m.compensates = "prev"
        assert m.event_id == "abc"
        assert m.summary == "x"
        assert m.payload == {"k": "v"}
        assert m.compensates == "prev"
