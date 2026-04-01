# Current Task

## Title

Dashboard polish: four parallel improvements (Feature 3b)

## Objective

Sharpen the dashboard with four independent improvements that each touch a different DOM section. No data or logic dependencies between them — all four can be implemented in parallel or in any order.

## Parallel Task Files

| Task | File | Section Touched | Backend Change? |
|------|------|-----------------|-----------------|
| 4a. Momentum line in hero | [TASK-4a.md](TASK-4a.md) | Hero stat chips | No |
| 4b. Day-grouped recent activity | [TASK-4b.md](TASK-4b.md) | Recent activity panel | No |
| 4c. Per-account staleness | [TASK-4c.md](TASK-4c.md) | Balance sheet panel | Yes (`lastTransactionDate`) |
| 4d. Cash flow time presets | [TASK-4d.md](TASK-4d.md) | Cash flow section | No |

Each task file is self-contained with full system behavior, acceptance criteria, and proposed sequence.

## Verification

After all four are complete:

- `pnpm check` passes (in `app/frontend`).
- `uv run pytest -q` passes (in `app/backend` — relevant for 4c).
- Visual check: all four hero states (uninitialized, onboarding, populated with queue, caught-up).
- Responsive check: 1100px and 720px breakpoints.

## Replacement Rule

Replace this file when the next active engineering task begins.
