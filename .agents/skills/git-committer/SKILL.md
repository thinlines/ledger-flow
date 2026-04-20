---
name: git-committer
description: "Inspect local git changes, split them into coherent commits, and write clean conventional commit messages with short subjects and concise bodies. Use when the user asks to commit work, says `gc`, `GC`, `commit`, or `git commit`, wants help grouping changes into readable history, or wants a commit message drafted or improved."
---

# Git Committer

## Overview

Turn working tree changes into readable history. Inspect the diff, choose the smallest sensible commit boundaries, and create one or more conventional commits with a headline of 50 characters or fewer.

## Workflow

### 1. Inspect the repo state

- Run `git status --short` first.
- Check both staged and unstaged changes before deciding commit boundaries.
- Read the relevant diffs, not just filenames.
- Identify untracked files, partial work, generated files, and unrelated user changes.
- If the user asked only for a message, inspect enough context to draft the right commit text without creating a commit.

### 2. Choose commit boundaries

- Prefer granular commits over one large commit when history becomes easier to scan or revert.
- Keep each commit to one coherent purpose: feature, fix, refactor, docs update, test change, or cleanup.
- Separate unrelated changes even when they were made in the same session.
- Split mechanical changes from behavioral changes when practical.
- Do not pull unrelated user edits into a commit just because they are present in the working tree.
- If unrelated changes are interleaved in the same file and clean separation would be risky, stop and ask instead of forcing a messy commit.

### 3. Write the message

- Use Conventional Commits when possible: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `build`, `ci`, `perf`, `style`.
- Add a scope when it sharpens the history: `fix(parser): ...`, `docs(readme): ...`.
- Keep the headline at 50 characters or fewer, including type and scope.
- Write the subject in imperative mood.
- Do not end the headline with a period.
- Keep the body optional. Add it only when it improves future understanding.
- Keep body notes concise and focused on why, risk, follow-up, or migration impact.
- Prefer a short body over a long narrative. A few plain lines are enough.

### 4. Create the commit safely

- Stage only the paths that belong in the current commit.
- Prefer non-interactive git commands.
- Run a quick verification step when it is cheap and relevant.
- Create the commit, then re-check `git status --short` before deciding whether another commit is needed.
- If the repo state is ambiguous, summarize the proposed split before committing.

### 5. Worktree git commands

A pre-tool-use hook auto-approves `git -C <worktree-path>` commands that follow specific patterns. Deviating from these patterns forces a manual approval prompt, which blocks agents.

#### Commit messages

Do **not** use a heredoc or `$(cat <<'EOF' ...)` — the `$(` triggers the shell-operator guard.

Instead, write the message to a file first, then commit with `-F`:

1. Use the **Write** tool to create `<worktree-path>/.commit-msg` with the full commit message.
2. Run `git -C <worktree-path> commit -F .commit-msg`.
3. Do not clean up `.commit-msg` — the worktree is ephemeral and the file is overwritten on subsequent commits.

#### Pipes

The hook allows piping git output to these commands only: `wc`, `head`, `tail`, `sort`, `uniq`, `grep`, `cat`, `less`, `cut`, `awk`, `sed`, `tr`, `column`, `fmt`, `nl`. Note: `sed -i` is blocked (in-place edit). You may prefix any of these with `xargs` (e.g. `| xargs wc -l`). Multiple pipes are fine as long as every segment follows these rules.

Do **not** use shell loops (`while read`, `for`, `do`, etc.), subshells, or process substitution after a pipe — they will be rejected. Use `xargs <safe-command>` instead when you need to apply a command per line. If you need more complex post-processing, use the **Read** or **Grep** tools instead of shell constructs.

#### Stderr redirects

`2>&1` and `2>/dev/null` are stripped before checking. Other redirects (`>`, `<`) are rejected.

#### Chaining

Do **not** chain commands with `&&`, `||`, or `;` after a git command. Run separate `git -C` calls instead.

## Message Heuristics

- Prefer `fix` for behavior corrections, `feat` for new user-visible capability, `refactor` for internal restructuring without behavior change, and `chore` only for maintenance that does not fit a clearer type.
- Keep headlines concrete. Name the thing changed and the intent.
- Avoid vague subjects like `update stuff`, `misc fixes`, or `work in progress`.
- Prefer two crisp commits over one blended commit when both are valid.

## Good Patterns

- `fix(import): skip blank csv rows`
- `docs: clarify local setup`
- `refactor(sync): split retry logic`

## Avoid

- Headlines over 50 characters
- Mixed-purpose commits
- Bodies that repeat the diff line by line
- Committing generated noise without purpose
- Bundling user changes you do not understand
