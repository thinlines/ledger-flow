# Task: Stable transaction identity proven through one edit flow

Issue: https://github.com/thinlines/ledger-flow/issues/16 (parent #14)
Spec: `docs/ledger-flow-projection-schema.md` (Revision 2) — authoritative; deviations update the doc in the same change.
Method: TDD — every slice starts with a failing test at the approved seam.

## Goal

One-time journal migration to `lf_` house-style metadata (stable `lf_txn_id`
per managed transaction, schema-named key renames), then prove the new
`(lf_txn_id, raw_block_hash)` mutation contract end to end through the
clearing-status toggle: frontend sends id + block hash, backend locates the
block by id, rejects true staleness by hash, re-projects the touched file,
and returns updated projected data.

## Scope decisions (made now, recorded here)

1. **Tracer flow = clearing-status toggle** (issue offers notes or toggle).
   It is the highest-frequency edit, it rewrites the header line (the exact
   text the old positional contract keyed on), and repeated toggling of the
   same transaction is the scenario stable identity must survive. The
   existing `newHeaderLine` re-spread contract is the positional coupling
   being removed.
2. **Migration is a service + CLI subcommand**, not a loose script:
   `services/journal_migration_service.py` `migrate_lf_metadata(config)`,
   exposed as `ledger-flow migrate-lf-metadata`. It runs through
   `journal_writer.mutate` (backup/rollback/event ritual;
   `event_type="journal.lf_metadata_migrated.v1"`), then refreshes the
   projection so assigned ids are adopted. Idempotent: second run changes
   nothing. (Precedent: `Scripts/migrate_journal_dates_to_iso.py` predates
   the writer chokepoint; this migration should not bypass it.)
3. **Id assignment**: every *managed* transaction block (projection
   `parse_status = 'ok'`) in role `journal` / `opening` / `archive` files
   without an `lf_txn_id` gets `    ; lf_txn_id: txn_<uuid7>` inserted
   directly after the header line. `uuid7` is time-ordered (same source as
   writer event ids). `preserved_raw` blocks are outside the managed subset
   and are never rewritten; `directives` files carry no transaction blocks
   and are skipped.
4. **No `lf_posting_id` minted yet.** House style says postings carry one
   "when the app needs stable posting identity" — no current flow does. The
   migration is the single home for future assignment ("needed" = none).
