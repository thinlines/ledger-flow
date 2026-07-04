---
labels: [ready-for-agent]
---

# DB-backed projection refactor: SQLite as projection, operation log, and reference data store

> GitHub: https://github.com/thinlines/ledger-flow/issues/14 (`ready-for-agent`)

Authoritative spec: `docs/ledger-flow-projection-schema.md` (Revision 2). This PRD is the
work order for adopting it end to end.

## Problem Statement

Ledger Flow's backend keeps its state scattered across half a dozen bespoke text stores —
an events JSONL, an import-log NDJSON, a rules NDJSON, a payee-aliases CSV with a
generated `.dat`, stage JSON files, and TOML sections — while the journals themselves are
re-parsed with regexes on every read. As the user, this shows up as real limitations:
transactions have no stable identity (the app finds them by line number and exact header
text, so anything that moves a line invalidates the UI), undo is split across two
mechanisms that behave differently, accounts/payees/tags aren't modeled at all (no
parent-picker, no close/delete lifecycle, no merchant list, validation requires shelling
out to the ledger CLI), and every screen recomputes its numbers in Python from a full
re-parse. Features added over time have accumulated as parallel one-off mechanisms,
cluttering both the backend and the UI, and making each next feature harder to build.

## Solution

Keep plaintext journals canonical and make SQLite the single structured layer beneath the
app, per the projection schema doc: a rebuildable **projection** of journals (transactions,
postings, comments, typed metadata, journal items), typed **reference data**
(accounts with type/subtype/hierarchy/lifecycle, payees-as-merchants with aliases and
default categories, tags, commodities) projected from the directive files that power
`ledger --strict`/`--pedantic`, a single durable **operations** spine with
compensation-based undo replacing both existing undo paths and both log files, **rules**
with grouped (DNF) conditions replacing the NDJSON, and workflow **stages** in the same
database. Transactions gain stable `lf_txn_id` identities written as house-style journal
metadata; amounts are stored as exact integer nanounits and rounded only at presentation;
typed metadata uses ledger's `::` value-expression syntax so ledger itself validates it at
parse time. One database, one audit trail, one identity model — and the journal files stay
the source of truth, byte-for-byte preserved wherever the app didn't touch them.

## User Stories

