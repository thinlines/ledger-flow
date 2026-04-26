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
- **Multi-step work in one directory**: prefer `git -C <path>` or pass absolute paths. If you genuinely need several commands in the same place, `cd` once at the top of a single call and then run plain commands — don't re-prefix `cd` on each call.
