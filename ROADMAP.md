# Product Roadmap

This document preserves potential product directions, not delivery status or
committed scope. GitHub milestones and issues are authoritative once work is
committed.

## Directions Under Consideration

- **Explore analytics** — A durable analytical surface with cross-filtering and, when justified, server-side aggregation for longer histories and finer time ranges.
- **Generic duplicate correction** — A transactions-level way to merge duplicates safely while preserving import identity and undo.
- **Agent and automation provenance** — Carry an explicit actor identity from automated clients into the operation history.
- **Reconciliation evidence and history** — Make past reconciliations easier to inspect and optionally associate with statement evidence.

## Deferred

- Full transaction editing, including date, payee, and amount.
- User-facing configuration for preferences such as date format and currency.
- Dedicated merchant management outside the contextual Review workflow.
- Richer rule conditions and actions beyond the current matching model.
- Reconciliation adjustments and warnings when changing previously reconciled activity.
- Debt-payment decomposition and richer liability-servicing workflows.
- Multi-currency account support.
