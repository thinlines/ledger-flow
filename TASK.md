# Current Task

## Objective

Consolidate repository context into a single top-level documentation set that works well for both humans and LLMs.

## Deliverables

- Refine `README.md` into a concise product-purpose document with a context map.
- Create `ARCHITECTURE.md`, `AGENT_RULES.md`, and `DECISIONS.md`.
- Migrate the relevant content from the retired embedded UX and import docs into the new top-level docs.
- Add a brief doc-ownership note to `ROADMAP.md`.
- Remove the retired embedded spec docs after migration.

## Success Criteria

- One obvious document answers each of these questions:
  - What is Ledger Flow?
  - How does the system work?
  - What rules should changes follow?
  - What is the current task?
  - Why do the current tradeoffs exist?
- Every important concept from the retired UX/import docs appears in exactly one top-level source of truth.
- No remaining repo references depend on the retired embedded UX/import docs.
- No runtime, API, or schema changes are introduced as part of this task.

## Out of Scope

- Product behavior changes
- UI redesign beyond documenting the existing direction
- Backend or API changes
- Roadmap reprioritization

## Replacement Rule

Replace this file when the next active engineering task begins.
