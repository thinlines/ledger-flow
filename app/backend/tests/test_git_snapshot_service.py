"""Unit tests for git_snapshot_service — repo init, gitignore, snapshots, age check."""

from __future__ import annotations

import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from services.config_service import AppConfig
from services.git_snapshot_service import (
    _MANAGED_GITIGNORE,
    ensure_gitignore,
    ensure_workspace_repo,
    hours_since_last_snapshot,
    snapshot_commit,
)
from services.operation_dump_service import check_operation_dump
from services.operations_service import record_operation
from services.projection_db import connect, database_path, ensure_database


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


def _git(workspace: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(workspace)] + args,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _git_log_oneline(workspace: Path) -> list[str]:
    return _git(workspace, ["log", "--oneline", "--format=%s"]).splitlines()


# ---------------------------------------------------------------------------
# ensure_gitignore
# ---------------------------------------------------------------------------


class TestEnsureGitignore:
    def test_creates_gitignore(self, tmp_path: Path) -> None:
        ensure_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert "*.bak.*" in content
        assert "inbox/" in content
        assert "imports/" in content
        assert ".workflow/" in content

    def test_overwrites_existing_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("old content\n", encoding="utf-8")
        ensure_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert content == _MANAGED_GITIGNORE

    def test_does_not_ignore_journals(self, tmp_path: Path) -> None:
        ensure_gitignore(tmp_path)
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert "journals/" not in content
        assert "events.jsonl" not in content
        assert "settings/" not in content
        assert "rules/" not in content


# ---------------------------------------------------------------------------
# ensure_workspace_repo
# ---------------------------------------------------------------------------


