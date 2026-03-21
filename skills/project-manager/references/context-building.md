# Context Building

Use this reference when the request is underspecified, the project is already in motion, or the relevant context is distributed across repo docs, tickets, and prior notes.

## Discovery pass

Capture the smallest set of facts needed to manage the work:

- What outcome is the user actually trying to achieve?
- What problem or decision is driving the request now?
- What is already done, in progress, blocked, or undecided?
- What hard constraints exist: date, scope, staffing, compliance, quality bar, rollout window?
- Who needs to be aligned or informed?
- What artifacts already exist and which of them is the source of truth?

## Useful source order

When working in a codebase or shared workspace, read sources in this order unless the user points elsewhere:

1. The user request and the active task file
2. README, architecture docs, roadmap, or decision records
3. Recent plans, issue summaries, or changelogs
4. The code or data that proves current behavior

## Build a PM snapshot

Summarize context into a compact working snapshot:

- Objective
- Current status
- In scope
- Out of scope
- Constraints
- Stakeholders
- Dependencies
- Risks and blockers
- Decisions made
- Decisions needed
- Immediate next step

If information is missing, list assumptions separately instead of blending them into facts.

## Handling ambiguity

When the user is vague, infer a likely project-management need from the request:

- "What should we do next?" usually needs a plan with sequencing.
- "Can you summarize where this stands?" usually needs a status update.
- "Why are we slipping?" usually needs blockers, root causes, and replan options.
- "Can you run this meeting?" usually needs an agenda, desired outcomes, and follow-up actions.

If the request could map to multiple artifacts, pick the one that is most operationally useful and state the assumption.

## What to avoid

- Do not restate large amounts of context without turning them into decisions or actions.
- Do not confuse documentation coverage with delivery progress.
- Do not treat every unknown as equally important; focus on what can change scope, timeline, or confidence.
