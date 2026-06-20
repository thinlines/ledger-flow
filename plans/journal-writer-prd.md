# PRD — `journal_writer` chokepoint

## Status

- **PR 1 — proof (complete)**
  - [x] `services/journal_writer.py` introduced with `mutate(...)` context manager, `JournalMutation` handle, `VerifyFailure` marker, `WriterRejected` / `WriterUnavailable` / `WriterError` exception surface
  - [x] Unit tests at `app/backend/tests/test_journal_writer.py` covering all 9 behaviors enumerated in §Testing Decisions (28 tests; 0 dependencies on domain code or the `ledger` CLI)
  - [x] `CONTEXT.md` lazily created with **journal mutation** as first entry
  - [x] Convert reconciliation route (`accounts_reconcile`) to flow through the writer (`mut.event_id` + `verify=verify_assertion` via signature-adapter lambda). `AssertionFailure` now subclasses `VerifyFailure` so the writer can surface it via `WriterRejected`. Route handles `WriterRejected` → 422 and `WriterUnavailable` → 500. `restore_from_backup` import dropped from `main.py` (still exported from `reconciliation_service` for any non-route caller until PR 2 deletes `backup_service`).
  - [x] Convert `_undo_transaction_deleted` to flow through the writer with `mut.compensates = original_event_id`. Dispatcher (`undo_event`) now accepts `config: AppConfig` (was `workspace_path: Path`); the converted handler returns the compensating event id (`str`) while unconverted handlers keep the legacy `dict[str, str]` protocol — dispatcher discriminates via `_WRITER_HANDLERS: frozenset[str]`. PR 2 will move every remaining entry from `_HANDLERS` into `_WRITER_HANDLERS` and drop the legacy branch.
- **PR 2 — sweep**: in progress
  - [x] Convert `_undo_transaction_recategorized` to flow through the writer; added `"transaction.recategorized.v1"` to `_WRITER_HANDLERS`. Handler signature now `(config: AppConfig, event: dict) -> str`; `backup_file(..., "undo")` removed (writer owns backup + rollback).
  - [ ] Convert `_undo_transaction_account_reassigned` (same shape as recategorized).
  - [ ] Convert `_undo_transaction_status_toggled`.
  - [ ] Convert `_undo_manual_entry_created`.
  - [ ] Convert `_undo_transaction_notes_updated`.
  - [ ] Convert `_undo_transaction_unmatched` (multi-file: main journal + archive).
  - [ ] Sweep remaining ~14 mutation routes in `main.py`.
  - [ ] Delete `backup_service.py`; drop `restore_from_backup` from `event_log_service` public exports; drop the legacy-handler branch from `undo_event`.
- **PR 3 — cleanup (manual transfer resolution removal + DECISIONS §22)**: not started

## Problem Statement

Every journal mutation in Ledger Flow today reproduces a seven-step ritual inline at the route: read the file's hash before the change, take a backup, perform the mutation, optionally verify it, hash the result, emit an event into `events.jsonl`, and (occasionally) restore from backup on failure. The ritual lives in over fifteen FastAPI routes and seven undo handlers — same intent, slightly different code each time.

That copy-paste pattern is how the DECISIONS §3 (workspace canonical), §4 (idempotent + non-rewriting), §12 (event-sourced undo + external-edit detection), §14–§21 (reconciliation trust boundaries), and §17 (import fence) invariants are *currently* enforced. A maintainer adding a new mutation has to remember every step, in order, with the right error handling, or one of those decisions gets quietly violated. The reconciliation route's verify-and-rollback policy lives inline at the route handler, not in any module that owns the concept. The undo path replays the same dance one more time inside `undo_service.py`. There is no single grep target for "where journal mutations happen."

The friction surfaces in three ways:

- **Adding a mutation is risky.** Any of the seven steps can be forgotten or done out of order. The reconciliation rollback policy (restore-from-backup on verify failure) is currently only applied at one route — any future op that wants the same semantics has to copy it.
- **Maintaining the pattern is expensive.** Changes to the dance (e.g., a new field on `journal_refs`, a new event-log invariant) require touching every site.
- **Auditing journal-write behavior is hard.** "What guarantees does Ledger Flow give about journal mutations?" is answered by inspection of dozens of routes, not by one module's contract.

