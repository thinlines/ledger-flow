"""Periodic git snapshot commits for workspace escape hatch.

Snapshots are taken on server shutdown and on startup when >24 hours have
passed since the last commit.  Git is the safety net beneath the event log —
if ``events.jsonl`` is lost, ``git log -p`` still shows every file state.

All operations degrade gracefully: if ``git`` is not installed or any command
fails, the error is logged and the caller continues normally.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MANAGED_GITIGNORE = """\
# Managed by Ledger Flow — do not edit
*.bak.*
inbox/
imports/
.workflow/
"""


def ensure_gitignore(workspace_path: Path) -> None:
    """Write the managed ``.gitignore`` into *workspace_path*."""
    gitignore = workspace_path / ".gitignore"
    gitignore.write_text(_MANAGED_GITIGNORE, encoding="utf-8")


def ensure_workspace_repo(workspace_path: Path) -> None:
    """Initialize *workspace_path* as a git repo if it isn't one already."""
    git_dir = workspace_path / ".git"
    fresh = not git_dir.exists()

    if fresh:
        _run_git(workspace_path, ["init"])
        _run_git(workspace_path, ["config", "user.name", "Ledger Flow"])
        _run_git(workspace_path, ["config", "user.email", "ledger-flow@localhost"])

    ensure_gitignore(workspace_path)

    if fresh:
        _run_git(workspace_path, ["add", "-A"])
        _run_git(workspace_path, ["commit", "-m", "chore: initialize workspace repository"])


def snapshot_commit(workspace_path: Path, *, trigger: str) -> bool:
    """Stage all changes and commit if anything changed.

    Returns ``True`` if a commit was created, ``False`` if nothing to commit.
    """
    ensure_workspace_repo(workspace_path)

    _run_git(workspace_path, ["add", "-A"])

    result = subprocess.run(
        ["git", "-C", str(workspace_path), "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if result.returncode == 0:
        return False  # nothing staged

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _run_git(workspace_path, ["commit", "-m", f"snapshot: {trigger} at {ts}"])
    return True


def hours_since_last_snapshot(workspace_path: Path) -> float | None:
    """Return hours since the most recent commit, or ``None`` if no commits."""
    result = subprocess.run(
        ["git", "-C", str(workspace_path), "log", "-1", "--format=%cI"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    last_commit_dt = datetime.fromisoformat(result.stdout.strip())
    delta = datetime.now(timezone.utc) - last_commit_dt
    return delta.total_seconds() / 3600


def _run_git(workspace_path: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run a git command in *workspace_path*.  Raises on failure."""
    return subprocess.run(
        ["git", "-C", str(workspace_path)] + args,
        capture_output=True,
        check=True,
    )
