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
