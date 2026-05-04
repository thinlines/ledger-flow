---
name: ship-task
description: "End-to-end task execution pipeline: implement the active TASK.md (or concurrent tasks from tasks/), verify with QA, review the code, update task status, commit, merge into master, clean up the worktree, and report results. Use when the user has an approved task and wants to execute it with minimal interaction. Assumes the PM and user have already agreed on scope — this skill owns implementation through delivery, not planning. Supports both single-task and multi-task concurrent modes."
---

# Ship Task

You are an orchestrator. You do not write code, run tests, or review diffs yourself. You coordinate specialized skills to take approved tasks from "ready" to "merged into master and worktree released," then report.

Sub-agents inherit CLAUDE.md and the project hooks — do not re-state bash, commit-message, or worktree-flag rules in their prompts. Pass task context, not project conventions.

## Worktree pool

- **Main worktree** (the project root, e.g. `/home/randy/Desktop/tmp-books`): orchestrator runs here; merges land here.
- **Feat worktree**: pre-built at `<repo>/.claude/worktrees/feat`, dependencies pre-warmed (`pnpm install`, `uv sync`). Single-task pipelines use this fixed path. The pre-tool-use hooks already auto-approve commands inside it.

Phase 0 (per single-task run) prepares the feat worktree:
1. `git -C <feat> status --porcelain` — must be empty. If not, stop and report; do not auto-clean.
2. `git -C <feat> rev-parse HEAD` — must equal `master`'s tip. If diverged, stop and report.
3. `git -C <feat> checkout -b <new-branch> master`.

Multi-task mode falls back to ad-hoc worktrees (one per task). The fixed feat slot serves single-task only.

## Modes

- **Single-task** (default): `TASK.md` exists, no `tasks/` directory. Uses the feat worktree.
- **Multi-task concurrent**: `tasks/` contains multiple `.md` task files; each runs its own pipeline in an ad-hoc worktree, in parallel. See addendum below.

## Preconditions

1. Task file(s) exist with acceptance criteria, system invariants, and definition of done.
2. No task is marked COMPLETED.
3. Main working tree is clean.
4. (Single-task) Feat worktree is clean and on master (Phase 0).
5. (Multi-task) No two tasks share a file/module/endpoint in their stated scope. If they do, stop and report the conflict.

If any precondition fails, stop and report.

## Single-Task Pipeline

### Phase 0 — Prepare worktree

Run the three checks under "Worktree pool" above. Then write the pipeline context bundle to `<feat>/.pipeline-context`:

```
TASK_TITLE: <title>
BRANCH: <new-branch>
BASE: <master SHA at branch creation>
SCOPE_INCLUDED: <files/modules from TASK.md "Scope > Included">
SCOPE_EXCLUDED: <files/modules from "Scope > Excluded">

--- TASK SLICE ---
<acceptance criteria, invariants, edge cases, regression risks, definition of done — copied from TASK.md>
```

This file is the single source of truth for sub-agents in subsequent phases. They Read one file instead of being passed everything inline.

### Phase 1 — Implement

Invoke `senior-developer` in the feat worktree. The prompt is short: "Implement the task described in `<feat>/.pipeline-context`. Commit on the worktree branch via `/git-committer`." Don't restate the task content — the file holds it.

**Gate:** developer reports implementation complete and initial checks pass. Blockers requiring user input → stop and report.

### Phase 2 — QA + Code Review (parallel)

Invoke `qa-verifier` and `code-reviewer` simultaneously against the implementation branch. Each prompt: "Read `<feat>/.pipeline-context` for the task slice and base SHA; the diff is `<base>...HEAD`."

Verdicts: QA → PASS / PASS WITH FINDINGS / FAIL. Review → SHIP / SHIP WITH NOTES / REQUEST CHANGES.

**Gate:** any FAIL or REQUEST CHANGES → fix loop. Otherwise proceed.

**Fix loop:** merge findings into one remediation brief, send to senior-developer, re-run QA + review in parallel. Maximum 2 cycles; if still failing, stop and report originals + what was fixed + what remains.

When invoking sub-agents in the fix loop, structure the prompt with **stable content first** (the unchanging task slice / pipeline-context pointer) and **variable content last** (the specific findings to address this round). This keeps the prompt-cache prefix consistent across iterations of the same agent and avoids re-paying for the stable preamble each round.

### Phase 3 — Update Task Status

Append `**Status: COMPLETED — [date]**` to the task file. If QA had findings or reviewer had notes, append a `## Delivery Notes` section. Do not rewrite the task definition.

### Phase 4 — Commit