## Solution

Introduce a single deep module, `journal_writer`, that owns the seven-step ritual behind one context-manager interface. Routes and undo handlers describe **what** they want to change; the writer enforces **how** the change is safely applied, hashed, verified, rolled back, and recorded.

A mutation reads, at the call site, as a `with` block:

```
with journal_writer.mutate(
    paths=[…],
    tag="…",
    event_type="…",
    verify=…,   # optional
) as mut:
    <the actual domain operation, using mut.event_id>
    mut.summary = "…"
    mut.payload = {…}
    mut.compensates = "…"   # only for undo handlers
```

On entry, the writer mints an event ID, captures pre-mutation hashes for every declared path, and backs up every existing path. On exit it runs the optional verifier, captures post-mutation hashes, emits an event into `events.jsonl` with `journal_refs` filtered to paths whose hash actually changed, and rolls back from backup if anything went wrong. The full §3/§4/§12/§17 invariant suite is enforced in one place.

The deepening lands in three pull requests:

- **PR 1 (proof)** — introduce the writer; convert the reconciliation route (the hardest case — pre-minted event ID + ledger-CLI verifier + rollback policy); convert the simplest undo handler (`transaction.deleted.v1` reversal) to prove the `compensates` path.
- **PR 2 (sweep)** — convert the remaining ~14 mutation routes and six undo handlers; delete `backup_service.py`; remove `restore_from_backup` from the route surface.
- **PR 3 (cleanup)** — remove the manual transfer resolution feature (route, service, dialog, model, test); record DECISIONS §22 capturing the design constraint it forced.

By the end of PR 2 there is exactly one place in the codebase where journals are mutated, and exactly one place where the event log is appended to as a side effect of a mutation.

## User Stories

