# Semantic Undo Coverage Completion (5e)

## Objective

Close out Feature 5 by filling the two remaining gaps in semantic undo: give notes-update events a real undo handler, and add a lightweight operation history list so users can reach events older than the active toast.

## Already Shipped (Confirmed Against Spec)

The bulk of 5e is already in the codebase. Re-confirmed against [`ROADMAP.md`](ROADMAP.md) §5e during PM intake:

- `POST /api/events/undo/{event_id}` endpoint at [main.py:1104](app/backend/main.py#L1104) — dispatches via the `_HANDLERS` table, returns structured outcome (`success` / `drift` / `not_found` / `already_compensated` / `unsupported` / `failed`).
- Per-file drift verification before applying any compensating action (see `undo_event` in [undo_service.py:108-155](app/backend/services/undo_service.py#L108-L155)).
- Idempotency guard via `_is_compensated` — re-running undo for the same event returns `ALREADY_COMPENSATED` with the existing compensating-event id.
- Compensating events emitted with `compensates: <forward_id>` linkage and `<event_type>.compensated.v1` typing; the forward event is never rewritten.
- Handlers landed for: `transaction.deleted.v1`, `transaction.recategorized.v1`, `transaction.status_toggled.v1`, `manual_entry.created.v1`, `transaction.unmatched.v1`.
- Toast component ([UndoToast.svelte](app/frontend/src/lib/components/UndoToast.svelte)) and store ([undo-toast.ts](app/frontend/src/lib/undo-toast.ts)) — slide-in from bottom-right, 8s auto-dismiss, `Undo` button → `Undoing…` → `Restored` (2s) or error state. Mounted in [+layout.svelte:203](app/frontend/src/routes/+layout.svelte#L203) so it survives route changes.
- Toast wired on: delete, reset-category, recategorize, unmatch, and manual-entry-create. See [transactionActions.ts](app/frontend/src/lib/transactions/transactionActions.ts) and [transactions/+page.svelte:235](app/frontend/src/routes/transactions/+page.svelte#L235).
- Tests in [test_undo_service.py](app/backend/tests/test_undo_service.py): not-found, unsupported, already-compensated, drift, round-trip restore for each handler, and compensating-event emission.
- Linearity ("most recent → earliest") is enforced implicitly via per-file hash drift: an older event in the same file fails drift if a newer one ran after it.

The "partial-undo report" language in the ROADMAP is N/A for the current handler set — every handler today mutates exactly one transaction, so any drift fails the whole undo. If a future handler touches multiple transactions in a single event, that's where partial-undo would matter; not in scope here.

## Scope

### Included

1. **Notes-update undo** — add `_undo_transaction_notes_updated` handler with the metadata it needs, and surface the toast on save.
2. **Operation history list** — a small, scoped UI surface listing recent events with an Undo button per row. Reaches events older than the active 8s toast.
3. **Backend events listing endpoint** — `GET /api/events` returns the latest N events with their type, summary, timestamp, and compensation status, so the history UI has data to render.

### Explicitly Excluded

- **Toast on clearing-status toggles.** The status pill cycles in one click (`unmarked → pending → cleared → unmarked`); a toast for every toggle would be UI noise, not safety. The backend continues to emit `transaction.status_toggled.v1` so the action lives in the history list and remains undoable from there — only the per-action toast is omitted. The existing `_undo_transaction_status_toggled` handler stays as-is.
- Redo. Not in spec; compensating events themselves are "redoable" only by repeating the original action.
- Multi-event undo (selecting two events and undoing both atomically). Linear undo is single-event.
- Undo for `import.applied.v1`, `unknowns.applied.v1`, `rules.history_applied.v1`, stage operations, or any non-`transaction.*` / non-`manual_entry.*` event types. Import already has its own dedicated `/api/import/undo` flow; the others are large-grain operations whose semantic inverses are out of scope for 5e.
- Operation history pagination / search / filtering. The list is "lightweight" — N most recent events, full-stop.
- Sticky / persistent toasts. The 8s auto-dismiss stays; the history list is the path to older actions.
- Refactoring the dynamic `import('$lib/undo-toast')` in `transactions/+page.svelte:235` to a static import. Cosmetic, deferred.

## System Behavior

### 1. Notes-Update Undo Handler

**Current state:** [main.py:877](app/backend/main.py#L877) emits `transaction.notes_updated.v1` with payload `{ journal_path, header_line, notes }`. There is no handler in `undo_service._HANDLERS`, so undoing returns `UNSUPPORTED`. No toast is shown today (the wiring isn't there in [TransactionDetailSheet.svelte](app/frontend/src/lib/components/transactions/TransactionDetailSheet.svelte) either).

**Decision:** Make notes fully undoable.

- Enrich the forward event payload with `previous_notes: string` (empty string if no prior notes line existed). Capture the previous value by parsing the block in `transactions_notes` before mutating. `_NOTES_RE` already exists at [main.py:831](app/backend/main.py#L831).
- Add `_undo_transaction_notes_updated` handler that locates the header, finds (or absence of) the current notes line, and rewrites it to `previous_notes`. Empty `previous_notes` → remove the line; non-empty → replace or insert in the same position the forward write used.
- Register the handler in `_HANDLERS` under `"transaction.notes_updated.v1"`.
- Wire the toast in the detail sheet save handler — summary `Notes updated on <payee>`. Payee comes from the current row; call site is the `apiPost` for `/api/transactions/notes` inside `TransactionDetailSheet.svelte` (search for `transactions/notes` to find the exact spot).

**Inputs:** User edits notes in the detail sheet, hits save. Forward event captures both new and previous notes.

**Outputs:** Toast appears with `Notes updated on <payee>`. Undo restores the prior notes (including the empty/absent state).

### 2. Operation History List

**Why:** The 8s toast covers the most recent action only. Users who walk away, switch tabs, or want to undo something from earlier in the session need a path to older events. The spec calls for a "lightweight operation history list".

**Backend:** Add `GET /api/events` returning the most recent **20** events newest-first. Each event row:

```json
{
  "id": "<uuidv7>",
  "type": "transaction.deleted.v1",
  "summary": "Removed Coffee Shop on 2026-04-12",
  "timestamp": "2026-04-26T15:42:11Z",
  "undoable": true,
  "compensated": false,
  "compensatedBy": null
}
```

- `undoable` = true iff `type` is in `_HANDLERS`. (Forward events only — `*.compensated.v1` events are not undoable themselves.)
- `compensated` = true iff a later event has `compensates == this.id`.
- `compensatedBy` = the compensating event id when `compensated` is true.
- Source of truth is `events.jsonl` — reuse `_read_events` from `undo_service.py` (or extract to `event_log_service.py` if it cleans the dependency direction).
- Fail-closed: if the file is missing, return an empty list (matches `_read_events` behavior).

**Frontend surface:** Add a single trigger (icon button) in the dashboard hero's right-edge / utility area or in the existing utility footer of `+layout.svelte` — pick one and document the choice in the PR. Tapping it opens a `bits-ui` Sheet (right-side, same primitive used by `TransactionDetailSheet`) titled `Recent activity`.

The sheet renders a vertical list of the 20 events:

- Each row: summary text on the left, relative-time stamp underneath (`2 minutes ago`, `1 hour ago`, `Yesterday at 3:42 PM` — reuse any existing relative-time helper or write a small one in `$lib/format.ts`).
- Right side per row: an `Undo` button when `undoable && !compensated`. When `compensated`, render the muted text `Undone` (no button). When `!undoable`, render no trailing element.
- Clicking `Undo` calls `triggerUndo(eventId)` (export a parameterized variant from `undo-toast.ts` — current `triggerUndo` reads from the store, so add `triggerUndoById(eventId, summary, refresh)` or restructure). On success, the row re-renders as `Undone`. On error, surface a small inline error under the row (`<span class="text-destructive">Undo failed: <message></span>`).
- After any successful undo, refetch the events list so the new compensating event appears at the top.

Empty state: `No recent activity yet.` Centered, muted.

Loading state: existing `apiGet` returns a promise — render a single line `Loading…` until it resolves.

Error state on the list fetch: `Couldn't load activity. Try again.` with a retry button.

**Refresh hooks:** The sheet refetches every time it opens. No background polling. No Server-Sent Events. No optimism — simplest possible.

### System Invariants

- The event log remains append-only. Undo via the history list is identical to undo via the toast — both call `POST /api/events/undo/{event_id}` and the backend writes a new compensating event. Past events are never edited or deleted.
- Drift detection wins over UI optimism: if the user opens the history list, sees an undoable event, then someone (or another tab) modifies the journal in between, the undo returns `DRIFT` and the UI surfaces the message instead of pretending it succeeded.
- Notes payload migration: events written before this change won't have `previous_notes`. The handler must treat missing `previous_notes` as `UndoFailedError("Pre-existing notes event lacks previous_notes — cannot undo")`. Do not silently default to empty.
- Toast and history list use the same code path for triggering undo. No duplication of the API call or the post-undo refresh logic.

### States

- **History sheet — closed:** existing app state; trigger button visible somewhere obvious.
- **History sheet — opening:** brief `Loading…` while the list fetches.
- **History sheet — populated:** scrollable list of up to 20 rows.
- **History sheet — empty:** `No recent activity yet.`
- **History sheet — error:** error message + retry.
- **Row — undoable:** `Undo` button visible.
- **Row — already compensated:** muted `Undone` label, no button.
- **Row — not undoable (e.g., import.applied.v1):** no trailing element. Row is shown for transparency, but there's nothing to do.
- **Row — undo in flight:** button label changes to `Undoing…`, disabled.
- **Row — undo succeeded:** list refetches; row re-renders as `Undone`.
- **Row — undo failed (drift, etc.):** inline error under the row.

### Edge Cases

- **User triggers undo from the toast and the history sheet simultaneously:** second call returns `ALREADY_COMPENSATED`. The history sheet should treat that outcome as success-equivalent for the row (mark as `Undone` and refetch), not as an error.
- **History list shows compensating events:** keep them in the list with `undoable: false` and a label like `Undid: <forward summary>` (the existing `summary` field on the compensating event already reads `Undid: <forward summary>` — reuse it). They are part of the operation history; hiding them would be confusing.
- **Toggle status spam:** rapid toggling produces a chain of events. Drift detection forces undo in reverse order. The history list correctly reflects this — undoing the latest is the only one that succeeds; older ones show as undoable until the latest is undone, at which point the next becomes undoable. No special UI handling needed; the natural behavior is correct.
- **Notes-update with identical text:** if the user "saves" notes with the same value, the journal hash doesn't change but an event is still emitted with `previous_notes == notes`. Undo is a no-op write but still emits a compensating event. Acceptable — it's rare and harmless.
- **Notes-update toast on detail sheet close:** save fires before close. Toast appears under the closing sheet, then the sheet animation completes. Verify the z-index: toast is `z-50`, sheet overlay is also `z-50`-ish. If they collide, bump the toast above the sheet (`z-60` or use bits-ui's portal layering).
- **Empty/whitespace notes:** treat `notes: "   "` as empty for the purposes of "remove the line", so the journal stays tidy.

### Failure Behavior

- `GET /api/events` failure: return 500 with a message; the frontend retry button re-fires the fetch.
- Notes-update undo on a pre-migration event (no `previous_notes`): `UndoFailedError` → outcome `FAILED` → user sees `Undo failed: Pre-existing notes event lacks previous_notes — cannot undo` in the toast or row error. No silent fallback.
- Concurrent undo attempts (toast + history): second one resolves as `ALREADY_COMPENSATED` per the existing handler. Frontend treats this as terminal success.
- Drift on history-list undo: surface the existing `message` ("File changed since the action: <path>") in the inline row error. Do not auto-retry.

### Regression Risks

- **Notes payload shape:** adding `previous_notes` to the forward event must not break any existing consumer of the event log. Confirm `_HANDLERS` and `_read_events` are the only readers (plus the future history endpoint).
- **History fetch perf:** parsing `events.jsonl` line-by-line on every open is fine at 20 events but worth a sanity check on a workspace with thousands. If parse + scan-for-compensations is slow, cap the scan at the most recent 200 events (the answer for "is event X compensated" only needs to look at events after X).
- **Toast z-index under the detail sheet:** confirmed above; verify visually.
- **Undo on a `transaction.unmatched.v1` event from the history list:** the existing handler is the most complex of the five; if a later edit touched either the main journal or `archived-manual.journal`, drift fails. Make sure the message is legible in the row error UI.

## Acceptance Criteria

- Saving notes from the transaction detail sheet shows an Undo toast with summary `Notes updated on <payee>`. Clicking Undo restores the prior notes (including the case where there were no notes before).
- Toggling the clearing-status pill does **not** show a toast. The action is still recorded in the event log and remains undoable via the history list.
- A new `Recent activity` trigger is reachable from the persistent UI shell (one click from any route).
- Opening `Recent activity` lists the 20 most recent events newest-first. Each row shows the summary, a relative timestamp, and either an Undo button, a muted `Undone` label, or nothing — per the row-state rules above.
- Clicking Undo in the history sheet performs the same undo as the toast and refreshes the list to reflect the new compensating event.
- A previously-compensated event in the history sheet shows `Undone` with no Undo button.
- Compensating events themselves appear in the list as informational rows with no Undo button.
- Status-toggle events show in the history list as undoable rows. Undoing one from the list restores the prior status.
- A drift error on history-sheet undo surfaces the backend `message` text inline under the row.
- `GET /api/events` returns 20 events, newest-first, with the documented schema.
- `pnpm check` passes.
- `uv run pytest -q` passes (existing tests + new tests for the notes-update handler and the events listing endpoint).

## Proposed Sequence

Sequenced smallest → largest, each step independently shippable.

1. **Notes-update payload enrichment** — backend change to `transactions_notes` in `main.py`. Adds `previous_notes` to the emitted payload. No undo handler yet; no behavior change yet.
2. **Notes-update undo handler + toast wiring** — backend handler in `undo_service.py` + dispatch entry; frontend `showUndoToast` call in the detail sheet save path. New backend test mirroring the existing handler tests.
3. **`GET /api/events` endpoint** — backend-only. New test for the listing response shape, compensation flag, and undoable flag.
4. **Operation history sheet** — frontend Sheet component, list rows, parameterized undo (`triggerUndoById` or refactored `triggerUndo`), trigger button placement. Manual verification across desktop and mobile widths.

## Definition of Done

- All 10 acceptance criteria visibly confirmed in the running app.
- `pnpm check` and `uv run pytest -q` both pass.
- Manual round-trip: every mutating action (delete, recategorize, reset-category, unmatch, manual-entry-create, toggle-status, notes-update) is undoable from the history sheet. Toast-driven undo is verified for all of them except toggle-status, which has no toast by design.
- Drift detection still works: edit the journal externally between forward action and undo; both surfaces show the drift error.
- ROADMAP.md updated: 5e marked shipped, Feature 5 closed.
- DECISIONS.md gets a single-line addendum if any open question's resolution is non-obvious; otherwise no change.

## UX Notes

- The history sheet must feel like a small utility, not a feature. Match the existing detail sheet's visual weight and copy density.
- `Recent activity` is the right header — neutral, descriptive. Don't call it `Undo history` (sounds like a power-user feature) or `Audit log` (sounds like compliance).
- Relative timestamps should match consumer-app conventions: `Just now`, `2 minutes ago`, `1 hour ago`, `Yesterday at 3:42 PM`, `Apr 18`. No absolute timestamps in the row body — keep it scannable.
- The trigger button should be discoverable but not loud. A clock-rewind icon (lucide `History`) in the layout's utility area is a natural fit; verify it doesn't compete with primary nav.
- Don't show a count badge on the trigger. The history list is informational, not an inbox.

## Out of Scope

- Redo
- Multi-event / batch undo
- Undo for import / unknowns / rules-history
- Pagination, filtering, search in the history list
- Background polling / SSE / live updates of the history sheet
- Refactor of the dynamic import in `transactions/+page.svelte:235`
- Visual redesign of the toast component
- Operation history persistence beyond `events.jsonl` itself

## Dependencies

None blocking. Depends on:

- 5b (event log) — shipped.
- 5d (transaction actions menu) — shipped.
- Toast component — shipped as part of the existing 5e partial.

## Open Questions

None. Decisions inline:

- **No toast on clearing-status toggles.** The pill cycles in one click; a toast would be unwelcome noise. Action remains in the event log and undoable via the history sheet.
- **Notes update: undoable, not "non-undoable".** Adds `previous_notes` to the payload, parallels the recategorize handler's structure. Pre-migration events fail closed with a legible message.
- **History list size: 20 events.** Lightweight per spec; adjustable later if real usage demands more.
- **History trigger placement: layout utility area, not a full nav entry.** The history list is a utility, not a destination. PR should include a screenshot showing the chosen spot at desktop and mobile widths.