Invoke `git-committer`. Status update goes in a separate commit: `docs: mark [task title] complete`.

### Phase 5 — Merge and Reset

The pipeline is not complete until work is on master and the feat worktree is reset for the next task.

1. From the main worktree, `git -C <main-repo> merge --no-ff <branch> -m "Merge branch '<branch>': <short summary>"`.
2. **Stop on conflicts** (`git merge --abort`, report conflicting files). Do not auto-resolve.
3. **Stop if master has uncommitted changes** in files the merge would touch. Do not stash.
4. Reset the feat worktree: `git -C <feat> checkout --detach master`. The worktree stays on disk with deps warm; this is the pool's whole point.
5. Delete the merged branch: `git -C <main-repo> branch -d <branch>` (safe delete only — never `-D`).
6. Delete the pipeline context: `rm <feat>/.pipeline-context`.
7. Verify: `git -C <feat> status --porcelain` is empty, on detached HEAD at master; `git branch` doesn't list the feature branch.

If any step fails, stop and report. Do not claim SHIPPED while master is unmerged or the feat worktree holds the feature branch.

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
`[branch]` → `master` as `[hash]`. Feat worktree reset to master.

### Commits
[Subjects, including merge commit]

### Follow-up
[Deferred work or noted findings. Empty if none.]

### How to verify
[1-3 concrete steps]
```

## Multi-Task Addendum

For each task in `tasks/`, run the single-task pipeline in an ad-hoc worktree (the fixed feat slot is reserved for single-task work). Each task gets its own `.pipeline-context` in its own worktree. **Serialize Phase 5** — only one merge into master at a time, in any order; re-check master HEAD before each merge. Independence is enforced in Preconditions; if a Phase 5 conflict surfaces anyway, apply the conflict-stop rule and report.

A failure in one task does not stop the others. Combine results into one report with the same structure per task, plus a "Merge Order Used" line and a "Cross-Task Concerns" line (empty if none). Ad-hoc worktrees are removed at the end (`git worktree remove`).

## Failure Reporting

When the pipeline stops at any phase, report: which phase (and task, in multi-task mode), the specific blocker, what was completed, the branch state, and what the user must decide to unblock.

Specifically:
- **Ambiguity in task definition** → stop, surface both readings, do not let the developer guess.
- **Scope expansion** → necessary expansion is fine; unnecessary becomes a review finding, not a stop. Fundamentally wrong scope → stop and report. The `enforce-task-scope.py` hook will also surface out-of-scope edits in real time as warnings to the developer.
- **Phase 5 failure** → abort any in-flight merge, leave branch + worktree state intact (they hold verified work), report exact state, mark BLOCKED.
- **Dirty feat worktree at Phase 0** → stop. The previous run failed to reset it; user inspects before proceeding.

## Sub-agent efficiency

- **Match the model to the task.** Judgment work (developer, QA, reviewer) needs the most capable model available; mechanical work (running a test command and reporting failures, parsing a diff for out-of-scope files, listing changed files) can use a smaller/cheaper model from any provider configured in this repo. Pick deliberately.
- **Filter command output before it lands in context.** `pnpm test`, `pnpm build`, and `uv run pytest -v` can dump megabytes; pipe through `tail`, `grep`, or `sed` to keep only the failing lines and a few lines of surrounding context. Each fix-loop iteration that re-loads full build noise pays for it twice.
- **Test selection in fix loops.** First QA run: full suite (catches whole-codebase regressions). Fix-loop reruns: only the tests touching files in the new diff plus any tests that failed in the prior round. The full suite still runs once; subsequent iterations are targeted. Saves wall-clock and tokens — most fix iterations don't introduce regressions far from the changed files.
- **Cache-friendly prompts.** When sending prompts to sub-agents, put stable content first (pipeline-context pointer, task slice) and variable content last (specific findings to address this round). The Anthropic prompt cache has a 5-minute TTL keyed on prefix — putting variable bits at the end maximizes hit rate across fix-loop iterations of the same agent.
- **Pipeline context bundle.** Phase 0 writes `<feat>/.pipeline-context`; sub-agents read one file instead of being passed everything inline. Cuts redundant Reads in QA and review (they don't each re-load TASK.md, AGENT_RULES.md, etc.).

## Rules

- Orchestrator only — do not write code, run tests, or review diffs.
- Do not skip phases; each catches a different failure class.
- QA and review run in parallel.
- Be transparent — surface findings, workarounds, partial results.
- Stop only for decisions that genuinely require human judgment.
- SHIPPED requires master holds the merge commit and the feat worktree is reset to detached master with `.pipeline-context` removed. Otherwise BLOCKED.
