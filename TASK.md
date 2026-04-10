# Current Task

## Title

Semantic undo with toast affordance

## Objective

Every journal mutation a user can perform from the UI is undoable for ~8 seconds via a toast that appears immediately after the action. Clicking Undo walks the event log backward, dispatches on the forward-event type to compute the inverse, verifies the relevant journal hasn't drifted since the event was written, applies the compensating action, and writes a new event linked back to the original via `compensates`. This is the trust deliverable that closes Feature 5: every action the app makes to a user's journal is reversible from the same screen, with explicit safety when external edits intervene.

Git is the escape hatch (already shipped). The event log is the audit trail (already shipped). This task wires undo on top of both.

## Scope

### Included

- New backend service `app/backend/services/undo_service.py` — dispatch table, hash verification, compensating-action implementations.
- New endpoint `POST /api/events/undo/{event_id}` — looks up the event, dispatches, returns a structured result.
- Mutating endpoints return the emitted `eventId` so the frontend can offer Undo.
- Compensating events emitted with `type: <forward_type>.compensated.v1` and `compensates: <forward_event_id>`.
- Drift handling: refuse-and-report when the target file's current hash differs from the event's `hash_after`. The user sees a clear "external edit detected" message.
- Frontend toast component (top-right, ~8s, single Undo button) shown after every mutating action.
- Toast queueing: the latest mutation replaces the visible toast (single-toast model).
- Idempotency: an event that has already been compensated cannot be compensated again.
- Backend tests for the undo dispatcher and each supported event type.
- Frontend wiring on the four single-row actions where the same gesture cannot reverse the change: delete, re-categorize, unmatch, manual entry create. **Status toggle deliberately excluded** — see §1 below.

### Explicitly Excluded

- A persistent operation history list / panel (deferred to a follow-up task).
- Undo for bulk events: `import.applied.v1`, `import.undone.v1`, `unknowns.applied.v1`, `rule.history_applied.v1`, `transfer_resolution.applied.v1`. These already have their own undo paths or modify many transactions at once; they need their own design.
- Undo of an undo (redo). The compensating event is final.
- Undo for `journal.external_edit_detected.v1` system events (not user-initiated, not undoable).
- Cross-file undo coordination beyond what the event's `journal_refs` already encode.
- Per-transaction partial undo within a single bulk event (out of scope for the supported event types — each supported type touches exactly one transaction).
- Multi-toast stacks. One visible toast at a time.
- Keyboard shortcut for undo (e.g., `Cmd+Z`). Defer.
- A "Last action" indicator outside the toast lifetime.

## System Behavior

### Inputs

- Mutating endpoint emits an event and returns `{ "eventId": "<uuidv7>", ... }`.
- Frontend shows a toast with the event's `summary` and an Undo button for ~8 seconds.
- User clicks Undo → `POST /api/events/undo/{event_id}`.
- Backend dispatches and returns a structured result.
- Frontend reloads the affected register and shows a confirmation or error toast.

### Logic

#### 1. Event return contract and toast eligibility

**Toast principle.** A toast undo is shown only when the same gesture that performed the action cannot reverse it. If a single click of the same control would already cycle back, a toast is noise on top of an existing affordance.

Every mutating endpoint that already calls `emit_event` must capture the returned `eventId` and include it in the response payload as `eventId`. If event emission fails (the existing `try/except` path), `eventId` is `null` — the action still succeeds but Undo is unavailable for it.

The endpoints in scope and their toast eligibility:

| Endpoint | Forward event type | Toast? | Reason |
|---|---|---|---|
| `POST /api/transactions/delete` | `transaction.deleted.v1` | **Yes** | Row is gone — no in-place reversal |
| `POST /api/transactions/recategorize` | `transaction.recategorized.v1` | **Yes** | Reversal requires walking the unknowns review queue |
| `POST /api/transactions/unmatch` | `transaction.unmatched.v1` | **Yes** | Multi-file change; reversal requires re-doing the unknowns match |
| `POST /api/transactions/create` | `manual_entry.created.v1` | **Yes** | Reversal requires locating the row and deleting it |
| `POST /api/transactions/toggle-status` | `transaction.status_toggled.v1` | **No** | The clearing indicator dot itself is the undo — clicking it again cycles back |

