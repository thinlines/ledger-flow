# Current Task

## Title

Git snapshot commits for workspace escape hatch

## Objective

Periodic git commits of `workspace/` provide a file-level recovery path independent of the event log. Snapshots are taken on server shutdown and on startup when >24 hours have passed since the last snapshot. This is the escape hatch described in DECISIONS.md §12: if `events.jsonl` is lost or corrupted, `git log -p` still shows every file state. Git is not the undo mechanism — it is the safety net beneath the event log.

## Scope

### Included

- New service: `app/backend/services/git_snapshot_service.py` — git init, `.gitignore` management, snapshot commit.
- Shutdown snapshot in the FastAPI lifespan teardown (after `yield`).
- Startup snapshot when the last commit is >24 hours old (or no commits exist yet).
- Managed `.gitignore` inside the workspace that excludes transient artifacts but includes all canonical files.
- Unit tests for the snapshot service.
- Integration with the existing lifespan handler in `main.py`.

### Explicitly Excluded

- Per-mutation commits (the event log is the primary audit trail; git snapshots are periodic).
- Git push, remote configuration, or multi-user sync.
- UI for browsing git history or restoring from snapshots.
- Git hooks, signing, or branch management.
- Snapshotting `.workflow/` contents (disposable by design).
- Any changes to the event log service or mutation endpoints.

## System Behavior

### Inputs

- Server startup (lifespan handler, before `yield`).
- Server shutdown (lifespan handler, after `yield`).

### Logic

**1. Workspace git repository initialization**

`ensure_workspace_repo(workspace_path: Path) -> None`:

1. Check if `workspace_path / ".git"` exists.
2. If not, run `git init` in the workspace directory.
3. Ensure `.gitignore` is present and up to date (see §2).
4. If this is a fresh init (no commits yet), create an initial commit: `"chore: initialize workspace repository"`.

The workspace git repo is separate from the app's own repo. The workspace directory (e.g., `~/Documents/MyBooks/`) is the user's financial data directory — it is not inside the app codebase.

**2. Managed `.gitignore`**

`ensure_gitignore(workspace_path: Path) -> None`:

Write/overwrite `workspace_path/.gitignore` with a managed block. The file is fully managed by the app — user customizations are not preserved (the workspace repo is an app-managed safety net, not a user-curated repo).

```gitignore
# Managed by Ledger Flow — do not edit
*.bak.*
inbox/
imports/
.workflow/
```

Rationale:
- `*.bak.*` — backup files created by `backup_service.py` (e.g., `2026.journal.import.bak.20260405143022`). Noise in diffs, large over time.
- `inbox/` — CSV files awaiting import. Transient; archived to `imports/` after successful import.
- `imports/` — archived CSVs. Useful for re-import but not needed in the safety-net repo. Potentially large.
- `.workflow/` — app state (stages, SQLite DB, import history). Disposable by design; rebuilt from journals.

Files that **are** tracked (by not being ignored):
- `journals/*.journal` — canonical financial data.
- `journals/archived-manual.journal` — matched manual entry archive (needed for unmatch).
- `events.jsonl` — the event log itself (the safety net backs up the safety net).
- `settings/workspace.toml` — workspace configuration.
- `rules/*.dat` — account declarations, tags, commodities, rule definitions.
- `opening/*.journal` — opening balance journals.

**3. Snapshot commit**

`snapshot_commit(workspace_path: Path, *, trigger: str) -> bool`:

1. Call `ensure_workspace_repo(workspace_path)` (idempotent).
2. Run `git -C <workspace> add -A` to stage all changes (respects `.gitignore`).
3. Check `git -C <workspace> diff --cached --quiet`. If exit code 0, no changes — return `False`.
4. Commit: `git -C <workspace> commit -m "snapshot: <trigger> at <ISO 8601 UTC timestamp>"`.
5. Return `True`.

The `trigger` parameter is `"shutdown"`, `"startup"`, or `"initial"` — included in the commit message for auditability.

Use `subprocess.run` with `capture_output=True` and `check=True`. Require `git` to be on `PATH` (reasonable for a developer-facing tool that already depends on `ledger` CLI).