1. As a developer adding a new mutation endpoint, I want to declare the change as a `with` block over a path set and an event type, so that I cannot accidentally skip drift detection, backup, hashing, or event emission.
2. As a developer reading a converted route handler, I want the mutation to be expressible in fewer than ~30 lines of route code, so that intent dominates and the dance recedes into the writer.
3. As a developer working on reconciliation, I want the verify-and-rollback policy to live in the writer, so that any future op that writes an invariant claim can opt in by passing a verifier.
4. As a developer writing tests for a new mutation, I want one unit-test surface (`journal_writer.mutate`), so that I do not have to re-test drift, backup, hash, verify, rollback, and emit for every op.
5. As a developer working on undo, I want each undo handler to flow through the same writer as forward ops, so that the compensating event automatically carries `journal_refs`, a `compensates` link, and a uniquely minted event ID.
6. As a developer maintaining the event log, I want to trust that every `journal_refs.hash_before`/`hash_after` pair came from one code path, so that the audit trail in `events.jsonl` is internally consistent.
7. As a user reconciling an account, I want the closing-balance assertion to fail loudly and roll the file back to its prior state if my journal's running balance does not match, so that I never end up with a journal that the `ledger` CLI rejects on the next read.
8. As a user undoing an action, I want the undo to roll back automatically if the inverse synthesizer fails mid-mutation, so that I cannot end up in a half-undone state where the journal is corrupt and the compensating event is missing.
9. As a user who occasionally hand-edits a journal in a text editor, I want pre-mutation drift detection (DECISIONS §12) to keep working through the writer, so that an external edit is recorded as a marker event before the app overwrites it.
10. As a developer adding a new event type, I want to set `summary`, `payload`, and (for undo) `compensates` inside the mutation block, so that event assembly is local to the operation rather than threaded through callbacks.
11. As a developer reading `undo_service.py` after the conversion, I want each `_undo_*` handler to be approximately the size of its inverse-synthesis logic alone, so that the dance no longer hides the inverse logic.
12. As a developer onboarding to the codebase, I want one grep target (`with journal_writer.mutate(`) for every journal mutation, so that I can audit the mutation surface in one pass.
13. As a developer maintaining the codebase, I want `backup_service.py` deleted, so that backups are not a separate concept routes have to remember to wire up.
14. As a developer of a multi-file mutation (unknowns apply, unmatch, rule reapply), I want to declare every journal-class file the op might touch in a single `paths` list, so that drift, backup, hash, and rollback behavior is uniform across the set.
15. As a developer writing the unknowns-apply path, I want the writer to filter `journal_refs` to paths whose hash actually changed, so that the conditional archive write does not produce a stale ref.
16. As a developer working on rules CRUD, I want my mutations to *not* route through the writer, so that the writer's scope stays narrow and rules-JSON edits do not accidentally start emitting journal events.
17. As a developer working on workspace bootstrap or opening-balance edits, I want those mutations to remain outside the writer, so that the writer's contract — "this op touches at least one `*.journal` file" — stays crisp.
18. As a developer working on import apply, I want the archive CSV move to remain outside the writer, so that the writer's scope stays "journal-class files" and CSV-move provenance continues to live in the `.workflow/` import index where it belongs (DECISIONS §3).
19. As a developer reviewing PR 1, I want exactly one route converted (reconciliation) and one undo handler converted, so that the interface gets pressure-tested against the hardest case before the sweep.
20. As a developer reviewing PR 2, I want the sweep to be mechanical — each route loses ~30 lines of dance and gains a `with` block — so that the diff is easy to read and the conversion is provably complete.
21. As a maintainer, I want the parallel-implementation window (where some routes use the writer and others still inline the dance) to be exactly one PR wide, so that the codebase does not develop a long-lived "two ways to mutate" state.
22. As a developer maintaining the reconciliation flow, I want the `reconciliation_event_id` to remain byte-identical between the journal metadata line and the event log entry (DECISIONS §15), so that the assertion transaction and its event stay linked.
23. As a developer reading future architecture reviews, I want the manual-transfer-resolution removal recorded as DECISIONS §22 with its load-bearing reason, so that the feature is not re-proposed without a design that avoids "discover-after" path resolution.
24. As a developer maintaining the project glossary, I want the term **journal mutation** documented in `CONTEXT.md` (created lazily by this PR), so that future PRDs and architecture reviews anchor on the same vocabulary.
25. As a developer running the test suite, I want the writer to be testable with a tempdir and a trivial fake op (no domain code, no `ledger` CLI), so that the writer's behavior is verifiable independently of any real mutation.
26. As a developer running the existing endpoint tests (`test_reconcile_endpoint.py`, `test_undo_service.py`), I want them to pass without shape changes after the conversion, so that integration coverage is preserved across the refactor.
27. As a developer writing a future op that wants a baseline "ledger parses the journal" check, I want to be able to add it as a default verifier without changing the writer's contract, so that the verify hook absorbs the extension without redesign.
28. As a maintainer auditing for §3 violations, I want the writer to be the only place `events.jsonl` is appended to as the result of a journal mutation, so that `.workflow/` and `workspace/` write boundaries stay clearly separated.

## Implementation Decisions

The design was grilled through eight branches; each landed on a specific resolution.

### 1. Event ID timing — always pre-mint

The writer mints `event_id = uuid7()` on context entry and exposes it on the mutation object before any op code runs. Ops that need to embed the ID in journal metadata (reconciliation does, per DECISIONS §15; future undo-compensation ops may) use it directly. Ops that do not care ignore it. This eliminates per-op branching over "is your event ID needed at write time."

### 2. Path set shape — declared up front, refs filtered by hash change

Each op declares an exact list of paths in `paths=[…]`. The writer:

- pre-mutation: drift-checks each path that exists, captures `hash_before`, backs up each existing path;
- post-mutation: re-hashes each path and assembles `journal_refs` only for paths whose hash actually changed.

This absorbs both multi-file ops (unmatch, unknowns apply, rule reapply) and conditional-touch ops (unknowns apply may or may not write the archive) without special cases. The `discover-after` worst case is no longer supported — see the "Out of Scope" note on manual transfer resolution.

### 3. Verify hook — optional callable, writer owns rollback policy

