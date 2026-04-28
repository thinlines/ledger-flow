---
name: ship-task
description: "End-to-end task execution pipeline: implement the active TASK.md (or concurrent tasks from tasks/), verify with QA, review the code, update task status, commit, merge into master, clean up the worktree, and report results. Use when the user has an approved task and wants to execute it with minimal interaction. Assumes the PM and user have already agreed on scope — this skill owns implementation through delivery, not planning. Supports both single-task and multi-task concurrent modes."
---

# Ship Task

## Overview

You are an orchestrator. You do not write code, run tests, or review diffs yourself. You coordinate a pipeline of specialized skills to take approved tasks from "ready" to "merged into master and worktree released." Your output to the user is a delivery report.

## Modes

### Single-task mode (default)

Triggered when `TASK.md` exists and no `tasks/` directory is present, or when the user invokes with a specific task reference.

### Multi-task concurrent mode

Triggered when a `tasks/` directory contains multiple `.md` task files. Each task runs its own pipeline in a separate worktree, in parallel.

---

## Preconditions

Before starting, verify:

1. Task file(s) exist and each has acceptance criteria, system invariants, and a definition of done
2. No task has a "COMPLETED" status marker
3. The working tree is clean (`git status` shows no uncommitted changes beyond expected working files)

**Multi-task additional checks:**
4. Read all task files in `tasks/` and identify file-scope overlap — if two tasks name the same file in their scope, they are not independent
5. If tasks overlap, stop and report which tasks conflict and on what files — the user or PM must split them differently or sequence them

If any precondition fails, stop and report why. Do not proceed with an incomplete task definition.

---

## Single-Task Pipeline

### Phase 1: Implement

Invoke the `senior-developer` skill in a worktree:

- The developer reads TASK.md and all supporting docs
- Implements following the proposed sequence
- Runs verification checks per AGENT_RULES.md
- Commits work on the worktree branch before returning, **via the `/git-committer` skill** (see commit-message rules below)

**Sub-agent prompt requirement:** when invoking the developer (or any sub-agent that will commit), the orchestrator's prompt MUST explicitly instruct it to:

1. Invoke the `/git-committer` skill for every commit on the worktree branch — never raw `git commit`.
2. For multi-line messages, write to a file under the worktree (e.g. `.commit-msg`) via the **Write** tool, then `git -C <worktree> commit -F .commit-msg`. Single-line subjects can use `-m "subject"` directly.
3. Never use `$(cat <<EOF ... EOF)` or `git commit -m "subject\n\nbody"` (multi-line `-m`) — both are rejected by the project's pre-tool-use hooks and force a manual approval prompt that blocks the worktree agent.
4. Never chain Bash commands with `&&`, `||`, `;`, or shell loops — issue separate tool calls instead. The pre-tool-use hook rejects chaining and forces a manual approval prompt.
5. To run non-git commands in the worktree (e.g. `pnpm install`, `pnpm test`, `mise run check`), `cd <worktree>` in one Bash call and then run the plain command in a separate Bash call — the working directory persists between calls. Do **not** use arg-flag forms like `pnpm --dir <worktree> install` or `pytest --rootdir=<worktree>`; those aren't covered by the auto-approval patterns and force a manual approval prompt. Git commands are the exception — `git -C <worktree> ...` is pre-approved and preferred.

This isn't decorative — sub-agents that don't get these instructions explicitly default to chained commands, multi-line `-m`, or `--dir`-style flags and get blocked.

**Gate:** The developer must report that implementation is complete and initial checks pass. If the developer reports blockers or ambiguity that requires user input, stop the pipeline and report the blocker to the user.

### Phase 2: QA + Code Review (parallel)

Invoke `qa-verifier` and `code-reviewer` simultaneously against the implementation branch:

**qa-verifier:**
- Walk through every acceptance criterion
- Check system invariants
- Exercise edge cases
- Run regression checks
- Produce verdict: PASS, PASS WITH FINDINGS, or FAIL

**code-reviewer:**
- Review the full diff for correctness, conventions, safety
- Check scope discipline
- Produce verdict: SHIP, SHIP WITH NOTES, or REQUEST CHANGES

**Gate logic (after both complete):**