**4. Last snapshot age check**

`hours_since_last_snapshot(workspace_path: Path) -> float | None`:

1. Run `git -C <workspace> log -1 --format=%cI` to get the committer date of the most recent commit.
2. Parse the ISO 8601 timestamp and compute hours elapsed.
3. Return `None` if there are no commits (fresh repo or git not initialized).

**5. Lifespan integration**

In the FastAPI lifespan handler:

```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    stages.cleanup_old(days=7)
    import_index.ensure_schema()
    # Existing startup drift check
    try:
        config = workspace_manager.load_active_config()
        if config is not None:
            check_startup_drift(config.root_dir)
    except Exception:
        _log.warning("Startup drift check failed — skipping", exc_info=True)
    # Startup snapshot (if stale)
    try:
        config = workspace_manager.load_active_config()
        if config is not None:
            age = hours_since_last_snapshot(config.root_dir)
            if age is None or age >= 24:
                snapshot_commit(config.root_dir, trigger="startup")
    except Exception:
        _log.warning("Startup git snapshot failed — skipping", exc_info=True)
    yield
    # Shutdown snapshot
    try:
        config = workspace_manager.load_active_config()
        if config is not None:
            snapshot_commit(config.root_dir, trigger="shutdown")
    except Exception:
        _log.warning("Shutdown git snapshot failed — skipping", exc_info=True)
```

Both startup and shutdown snapshots are wrapped in `try/except` — git failures must never crash the server or prevent shutdown.

**6. Git failure behavior**

Git snapshot operations are advisory — same precedence as the event log (journals > events > git). If any git command fails:
- Log the error with `logger.warning`.
- Continue — the server starts/stops normally.
- Do not retry (the next startup/shutdown will try again).
- If `git` is not installed, every snapshot call logs a warning and returns. The app functions normally without git.

### Outputs

- `workspace/.git/` — git repository with periodic snapshot commits.
- `workspace/.gitignore` — managed ignore rules.
- Commit history viewable via `git -C <workspace> log` and `git -C <workspace> log -p`.
- No API changes. No UI changes.

## System Invariants

- The workspace git repo is independent of the app's own git repo.
- Snapshot commits never block server startup or shutdown.
- `.gitignore` is fully managed — overwritten on every `ensure_workspace_repo` call.
- Snapshots only commit when there are staged changes (no empty commits).
- The commit message includes the trigger and timestamp for auditability.
- Git is not required for the app to function — all git operations degrade gracefully.

## States

- **No workspace configured**: all git operations skipped. No error.
- **Workspace exists, no `.git/`**: first `ensure_workspace_repo` call initializes the repo and creates an initial commit.
- **Workspace repo exists, no changes**: `snapshot_commit` returns `False`. No empty commit.
- **Workspace repo exists, changes present**: `snapshot_commit` stages and commits. Returns `True`.
- **Last snapshot <24h ago at startup**: startup snapshot skipped (no redundant commits during restarts/reloads).
- **Last snapshot >=24h ago at startup**: startup snapshot taken (covers long-running sessions where no shutdown snapshot was taken).
- **Git not installed**: all operations log a warning and return. App functions normally.

## Edge Cases

- **First-ever workspace bootstrap**: `bootstrap_workspace` creates the directory structure. The next server startup (or the shutdown of the current session) will initialize the git repo and create the initial commit.
- **Workspace directory moved or renamed**: the `.git/` directory moves with it. Next snapshot works normally.
- **Very large workspace**: `git add -A` + `commit` may be slow if many files exist. Journal files are typically <1 MB each; this is not a realistic concern. The `.gitignore` excludes the bulkiest artifacts (CSVs, backups).
- **Concurrent app instances**: same caveat as existing journal writes — single-user assumption. Two instances committing simultaneously could conflict, but this is not a supported configuration.
- **Shutdown during git operation**: `subprocess.run` will be interrupted. The git repo may have a stale lock file. The next startup's `git` command will either succeed (lock was cleaned up) or fail with a lock error (logged, skipped).
- **User runs their own git commands in the workspace**: the app does not hold or check locks. The app's managed `.gitignore` will be overwritten, but the user's commits are preserved. The app's snapshot commits coexist with user commits in the same history.