1. As a Ledger Flow user, I want every transaction and posting to have a stable identity, so that edits, undo, and history keep referring to the same transaction no matter where it sits in the file.
2. As a user who edits journals in a text editor, I want the app to detect my external edits and re-project the affected files automatically, so that the UI never shows stale data and never overwrites my hand edits.
3. As a user, I want the entire projection to be rebuildable from my journal files at any time, so that the database can never hold my data hostage or drift silently from the truth.
4. As a user, I want journal content the app didn't touch to round-trip byte-for-byte through any operation, so that my formatting, comments, and unsupported ledger constructs survive.
5. As a user, I want balances and running balances computed with exact integer arithmetic, so that the app's numbers always agree with the ledger CLI to the cent.
6. As a user with multiple year files, I want a deterministic cross-file ordering for the register and running balance, so that same-date transactions never reorder between reads.
7. As a user, I want accounts, payees, tags, and commodities to be first-class entities with declarations, so that `--pedantic`-grade validation catches typos before they land in a journal.
8. As a user creating an account, I want to pick a parent account and type a new leaf name, so that building out my chart of accounts is a two-field operation.
9. As a user, I want accounts to carry a type and subtype (vehicle, mortgage, credit card…), so that net-worth and dashboard groupings reflect how I actually think about my finances.
10. As a user, I want to close an account so it disappears from pickers and autocomplete while its history and reports stay intact, so that old accounts stop cluttering data entry.
11. As a user, I want deleting an account declaration to be blocked while any posting still references it or a descendant, so that I can't orphan history by accident.
12. As a user, I want account/payee/tag autocomplete served from the database, so that data entry is instant and doesn't shell out to the ledger CLI.
13. As a user importing bank statements, I want messy statement payees normalized to canonical merchant names on the payee line, so that my register and reports read cleanly.
14. As a user, I want the original statement text preserved as metadata on every imported transaction, so that I can always see exactly what the bank sent.
15. As a user, I want merchants to carry a default category, so that the common case categorizes itself on import without my writing a rule.
16. As a user in Review (unknowns triage), I want to create a merchant — alias pattern plus default category — in context, so that categorizing one transaction teaches the app durably.
17. As a user, I want recurring undeclared payees surfaced as "create merchant from this?" suggestions rather than errors, so that manual one-off payees stay frictionless.
18. As a user, I want rules with grouped conditions like `(payee matches X AND amount < 20) OR (payee matches Y)`, so that one rule can express real matching logic.
19. As a user, I want rules to act as an exception layer above merchant defaults (rule → merchant default → Unknown), so that my rules list stays short and comprehensible.
20. As a user, I want rule and reference-data edits recorded in the same operation history as journal mutations, so that I can see when and why categorization behavior changed.
21. As a user, I want duplicate detection keyed on durable import identities that survive projection rebuilds, so that re-importing a statement never double-books transactions.
22. As a user, I want to undo an import and later re-import the same file cleanly, so that a mistaken import is fully reversible in both directions.
23. As a user, I want every app change recorded as an operation with one-click compensating undo, so that no action in the app feels risky.
24. As a user, I want one coherent activity feed across imports, edits, reconciliations, merchant changes, and rule changes, so that I can audit what happened in one place.
25. As a user, I want my operation history exported into the existing git snapshot safety net, so that even database loss can't erase the audit trail.
26. As a user reconciling accounts, I want balance assertions still verified by `ledger bal --strict` after every write, so that the app's math is independently checked by ledger itself.
27. As a user, I want app-written typed metadata (dates, amounts, booleans) validated by ledger at parse time via `::` typed-metadata syntax, so that an invalid value fails loudly and immediately.
28. As a user, I want journal constructs the app doesn't manage surfaced as file/line diagnostics instead of blocking the app, so that valid-but-unsupported ledger syntax degrades gracefully.
29. As a user with six years of daily data, I want transactions, search, and dashboard numbers served by SQL queries instead of full-file re-parses, so that the app stays fast at scale and the deferred Explore aggregation engine (ADR-0005) has its substrate.

## Implementation Decisions

The projection schema document is the authoritative spec; decisions recorded there and
agreed during design review:

- **Journal files remain canonical** (explicitly reaffirmed against a DB-canonical
  alternative). The database is a projection plus durable app history; projection tables
  are safe to wipe and rebuild from plaintext.
- **Three table classes**: projection (rebuildable), operation (durable, not
  rebuildable), workflow (disposable). Rules are operation-class; reference data is
  projection-class.
- **Stable identities**: transactions/postings carry `lf_txn_id`/`lf_posting_id` house
  metadata. The client mutation contract moves from (path, line number, header text) to
  (entity id, block hash); staleness is a block-hash mismatch.
- **Mutation-time incremental projection** inside the existing journal-writer
  backup/verify/rollback ritual: touched files re-project in the same SQLite transaction;
  file writes and projection commit or revert together; full rebuild is the recovery
  path. Drift detection is a content-hash comparison; self-healing re-projection on read.
- **Amounts as integer nanounits** (10^-9 major units), exact SQL summation, rounding
  once at presentation via per-commodity display scale; parse decimal text with
  string/integer math, never through floats. Prices/costs stay with the ledger CLI until
  stocks are supported, at which point they are stored as integer rationals
  (numerator/denominator) and multiplied with arbitrary-precision rational math.
- **Reference data** projected from the directive files as the union of declared and
  used entities; `used AND NOT declared` is the `--pedantic` diagnostic. Accounts use
  materialized-path hierarchy (no parent_id) with derived parent/depth columns; type
  derived from the root segment; subtype and close date as `lf_` metadata in the account
  directive. Deletion guarded by the usage anti-join. Nothing foreign-keys into accounts;
  postings join by name.
- **Merchant layer**: payees table doubles as the merchant list; the app (not
  `ledger convert`) applies alias regexes at import, writes the canonical merchant to the
  payee line, preserves raw statement text as metadata. Categorization precedence: rule →
  merchant default account → Unknown. The payee-aliases CSV and its generated file are
  retired; payee/alias directives live in the directives file.