The writer accepts `verify: Verifier | None = None`. The contract:

- `verify(config, paths) -> None` means verification passed.
- `verify(...) -> VerifyFailure` means the op is rejected — the writer restores every backed-up path and raises `WriterRejected(failure)`.
- `verify(...)` raising `RuntimeError` means the verifier is unavailable — the writer restores every backed-up path and raises `WriterUnavailable`.

Reconciliation passes `verify_assertion`; all other ops today pass nothing. The verifier is the seam for any future op that writes an invariant claim against pre-existing journal data.

### 4. Interface shape — context manager

The writer's public interface is `journal_writer.mutate(...)`, a context manager. The mutation object exposes `event_id`, and accepts assignment to `summary`, `payload`, and `compensates`. On exit:

- if an exception escaped the block: restore every backed-up path; re-raise;
- else if a verifier was supplied and returned failure or raised: restore every backed-up path; raise `WriterRejected` / `WriterUnavailable`;
- else: re-hash every path, assemble `journal_refs` (changed paths only), call `emit_event` with the assembled payload.

The block reads top-to-bottom in the route handler, matching the rest of `main.py`'s imperative style. Failure semantics ride on Python exceptions — the route does not need to remember any cleanup pattern.

### 5. Undo routing — through the writer with `compensates`

Each `_undo_*` handler in `undo_service.py` becomes a `with journal_writer.mutate(...)` block over the file(s) it reverses. The handler sets `mut.compensates = original_event_id` so the emitted event carries the link.