**Why status toggle is excluded:** During reconciliation, users click through 20-30 transactions in a row marking them bank-confirmed. A toast after each click would be hostile. The clearing indicator is already a direct, in-place toggle — the user has zero-friction reversal without ever leaving the row. The backend endpoint still emits `transaction.status_toggled.v1` (for the audit log and future bulk-undo), and the undo handler still implements it (so a future history-list UI can use it), but the frontend does not call `showUndoToast` after a status change.

The other event-emitting endpoints (`import.applied.v1`, `unknowns.applied.v1`, `rule.history_applied.v1`, `transfer_resolution.applied.v1`) are not wired in this task. They may still return `eventId` for forward compatibility, but the frontend does not show an Undo toast for them.

#### 2. `undo_service.py`

Public surface:

```python
class UndoOutcome(Enum):
    SUCCESS = "success"
    DRIFT = "drift"
    NOT_FOUND = "not_found"
    ALREADY_COMPENSATED = "already_compensated"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"

@dataclass(frozen=True)
class UndoResult:
    outcome: UndoOutcome
    message: str
    compensating_event_id: str | None
    forward_event_id: str

def undo_event(workspace_path: Path, event_id: str, *, config: AppConfig) -> UndoResult: ...
```

Internal flow:

1. **Locate the forward event.** Read `events.jsonl`, find the event whose `id == event_id`. If not found → `NOT_FOUND`.
2. **Idempotency check.** Scan forward (toward end of file) for any event whose `compensates == event_id`. If one exists → `ALREADY_COMPENSATED` with a reference to the existing compensating event.
3. **Dispatch table lookup.** Map the forward event's `type` to a compensating-action callable. If not in the table → `UNSUPPORTED`.
4. **Drift verification.** For each entry in the forward event's `journal_refs`, compute the current hash of `<workspace>/<path>`. If any current hash differs from the event's `hash_after`, return `DRIFT` with a message naming the file. (Drift means: something changed the file between the forward action and now, so the inverse may not be safe.)
5. **Apply the compensating action.** Each handler:
   - Reads the journal (and archive, if relevant), finds the affected transaction by `header_line` from the payload, and applies the inverse mutation.
   - Backs up via `backup_file()` first, with operation name `undo`.
   - Writes the file.
   - Returns the new file hashes for the new event's `journal_refs`.
   - Raises `UndoFailedError(message)` if the affected transaction cannot be found or the inverse cannot be applied cleanly.
6. **Emit the compensating event** with `type = "<forward_type>.compensated.v1"`, `compensates = forward_event_id`, `summary = f"Undid: {forward.summary}"`, and the same `payload` shape extended with `compensated_event_id: forward_event_id`. Hashes in `journal_refs` reflect the post-undo state.
7. **Return** `UndoResult(SUCCESS, message, compensating_event_id, forward_event_id)`.

If the handler raises `UndoFailedError`, return `FAILED` with the message — and do **not** emit a compensating event. The backup is left in place for manual recovery.

#### 3. Compensating-action handlers

Each handler is a pure function: `(workspace_path, config, forward_event) -> dict[str, str]` that returns the post-undo file hashes keyed by relative path.

**a. `transaction.deleted.v1` → restore the deleted block**

Payload available: `journal_path`, `header_line`, `deleted_block`.

1. Read the target journal.
2. Parse the date from `header_line` (first 10 chars).
3. Find the insertion index in the existing journal where the restored transaction's date is `<=` the next transaction's date. Match the existing date-ordered insert behavior used by unmatch.
4. Insert the `deleted_block` lines at the chosen position, with one blank line separator from neighbors.
5. Write and return the new hash.