- **Rules**: two-level DNF (condition groups OR'd; conditions within a group AND'd),
  normalized tables for rules/groups/conditions/actions, seeded once from the NDJSON,
  then the NDJSON is deleted.
- **Operations spine**: replaces both the events JSONL and the import-log NDJSON. Undo is
  forward-only compensation via a compensates link; both existing undo paths (semantic
  event undo and import undo) converge on it. Operation ids are pre-minted so journal
  metadata (`lf_operation_id`, renamed from `reconciliation_event_id`) matches the row.
  Import identities treat `undone` as absent so undone imports can re-import; merged
  duplicates keep one identity row per carried identity.
- **Typed metadata** serializes with ledger's `::` value-expression syntax (dates
  bracketed, booleans, amounts); strings keep single-colon form; rendering derives the
  form from the stored value type.
- **Durability**: the database is workspace-scoped (resolved from workspace config, not a
  process-level root — fixing the existing divergence); operation-class data reaches the
  git safety net via a text dump on the existing snapshot hooks.
- **Booleans** are declared `BOOLEAN` with `TRUE`/`FALSE` (SQLite stores 1/0; the
  spelling is Postgres-portable). IDs are text throughout for Postgres portability.
- **No backwards compatibility** (alpha, single user): one-time journal rewrite migrates
  metadata keys to `lf_` house style; operation history starts fresh; superseded files
  are deleted at each cutover step. Adoption order is the schema doc's 11-step plan.
- The ledger CLI remains a runtime dependency for CSV conversion (`ledger convert`) and
  reconciliation verification (`bal --strict`); the `accounts --count` shell-out is
  replaced by the reference tables.

## Testing Decisions

Good tests here assert external behavior — journal file text, API/service payloads, and
ledger-CLI agreement — never the shape of SQL or internal call patterns.

- **Primary seam (existing)**: temp workspace on disk → service/endpoint call → assert on
  journal text and returned payloads. This is the pattern the existing backend suite
  already uses everywhere (workspace fixtures + service tests + endpoint tests), and that
  suite passing largely unchanged is the core regression signal for the migration.
- **One new seam: the projection boundary** (parse→project and project→render), tested
  with golden workspace fixtures for the four invariants:
  1. **Round-trip**: project then render an untouched file → byte-identical.
  2. **Ledger parity**: projection balances and declared/used diagnostics agree with
     `ledger bal` / `--pedantic` on the same files.
  3. **Rebuild ≡ incremental**: full rebuild and mutation-time re-projection yield
     identical database state.
  4. **Atomicity**: an injected failure mid-write rolls back file and projection
     together.
- Prior art: the existing event-log integration tests (multi-service flows over a temp
  workspace) are the closest model for the operations-spine tests; reconciliation tests
  already exercise the ledger CLI in the test environment, so parity tests can assume it.
- Undo tests assert behavior pairs: do X, undo X, journal text and payloads match the
  before state; then redo where applicable (import → undo → re-import).

## Out of Scope

- The Explore server-side aggregation engine and cross-filter backend (ADR-0005 stays
  deferred; this refactor only lays its substrate).
- Stocks/priced commodities: the rational price representation is reserved in the schema
  but not implemented; `@`/`@@` and prices remain CLI-verified raw constructs.
- The DB-canonical inversion (considered and rejected — journals stay canonical).
- Postgres migration (portability is preserved, not exercised).
- Frontend changes beyond adapting the mutation contract and consuming new
  endpoints/fields; no visual or IA work.
- The "further consolidation candidates" in the schema doc (tracked/import accounts out
  of TOML, FTS5 search, writer pre-images replacing `.bak` files, category-suggestion
  stats) — each is a separate deliberate decision after this lands.
- Multi-user/multi-writer concurrency beyond the existing single-writer lock model.

## Further Notes

- `docs/ledger-flow-projection-schema.md` is the living spec; if implementation forces a
  deviation, update the doc in the same change.
- Vocabulary per `CONTEXT.md`: "journal mutation", "Review" (triage), "Explore"
  (analytics) are used in their glossary senses throughout.
- The per-account running balance is a load-bearing power-user feature; the deterministic
  cross-file ordering exists to protect it and must survive any implementation shortcuts.
- Implementation should follow the adoption plan's step order; several steps are
  independently shippable and the suite must be green after each.