| QA Verdict | Review Verdict | Action |
|---|---|---|
| PASS | SHIP | Proceed to Phase 3 |
| PASS | SHIP WITH NOTES | Proceed to Phase 3 |
| PASS WITH FINDINGS | SHIP | Proceed to Phase 3 |
| PASS WITH FINDINGS | SHIP WITH NOTES | Proceed to Phase 3 |
| FAIL | any | → fix loop |
| any | REQUEST CHANGES | → fix loop |

**Fix loop:**
1. Merge findings from both QA and review into a single remediation brief
2. Send the combined brief to the senior-developer
3. The developer addresses all issues in one pass
4. Re-run both QA and review in parallel (fixes may have introduced new issues)
5. Maximum 2 fix cycles. If still failing after 2 cycles, stop the pipeline and report to the user with:
   - The original findings
   - What was fixed
   - What remains unresolved
   - The developer's assessment of what's blocking

### Phase 3: Update Task Status

Update the task file to reflect completion:

- Add a status line at the top: `**Status: COMPLETED — [date]**`
- If QA had findings or the reviewer had notes, append a `## Delivery Notes` section summarizing them
- Do not rewrite the task definition — only append status information

### Phase 4: Commit

Invoke the `git-committer` skill:

- Commit the implementation with clean conventional commit messages
- The task status update goes in a separate commit: `docs: mark [task title] complete`

### Phase 5: Merge and Cleanup

The pipeline is not complete until the work is on master and the worktree is released.

1. **Merge into master.** From the main worktree (not the feature worktree), merge the implementation branch with `--no-ff` and a descriptive merge subject. Example: `git -C <main-repo> merge --no-ff <branch> -m "Merge branch '<branch>': <short summary>"`. Use `--no-ff` so the feature commits stay grouped under a merge commit, matching project history convention. Keep the `-m` value single-line and free of `` ` `` / `$(...)` so the permission system auto-approves; if you want a body, write the message via the **Write** tool and use `git merge --no-ff <branch> -F /tmp/<file>.txt`.
2. **Stop on conflicts.** If the merge produces conflicts, abort it (`git merge --abort`) and report the conflicting files to the user. Do not attempt to auto-resolve. Conflicts mean either (a) master moved during the pipeline run, or (b) the task scope overlapped something the user changed locally — both require human judgment.
3. **Stop if master has uncommitted changes** in files the merge would touch. Do not stash or discard the user's working tree. Report and let the user decide.
4. **Remove the worktree.** Once the merge lands, run `git -C <main-repo> worktree remove <worktree-path>`. If the worktree was created via the Agent tool's `isolation: "worktree"`, it may be locked — `git worktree unlock <path>` first.
5. **Delete the merged branch.** `git -C <main-repo> branch -d <branch>`. Use `-d` (safe delete), never `-D`. If `-d` refuses, the branch isn't fully merged — investigate before forcing.
6. **Verify cleanup.** `git worktree list` should show only the main worktree. `git branch` should not list the feature branch.

If any step in this phase fails, stop and report. Do not proceed to the report claiming the task shipped if the worktree is still on disk or the branch is still unmerged.

### Phase 6: Report

Produce a delivery report for the user:

```markdown
## Delivery Report: [Task Title]

### Result: [SHIPPED | SHIPPED WITH NOTES | BLOCKED]

### What was built
[2-3 sentences summarizing the implementation]

### QA Verdict: [PASS | PASS WITH FINDINGS]
[If findings: brief summary]

### Review Verdict: [SHIP | SHIP WITH NOTES]
[If notes: brief summary]

### Fix cycles: [0 | 1 | 2]
[If >0: what was caught and fixed]

### Merged
`[branch name]` → `master` as `[merge commit hash]`. Worktree removed, branch deleted.

### Commits
[List of commit subjects, including the merge commit]

### Follow-up items
[Any deferred work, noted findings, or reviewer suggestions. Empty if none.]

### How to verify
[1-3 concrete steps the user can take to confirm the result]
```

---

## Multi-Task Concurrent Pipeline

### Phase 0: Validate independence

For each pair of tasks in `tasks/`:
- Parse the **Scope > Included** section to extract file paths and modules
- If any two tasks share a file, module, or API endpoint: flag the conflict
- Present the independence assessment to the user:

```markdown
## Task Independence Check

### Independent (can run concurrently)
- task-4a.md: unified backend endpoint (backend services, tests)
- task-4c.md: search formula syntax (frontend components)

### Conflicting (must be sequenced)
- task-4a.md and task-4b.md: both touch transaction_helpers.py