Failure: if a transaction with the same `header_line` already exists in the file, raise `UndoFailedError("Transaction was re-created — refusing to duplicate")`.

**b. `transaction.recategorized.v1` → restore the previous account**

Payload available: `journal_path`, `header_line`, `previous_account`, `new_account`.

1. Read the journal, locate the unique transaction block by `header_line` (use the existing `_locate_header` + `_find_transaction_block` helpers — they need to move from `main.py` into a shared helper module, see §6).
2. Find the destination posting whose account == `new_account` (`Expenses:Unknown`). If multiple match, fail.
3. Use `rewrite_posting_account()` to rewrite back to `previous_account`.
4. Write and return the new hash.

Failure: header not found, or destination account no longer matches `new_account` → `UndoFailedError`.

**c. `transaction.status_toggled.v1` → toggle back to the previous status**

Payload available: `journal_path`, `header_line`, `previous_status`, `new_status`.

1. Read the journal, locate the header line.
2. Use `set_header_status()` to rewrite the line with `previous_status`.
3. Write and return the new hash.

Failure: header not found, or current status differs from the recorded `new_status` → `UndoFailedError`. (The drift check would normally catch this earlier via file hash; this is a per-transaction safety check for completeness.)

**d. `manual_entry.created.v1` → delete the created entry**

Payload available: `date`, `payee`, `amount`, `currency`, `destination_account`, `source_account`. The journal_refs entry tells us which file. There is no `header_line` field today.

1. Reconstruct the header line from `(date, payee)`. Manual entries are created with `unmarked` clearing status, so the header is `f"{date} {payee}"`.
2. Read the target journal, find the transaction block with that header AND a destination posting account matching `destination_account` AND a posting on `source_account` with the recorded amount. The combined match disambiguates from any other entry sharing the same payee + date.
3. Remove the block (with the same blank-line cleanup used in delete).
4. Write and return the new hash.

Failure: no unique block matches the criteria → `UndoFailedError("Could not locate the manual entry to undo")`.

> **Implementation note.** The disambiguation logic above is the only place this task adds complexity to the existing manual-entry payload shape. We deliberately don't change `manual_entry_service.create_manual_transaction` to also write `header_line` into the event payload, because the value is trivially derivable from `date + payee` for unmarked entries. If this turns out to be too brittle in practice, the follow-up is to enrich the payload, not to widen this task.

**e. `transaction.unmatched.v1` → re-create the match**

Payload available: `journal_path`, `archive_path`, `header_line`, `match_id`, `restored_manual_block`.

1. Read both the main journal and the archive (creating the archive file with the standard header if absent — same as `archive_service.archive_manual_entry`).
2. Locate the `header_line` in the main journal and find its block.
3. Re-stamp the imported transaction: insert `; :manual:` and `; match-id: {match_id}` lines after the header (matching the `unknowns_service` order: `:manual:` first, then `match-id`).
4. Rewrite the destination posting from `Expenses:Unknown` back to the matched manual entry's category (which we recover from `restored_manual_block` by parsing its non-source posting).
5. Find the restored manual entry in the main journal (it was inserted there by the original unmatch). It is identified by exact match on `restored_manual_block` lines starting from a matching header + payee. Remove that block.
6. Append the manual entry back to the archive via `archive_service.archive_manual_entry(archive_path, match_id, original_block_lines)`. The original block lines are derived from `restored_manual_block` (split on newlines).
7. Write both files and return their new hashes.

Failure modes:
- `restored_manual_block` cannot be parsed for its category → `UndoFailedError`.
- The imported transaction in the main journal cannot be located → `UndoFailedError`.
- The restored manual entry cannot be located in the main journal → `UndoFailedError`.

> **Risk callout.** Re-match is the most complex handler. The clean v1 boundary is: it works when no further edits happened between unmatch and undo. The drift check on the file hash provides this guarantee. If we discover edge cases during implementation, the right cut is to mark `transaction.unmatched.v1` as `UNSUPPORTED` for v1 rather than ship a half-working handler. Document the cut in the task close-out and ship the other four handlers.