5. **Key renames = exactly the families the schema names** (issue: "where
   covered by the projection schema"): `source_identity(_N)` →
   `lf_source_identity(_N)` and `reconciliation_event_id` →
   `lf_operation_id`. Other app keys (`import_account_id`,
   `source_payload_hash`, `statement_period`, `match-id`, transfer keys,
   `notes`, `statement_payee`) are not schema-named; they migrate in the
   issues that own their flows (#20 imports, #22 operations, #24 merchant)
   by extending the same command's rename table. Renames apply inside
   transaction blocks only; every other byte is preserved.
6. **Readers/writers rename in the same change** (no backcompat): import
   write path, import fence/history, unknowns, reconciliation write +
   context + duplicate services, unified transactions (`is_assertion`
   detection), and `SYSTEM_METADATA_KEYS`. `lf_txn_id` / `lf_posting_id` /
   `lf_operation_id` / `lf_source_identity` join the system-key lists so
   user-metadata extraction (unmatch/apply) never copies identity between
   blocks.
7. **Duplicate `lf_txn_id` hardening**: `transactions.id` is a primary key;
   once journals carry ids, a hand-copied block could collide. The
   projection adopts the first occurrence; later duplicates get an ephemeral
   id plus a `duplicate_lf_txn_id` diagnostic instead of crashing the
   rebuild.
8. **New toggle contract**: request `{txnId, blockHash}` (replaces
   `{journalPath, headerLine, lineNumber}` — no backcompat). Backend:
   `refresh_projection` (self-healing) → look up transaction by id (404
   "Transaction not found (stale data — try refreshing)" when missing) →
   compare submitted `blockHash` to projected `raw_block_hash` (409 "This
   transaction changed since it was loaded — refresh and try again" on
   mismatch) → rewrite the header line at the projected
   `source_start_line` inside `journal_writer.mutate` → re-project the
   touched file → return `{newStatus, newHeaderLine, txnId, blockHash,
   eventId}` with the *post-edit* projected id + hash.
9. **Response keeps `newHeaderLine` transitionally**: the other row actions
   (delete/recategorize/unmatch/notes) stay positional until #17, and the
   frontend re-spread must keep their `headerLine` fresh after a toggle.
   Ephemeral-id blocks (`preserved_raw`) stay toggleable: the response
   returns the re-projected id (recovered via stable `txn_order`), so
   follow-up toggles keep working even though the hash-derived id changed.
10. **Register payload carries identity**: `ParsedTransaction` gains
    `txn_id` / `block_hash` (populated only by the projection loader —
    the legacy loader's block boundary includes trailing blanks, so its
    text is not hash-comparable). Unified rows expose them per leg
    (`legs[].txnId`, `legs[].blockHash`) beside the positional fields.
    The A/B parity test nulls the two new fields for the legacy side —
    documented as the one intentional payload difference.
11. **Toggle works for included-file transactions now**: the old contract
    rejected them via the `-1` line-number sentinel; id + hash has no such
    limit. This is a deliberate behavior improvement, not a regression.
12. **Frontend**: leg type gains `txnId` / `blockHash`; `toggleClearing`
    sends `{txnId, blockHash}`, re-spreads `legs[0]` with the returned
    `headerLine`/`txnId`/`blockHash`, keeps optimistic status + silent
    revert semantics unchanged.

## TDD slices

Each slice: write the test → watch it fail for the right reason → implement
→ green → refactor.

- **Slice A — migration** (`tests/test_journal_lf_migration.py`)
  - Assigns `lf_txn_id` to managed blocks missing one; adopts, never
    replaces, existing ids; inserts directly after the header.
  - Renames `source_identity(_N)` / `reconciliation_event_id` inside blocks.
  - Byte preservation: untouched blocks, file comments, blank runs, CRLF-free
    files, missing trailing newline, `preserved_raw` blocks, `.dat` files —
    all byte-identical outside inserted/renamed lines.
  - Idempotent second run; report counts; backup files exist; event emitted.
  - After migration + refresh, `transactions.id` equals the journal's
    `lf_txn_id` for every managed block.
  - Duplicate `lf_txn_id` → first adopted, second ephemeral + diagnostic.
  - CLI subcommand wired (`ledger-flow migrate-lf-metadata`).
- **Slice B — reader/writer renames** (existing suites, updated first)
  - Update key expectations in import/reconciliation/unknowns/unified tests
    to `lf_` names → red → flip the service literals → green.
  - System-key lists include the new `lf_` keys; user-metadata extraction
    never carries `lf_txn_id` across blocks (new assertion).
- **Slice C — toggle by id** (`tests/test_toggle_status_by_id.py`, endpoint
  seam via FastAPI TestClient like `test_reconcile_endpoint.py`)
  - Toggle by `{txnId, blockHash}` cycles status in the journal text and
    returns updated projected id + hash; projection row reflects the edit
    without a manual refresh.
  - Stale hash → 409, journal untouched. Unknown id → 404.
  - External edit *before* the transaction (line shift) then toggle → still
    succeeds (the positional contract's failure case, now fixed).
  - Repeated toggles succeed using each response's returned hash.
  - Included-file transaction toggles successfully.
  - Register payload exposes `legs[].txnId` / `legs[].blockHash`; parity
    test updated per decision 10.
- **Slice D — frontend contract** (`transactionActions` vitest)
  - `toggleClearing` posts `{txnId, blockHash}`, updates `row.status`,
    re-spreads leg identity from the response, reverts on error; skips when
    the leg has no identity.
- **Slice E — full suites**: backend `uv run pytest`, frontend `pnpm test`.

## Acceptance criteria (from issue #16)

- [x] Deliberate migration command assigns stable `lf_txn_id` (and needed
      `lf_posting_id` — none currently) to existing managed transactions.
- [x] Schema-named metadata keys rewritten to `lf_` house style; user text
      outside managed metadata preserved byte-for-byte.
- [x] Toggle-status flow sends transaction id + block hash; no line-number /
      header-text dependence.
- [x] Backend rejects stale block hash (409; 404 for unknown ids).
- [x] Successful edits re-project the touched file and return updated
      projected data.
- [x] Tests: id assignment, metadata rewrite, stale rejection, byte
      preservation — plus live verification (CLI migration on a scratch
      workspace; API toggle cycle, 409/404/422 probes, and a 3-click UI
      round-trip on the running app, journal restored byte-identically).

## Out of scope

Converting the remaining mutation flows (#17), writer-transactional
projection (#17), `lf_posting_id` minting, operations spine / `lf_operation_id`
row semantics (#22), import-identity tables (#20), renaming non-schema-named
metadata keys, `::` typed-metadata writing, frontend stale-state copy
redesign (#17), FTS, reference data.
