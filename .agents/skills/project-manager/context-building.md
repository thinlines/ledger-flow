# Context Building

Use this reference when starting a session, receiving an underspecified request, or when relevant context is distributed across project docs.

## Document Ownership Map

Each document owns a distinct piece of the picture. Read in this order:

| Document | Owns | When to read |
|---|---|---|
| `TASK.md` | Active engineering task | Every session |
| `ROADMAP.md` | Delivery direction, current focus, deferred items | Every session |
| `README.md` | Product purpose, audience, posture | When uncertain about product identity |
| `ARCHITECTURE.md` | System shape, data flow, boundaries, invariants | Before writing tasks that touch backend, data, or API contracts |
| `AGENT_RULES.md` | Implementation rules, copy rules, verification commands | Before writing tasks; always check copy and data rules |
| `DECISIONS.md` | Durable tradeoffs and rationale | Before proposing anything in a previously decided area |
| `domain-model.md` | Project vocabulary: account types, transaction states, system invariants | When writing task definitions that use domain terminology |

**Static context** (read once or when uncertain): `README`, `ARCHITECTURE`, `AGENT_RULES`, `DECISIONS`, `domain-model.md`

**Dynamic context** (read every session): `ROADMAP`, `TASK.md`

## Discovery Pass

Capture the minimum facts needed before writing any task:

- What outcome is the user trying to achieve?
- What is already done, in progress, blocked, or undecided?
- What hard constraints exist: scope, system invariants, quality bar?
- What does `DECISIONS.md` say about this area?
- What does `ROADMAP.md` say is current focus vs. deferred?
- Which `AGENT_RULES.md` rules apply to this change?

## PM Snapshot

Summarize context into a compact working snapshot before producing output:

- Objective
- Current status
- In scope / Out of scope
- Constraints
- Decisions made
- Decisions needed
- Immediate next step

If information is missing, list assumptions separately. Do not blend assumptions into facts.

## Handling Ambiguity

When the request is vague, infer a likely need:

- "What should we work on next?" → task selection from `ROADMAP.md` + current task status
- "What's the current state?" → PM snapshot from project docs
- "Why isn't this working?" → identify unclear task definition, missing invariant, or regression
- "Is this ready?" → evaluate against `ux-quality-bar.md`

If the request could map to multiple artifacts, pick the most operationally useful one and state the assumption.

## What to Avoid

- Do not write tasks before reading `ARCHITECTURE.md` and `DECISIONS.md` — both contain constraints that invalidate tasks written without them.
- Do not restate context without converting it into decisions or actions.
- Do not treat every unknown as equally important — focus on what can change scope, correctness, or system invariants.
