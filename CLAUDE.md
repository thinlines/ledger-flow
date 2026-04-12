# Ledger Flow — Agent Instructions

## Working on tasks

When the user asks to implement, build, ship, finish, or work on a task — or references TASK.md, ROADMAP.md, or similar planning artifacts — invoke the `senior-developer` skill before starting work. That skill owns the end-to-end workflow for engineering tasks in this repo.

## Shell command style

Prefer non-chaining command forms so per-subcommand permission rules apply cleanly. The Bash permission matcher is shell-operator aware: a rule like `Bash(git add:*)` does **not** match `cd /worktree && git add .`, so chaining forces a fresh approval prompt every time.

- **Git in another directory**: use `git -C /path/to/dir <subcommand>` instead of `cd /path/to/dir && git <subcommand>`.
- **One-shot reads**: use absolute paths with the dedicated tool (Read, Glob, Grep) instead of `cd <dir> && cat file`.
- **Multi-step work in one directory**: if you genuinely need to run several commands in the same place, `cd` once at the top of the work block and then run plain commands — don't re-prefix `cd` on each call.
- **Only chain with `&&` when the steps are inherently coupled** (e.g., `mkdir -p foo && touch foo/bar`), not as a shortcut to set a working directory.
