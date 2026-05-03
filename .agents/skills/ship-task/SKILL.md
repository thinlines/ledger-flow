---
name: ship-task
description: "End-to-end task execution pipeline: implement the active TASK.md (or concurrent tasks from tasks/), verify with QA, review the code, update task status, commit, merge into master, clean up the worktree, and report results. Use when the user has an approved task and wants to execute it with minimal interaction. Assumes the PM and user have already agreed on scope — this skill owns implementation through delivery, not planning. Supports both single-task and multi-task concurrent modes."
---

# Ship Task

You are an orchestrator. You do not write code, run tests, or review diffs yourself. You coordinate specialized skills to take approved tasks from "ready" to "merged into master and worktree released," then report.

Sub-agents inherit CLAUDE.md and the project hooks — do not re-state bash, commit-message, or worktree-flag rules in their prompts. Pass task context, not project conventions.

## Modes

- **Single-task** (default): `TASK.md` exists, no `tasks/` directory.
- **Multi-task concurrent**: `tasks/` contains multiple `.md` task files; each runs its own pipeline in a separate worktree, in parallel. See addendum below.

## Preconditions

1. Task file(s) exist with acceptance criteria, system invariants, and definition of done.
2. No task is marked COMPLETED.
3. Working tree is clean.
4. (Multi-task) No two tasks share a file/module/endpoint in their stated scope. If they do, stop and report the conflict.

If any precondition fails, stop and report.

## Single-Task Pipeline

### Phase 1 — Implement

Invoke `senior-developer` in a worktree. Pass the task content and any context the developer needs that isn't in CLAUDE.md / AGENT_RULES.md. Require commits via `/git-committer` on the worktree branch.

**Gate:** developer reports implementation complete and initial checks pass. Blockers requiring user input → stop and report.

### Phase 2 — QA + Code Review (parallel)

Invoke `qa-verifier` and `code-reviewer` simultaneously against the implementation branch. Pass each a context bundle: the relevant TASK.md slice, the diff range (`<base>...HEAD`), and pointers to any docs that aren't already in CLAUDE.md context. They should not re-read the same docs separately.

Verdicts: QA → PASS / PASS WITH FINDINGS / FAIL. Review → SHIP / SHIP WITH NOTES / REQUEST CHANGES.

**Gate:** any FAIL or REQUEST CHANGES → fix loop. Otherwise proceed.

**Fix loop:** merge findings into one remediation brief, send to senior-developer, re-run QA + review in parallel. Maximum 2 cycles; if still failing, stop and report originals + what was fixed + what remains.

### Phase 3 — Update Task Status

Append `**Status: COMPLETED — [date]**` to the task file. If QA had findings or reviewer had notes, append a `## Delivery Notes` section. Do not rewrite the task definition.

### Phase 4 — Commit

Invoke `git-committer`. Status update goes in a separate commit: `docs: mark [task title] complete`.

### Phase 5 — Merge and Cleanup

The pipeline is not complete until work is on master and the worktree is released.

1. From the main worktree, `git -C <main-repo> merge --no-ff <branch> -m "Merge branch '<branch>': <short summary>"`.
2. **Stop on conflicts** (`git merge --abort`, report conflicting files). Do not auto-resolve.
3. **Stop if master has uncommitted changes** in files the merge would touch. Do not stash.
4. `git -C <main-repo> worktree remove <worktree-path>` (unlock first if needed).
5. `git -C <main-repo> branch -d <branch>` (safe delete only — never `-D`).
6. Verify: `git worktree list` shows only the main worktree; `git branch` doesn't list the feature branch.

If any step fails, stop and report. Do not claim SHIPPED while the worktree or branch persist.

### Phase 6 — Report

```markdown
## Delivery Report: [Task Title]

### Result: [SHIPPED | SHIPPED WITH NOTES | BLOCKED]

### What was built
[2-3 sentences]

### Verdicts
- QA: [PASS | PASS WITH FINDINGS] — [brief summary if findings]
- Review: [SHIP | SHIP WITH NOTES] — [brief summary if notes]
- Fix cycles: [0 | 1 | 2] — [what was caught if >0]

### Merged
`[branch]` → `master` as `[hash]`. Worktree removed, branch deleted.

### Commits
[Subjects, including merge commit]

### Follow-up
[Deferred work or noted findings. Empty if none.]

### How to verify
[1-3 concrete steps]
```

## Multi-Task Addendum

For each task in `tasks/`, run the single-task pipeline in its own worktree, in parallel. **Serialize Phase 5** — only one merge into master at a time, in any order; re-check master HEAD before each merge. Independence is enforced in Preconditions; if a Phase 5 conflict surfaces anyway, apply the conflict-stop rule and report.

A failure in one task does not stop the others. Combine results into one report with the same structure per task, plus a "Merge Order Used" line and a "Cross-Task Concerns" line (empty if none).

## Failure Reporting

When the pipeline stops at any phase, report: which phase (and task, in multi-task mode), the specific blocker, what was completed, the branch state, and what the user must decide to unblock.

Specifically:
- **Ambiguity in task definition** → stop, surface both readings, do not let the developer guess.
- **Scope expansion** → necessary expansion is fine; unnecessary becomes a review finding, not a stop. Fundamentally wrong scope → stop and report.
- **Phase 5 failure** → abort any in-flight merge, leave branch + worktree intact (they hold verified work), report exact state, mark BLOCKED.

## Rules

- Orchestrator only — do not write code, run tests, or review diffs.
- Do not skip phases; each catches a different failure class.
- QA and review run in parallel.
- Be transparent — surface findings, workarounds, partial results.
- Stop only for decisions that genuinely require human judgment.
- SHIPPED requires `git worktree list` shows only the main worktree and the feature branch is gone. Otherwise BLOCKED.
