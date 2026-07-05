# Task: Stages proven through Import and Review resume flows

Issue: https://github.com/thinlines/ledger-flow/issues/21 (parent #14)
Spec: `docs/ledger-flow-projection-schema.md` (Revision 2) — authoritative; deviations update the doc in the same change.
Method: TDD — every slice starts with a failing test at the approved seam.

## Goal

Move workflow stages out of `.workflow/stages/*.json` into the SQLite
`stages` table, then prove the cutover through the real staged workflows:
Import preview/apply, Review (unknowns) autosave/resume/apply/discard, and
rule-history scan/apply from Review. Route/query behavior and local UI
recovery expectations are preserved; no JSON stage files are created after
cutover.

## Scope decisions (made now, recorded here)

1. **Migration 3 creates `operations` + `stages`** (spec DDL verbatim,
   including the operations indexes). The spec's `stages.applied_operation_id`
   references `operations(id)`, and SQLite refuses all DML on a child table
   whose FK parent is missing — so the `operations` table ships now as pure
   DDL, empty until #22 wires the operations spine. `operation_files` /
   `operation_entities` wait for #22 (nothing here needs them).
2. **`stages` is workflow state, not projection**: it is NOT added to
   `PROJECTION_TABLES` — a projection wipe/rebuild must leave in-flight
   stages intact (they are resumable workflow state, not rebuildable from
   journals). Same for `operations` (durable history class).
3. **`StageStore` is rewritten in place** (`services/stage_store.py`) as a
   workspace-config-scoped DB store — spec durability rule 1: the database
   resolves from workspace config, not a process-level root. Same method
   surface (`create` / `load` / `save` / `delete` / `find_latest` /
   `cleanup_old`) so endpoint call sites change minimally; constructed
   per-request from config (no module singleton). `ensure_database(config)`
   is its idempotent entry point.
4. **Row shape**: `payload_json` stores the full stage payload exactly as
   today (including injected `stageId` / `createdAt`), so `load()` returns a
   dict equivalent to the old JSON file. `kind`, `status`, `summary_json`
   are mirrored into columns on create *and* save (status transitions
   `ready` → `applied` happen via `save`). `updated_at` bumps on save;
   `find_latest` orders by it (replaces file mtime); `cleanup_old` deletes
   rows older than the cutoff by `updated_at`.
5. **`load()` raises `StageNotFoundError`** (new, in `stage_store.py`)
   instead of `FileNotFoundError` — a DB store raising a filesystem
   exception is a lie. Endpoints catch it → 404, same as today.
