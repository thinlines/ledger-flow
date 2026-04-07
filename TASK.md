# Current Task

## Title

Append-only event log with drift detection for all journal mutations

## Objective

Every journal mutation emits a structured event to `workspace/events.jsonl`. Events form the causal record of what the app did and why, enabling future undo (Feature 5e). Pre-mutation and startup hash checks detect external edits and record them as marker events. Journals remain canonical state; events are advisory. See DECISIONS.md §12.

## Scope

### Included

- New service: `app/backend/services/event_log_service.py` — event writer, file hashing, drift detection, in-memory hash cache.
- Event envelope: UUIDv7 `id`, ISO 8601 `ts`, `actor`, `type`, `summary`, `payload` (type-specific dict), `journal_refs` (list of `{path, hash_before, hash_after}`), nullable `compensates` link.
- Seven event types for the seven mutating endpoints, plus one drift marker type.
- Pre-mutation drift check in each of the 7 mutating route handlers.
- Startup drift check in the FastAPI lifespan handler.
- Unit tests for event log service (write, read-back, hash, drift detection, cache).
- Integration tests for event emission from each endpoint.

### Explicitly Excluded

- Compensating event logic and undo dispatcher (Feature 5e).
- Event-based projections, indexes, aggregations, or query endpoints.
- UI for event history or undo affordances (Feature 5e).
- Event file rotation, compaction, or size caps.
- Multi-user sync or merge conflict handling on `events.jsonl`.
- Git snapshot commits (Feature 5c).
- Transaction actions menu (Feature 5d).
- Changes to existing mutation logic — event emission wraps existing behavior, does not alter it.

## System Behavior

### Inputs

- Any of the 7 mutating API calls (see Logic §2 for the full list).
- Server startup (lifespan handler).

### Logic

**1. Event envelope schema**

Each line in `workspace/events.jsonl` is a single JSON object:

```json
{
  "id": "019d615b-8396-72ce-9618-ac67e6f5db32",
  "ts": "2026-04-05T14:30:22.123456Z",
  "actor": "user",
  "type": "import.applied.v1",
  "summary": "Imported 12 transactions from Chase Checking",
  "payload": { },
  "journal_refs": [
    {
      "path": "journals/2026.journal",
      "hash_before": "sha256:abc123...",
      "hash_after": "sha256:def456..."
    }
  ],
  "compensates": null
}
```

Field rules:
- `id`: `str(uuid.uuid7())`. Native Python 3.14.
- `ts`: `datetime.now(timezone.utc).isoformat()`. Always UTC.
- `actor`: `"user"` for mutation endpoints, `"system"` for drift detection events.
- `type`: dotted event type string with `.v1` suffix.
- `summary`: human-readable one-liner for future UI display.
- `payload`: type-specific dict (see §3 below). Must be JSON-serializable.
- `journal_refs`: list of workspace-relative paths with SHA-256 hashes of file content immediately before and after the mutation. Only canonical `workspace/` files — never `.workflow/` files. Empty list for drift events (drift events carry the hash details in their payload).
- `compensates`: nullable UUIDv7 string — populated by future undo events (Feature 5e). Always `null` for forward events emitted in this task.

**2. Mutating endpoints and their event types**

| # | Endpoint | Route handler | Event type | Files tracked in `journal_refs` |
|---|----------|---------------|------------|---------------------------------|
| 1 | `POST /api/transactions/create` | `main.py:411` `transactions_create` | `manual_entry.created.v1` | year journal |
| 2 | `POST /api/transactions/toggle-status` | `main.py:463` `transactions_toggle_status` | `transaction.status_toggled.v1` | target journal |
| 3 | `POST /api/unknowns/apply` | `main.py:971` `unknown_apply` | `unknowns.applied.v1` | year journal, `accounts.dat`, `archived-manual.journal` (if match occurred) |
| 4 | `POST /api/import/apply` | `main.py:856` `import_apply` | `import.applied.v1` | target journal |
| 5 | `POST /api/import/undo` | `main.py:913` `import_undo` | `import.undone.v1` | target journal |
| 6 | `POST /api/rules/history/apply` | `main.py:1097` `rules_history_apply` | `rule.history_applied.v1` | year journal |
| 7 | `POST /api/transactions/manual-transfer-resolution/apply` | `main.py:447` `transactions_manual_transfer_resolution_apply` | `transfer_resolution.applied.v1` | year journal |

