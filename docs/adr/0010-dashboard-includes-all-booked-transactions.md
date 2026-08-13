# Dashboard includes all booked transactions

Dashboard accounting measures include every transaction currently present in
the canonical books, whether or not it has completed Review or Reconcile.
Unknown categories and unreconciled activity remain explicit, and book health
communicates the resulting uncertainty.

## Considered Options

- **Include only reconciled transactions** — rejected because reconciliation
  increases confidence but does not determine whether recorded activity exists.
- **Exclude unknown categories from analysis** — rejected because it produces a
  cleaner-looking but knowingly incomplete financial picture.

## Consequences

Incomplete work may lower confidence in a measure but cannot silently remove
transactions from it. Status filters are allowed only when their narrower scope
is visible and preserved through drill-through.