#### 4. Endpoint

```
POST /api/events/undo/{event_id}
```

Response shape:

```json
{
  "outcome": "success" | "drift" | "not_found" | "already_compensated" | "unsupported" | "failed",
  "message": "Undid: Deleted transaction: Whole Foods on 2026-03-15",
  "compensatingEventId": "0192…" | null,
  "forwardEventId": "0192…"
}
```

HTTP status:
- `200` on `SUCCESS` and `ALREADY_COMPENSATED` (the latter is a no-op, not an error).
- `404` on `NOT_FOUND`.
- `409` on `DRIFT` (state conflict).
- `422` on `UNSUPPORTED` and `FAILED`.

#### 5. Frontend toast

A new shared component `app/frontend/src/lib/components/UndoToast.svelte`:

- Position: fixed, bottom-right, above content, `z-index: 50`.
- Width: `min(360px, calc(100vw - 2rem))`.
- Visual: white card, soft border, subtle shadow, finance-first copy.
- Single visible toast — newer toasts replace older ones.
- Auto-dismiss after 8000ms.
- Two slots: a `summary` line and an `Undo` button.
- After clicking Undo: show inline loading state on the button. On success, replace toast with "Restored" for 2s. On drift / failure, replace with the error message and a Dismiss button (no auto-dismiss).
- Cancellable: another mutation that arrives before auto-dismiss replaces the current toast.

A small global store `app/frontend/src/lib/undo-toast.ts`:

```ts
type ToastState = {
  eventId: string;
  summary: string;
  status: 'idle' | 'undoing' | 'restored' | 'error';
  message?: string;
};
export const undoToast = writable<ToastState | null>(null);
export function showUndoToast(eventId: string, summary: string) { ... }
export async function triggerUndo(refresh: () => Promise<void>) { ... }
```

The store owns the auto-dismiss timer and the lifecycle. `triggerUndo` accepts a callback so the caller (e.g., the transactions page) can refresh its own data after a successful undo. The store does not know about the register.

Mount the toast component once in the root layout (`+layout.svelte`) so it appears across routes.

#### 6. Helper extraction

`_locate_header` and `_find_transaction_block` are currently private helpers in `main.py`. Move them to a new module `app/backend/services/journal_block_service.py` so the undo service and the existing transaction-action endpoints can share them. Update `main.py` to import from the new module. This is a pure refactor — no behavior change. Verify by running the existing tests.

> **Why this matters.** The undo service needs the same block-finding logic. Duplicating it would split the source of truth on what counts as a "transaction block." Extracting now keeps both call sites correct.

### Outputs

- New file `app/backend/services/undo_service.py` (~300 lines).
- New file `app/backend/services/journal_block_service.py` (~40 lines).
- New endpoint registered in `main.py`.
- Five mutation endpoints return `eventId` (status toggle included for forward compat).
- New frontend store `app/frontend/src/lib/undo-toast.ts`.
- New frontend component `app/frontend/src/lib/components/UndoToast.svelte`.
- Toast mounted in `+layout.svelte`.
- Four mutation call sites in `transactions/+page.svelte` call `showUndoToast` with the event id and summary: delete, recategorize, unmatch, create. Status toggle does **not** call `showUndoToast`.
- New backend test file `app/backend/tests/test_undo_service.py`.
- Compensating events appear in `events.jsonl` linked via `compensates`.

## System Invariants

- Journals remain canonical state. Undo writes journals; the event log records the change. No undo path skips the journal write.
- The compensating event is written **after** the journal mutation succeeds, never before. If the journal write fails, no compensating event exists, and the user sees a clear failure message.
- Undo always backs up the affected journal (`backup_file(path, "undo")`) before writing.
- A forward event can be compensated at most once. The idempotency check is authoritative.
- Drift detection is preventative for undo: if any ref'd file has changed since the forward event, undo refuses without modifying anything.
- The event log itself is never rewritten or trimmed by undo. Compensating events are appended.
- An undone event remains in the log — undo creates a new linked event, it does not delete the forward event.
- Git snapshots are unaffected. They continue to capture the workspace independently.
- The toast is purely UI. Undo correctness does not depend on whether the toast was shown or dismissed.

