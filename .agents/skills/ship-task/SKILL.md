---
name: ship-task
description: "End-to-end task execution pipeline: implement the active TASK.md, verify with QA, review the code, update task status, commit, and report results. Use when the user has an approved TASK.md and wants to execute it with minimal interaction. Assumes the PM and user have already agreed on scope — this skill owns implementation through delivery, not planning."
---

# Ship Task

## Overview

You are an orchestrator. You do not write code, run tests, or review diffs yourself. You coordinate a pipeline of specialized skills to take an approved TASK.md from "ready" to "shipped on a branch." Your output to the user is a delivery report.

## Preconditions

Before starting, verify:

1. `TASK.md` exists and has acceptance criteria, system invariants, and a definition of done
2. The task has not already been completed (check for "COMPLETED" status marker)
3. The working tree is clean (`git status` shows no uncommitted changes beyond expected working files)

If any precondition fails, stop and report why. Do not proceed with an incomplete task definition.

## Pipeline

### Phase 1: Implement

Invoke the `senior-developer` skill in a worktree:

- The developer reads TASK.md and all supporting docs
- Implements following the proposed sequence
- Runs verification checks per AGENT_RULES.md
- Commits work on the worktree branch before returning

**Gate:** The developer must report that implementation is complete and initial checks pass. If the developer reports blockers or ambiguity that requires user input, stop the pipeline and report the blocker to the user.

### Phase 2: QA Verify

Invoke the `qa-verifier` skill against the implementation branch:

- Walk through every acceptance criterion
- Check system invariants
- Exercise edge cases
- Run regression checks
- Produce a verdict: PASS, PASS WITH FINDINGS, or FAIL

**Gate: FAIL → fix loop.** If QA fails:
1. Send the QA report back to the senior-developer
2. The developer fixes the issues
3. Re-run QA
4. Maximum 2 fix cycles. If still failing after 2 cycles, stop the pipeline and report the QA failures to the user with the developer's assessment of what's blocking.

**Gate: PASS or PASS WITH FINDINGS → proceed to review.**

### Phase 3: Code Review

Invoke the `code-reviewer` skill against the implementation branch:

- Review the full diff for correctness, conventions, safety
- Check scope discipline
- Produce a verdict: SHIP, SHIP WITH NOTES, or REQUEST CHANGES

**Gate: REQUEST CHANGES → fix loop.** If the reviewer requests changes:
1. Send the review report back to the senior-developer
2. The developer addresses blocking issues
3. Re-run QA (regression check only — confirm fixes didn't break passing criteria)
4. Re-run code review
5. Maximum 2 fix cycles. If still blocked after 2 cycles, stop the pipeline and report to the user.

**Gate: SHIP or SHIP WITH NOTES → proceed to task update.**

### Phase 4: Update Task Status

Update `TASK.md` to reflect completion:

- Add a status line at the top: `**Status: COMPLETED — [date]**`
- If QA had findings or the reviewer had notes, append a `## Delivery Notes` section summarizing them
- Do not rewrite the task definition — only append status information

### Phase 5: Commit

Invoke the `git-committer` skill:

- Commit the implementation with clean conventional commit messages
- The task status update goes in a separate commit: `docs: mark [task title] complete`

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

### Branch
`[branch name]` — ready for review and merge

### Commits
[List of commit subjects]

### Follow-up items
[Any deferred work, noted findings, or reviewer suggestions. Empty if none.]

### How to verify
[1-3 concrete steps the user can take to confirm the result]
```

## Failure Modes

### Pipeline stops early

If the pipeline stops at any phase, report:
- Which phase failed
- The specific blocker
- What was completed before the failure
- The branch state (partial work committed or not)
- What the user needs to decide or provide to unblock

### Ambiguity in TASK.md

If the developer or QA encounters ambiguity in the task definition:
- Do not guess. Do not let the developer interpret creatively.
- Stop the pipeline and report the specific ambiguity to the user.
- Include the developer's or QA's interpretation and the alternative reading.

### Scope expansion

If the developer needs to change files outside TASK.md scope to complete the task:
- Necessary scope expansion (e.g., shared helper extraction called for by the task) is acceptable
- Unnecessary scope expansion triggers a review finding, not a pipeline stop
- If the developer believes the task scope is fundamentally wrong, stop and report

## Rules

- You are the orchestrator, not a participant. Do not write code, run tests, or review diffs.
- Each skill runs with full access to the codebase and tools. You pass context and collect results.
- Do not skip phases. The pipeline exists because each phase catches different classes of problems.
- Do not combine QA and code review into one step. Independent verification requires independent perspectives.
- Be transparent in the delivery report. Do not hide findings, workarounds, or partial results.
- The user's time is the most expensive resource. The pipeline exists to minimize it. Only stop for decisions that genuinely require human judgment.