## Failure Behavior

- **`git init` fails**: log warning, skip all subsequent git operations for this call. App functions normally.
- **`git add -A` fails**: log warning, skip commit. Next snapshot will retry.
- **`git commit` fails**: log warning. If due to lock file, next attempt may succeed once lock is released.
- **`git log` fails** (for age check): treat as `None` (no previous snapshot), proceed with snapshot.
- **`git` not on PATH**: `FileNotFoundError` from `subprocess.run`. Caught, logged, skipped.
- **Lifespan teardown interrupted** (SIGKILL): shutdown snapshot is best-effort. The next startup snapshot will capture the state.

## Regression Risks

- **Server startup time**: `git init` + initial commit + `git add -A` + `git status` adds latency on first run. Subsequent startups only check `git log -1` (fast). Acceptable for a developer-facing tool.
- **Server shutdown time**: one `git add -A` + `git commit` on shutdown. Typically <100ms for a small workspace. Should not noticeably delay shutdown.
- **Disk usage**: git objects accumulate over time. Without `git gc`, the `.git/` directory will grow. For a workspace with ~10 journal files and daily snapshots, this is ~50 KB/day. After a year, ~20 MB. Acceptable without compaction.
- **Existing tests**: no test currently depends on the workspace being a non-git directory. The `tmp_path` fixtures create fresh directories that are not git repos. Snapshot service tests will use `tmp_path` with explicit `git init`.
- **`workspace_manager.load_active_config()` called twice in lifespan**: once for drift check, once for snapshot. The function is cheap (reads a TOML file). Could be deduplicated, but clarity is worth more than the microsecond saved.

## Acceptance Criteria

- On server shutdown, `workspace/.git/` contains a commit with the current state of all non-ignored files.
- On server startup, if >24 hours have passed since the last commit (or no commits exist), a snapshot commit is created.
- `workspace/.gitignore` excludes `*.bak.*`, `inbox/`, `imports/`, `.workflow/`.
- `workspace/.gitignore` does not exclude `journals/`, `events.jsonl`, `settings/`, `rules/`, or `opening/`.
- No empty commits are created when nothing has changed.
- Commit messages include the trigger (`shutdown`/`startup`/`initial`) and UTC timestamp.
- Git failures do not prevent server startup or shutdown.
- The app functions normally when `git` is not installed (graceful degradation).
- `uv run pytest -q` passes in `app/backend`.
- `pnpm check` passes in `app/frontend` (no frontend change).

## Proposed Sequence

1. **Create `git_snapshot_service.py`** with `ensure_gitignore()`, `ensure_workspace_repo()`, `snapshot_commit()`, `hours_since_last_snapshot()`. Unit tests: repo initialized, gitignore written, snapshot creates commit, no empty commit when unchanged, age check returns correct hours, graceful failure when git missing.

2. **Integrate into FastAPI lifespan**: startup snapshot (conditional on age), shutdown snapshot (unconditional). Verify existing startup drift check still runs. Test: startup with stale repo creates commit; startup with fresh repo skips; shutdown always attempts.

3. **Manual verification**: start the app with a workspace, make an import, stop the server, inspect `git -C <workspace> log --oneline` for snapshot commits.

## Definition of Done

- Periodic git snapshot commits capture workspace state on shutdown and stale startup.
- `.gitignore` excludes transient artifacts, includes all canonical files.
- Git operations never block or crash the server.
- The workspace git repo is independent of the app repo.
- All existing tests pass. New tests cover the snapshot service.
- No UI-visible change. No API change.

## Out of Scope

- Per-mutation commits.
- Git push, remote, or sync.
- UI for git history browsing or restoration.
- Git hooks, signing, tags, or branches.
- `.workflow/` in the snapshot (disposable by design).
- `git gc` or repository maintenance.
- Event log changes.