## States

- **Default**: no toast visible. Register behaves normally.
- **Toast visible**: bottom-right card with summary + Undo. Auto-dismiss timer running.
- **Toast undoing**: Undo button shows loading state, disabled. Other actions still work.
- **Toast restored**: success card with "Restored" message, 2s, then dismiss.
- **Toast drift error**: red-tinted card with "External edit detected — undo unavailable" + Dismiss. No auto-dismiss.
- **Toast failed**: red-tinted card with the failure message + Dismiss. No auto-dismiss.
- **Toast already-compensated**: shouldn't be reachable from the toast (the toast disappears after one click), but if it does occur (e.g., double-click), display "Already undone" briefly and dismiss.
- **Toast not-found**: same handling as failed.

## Edge Cases

- **Mutation A, mutation B, click Undo.** Toast shows for B (the latest). Undo undoes B. The event for A is still in the log but no longer surfaced via toast. This is intentional — multi-step undo is in the deferred history list.
- **Two mutations on the same transaction in quick succession.** A: re-categorize. B: delete. Click Undo. Undoes B (restores deleted block with the post-recategorize state). Correct.
- **Drift between mutation and undo (external edit).** Drift check fails. Toast shows "External edit detected — refusing to undo." User can resolve manually.
- **Drift between mutation and undo (in-app edit).** Same as above — the in-app edit changes the file hash. The user sees the message and can undo the more recent action first (via the deferred history list — for v1, they cannot, and the message tells them why).
- **Server restart between mutation and undo.** The event log persists across restarts. The toast does not. After a restart there is no toast affordance — the user must wait for the history list (deferred). Acceptable for v1.
- **Undo of `transaction.unmatched.v1` when the imported transaction has been re-categorized since.** Drift check triggers. Refuses cleanly.
- **Undo of `manual_entry.created.v1` when the entry was matched after creation.** The match would change the file hash → drift refuses. Correct: the user should undo the match first, then the creation.
- **Undo of `transaction.deleted.v1` when a new transaction with the same header was added.** The handler catches this in step 5 of (a) and refuses with "Transaction was re-created — refusing to duplicate."
- **Event id from a different workspace.** The event log is workspace-scoped. The `_require_workspace_config()` call resolves the active workspace; the lookup happens in that workspace's `events.jsonl`. An id from a different workspace returns `NOT_FOUND`.
- **Malformed event id.** Treated as not found. No 500.
- **`events.jsonl` corruption mid-line.** Already handled by the event log scanner — it skips bad lines and continues.

## Failure Behavior

- **Journal write fails mid-undo**: backup file remains. No compensating event written. User sees "Undo failed" with a generic message and the backup path in logs.
- **Compensating event emission fails**: the journal mutation has already succeeded. Log the error but return `SUCCESS` to the caller. The undo is durable in the journal; the link is best-effort. (The next undo of the same event would be blocked by the journal hash mismatch, which is the correct behavior.)
- **Drift detected**: refuse, no journal change, no event.
- **Backup creation fails**: refuse, no journal change.
- **Frontend network error during undo**: toast shows "Undo failed — try again." Does not retry automatically.

## Regression Risks

