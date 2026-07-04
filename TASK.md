# Task: Projection foundation proven through Transactions read path

Issue: https://github.com/thinlines/ledger-flow/issues/15 (parent #14)
Spec: `docs/ledger-flow-projection-schema.md` (Revision 2) — authoritative; deviations update the doc in the same change.
Method: TDD — every slice starts with a failing test at the approved seam.

## Goal

Create the workspace-scoped SQLite migration/bootstrap path and the first
rebuildable journal projection, then serve the Transactions register from it.
Journals stay canonical; behavior of `GET /api/transactions` is unchanged.

## Scope decisions (made now, recorded here)

1. **Same database file** as the import index: `<workspace>/.workflow/state.db`,
   resolved from `config.root_dir` (never the process `ROOT_DIR` — that global
   is a known wart). New tables live beside `imported_transactions_v2`.
2. **Migration runner** is a new `services/projection_db.py`: ordered in-code
   migration list, `schema_migrations(version, name, applied_at)` bookkeeping,
   idempotent `ensure_database(config)`. WAL + synchronous=NORMAL pragmas,
   foreign_keys ON per connection (matches ImportIndex conventions).
3. **Projection tables in this slice** (DDL per spec Core DDL / Comments /
   Diagnostics sections): `journal_files`, `journal_items`, `transactions`,
   `postings`, `comments`, `metadata_entries`, `journal_diagnostics`.
   Reference-data, rules, imports, operations tables are later issues.
4. **Projected file set**: every physical file reachable from
   `journal_dir/*.journal` via `include` (recursive, glob-aware), each exactly
   once. Roles: `archived-manual.journal` → `archive`; files under the opening
   dir → `opening`; `*.dat` → `directives`; else `journal`. Paths stored
   relative to `config.root_dir` (POSIX form).
5. **Managed-subset parse**: a transaction block projects into structured rows
   only when every posting parses cleanly (header OK, ISO date, amounts parse
   or are the single elided posting, ≤9 decimal places, no `@`/`@@`, no
   balance-assertion-only weirdness beyond the supported `= amount` form).
   Otherwise the block stays a `transaction` item with
   `transactions.parse_status = 'preserved_raw'` plus a diagnostic — never an
   app-blocking error.
6. **Amounts**: `postings.amount_nano` INTEGER nanounits (10^-9), converted
   from the parsed `Decimal` with exact integer scaling; >9 dp →
   preserved_raw + `amount_precision_exceeded` diagnostic. Elided posting
   inference happens at projection time (`amount_inferred = TRUE`), summing in
   nanounits.
7. **No `lf_` id assignment during passive rebuild** (spec Rebuild Flow rule 4):
   `transactions.id` adopts an existing `lf_txn_id` metadata value when the
   block carries one, else gets a generated ephemeral id. Journal files are
   never written by this feature.
8. **Round-trip**: `journal_items.raw_text` holds exact byte slices of the
   original file (including original line endings / trailing-newline state);
   rendering a file = concatenation of its items' raw_text, byte-identical.
9. **Freshness = self-healing content hash** (spec Mutation-Time Projection
   rule 4): on read, any file whose disk sha256 differs from
   `journal_files.content_hash` is re-projected; missing files are removed;
   new files are added. Writer integration (projection inside the mutate
   ritual) is issue #17 — the hash check keeps every existing mutation flow
   correct in the meantime.
10. **Transactions read path**: `build_unified_transactions` switches its
    loader to `load_transactions_projected(config)` which (a) ensures
    schema + freshness, (b) reconstructs the exact `ParsedTransaction`
    contract from projection rows (Decimal amounts from nanounits — exact,
    metadata dict rebuilt by applying the legacy `META_RE` to stored comment
    raw text so key semantics match byte-for-byte, `header_line_number`
    physical offset with the `-1` include sentinel, `source_journal` = the
    top-level year journal). `preserved_raw` blocks are re-parsed with the
    legacy `_parse_transaction` so out-of-subset journals behave exactly as
    today. Row assembly, filters, running balance, and API shape are untouched.
