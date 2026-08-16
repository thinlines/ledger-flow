# CONTEXT — Ledger Flow domain vocabulary

Living glossary of project-specific terms. Architecture reviews, PRDs, and
agent prompts should anchor on the definitions here so that the same noun
means the same thing across documents.

## Product

**First-party application**:
The primary Ledger Flow experience through which a person understands and
maintains their finances. It owns the coherent human workflow across Import,
Review, Reconcile, Transactions, and Explore.
_Avoid_: Optional frontend, reference client

**Accounting API**:
The shared accounting capability used by the first-party application and by
automation clients such as scripts and agents. API access does not define a
separate or lesser accounting model.
_Avoid_: Backend implementation detail, API-only product

**Accounting measure**:
A number that reconciles exactly to the canonical books for its stated scope
and can be traced to the complete set of transactions that produced it.
_Avoid_: Metric, insight

**Analytical insight**:
An interpretation derived from accounting measures, potentially using
heuristics. It must be distinguishable from an accounting measure and disclose
the basis of the interpretation.
_Avoid_: Accounting fact

**Trust contract**:
The promise that every accounting measure states its scope, reconciles to the
canonical books, and exposes its complete row-level composition.

**Dashboard population**:
All transactions currently present in the canonical books, regardless of
Review or Reconcile status. Unresolved status remains visible and affects
confidence; it does not erase recorded activity from accounting measures.
_Avoid_: Reconciled transactions only, Clean transactions only

**Book health**:
Global facts about the completeness and currency of the books, including work
awaiting Import, Review, or Reconcile. Book health is not narrowed by analytical
selections.
_Avoid_: Dashboard metric

## Planning

**Planning hygiene**:
The state in which a new agent can determine the current outcome, its
authoritative work item, what is likely next, and why within five minutes,
without reconstructing intent from commit history.

**Authoritative work item**:
A GitHub issue that owns the scope and execution status of a piece of work.
Repository planning documents may point to it but do not duplicate its status.
_Avoid_: Task document, active roadmap feature

**Direction**:
A potential product outcome worth preserving for future consideration, without
a commitment to execute it. Directions and their rationale belong in the
roadmap; executable scope belongs in an authoritative work item.
_Avoid_: Task, active feature

**Milestone**:
A GitHub grouping for one committed outcome, containing its specification and
the executable tickets derived from it.
_Avoid_: Roadmap feature, project phase

## journal mutation

A bounded operation that changes one or more journal-class files
(`*.journal`, with `10-accounts.dat` and `archived-manual.journal` allowed
as co-candidates), identified by a UUIDv7 event ID, with optional
post-write verification and automatic rollback. Every journal mutation —
forward or compensating — is recorded as one durable operation in
`.workflow/state.db`.

Journal mutations flow through `services/journal_writer.py`'s
`mutate(...)` context manager. The writer owns the ritual that
enforces DECISIONS §3 (workspace canonical), §4 (idempotent +
non-rewriting), §12 (operation-backed undo), §15
(reconciliation_event_id linkage), §17 (import fence), and the
reconciliation verify-and-rollback policy. External edits are not
detected or logged: the journal files are the source of truth, and the
projection absorbs them on refresh. The only write guards are the
per-block staleness check (HTTP 409) and undo's drift refusal.

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

## Dashboard

The durable surface that combines book health, work requiring attention, and
opinionated interactive financial exploration. Its coordinated visuals support
cross-filtering, drill-down, and drill-through; it is not a report-authoring
canvas. It is the single home for the former Overview and Explore concepts.
_Avoid_: Overview page, Explore page, Report builder

## Cash-flow analysis

The Dashboard's default analytical lens, in which income, expenses, and
transfers retain their distinct financial meanings. Transfers and balance-sheet
movements are not treated as spending, and income is not ranked alongside
expenses merely by transaction magnitude.
_Avoid_: Activity magnitude, Top transactions

## Explore

The analytical job performed within the **Dashboard**: exploring financial
patterns over time through cross-filtering, drill-down, and drill-through.
Explore is a mode of inquiry, not a separate destination.
_Avoid_: Explore page

## cross-filter vs drill-through

Two distinct progressive-disclosure mechanics on analytical surfaces. A
**cross-filter** is *in-page*: clicking a mark in one visual re-scopes or
highlights the other visuals on the same page for that selection; the user stays
put. A **drill-through** is the explicit *escape to row-level truth*: an action
("see these transactions →") that navigates to Transactions for the complete
picture. Clicking a mark cross-filters; only an explicit action drills through.

## cross-filter context

The shared analytical selection state on Dashboard. Analytical visuals
subscribe to it, while book-health and workflow status remain global. Designed
selection-first so a future aggregation backend can respond to the same
selection without changing the interaction model.

## durable surface vs workflow surface

A **durable surface** is a place a user returns to and dwells in: Dashboard,
Accounts, Transactions. A **workflow surface** is a task-flow entered and left
when there is work to do: Import, Review, Reconcile. Workflows are surfaced
contextually (e.g. Dashboard says "12 to review →") rather than holding
permanent equal real estate. Rules is neither — it is an in-context capability
woven into Review, not a destination.

## transaction match

A durable relationship where an imported transaction replaces or absorbs a
manual transaction that represented the same real-world movement of money. The
match exists while the current journal state links the surviving imported
transaction to the archived manual transaction.