- **Mutation endpoints now return `eventId`.** This is an additive payload change. Existing frontend callers that ignore unknown fields are unaffected. Verify by reading every existing call site of the five endpoints (delete, recategorize, unmatch, toggle-status, create).
- **`_locate_header` / `_find_transaction_block` move from `main.py` to `journal_block_service.py`.** Pure refactor. The existing transaction action tests must continue to pass without modification.
- **Toast component mounted in root layout.** Must not interfere with existing dialogs (manual resolution modal, confirm-delete, confirm-unmatch). Z-index hierarchy: confirm dialogs at 31, toast at 50. The toast appears above dialogs intentionally (e.g., if a confirm dialog is open and another tab triggers an action — unlikely, but the layering is well-defined).
- **Undo of unmatch is the most complex handler.** If it ships broken, it can corrupt the archive ↔ main journal link. Mitigation: comprehensive tests for the unmatch undo path that verify both files end up in the exact pre-unmatch state, byte-for-byte where possible. If the tests are flaky, mark unsupported and ship the other four.
- **Manual entry undo relies on header reconstruction from `date + payee`.** If a future change adds a clearing flag to manual entries, the reconstruction breaks. Mitigation: add an explicit assertion in the handler that the located header line starts with `f"{date} {payee}"` and contains no `*`/`!` flag. If this becomes a real concern, enrich the payload in a follow-up.
- **Hash check is per-file, not per-transaction.** Any unrelated edit to the journal (e.g., the user adds a new transaction in another tool) blocks undo. This is a deliberate trust choice — false-positive refusals are safer than false-positive applies. Document in the failure-message copy.

## Acceptance Criteria

- After delete, re-categorize, unmatch, and create mutations, a toast appears in the bottom-right with a summary and Undo button.
- After a status toggle, **no toast appears**. The clearing indicator remains the only undo affordance for that action.
- Clicking Undo within 8s reverses the mutation and reloads the register.
- Undo of delete restores the exact transaction block at the correct date-ordered position.
- Undo of re-categorize restores the previous category account on the correct transaction.
- Undo of toggle-status (via the backend handler — exercised in tests, not surfaced in the UI) restores the previous clearing flag.
- Undo of create deletes the created manual entry (and only that entry).
- Undo of unmatch restores both the imported transaction's match tags and the archived manual entry, byte-equivalent to the pre-unmatch state.
- Compensating events appear in `events.jsonl` with `compensates` linking to the forward event.
- A second undo of the same event returns `ALREADY_COMPENSATED` and does not modify the journal.
- An undo where the journal hash has changed since the forward event returns `DRIFT` and modifies nothing.
- Toast auto-dismisses after 8s. A new mutation replaces the visible toast.
- The four other mutating endpoints (`import.applied.v1`, `unknowns.applied.v1`, `rule.history_applied.v1`, `transfer_resolution.applied.v1`) are not affected by this change. They continue to work and emit events as before. They simply have no toast affordance.
- `uv run pytest -q` passes in `app/backend`.
- `pnpm check` passes in `app/frontend`.

## Proposed Sequence

1. **Refactor: extract `journal_block_service.py`.** Move `_locate_header`, `_find_transaction_block`, and the preceding-blank-line cleanup helper into the new module. Update `main.py` imports. Run existing tests — no failures expected. Behavior-preserving step.