11. **Ordering parity**: the register keeps today's order — per top-level
    journal in filename order, include-expansion position within it, stable
    sort by date. The projection reconstructs expansion order by walking
    `journal_items` include links. The spec's `(date, path, txn_order)`
    paragraph gets amended to record expansion order as the register's
    tiebreaker (doc update in this change).
12. **Dashboard/activity/other consumers stay on the legacy loader** in this
    slice; only the unified Transactions path is switched (tracer bullet).

## TDD slices

Each slice: write the test → run it → watch it fail for the right reason →
implement → green → refactor.

- **Slice 1 — migrations/bootstrap** (`tests/test_projection_db.py`)
  - `ensure_database(config)` creates `.workflow/state.db` with
    `schema_migrations` + all seven projection tables, beside
    `imported_transactions_v2` when ImportIndex ran first.
  - Idempotent: second call applies nothing new; versions recorded once.
  - Projection tables can be wiped and re-created (rebuild-safe).
- **Slice 2 — projection golden tests** (`tests/test_projection_service.py` +
  `tests/fixtures/projection/` golden workspace)
  - Round-trip: every projected file renders byte-identical (fixtures include
    file comments, blank runs, directives, includes, unicode, trailing
    whitespace, missing trailing newline, CRLF-free plain files).
  - Structure: transactions/postings/comments/metadata rows match expected
    values incl. nanounits, inferred elision, status, tags (`; :flag:`),
    typed `key::` metadata, kv metadata.
  - Rebuild: external edit → refresh re-projects only the changed file;
    full rebuild from scratch ≡ refreshed state; wipe + rebuild is lossless.
  - No `lf_` assignment: journals on disk untouched; generated ids only where
    no `lf_txn_id` metadata exists; existing `lf_txn_id` adopted.
  - Diagnostics: `@` price, >9 dp, ≥2 elided postings, unknown top-level
    construct → `journal_diagnostics` rows with file/line/code; blocks
    preserved raw; rest of the file still projects.
- **Slice 3 — ledger CLI parity** (same test module; assumes `ledger` in the
  test env like the reconciliation tests do)
  - Account balances from `SUM(amount_nano)` (roles journal+opening, archive
    excluded) equal `ledger bal --flat` on the golden workspace, to the cent.
- **Slice 4 — Transactions read path** (`tests/test_projection_read_path.py`)
  - A/B parity: `build_unified_transactions` payload identical between legacy
    loader and projection loader on a rich fixture (rows, running balances,
    ordering, legs line numbers incl. `-1` sentinel, summary, accountMeta).
  - Self-healing: mutate journal on disk between calls → projected read
    reflects the edit.
  - Then swap the loader in `unified_transactions_service` and keep the whole
    existing suite green (`test_unified_transactions_service.py` is the
    regression harness — it now exercises the projection).
- **Slice 5 — full suites**: backend `uv run pytest`, frontend `pnpm test`.

## Acceptance criteria (from issue #15)

- [ ] Workspace-scoped SQLite DB created from migrations, projection tables
      wipe-and-rebuild safe.
- [ ] Journals + includes project into files/items/transactions/postings/
      comments/metadata/diagnostics; no missing-`lf_` assignment on passive
      rebuild.
- [ ] Transactions register served from the projection, UI behavior and API
      shape preserved.
- [ ] Integer nanounit arithmetic; deterministic cross-file ordering.
- [ ] Golden tests: round-trip, ledger parity, rebuild, diagnostics.
- [ ] Existing backend and frontend suites green.

## Out of scope

Writer-ritual projection hook, `(lf_txn_id, raw_block_hash)` mutation
contract, reference data tables, operations spine, imports migration,
dashboard/activity loader switch, FTS, deleting the mtime cache.
