# CONTEXT — Ledger Flow domain vocabulary

Living glossary of project-specific terms. Architecture reviews, PRDs, and
agent prompts should anchor on the definitions here so that the same noun
means the same thing across documents.

## journal mutation

A bounded operation that changes one or more journal-class files
(`*.journal`, with `10-accounts.dat` and `archived-manual.journal` allowed
as co-candidates), identified by a UUIDv7 event ID, with optional
post-write verification and automatic rollback. Every entry in
`workspace/events.jsonl` corresponds to one journal mutation — forward or
compensating.

Journal mutations flow through `services/journal_writer.py`'s
`mutate(...)` context manager. The writer owns the seven-step ritual that
enforces DECISIONS §3 (workspace canonical), §4 (idempotent +
non-rewriting), §12 (event-sourced undo + external-edit detection), §15
(reconciliation_event_id linkage), §17 (import fence), and the
reconciliation verify-and-rollback policy.

Out of scope (these writes are *not* journal mutations and do not flow
through the writer): rules JSON (`workspace/rules/*.json`), workspace
config (`workspace/settings/workspace.toml`), opening-balance files
(`workspace/opening/*`), and `.workflow/` operational state.

See `plans/journal-writer-prd.md` for the full design rationale.

## Review

The triage job: categorizing freshly imported transactions that arrived
without a category ("unknowns"). Part of the weekly import loop. Rule-building
happens *in context* here — categorizing a transaction and saving it to a rule
is one continuous flow, not a trip to a separate Rules page. "Review" always
means this triage sense, never analytical review (see **Explore**).

## Explore

The analytical job: exploring spending habits and patterns over time. A durable
destination distinct from **Review**. Furnished with data the app already
computes; genuinely new analytics that require new backend aggregations are
deferred (the future direction is a flexible, uniform interface for varied
analytical needs).

## cross-filter vs drill-through

Two distinct progressive-disclosure mechanics on analytical surfaces. A
**cross-filter** is *in-page*: clicking a mark in one visual re-scopes or
highlights the other visuals on the same page for that selection; the user stays
put. A **drill-through** is the explicit *escape to row-level truth*: an action
("see these transactions →") that navigates to Transactions for the complete
picture. Clicking a mark cross-filters; only an explicit action drills through.

## cross-filter context

The page-level shared reactive selection state on Explore that every visual
subscribes to. ECharts click/select/brush events write to it; visuals re-render
against it. Designed selection-first so a future server-side aggregation backend
can slot behind it (selection → query) without reworking the interaction layer.
The performant aggregation engine itself is deferred backend work — see
`docs/adr/0005`.

## durable surface vs workflow surface

A **durable surface** is a place a user returns to and dwells in: Overview,
Accounts, Transactions, Explore. A **workflow surface** is a task-flow entered
and left when there is work to do: Import, Review, Reconcile. Workflows are
surfaced contextually (e.g. Overview says "12 to review →") rather than holding
permanent equal real estate. Rules is neither — it is an in-context capability
woven into Review, not a destination.
