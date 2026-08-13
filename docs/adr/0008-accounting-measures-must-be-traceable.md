# Accounting measures must be traceable

Every accounting measure shown by Ledger Flow must reconcile exactly to the
canonical books for its stated scope and drill through to the complete
transaction set that produced it. Derived or heuristic analytical insights are
allowed, but they must be visibly distinguishable from accounting facts and
disclose their basis.

## Considered Options

- **Treat mathematical correctness as sufficient** — rejected because a number
  can be calculated correctly yet communicate a misleading scope, such as
  ranking income and expenses together by absolute magnitude.
- **Forbid heuristic insights** — rejected because interpretation can be useful
  when it is clearly separated from the accounting record.

## Consequences

Visuals cannot present unexplained aggregates. Filters, exclusions, sign
conventions, and time periods are part of the measure's meaning, and
drill-through must preserve that meaning at row level.