6. **Base file hashes**: `create(payload, base_files=[...])` computes
   `base_file_hashes_json` as `{path: sha256(file bytes)}` at stage
   creation — import passes `targetJournalPath`, unknowns and rule-history
   pass `journalPath`. This records what the stage was computed against
   (the drift anchor the spec's `stale` status will use); no staleness
   *behavior* is added now — apply revalidates content itself, as today.
7. **`base_revision` and `applied_operation_id` stay NULL** until #22
   defines revisions and operation rows. Import's applied-operation linkage
   remains `result.historyId` inside the payload (import history NDJSON is
   cut over in #20/#22).
8. **Discard = hard DELETE** of the row (spec keeps a `discarded` status for
   the future operations-linked world; today's contract is "discardable" —
   the JSON store unlinked the file, the DB store deletes the row, and
   resume scans stay trivially correct).
9. **Endpoint scoping**: `get_stage`, `delete_stage`, and
   `unknown_stage_mappings` gain `_require_workspace_config()` (they need
   config to reach the workspace DB). New behavior: 409
   `workspace_not_initialized` without a workspace — previously they'd poke
   a root-scoped file store. Correct, not a regression.
10. **Lifespan**: stage cleanup runs only when a workspace config loads
    (`StageStore(config).cleanup_old(days=7)`); it also removes the legacy
    `ROOT_DIR/.workflow/stages/` directory once (existing JSON stages are
    abandoned, not migrated — stages are ephemeral, alpha, no backcompat).
11. **Frontend behavior is unchanged** (same endpoints, same shapes). The
    frontend work is test coverage via behavior-preserving extraction into
    shared modules (per component-patterns rule):
    - `$lib/stage-client.ts`: `loadStage`, `discardStage`,
      `applyImportStage`, `applyUnknownStage`, `saveUnknownSelections` —
      thin wrappers over `api.ts` used by `ImportFlow.svelte` and the
      unknowns page (rules page keeps its scan call; it only forwards
      `stageId` into the route).
    - `$lib/unknown-stage-memory.ts`: the localStorage remember/recall/clear
      trio, parameterized by `workspacePath` (storage key
      `ledger-flow:unknown-review:<workspacePath>` unchanged).
    Resume *orchestration* (route `stageId` > remembered stage > fresh scan)
    stays in the page component; its server semantics are covered by the
    endpoint tests.

## TDD slices

Each slice: write the test → watch it fail for the right reason → implement
→ green → refactor.

- **Slice A — schema migration** (`tests/test_projection_db.py`)
  - Migration `(3, "operations_and_stages_tables", …)` creates `operations`
    and `stages` per spec DDL; idempotent; recorded once in
    `schema_migrations`.
  - `stages` columns: id, kind, status (+CHECK), created_at, updated_at,
    base_revision, base_file_hashes_json, summary_json, payload_json,
    applied_operation_id.
  - FK: insert with bogus `applied_operation_id` fails; NULL succeeds.
  - Status CHECK rejects unknown values.
  - Projection wipe-and-rebuild leaves `stages` rows intact
    (`PROJECTION_TABLES` unchanged).
- **Slice B — DB stage store** (`tests/test_stage_store.py`, new)
  - `create` returns id, injects `stageId`/`createdAt`, mirrors
    kind/status/summary columns, computes `base_file_hashes_json` from
    `base_files`; `load` round-trips the exact payload; missing id →
    `StageNotFoundError`.
  - `save` persists payload changes, re-mirrors status/summary, bumps
    `updated_at`.
  - `delete` removes the row (idempotent); `find_latest(predicate)` returns
    the most-recently-updated match or None; `cleanup_old` deletes only
    rows older than the cutoff and reports the count.
  - No `.workflow/stages/` directory or JSON file is created anywhere in
    the workspace.
- **Slice C — endpoint cutover** (update `test_unknown_stage_resume.py`
  first; new `tests/test_stage_endpoints.py` via FastAPI TestClient like
  `test_reconcile_endpoint.py`)
  - Import: preview creates a `stages` row (kind/status/summary/base file
    hashes populated); apply flips status to `applied`, stores `result`
    with `historyId`, is idempotent on re-apply; stage readable via
    `GET /api/stages/{id}` before and after.
  - Unknowns: scan creates; rescan resumes same `stageId` preserving
    selections (existing tests, re-pointed at the DB store); autosave
    updates selections/summary in the row; apply flips to `applied` with
    result; `DELETE /api/stages/{id}` discards the row and a following
    scan mints a fresh stage.
  - Rule-history: scan creates a `rule_history` stage; apply flips to
    `applied` with `selectedCandidateIds` + result; `DELETE` cleans up
    (the frontend's post-redirect cleanup call).
  - Unknown stage id → 404 for GET/apply; kind mismatch → 400 (unchanged
    contracts).
  - After each flow: `.workflow/stages/` contains no new JSON files.
- **Slice D — frontend extraction + tests** (vitest)
  - `unknown-stage-memory.test.ts`: remember/recall round-trip; remember
    with null stage clears; corrupted JSON clears and returns null; no
    workspacePath → no-op/null.
  - `stage-client.test.ts`: each helper hits the right endpoint with the
    right payload/method (api.ts mocked).
  - Rewire `ImportFlow.svelte` + unknowns page onto the extracted modules;
    behavior-preserving (no copy, timing, or route changes).
- **Slice E — full suites + live verification**
  - Backend `uv run pytest`, frontend `pnpm test`.
  - Live: run the app; import preview→apply round trip; unknowns
    select→autosave→reload (route resume)→apply; discard path; confirm
    rows in `.workflow/state.db` `stages` table and no new files under
    `.workflow/stages/`.

## Acceptance criteria (from issue #21)

- [x] Import preview creates and resumes stage rows in SQLite with
      equivalent summary/payload/result behavior to the existing JSON stage
      store.
- [x] Review unknowns autosave, route `stageId`, local remembered stage,
      resume, apply, and discard flows work against the database-backed
      stage store.
- [x] Rule-history scan/apply stages continue to redirect and clean up as
      they do today.
- [x] Stage status, base revision/file hashes, summary, payload, and
      applied operation linkage are represented in the `stages` table.
- [x] Old JSON stage files are no longer created for new stages after
      cutover (startup also removes the legacy `.workflow/stages/` dir).
- [x] Endpoint and frontend tests cover resume/apply/discard for Import and
      Review — plus live verification on a scratch workspace (UI review
      select → autosave → reload resume → apply; import preview → apply;
      API discard → 404; stage rows inspected in `state.db`; no JSON stage
      files created).

## Out of scope

Operations spine behavior and rows (#22), `operation_files` /
`operation_entities` DDL (#22), stage `stale`/`failed`/`discarded` status
*behavior*, transactional stage-save-with-writer-rollback coupling (#17),
import-identity tables (#20), migrating existing JSON stage files (deleted,
not migrated), frontend resume-orchestration redesign, staleness detection
UX.