Plus the drift marker:

| | Trigger | Event type |
|---|---------|------------|
| 8 | Pre-mutation check or startup check | `journal.external_edit_detected.v1` |

**3. Payload definitions per event type**

Each payload captures enough to describe the operation for audit and to support future compensating-event construction (Feature 5e). Keep payloads minimal — include what's needed, not everything available.

**`manual_entry.created.v1`**
```json
{
  "date": "2026-03-15",
  "payee": "Whole Foods Market",
  "amount": "50.00",
  "currency": "USD",
  "destination_account": "Expenses:Groceries",
  "source_account": "Assets:Checking:Chase"
}
```

**`transaction.status_toggled.v1`**
```json
{
  "journal_path": "journals/2026.journal",
  "header_line": "2026-03-15 * Whole Foods Market",
  "previous_status": "unmarked",
  "new_status": "cleared"
}
```

**`unknowns.applied.v1`**
```json
{
  "journal_path": "journals/2026.journal",
  "mappings_applied": 5,
  "matches_applied": 2,
  "match_ids": ["uuid1", "uuid2"],
  "warnings": []
}
```

**`import.applied.v1`**
```json
{
  "journal_path": "journals/2026.journal",
  "source_file": "chase_checking_2026-03.csv",
  "account_id": "chase-checking",
  "transactions_added": 12,
  "duplicates_skipped": 3,
  "conflicts": 0,
  "history_id": "abc123"
}
```

**`import.undone.v1`**
```json
{
  "journal_path": "journals/2026.journal",
  "history_id": "abc123",
  "transactions_removed": 12
}
```

**`rule.history_applied.v1`**
```json
{
  "journal_path": "journals/2026.journal",
  "transactions_updated": 8,
  "selected_candidate_count": 8,
  "warnings": []
}
```

**`transfer_resolution.applied.v1`**
```json
{
  "journal_path": "journals/2026.journal",
  "date": "2026-03-15",
  "payee": "Transfer",
  "source_account": "Assets:Checking",
  "destination_account": "Assets:Savings",
  "amount": "500.00"
}
```

**`journal.external_edit_detected.v1`**
```json
{
  "journal_path": "journals/2026.journal",
  "expected_hash": "sha256:abc123...",
  "actual_hash": "sha256:def456...",
  "trigger": "pre_mutation"
}
```
`trigger` is `"pre_mutation"` or `"startup"`.

**4. File hash computation**

`hash_file(path: Path) -> str`: read file as bytes, compute SHA-256, return `"sha256:" + hexdigest`. If file does not exist, return `"sha256:none"` (sentinel for file-not-yet-created state, e.g., first import into a new year journal).

Reuse the existing `hashlib.sha256` pattern from `import_identity_service.py`. Operate on raw bytes (`path.read_bytes()`), not decoded text, for exact round-trip fidelity.

**5. In-memory hash cache**

Module-level `_hash_cache: dict[str, str]` mapping absolute path strings to their last-known hash. Populated on startup drift check (see §7). Updated after each event emission. Purpose: avoid scanning `events.jsonl` to find the last known hash for a file. If the cache misses (first mutation after cold start without startup check), fall back to scanning the log backward.

The cache is an optimization, not a persistence layer. If lost (process restart), it is rebuilt from the startup drift check or on first access.

**6. Pre-mutation drift check**

Before each of the 7 mutations, for each journal file that will be written:

1. Compute `current_hash = hash_file(path)`.
2. Look up `expected_hash` from `_hash_cache[str(path)]`. If not in cache, scan `events.jsonl` backward for the most recent event whose `journal_refs` includes this path, and use its `hash_after`. If no event found, the file predates the event log — skip drift check (no baseline).
3. If `expected_hash` exists and `current_hash != expected_hash`: emit a `journal.external_edit_detected.v1` event and update the cache to `current_hash`.
4. Update `_hash_cache[str(path)] = current_hash` (even if no drift — ensures cache is current for the upcoming mutation's `hash_before`).

Return the `current_hash` so the caller can use it as `hash_before` in the mutation event's `journal_refs`.

**7. Startup drift check**

In the FastAPI lifespan handler, after existing initialization (`stages.cleanup_old`, `import_index.ensure_schema`):

1. Attempt to load workspace config. If no workspace is configured yet, skip (nothing to check).
2. Glob `workspace/journals/*.journal` plus `workspace/journals/archived-manual.journal` (if exists).
3. For each file, compute current hash and compare to last known `hash_after` from the event log (scan backward). Emit `journal.external_edit_detected.v1` for each drifted file.
4. Populate `_hash_cache` with current hashes for all discovered journal files.

If `events.jsonl` does not exist yet, skip all drift checks (no baseline). This is the initial state — the first mutation event will establish the baseline.

**8. Event writer**

```python
def emit_event(
    workspace_path: Path,
    *,
    event_type: str,
    summary: str,
    payload: dict,
    journal_refs: list[dict],
    actor: str = "user",
    compensates: str | None = None,
) -> str:
```

1. Build the event dict per the envelope schema (§1).
2. Serialize to a single JSON line (`json.dumps(event, separators=(",", ":"))` — compact, no pretty-print).
3. Append to `workspace/events.jsonl` via `open(path, "a", encoding="utf-8")` + `write(line + "\n")`.
4. Update `_hash_cache` entries for each `journal_refs` item using its `hash_after`.
5. Return the event `id`.

**9. Integration pattern in route handlers**

Each of the 7 route handlers follows this pattern (illustrated for `import_apply`):

```python
# Before mutation:
events_path = config.workspace_path  # or derive workspace root
journal_path = Path(stage["targetJournalPath"])
hash_before = check_drift_and_get_hash(events_path, journal_path)

# Existing mutation call:
journal_path, appended_count, ... = apply_import(config, stage)

# After mutation:
hash_after = hash_file(journal_path)
emit_event(
    events_path,
    event_type="import.applied.v1",
    summary=f"Imported {appended_count} transactions from ...",
    payload={...},
    journal_refs=[{"path": _rel(journal_path, events_path), "hash_before": hash_before, "hash_after": hash_after}],
)
```

For endpoints that write multiple files (unknowns apply), compute `hash_before` for each file before the mutation and `hash_after` for each file after, producing multiple entries in `journal_refs`.

**10. Event emission failure behavior**

Event emission is advisory — it must NOT block the mutation. If `emit_event` raises (disk full, permissions, I/O error):
- Log the error with full context (`logger.error`).
- Continue — the journal write already succeeded, and the user's data is safe.
- The in-memory cache may be stale; the next startup drift check will detect and recover the hash chain.

Drift check failures (reading `events.jsonl`) follow the same rule: log and skip, never block the mutation.

This matches the precedence rule from DECISIONS.md §12: journals > events > git.

### Outputs

- `workspace/events.jsonl` grows by one line per mutation (plus optional drift events).
- Mutation endpoints return the same response payloads as before — no API contract change.
- No UI-visible change.

## System Invariants

- `events.jsonl` is append-only within the app. No rewrites, no deletions, no compaction.
- Event emission never blocks or fails a journal mutation. Journals are canonical; events are advisory.
- Every event has a unique UUIDv7 `id` that sorts chronologically.
- `journal_refs` paths are always relative to the workspace root (portable across machines).
- `hash_before` and `hash_after` in `journal_refs` reflect the exact file content immediately before and after the mutation (byte-level SHA-256).
- Drift events are informational — they do not modify journals or prevent mutations.
- The event log file (`events.jsonl`) is never `include`d by ledger CLI (it's not a `.journal` file).

## States

- **No `events.jsonl` yet**: first mutation creates the file. No startup drift check (no baseline). First event establishes the hash chain.
- **`events.jsonl` exists, workspace cold-started**: startup drift check runs, populates hash cache, emits drift events if any files changed while the server was down.
- **Normal operation**: each mutation emits one event. Drift checks pass silently (hashes match). Cache is warm.
- **External edit detected**: drift event emitted, hash cache updated to current state, mutation proceeds normally.
- **Event emission fails**: logged, mutation succeeds, cache may be stale. Next startup recovers the chain.
- **No workspace configured yet**: startup drift check skipped entirely. First workspace bootstrap does not emit events (workspace creation is not a journal mutation).

## Edge Cases

- **First-ever mutation in the project**: `events.jsonl` doesn't exist, drift check is skipped (no baseline), mutation proceeds, event file is created with the first event line.
- **Journal file doesn't exist yet** (first import into a new year): `hash_file` returns `"sha256:none"` for `hash_before`. After mutation, `hash_after` reflects the new file. No drift check against a nonexistent baseline.
- **Multiple files mutated in one endpoint** (unknowns apply): each file gets its own entry in `journal_refs` with independent `hash_before`/`hash_after`. Drift is checked per-file.
- **Concurrent requests**: same concurrency caveat as existing journal writes — `events.jsonl` append uses `open("a")` + `write()`. Single-process FastAPI with synchronous handlers means no true concurrency today, but the append pattern is safe for future use.
- **Large `events.jsonl`**: backward scan for last known hash is O(n). Mitigated by the in-memory cache (constant-time lookup). Cold-start scan reads the full file once. 10,000 events ≈ 5–10 MB — acceptable.
- **User manually edits `events.jsonl`**: the app does not validate log integrity. A corrupted line will cause a JSON parse error during backward scan — skip that line and continue. Log a warning.
- **`events.jsonl` deleted while server is running**: next `emit_event` recreates the file. Hash cache is still warm, so no data loss for ongoing drift detection. On next restart, startup check treats it as no-baseline (skip).

## Failure Behavior

- **Event file write fails** (I/O error, permissions, disk full): log error, do NOT fail the mutation. Return normally. The event is lost; the hash chain has a gap. Next startup drift check recovers by detecting the hash mismatch.
- **Event file read fails** (corrupt JSON, permissions): log warning, skip drift check for that file. Proceed with mutation. Do not surface an error to the user.
- **Hash computation fails** (file disappeared between check and mutation): log warning, emit event with `"sha256:none"` for that ref. Not a blocking error.
- **Startup drift check fails** (no workspace, corrupt config): skip silently. The lifespan handler must not crash the server.

## Regression Risks

- **Import/apply performance**: adding `hash_file()` reads each journal file twice (once for hash_before, once for hash_after). Journal files are typically <1 MB; two extra reads are negligible. Do not read the file a third time — the mutation itself already reads it.
- **Existing test assertions**: route handlers return the same response shapes. No test should break from event emission alone. If a test patches file I/O or freezes time, ensure `emit_event` doesn't interfere (it writes to a different file path).
- **`events.jsonl` in workspace glob**: existing code globs `workspace/journals/*.journal` — `events.jsonl` is in `workspace/` root, not `journals/`, so it won't be picked up. Verify no broad `workspace/**` glob exists that could load it.
- **Backup file naming**: `backup_service.backup_file` creates `.bak` files in the journal directory. Event log writes to `workspace/events.jsonl`. No naming collision.
- **Toggle-status endpoint**: this endpoint receives `journalPath` from the client as an absolute path. Derive the workspace-relative path for `journal_refs` by stripping the workspace root prefix. Handle gracefully if the path is outside the workspace (log warning, use absolute path as fallback).

## Acceptance Criteria

- After any of the 7 mutating API calls, `workspace/events.jsonl` contains a new line with the correct event type, valid UUIDv7 `id`, UTC timestamp, and populated `journal_refs`.
- `journal_refs[].hash_before` matches the SHA-256 of the file content before the mutation; `hash_after` matches after.
- `journal_refs[].path` is workspace-relative (e.g., `journals/2026.journal`, not an absolute path).
- When a journal file is edited externally between mutations, a `journal.external_edit_detected.v1` event is emitted before the next mutation event for that file.
- On server startup with a modified journal, a `journal.external_edit_detected.v1` event with `"trigger": "startup"` is emitted.
- Event emission failure does not cause any mutation endpoint to return an error.
- Each line in `events.jsonl` is valid JSON parseable by `json.loads()`.
- `events.jsonl` is never read by `ledger` CLI (not a journal file, not `include`d anywhere).
- `uv run pytest -q` passes in `app/backend`.
- `pnpm check` passes in `app/frontend` (no frontend change, but verify API contract intact).
- Existing tests for all 7 mutation endpoints continue to pass without modification (event emission is transparent).

## Proposed Sequence

1. **Create `event_log_service.py`** with: `hash_file()`, `emit_event()`, `get_last_known_hash()` (backward JSONL scan), module-level `_hash_cache`, `check_drift()` (per-file drift check + cache update, returns `hash_before`), `check_startup_drift()` (all journals). Unit tests: event write creates file, second write appends, hash computation is stable, drift detected when hash mismatches, drift skipped when no baseline, corrupt JSONL line handled gracefully, cache populated after emit.

2. **Integrate startup drift check** into the FastAPI lifespan in `main.py`. After `import_index.ensure_schema()`, call `check_startup_drift(workspace_path)` wrapped in try/except (never crash the server). Test: start server with modified journal → drift event in log; start server with no workspace → no crash.

3. **Integrate with simple single-journal endpoints** — `transactions_create` (endpoint 1), `transactions_toggle_status` (endpoint 2), `transactions_manual_transfer_resolution_apply` (endpoint 7). Each gets: `hash_before = check_drift(...)` before the mutation, `hash_after = hash_file(...)` + `emit_event(...)` after. Tests: call endpoint → event appears in log with correct type and hashes.

4. **Integrate with `rules_history_apply`** (endpoint 6). Same pattern as step 3 but with stage-based flow. Test: apply rule history → event with correct `journal_refs`.

5. **Integrate with `import_apply`** (endpoint 4). Compute `hash_before` before `apply_import()` call. Build payload from the stage and result. Test: import apply → event with transaction count, history ID.

6. **Integrate with `import_undo`** (endpoint 5). The `undo_import` service already resolves the journal path internally — compute `hash_before` before the call using the same path resolution. Test: undo → event with history ID and removal count.

7. **Integrate with `unknown_apply`** (endpoint 3). Most complex: tracks journal, `accounts.dat`, and optionally `archived-manual.journal`. Compute `hash_before` for all three files before `apply_unknown_mappings()`. Build `journal_refs` with entries for each file that was actually modified. Test: unknowns apply with match → event with 3 `journal_refs` entries including archive; unknowns apply without match → event with 2 entries (no archive ref).

8. **Add drift integration test**: modify a journal file directly (simulating external edit), then call a mutation endpoint → verify drift event appears before the mutation event in the log.

9. **Manual verification**: run the app, perform an import → review → apply cycle, inspect `events.jsonl`, verify event types and hash chains are correct.

## Definition of Done

- Every journal mutation produces a structured event in `workspace/events.jsonl` with correct envelope, type, payload, and file hashes.
- External edits to journal files are detected and recorded — both at startup and before mutations.
- Event emission is transparent to existing behavior: no API changes, no mutation failures from event errors.
- The hash chain in `journal_refs` is correct: `hash_after` of event N equals `hash_before` of event N+1 for the same file (assuming no external edits between them).
- All existing tests pass: `uv run pytest -q` and `pnpm check`.
- New tests cover: event writing, hash computation, drift detection, per-endpoint emission, emission failure resilience.
- No UI-visible change.

## Out of Scope

- Undo logic, compensating events, or inverse-action dispatch (Feature 5e).
- API endpoints for reading or querying the event log.
- Event log UI (history list, undo button, toast).
- Git snapshot commits (Feature 5c).
- Transaction actions menu (Feature 5d).
- Event file rotation, archival, or size management.
- `accounts.dat` or rule-file drift detection (only journal files are tracked for drift — `accounts.dat` is tracked in `journal_refs` when mutated but not drift-checked at startup).