Inverse synthesis (parsing the original block, reconstructing the inverse, finding the insertion point) stays in `undo_service` — it is domain logic, not write logic. Per-event drift detection (comparing the current journal hash to the original event's `hash_after` before constructing the inverse) also stays in `undo_service`, as a precondition that runs *before* entering the mutate block.

### 6. Scope — journal-class only

The writer is required when `paths` contains at least one `*.journal` file. `10-accounts.dat` and `archived-manual.journal` may ride along as co-candidates when an op touches them alongside a year journal. Rules JSON (`workspace/rules/*.json`), workspace config (`workspace.toml`), opening-balance files (`workspace/opening/*`), and operational state under `.workflow/` are explicitly **out of scope** — they may have their own audit story later, but it is not this one.

### 7. Migration — proof then sweep

The migration is two-phase by design, with a one-PR parallel-impl window.

- **PR 1** introduces `services/journal_writer.py`, converts the reconciliation route (`accounts_reconcile`), converts one undo handler (`_undo_transaction_deleted`), and adds writer unit tests.
- **PR 2** sweeps the remaining ~14 mutation routes and six undo handlers, deletes `backup_service.py`, and removes `restore_from_backup` from the event-log service's public exports.
- **PR 3** removes the manual transfer resolution feature in full.

Holding PR 2 indefinitely behind PR 1 is not an acceptable state — the deepening's leverage argument depends on the chokepoint actually being a chokepoint. PR 2 is teed up against PR 1's branch on the same day.

### 8. Naming — `journal_writer.mutate(...)`

The module is `services/journal_writer.py`, consistent with the existing `*_service.py` / `*_runner.py` convention. The verb `mutate` matches DECISIONS §12's existing "journal mutations are recorded as events" framing. The mutation context object is typed `JournalMutation`.

A new term, **journal mutation**, is added to `CONTEXT.md` (created lazily by PR 1 if absent), defined as: *a bounded operation that changes one or more journal-class files, identified by a UUIDv7 event ID, with optional post-write verification and automatic rollback. Every entry in `workspace/events.jsonl` corresponds to one journal mutation, forward or compensating.*

### Side decisions folded into the implementation

These were grilled briefly and have an unambiguous shape; they are decisions, not just defaults:

- **External-edit detection** rides on the existing `check_drift` — the writer calls it for each path that already exists at entry. The `journal.external_edit_detected.v1` marker continues to be emitted as a side effect of `check_drift`. Startup drift detection (`check_startup_drift`) stays where it is and is not the writer's concern.
- **Backup on missing files.** If a declared path does not exist pre-mutation, the writer skips backup for it. Rollback policy for that path is *delete the file if it now exists*; restore-from-backup applies only to paths that existed pre-mutation.
- **Partial rollback failure.** If one of the per-path restores fails during rollback, the writer attempts every other restore, collects per-file failures, and raises an aggregate `WriterError` carrying the per-file outcomes. The writer does not attempt to recover from a partial-restore state — that is operator territory.
- **Git snapshots** remain lifespan-only (current behavior), not per-mutation. The writer does not coordinate with `git_snapshot_service`.
- **`archive_inbox_csv`** (the import CSV move into `workspace/imports/processed/`) is **not** part of the import-apply op's `paths` set. It runs inside the op as a domain side effect; its provenance lives in `.workflow/state.db` via the import history index.

### Op anatomy (from prototype-quality sketch)

The writer's public surface, encoded precisely:

```python
@contextmanager
def mutate(
    *,
    paths: list[Path],
    tag: str,
    event_type: str,
    verify: Verifier | None = None,
) -> Iterator[JournalMutation]: ...


class JournalMutation:
    event_id: str            # minted on __enter__
    summary: str             # set inside the block
    payload: dict            # set inside the block
    compensates: str | None  # set by undo handlers

Verifier = Callable[[Config, list[Path]], VerifyFailure | None]

class WriterRejected(Exception): ...      # raised on verifier failure
class WriterUnavailable(Exception): ...   # raised on verifier RuntimeError
class WriterError(Exception): ...         # raised on rollback failure (aggregate)
```

The writer must enforce that `paths` contains at least one `*.journal` file. Calling `mutate` with no journal-class path is a programming error, not a runtime branch.

## Testing Decisions

**What makes a good test for this feature.** The writer is a deep module — its tests should exercise observable external behavior at the `mutate(...)` interface and assert against the filesystem and the event log. They should not assert against internal helpers (e.g., they should not test `_hash_paths` directly, nor mock the existing `check_drift`/`hash_file`/`backup_file` functions). The op passed into the writer in tests is a trivial fake (writes a known string to a path) — no domain code, no `ledger` CLI, no real reconciliation logic. The intent is that the writer's contract is fully covered by tests that do not import any domain service.

**Primary new seam — `journal_writer.mutate(...)`.** The full set of behaviors to cover at this seam, in tempdir-backed unit tests:

- Entry mints a non-empty UUIDv7 `event_id`, distinct across calls.
- Pre-mutation hashing covers every existing path in `paths` and is consistent with `hash_file`.
- Backup is created for every existing path; missing-file paths are not backed up.
- Successful exit emits exactly one event whose `event_id`, `event_type`, `summary`, `payload`, and (optionally) `compensates` match what the block set; `journal_refs` is restricted to paths whose `hash_after` differs from `hash_before`.
- Exception inside the block: every backed-up path is restored byte-for-byte; missing-file paths created during the block are deleted; the original exception propagates; no event is emitted.
- `verify` returning a `VerifyFailure` causes restore + `WriterRejected`; no event is emitted on rejection.
- `verify` raising `RuntimeError` causes restore + `WriterUnavailable`; no event is emitted.
- A `paths` list containing zero `*.journal` files raises before entering the block.
- Partial rollback (simulate one path's restore failing) raises an aggregate `WriterError` describing per-path outcomes; other paths are still restored.

**Existing seams retained, with no shape change.** The conversion should not require these tests to change beyond mechanical adjustments:

- `test_reconcile_endpoint.py` — HTTP-level reconciliation flow (200 on success, 422 on assertion failure with the expected/actual fields populated, 500 on `ledger` CLI unavailability). The endpoint's external behavior is preserved.
- `test_reconciliation_service.py` — direct tests of `write_assertion_transaction`, `verify_assertion`, fence lookup, failure detection. The service's interface is unchanged.
- `test_undo_service.py` — `undo_event` orchestration plus the converted `_undo_transaction_deleted` handler. The handler now constructs the inverse and runs it inside `mutate`; the test continues to assert end-state (journal text + emitted compensating event with `compensates` populated).
- `test_events_endpoint.py` — event-log API behavior. No change.

**Prior art.** The tempdir-based pattern lives in every backend service test (`test_reconciliation_service.py`, `test_unified_transactions_service.py`, `test_undo_service.py`, `test_manual_entry_service.py`). The writer's tests follow the same shape: `tmp_path` fixture, write a fixture journal, call into the module under test, assert against filesystem state and event log contents. No new test infrastructure is introduced.

**Seams explicitly not added.** An in-memory file-storage adapter is not introduced — there is only one production implementation, so a second adapter would be a hypothetical seam (`one adapter = hypothetical seam, two = real`). A writer-protocol seam (so ops can mock the writer in their own tests) is not introduced — the writer is concrete, ops do not need to mock it. An event-log seam is not introduced — the writer calls existing `emit_event` directly.

## Out of Scope

- **Rules CRUD mutations** to `workspace/rules/*.json`. Outside the writer's scope; do not retrofit.
- **Workspace config edits** to `workspace/settings/workspace.toml`. Outside the writer's scope.
- **Opening-balance files** under `workspace/opening/*`. Outside the writer's scope. (Opening-balance *journal entries* are still journal mutations and continue to flow through the writer.)
- **`.workflow/` mutations.** Operational, disposable per DECISIONS §3. The import index, stage store, and `app_state.json` writes do not flow through the writer.
- **Archive CSV moves** into `workspace/imports/processed/`. Side effect of import apply, not a journal-class mutation; provenance lives in `.workflow/state.db`.
- **Per-mutation git snapshots.** Snapshots stay lifespan-only, matching existing behavior.
- **Baseline parse-the-journal verifier on every write.** A reasonable future default for `verify`, but not part of this scope. Each op explicitly chooses its verifier (or `None`) until evidence motivates a default.
- **An in-memory file-storage abstraction.** No production need today; do not introduce a second adapter for hypothetical testability.
- **Multi-process or concurrent-mutation locking.** Ledger Flow is single-process; the writer assumes one mutation in flight at a time.
- **Manual transfer resolution feature.** The route, service, dialog, model, and test are removed in PR 3. The feature is explicitly *not* preserved across the deepening because the only design that fit the previous "discover-after" path resolution forced glob-all-journals pre-hashing, which is incompatible with the writer's `paths`-declared-up-front contract. Reintroducing this feature in future is allowed but must pre-resolve the target journal path *outside* the writer, with a real-world use case to justify it; DECISIONS §22 will record this constraint so future architecture reviews do not re-propose the previous design.
- **A writer-owned event for "verifier rejected the write."** Verifier failure is surfaced to the user as a 422 (HTTP) or raised exception; no `*.rejected.v1` event is emitted. Future telemetry could change this; not in scope here.

## Further Notes

- This PRD is candidate #1 from the architecture review at `/tmp/claude-1000/architecture-review-20260619-235830.html`. Five other candidates were surfaced; the journal-writer chokepoint was selected as the top recommendation because every other candidate (reconciliation cluster collapse, transactions query module, unknowns route deepening, shallow import-helper inline, transaction-categorization unification) composes against journal writes. Establishing the chokepoint first means subsequent deepenings describe operations instead of orchestrating them.
- **DECISIONS §22 entry to be added in PR 3**, capturing the manual-transfer-resolution removal. The load-bearing reason is the design constraint, not the usage frequency: any future reintroduction must pre-resolve the target path before entering the writer, because the writer requires `paths` to be declared up front.
- **`CONTEXT.md` is created lazily in PR 1** if it does not yet exist, with **journal mutation** as its first entry. This anchors the new term in the project's domain vocabulary and supports the `/improve-codebase-architecture`, `/grill-me`, and `/domain-modeling` skills.
- After PR 2 lands, candidate #2 from the architecture review (reconciliation cluster collapse) becomes substantially cheaper: the three reconciliation services share a writer, so the deepening can focus on the block-parsing and metadata-regex consolidation without re-litigating mutation semantics.
- Grilled design history is in the current Claude Code conversation transcript; the eight decisions above correspond one-to-one with Q1–Q8 from that session.