### Recommendation
Run task-4a and task-4c concurrently. Queue task-4b after task-4a merges.
```

If all tasks are independent, proceed. If conflicts exist and the user hasn't acknowledged them, stop and report.

### Phase 1: Parallel implementation

For each independent task, spawn a separate pipeline. Each pipeline gets:
- Its own worktree (isolated branch)
- Its own task file as the active spec
- Full access to the codebase (read-only for files outside its scope)

All pipelines run the full single-task pipeline (implement → parallel QA+review → commit → merge+cleanup) concurrently.

**Merge serialization.** Implementation runs in parallel, but the Phase 5 merge into master must be serialized — only one merge into master at a time, in any order. After each merge, re-check master's HEAD before starting the next merge so each pipeline merges into the latest state. If a later merge produces conflicts (because an earlier merge moved master under it), apply the conflict-stop rule from Phase 5 and report.

### Phase 2: Collect results

Wait for all pipelines to complete. Produce a combined report:

```markdown
## Concurrent Delivery Report

### Overview
[N] tasks executed concurrently. [X] shipped, [Y] blocked.

---

### Task: [Title from task-4a.md]
**Result:** SHIPPED
**Merged:** `feat/unified-endpoint` → `master` as `[merge commit hash]`. Worktree removed, branch deleted.
**Commits:** [list, including merge commit]
[QA and review summary]

---

### Task: [Title from task-4c.md]
**Result:** SHIPPED WITH NOTES
**Merged:** `feat/search-syntax` → `master` as `[merge commit hash]`. Worktree removed, branch deleted.
**Commits:** [list, including merge commit]
[QA and review summary]
[Notes]

---

### Merge Order Used
[The actual order tasks merged into master. Note any branch that hit conflicts and was deferred.]

### Cross-Task Concerns
[Any issues that span tasks: shared type changes, migration conflicts, test interactions. Empty if none.]

### How to verify
[Per-task verification steps]
```

---

## Failure Modes

### Pipeline stops early

If the pipeline stops at any phase, report:
- Which phase failed (and which task, in multi-task mode)
- The specific blocker
- What was completed before the failure
- The branch state (partial work committed or not)
- What the user needs to decide or provide to unblock

### Ambiguity in task definition

If the developer or QA encounters ambiguity:
- Do not guess. Do not let the developer interpret creatively.
- Stop that task's pipeline (other concurrent tasks continue).
- Report the specific ambiguity to the user.
- Include the developer's or QA's interpretation and the alternative reading.

### Scope expansion

If the developer needs to change files outside the task scope:
- Necessary scope expansion (e.g., shared helper extraction called for by the task) is acceptable
- Unnecessary scope expansion triggers a review finding, not a pipeline stop
- If the developer believes the task scope is fundamentally wrong, stop and report

### Cross-task conflict (multi-task mode)

If two concurrent tasks produce changes that conflict at merge time:
- This should have been caught in Phase 0, but if it wasn't:
- Report which tasks conflict and on what files
- Do not attempt to merge-resolve — the user decides which takes priority

### Merge or cleanup failure (Phase 5)

If the Phase 5 merge fails (conflicts, dirty master working tree, locked worktree, refused branch deletion):
- Abort any in-flight merge (`git merge --abort`)
- Leave the implementation branch and worktree intact — they hold the verified work
- Report the exact failure and what state was reached: implementation committed? merge attempted? worktree still on disk? branch still present?
- The task is BLOCKED until the user resolves the underlying issue. Do not claim SHIPPED.

## Rules

- You are the orchestrator, not a participant. Do not write code, run tests, or review diffs.
- Each skill runs with full access to the codebase and tools. You pass context and collect results.
- Do not skip phases. The pipeline exists because each phase catches different classes of problems.
- QA and code review run in parallel — do not sequence them. They check different failure classes and neither depends on the other.
- Be transparent in the delivery report. Do not hide findings, workarounds, or partial results.
- The user's time is the most expensive resource. The pipeline exists to minimize it. Only stop for decisions that genuinely require human judgment.
- In multi-task mode, a failure in one task does not stop other tasks. Each pipeline is independent. Report all results together.
- A pipeline is not complete until the implementation is merged into master and the worktree is released. SHIPPED requires that `git worktree list` shows only the main worktree and `git branch` does not list the feature branch. If either remains, the result is BLOCKED, not SHIPPED.