2. **Backend: mutation endpoints return `eventId`.** Capture the return value of `emit_event` in each of the five wired endpoints. Add `eventId` to the response dict. Update existing tests if any assert on the response shape (none should — they're at the service layer).

3. **Backend: build `undo_service.py` skeleton.** `UndoOutcome`, `UndoResult`, `UndoFailedError`, `undo_event()` with the lookup, idempotency, dispatch, and drift-check skeleton. Empty handler stubs. Test: `UNSUPPORTED` for unknown event types, `NOT_FOUND` for missing ids, `ALREADY_COMPENSATED` when a `compensates` link already exists, `DRIFT` when file hash differs.

4. **Backend: handler for `transaction.deleted.v1`.** Implement and test: round-trip (delete + undo restores the block exactly), failure on duplicate, drift refusal.

5. **Backend: handler for `transaction.recategorized.v1`.** Implement and test: round-trip restores the previous account, failure when destination changed.

6. **Backend: handler for `transaction.status_toggled.v1`.** Implement and test: round-trip, failure when current status differs.

7. **Backend: handler for `manual_entry.created.v1`.** Implement and test: round-trip removes the created entry, failure when ambiguous (e.g., two entries with same date + payee + amount + accounts → fall back to refusal).

8. **Backend: handler for `transaction.unmatched.v1`.** Implement and test: full round-trip from match → unmatch → undo unmatch, verifying main journal and archive both return to their pre-unmatch state. If tests reveal edge cases that can't be cleanly handled, mark unsupported with a clear comment and skip the handler.

9. **Backend: register `POST /api/events/undo/{event_id}` in `main.py`.** Wire response codes from `UndoOutcome`. Integration test: end-to-end via the FastAPI test client with a real workspace fixture.

10. **Frontend: toast store and component.** Build `undo-toast.ts` and `UndoToast.svelte`. Mount in `+layout.svelte`. Visual sanity check.

11. **Frontend: wire the four mutation call sites.** Update callers in `transactions/+page.svelte` to capture `eventId` from the response and call `showUndoToast` for delete, recategorize, unmatch, and create. Manual entry create is in the "Add transaction" panel. **Do not** call `showUndoToast` after `toggleClearingStatus` — leave that flow exactly as it is today.

12. **Manual verification.** Make a manual entry, see the toast, click Undo, verify it's gone. Delete a transaction, undo, verify it's back. Re-categorize, undo, verify. Toggle status — **verify no toast appears** and the clearing indicator still cycles correctly. Match a manual entry via unknowns review, then unmatch via the row menu, then undo the unmatch — verify both files are exact.

13. **Run full test suite.** `uv run pytest -q` and `pnpm check`. Update `ROADMAP.md` to mark 5d shipped and 5e active, then mark 5e shipped on close. Update `DECISIONS.md` only if the implementation forced a decision the original §12 didn't capture.

## Definition of Done

- Five mutation actions are undoable from the toast within 8s of the action.
- Undo preserves canonical journal state. Compensating events link forward and backward.
- Drift refusal works correctly: the user gets a clear message, no journal changes, no compensating event.
- Idempotency works: a forward event can be compensated at most once.
- Backups are created on every undo path. Failures leave the backup in place.
- All five handlers have unit tests covering happy path + drift + per-handler failure modes.
- Integration test exercises the endpoint via the FastAPI test client.
- Frontend toast appears in the bottom-right, dismisses after 8s, replaces older toasts, shows clear errors.
- All existing tests pass. New tests cover the undo service.
- Feature 5 (event-sourced undo) is shipped end-to-end.

## UX Notes

- Toast copy is finance-first, never technical. The four toast-eligible actions:
  - "Removed Whole Foods on Mar 15 · Undo"
  - "Reset category on Whole Foods · Undo"
  - "Added Whole Foods · Undo"
  - "Undid match for Whole Foods · Undo"
- **No toast** for status toggle. The clearing indicator's color change is the entire feedback.
- After a successful undo: "Restored" with a brief checkmark, then dismiss.
- After a drift refusal: "We can't undo this — the file changed since the action. Open the journal to investigate." (No technical hash language.)
- After a generic failure: "Couldn't undo — please try again."
- Toast button: text-only "Undo", with focus ring for keyboard users. The toast itself is not focusable; only the button is.
- Toast is dismissable by pressing Escape when focused, or by clicking outside (no — clicking outside would conflict with normal interaction; just rely on auto-dismiss or the Dismiss button on error states).
- Color: neutral white card for normal/restored states, light red tint for drift/failed states. Never use the brand color for error states.

## Out of Scope

- Persistent operation history list / panel (deferred).
- Undo for bulk events (`import.*`, `unknowns.*`, `rule.*`, `transfer_resolution.*`).
- Redo. The compensating event is final.
- Keyboard shortcut (`Cmd+Z`).
- Multi-toast stack.
- Toast for non-mutating actions.
- Per-transaction partial undo of bulk events.
- Cross-workspace undo.
- Surfacing `journal.external_edit_detected.v1` events in the UI (separate trust feature).