class TestEnsureWorkspaceRepo:
    def test_initializes_git_repo(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "journals").mkdir()
        (workspace / "journals" / "2026.journal").write_text("data\n")

        ensure_workspace_repo(workspace)

        assert (workspace / ".git").is_dir()
        commits = _git_log_oneline(workspace)
        assert len(commits) == 1
        assert "initialize" in commits[0]

    def test_idempotent_on_existing_repo(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        ensure_workspace_repo(workspace)
        ensure_workspace_repo(workspace)

        commits = _git_log_oneline(workspace)
        assert len(commits) == 1  # only the initial commit

    def test_creates_gitignore_in_repo(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        ensure_workspace_repo(workspace)

        assert (workspace / ".gitignore").exists()
        # .gitignore should be committed
        tracked = _git(workspace, ["ls-files", ".gitignore"])
        assert ".gitignore" in tracked


# ---------------------------------------------------------------------------
# snapshot_commit
# ---------------------------------------------------------------------------


class TestSnapshotCommit:
    def test_exports_operation_history_dump_before_snapshot(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        config = _make_config(workspace)
        ensure_workspace_repo(workspace)

        record_operation(
            config,
            operation_type="manual_entry.created.v1",
            summary="Created Lunch",
            payload={"txn_id": "txn-2"},
            files=[
                {
                    "path": "journals/2026.journal",
                    "hash_before": "",
                    "hash_after": "sha256:after",
                }
            ],
            operation_id="op-2",
            created_at="2026-07-05T11:00:00+00:00",
        )

        result = snapshot_commit(workspace, trigger="shutdown")

        assert result is True
        dump_path = workspace / "operation-history.dump.sql"
        dump = dump_path.read_text(encoding="utf-8")
        assert "manual_entry.created.v1" in dump
        assert "Created Lunch" in dump
        assert "journals/2026.journal" in dump
        tracked = _git(workspace, ["ls-files"]).splitlines()
        assert "operation-history.dump.sql" in tracked
        assert not any(".workflow" in f for f in tracked)

    def test_projection_and_workflow_table_changes_do_not_churn_dump(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        config = _make_config(workspace)
        ensure_workspace_repo(workspace)
        record_operation(
            config,
            operation_type="manual_entry.created.v1",
            summary="Created Lunch",
            payload={},
            files=[],
            operation_id="op-2",
            created_at="2026-07-05T11:00:00+00:00",
        )
        assert snapshot_commit(workspace, trigger="shutdown") is True
        dump_path = workspace / "operation-history.dump.sql"
        before = dump_path.read_text(encoding="utf-8")

        db_path = ensure_database(config)
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO journal_files (
                    id, path, role, content_hash, parsed_at, parse_status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "file-1",
                    "journals/2026.journal",
                    "journal",
                    "sha256:projection",
                    "2026-07-05T12:00:00+00:00",
                    "ok",
                ),
            )
            conn.execute(
                """
                INSERT INTO stages (
                    id, kind, status, created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "stage-1",
                    "unknowns",
                    "ready",
                    "2026-07-05T12:00:00+00:00",
                    "2026-07-05T12:00:00+00:00",
                    "{}",
                ),
            )

        assert snapshot_commit(workspace, trigger="shutdown") is False
        assert dump_path.read_text(encoding="utf-8") == before
        assert "journal_files" not in before
        assert "stages" not in before

    def test_operation_dump_check_survives_database_loss(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        config = _make_config(workspace)
        ensure_workspace_repo(workspace)
        record_operation(
            config,
            operation_type="manual_entry.created.v1",
            summary="Created Lunch",
            payload={"txn_id": "txn-2"},
            files=[],
            operation_id="op-2",
            created_at="2026-07-05T11:00:00+00:00",
        )
        assert snapshot_commit(workspace, trigger="shutdown") is True

        db_path = database_path(config)
        for path in [
            db_path,
            db_path.with_name(f"{db_path.name}-wal"),
            db_path.with_name(f"{db_path.name}-shm"),
        ]:
            path.unlink(missing_ok=True)

        result = check_operation_dump(workspace)

        assert result == {
            "ok": True,
            "operation_count": 1,
            "tables": {
                "operations": 1,
                "operation_files": 0,
                "operation_entities": 0,
                "rules": 0,
                "rule_condition_groups": 0,
                "rule_conditions": 0,
                "rule_actions": 0,
            },
        }

    def test_creates_commit_when_changes_exist(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ensure_workspace_repo(workspace)

        # Add a file after initial commit
        (workspace / "journals").mkdir()
        (workspace / "journals" / "2026.journal").write_text("data\n")

        result = snapshot_commit(workspace, trigger="shutdown")

        assert result is True
        commits = _git_log_oneline(workspace)
        assert len(commits) == 2
        assert "snapshot: shutdown at" in commits[0]

    def test_returns_false_when_nothing_changed(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ensure_workspace_repo(workspace)

        result = snapshot_commit(workspace, trigger="shutdown")

        assert result is False
        commits = _git_log_oneline(workspace)
        assert len(commits) == 1  # only initial commit

    def test_trigger_appears_in_commit_message(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ensure_workspace_repo(workspace)

        (workspace / "test.txt").write_text("hello\n")
        snapshot_commit(workspace, trigger="startup")

        msg = _git_log_oneline(workspace)[0]
        assert "snapshot: startup at" in msg

    def test_gitignore_excludes_bak_files(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "journals").mkdir()
        ensure_workspace_repo(workspace)

        # Create a .bak file and a journal
        (workspace / "journals" / "2026.journal").write_text("data\n")
        (workspace / "journals" / "2026.journal.import.bak.20260405").write_text("backup\n")

        snapshot_commit(workspace, trigger="shutdown")

        tracked = _git(workspace, ["ls-files"]).splitlines()
        assert "journals/2026.journal" in tracked
        assert not any(".bak." in f for f in tracked)

    def test_gitignore_excludes_workflow_dir(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ensure_workspace_repo(workspace)

        (workspace / ".workflow").mkdir()
        (workspace / ".workflow" / "state.db").write_text("db\n")
        (workspace / "events.jsonl").write_text("{}\n")

        snapshot_commit(workspace, trigger="shutdown")

        tracked = _git(workspace, ["ls-files"]).splitlines()
        assert "events.jsonl" in tracked
        assert not any(".workflow" in f for f in tracked)

    def test_gitignore_excludes_inbox_and_imports(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ensure_workspace_repo(workspace)

        for d in ["inbox", "imports"]:
            (workspace / d).mkdir()
            (workspace / d / "file.csv").write_text("csv\n")

        (workspace / "settings").mkdir()
        (workspace / "settings" / "workspace.toml").write_text("[workspace]\n")

        snapshot_commit(workspace, trigger="shutdown")

        tracked = _git(workspace, ["ls-files"]).splitlines()
        assert "settings/workspace.toml" in tracked
        assert not any("inbox/" in f for f in tracked)
        assert not any("imports/" in f for f in tracked)

    def test_initializes_repo_if_needed(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "data.txt").write_text("hello\n")

        # snapshot_commit should init the repo automatically
        result = snapshot_commit(workspace, trigger="startup")

        assert (workspace / ".git").is_dir()
        # Initial commit + snapshot (if data.txt was already committed in init,
        # the snapshot would be empty — but .gitignore change counts)
        commits = _git_log_oneline(workspace)
        assert len(commits) >= 1


# ---------------------------------------------------------------------------
# hours_since_last_snapshot
# ---------------------------------------------------------------------------


class TestHoursSinceLastSnapshot:
    def test_returns_none_for_non_repo(self, tmp_path: Path) -> None:
        assert hours_since_last_snapshot(tmp_path) is None

    def test_returns_none_for_empty_repo(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        subprocess.run(["git", "-C", str(workspace), "init"], capture_output=True, check=True)
        assert hours_since_last_snapshot(workspace) is None

    def test_returns_small_value_for_recent_commit(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ensure_workspace_repo(workspace)

        age = hours_since_last_snapshot(workspace)
        assert age is not None
        assert age < 1  # commit was just made

    def test_returns_correct_age(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ensure_workspace_repo(workspace)

        # Amend the commit with a date 48 hours ago
        old_date = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        monkeypatch.setenv("GIT_COMMITTER_DATE", old_date)
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "--amend", "--no-edit",
             "--date", old_date],
            capture_output=True,
            check=True,
        )

        age = hours_since_last_snapshot(workspace)
        assert age is not None
        assert age >= 47  # at least 47 hours (allowing for test execution time)
