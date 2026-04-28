# Ledger Flow — Agent Instructions

## Working on tasks

When the user asks to implement, build, ship, finish, or work on a task — or references TASK.md, ROADMAP.md, or similar planning artifacts — invoke the `senior-developer` skill before starting work. That skill owns the end-to-end workflow for engineering tasks in this repo.

## Shell command style

**Prefer built-in tools over Bash.** Built-in tools are fast, cached, and don't trigger permission prompts. Every shell command passes through a pre-tool-use hook with strict pattern rules — deviations force a manual approval that blocks worktree agents.

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

**Never chain commands with `&&`, `||`, or `;`. No shell loops (`while read`, `for`).** This is a flat rule with no exceptions — even "inherently coupled" steps like `mkdir -p foo && touch foo/bar` must be two tool calls. Issue separate tool calls instead; independent ones can run in parallel. The pre-tool-use hook actively denies chained Bash and reports the offending operator. Pipes (`|`) and stderr redirects (`2>/dev/null`, `2>&1`) are still fine — they don't chain commands.

- **Git**: _always_ use the /git-committer skill to commit to git.
- **Working in another directory** (e.g. a worktree):
  - For git, use `git -C <path> <subcommand>` — these patterns are pre-approved by the hook.
  - For everything else (`pnpm`, `npm`, `mise`, `pytest`, etc.), prefer two separate Bash calls — `cd <path>` in one call, then the plain command in another — over arg-flag forms like `pnpm --dir <path> install` or `pytest --rootdir=<path>`. The working directory persists between Bash calls, so `cd` once and subsequent calls run in that directory until you `cd` again. The `--dir`/`--cwd`/`--rootdir`-style flags are **not** covered by the auto-approval patterns and force a manual permission prompt that halts worktree agents. Example preferred pattern: `cd my/worktree/dir\npnpm install`. Disallowed: `pnpm --dir my/worktree/dir install`.
