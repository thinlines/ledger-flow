# Ledger Flow — Agent Instructions

## Working on tasks

When the user asks to implement, build, ship, finish, or work on a task — or references TASK.md, ROADMAP.md, or similar planning artifacts — invoke the `senior-developer` skill before starting work. That skill owns the end-to-end workflow for engineering tasks in this repo.

## Worktrees

- **Main worktree:** the project root (`/home/randy/Desktop/tmp-books`). Orchestrators run here; merges land here.
- **Feat worktree:** pre-built at `.claude/worktrees/feat`, dependencies pre-warmed (`pnpm install`, `uv sync`). Single-task `ship-task` pipelines run implementation here. Sandbox mode auto-approves Bash inside `.claude/worktrees/*` (the directory sits under `.claude/`, which is in the sandbox writable allowlist via `additionalDirectories`). Ship-task creates a per-task branch with `git -C <feat> checkout -b <branch> master` at Phase 0 and resets it back to detached master at Phase 5.
- **Ad-hoc worktrees:** multi-task concurrent mode creates worktrees under `.claude/worktrees/agent-*` per task and removes them after merge.

## Pipeline scope enforcement

When a `<worktree>/.pipeline-context` file exists (created by `ship-task` Phase 0), the `enforce-task-scope.py` PreToolUse hook checks every Edit/Write against that task's `SCOPE_INCLUDED` / `SCOPE_EXCLUDED`. Out-of-scope edits are **allowed but warned** — the warning is surfaced back to the agent so it can self-correct or note the necessary collateral. Scope drift is the most common cause of fix-loop iterations; treat warnings as a signal to pause, not a green light to continue blindly.

## Shell command style

**Prefer built-in tools over Bash.** Built-in tools are faster than spawning a subprocess and produce cleaner tool-call streams (precise diffs from `Edit` vs `sed`, structured `Grep`/`Glob` results vs raw shell output).

| Instead of...                         | Use...                                      |
|---------------------------------------|---------------------------------------------|
| `cat <file>`                          | **Read**                                    |
| `head -N <file>` / `tail -N <file>`   | **Read** with `offset` / `limit`            |
| `grep <pattern> <file>`               | **Grep**                                    |
| `find . -name "<pattern>"`            | **Glob**                                    |
| `ls <dir>/`                           | **Glob** with `<dir>/**`                    |
| `git show HEAD:<path>` (file on disk) | **Read** (unless you need a past revision)  |
| `sed 's/.../.../' <file>` to edit     | **Edit**                                    |

**Reserve Bash for what built-ins cannot do:** running tests, build commands, git operations (`commit`, `add`, `status`, `log`, `diff`), dev servers, installing dependencies, linters.

**Prefer parallel tool calls over chained shell.** Independent commands should run as separate Bash calls in the same response — they execute in parallel. Chains (`&&`, `||`, `;`) and shell loops force serial execution and obscure per-step exit codes, so reach for them only when steps are genuinely coupled (e.g. setting an env var the next command reads). Pipes (`|`) and stderr redirects (`2>/dev/null`, `2>&1`) are not chains — use them freely.

- **Git**: _always_ use the /git-committer skill to commit to git.
- **Working in another directory** (e.g. a worktree):
  - For git, prefer `git -C <path> <subcommand>` — keeps the working directory unambiguous in the tool-call stream.
  - For everything else (`pnpm`, `npm`, `mise`, `pytest`, etc.), `cd <path>` in one call, then run the plain command in subsequent calls. The working directory persists between Bash calls, so one `cd` covers a sequence.
