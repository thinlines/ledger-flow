# Current Task

## Title

Transaction actions menu: delete, re-categorize, unmatch

## Objective

Users can act on individual transactions from the register via a three-dot overflow menu. Three actions are available — delete (remove transaction), re-categorize (reset to unknown, resurface in review queue), and unmatch (restore archived manual entry and revert match tags). Each action writes a structured event to the event log and follows the established mutation pattern (backup, drift check, modify, emit event). No undo affordance yet — that ships in 5e.

## Scope

### Included

- Three-dot overflow menu button on each register row (per-account register only).
- Context-dependent action visibility per transaction type.
- Three backend endpoints: delete, re-categorize, unmatch.
- Event emission for each action through the existing event log service.
- Confirmation dialog for delete and unmatch (destructive/complex actions).
- `matchId` field added to `RegisterEvent` so the frontend can determine unmatch availability.
- Backend tests for all three endpoints.
- Frontend types updated for the new `matchId` field and new API calls.

### Explicitly Excluded

- Undo toast or compensating events (5e).
- Actions in the activity view (cross-account view) — per-account register only.
- Batch actions (multi-select).
- Transaction editing (deferred per ROADMAP).
- Split transaction re-categorize (only single-destination transactions).
- Any changes to the event log service itself.

## System Behavior

### Inputs

- User clicks three-dot menu on a register row.
- User selects an action from the popover menu.
- For delete and unmatch: user confirms in a dialog.

### Logic

**1. Action availability per transaction type**

Each row's available actions are determined by data already in the register response, plus the new `matchId` field:

| Condition | Delete | Re-categorize | Unmatch |
|---|---|---|---|
| Opening balance (`isOpeningBalance`) | No | No | No |
| Unknown category (`isUnknown`) | Yes | No | No |
| Transfer (`transferState` is set) | Yes | No | No |
| Has match-id (`matchId` is set) | Yes | Yes | Yes |
| Standard categorized (none of above) | Yes | Yes | No |

Rules:
- Opening balances are never actionable (system-managed).
- Re-categorize requires a non-unknown, non-transfer, non-opening-balance transaction (must have a meaningful category to reset).
- Unmatch requires a `matchId` (only transactions that were matched to a manual entry via unknowns review).
- Delete is available on everything except opening balances.
- If no actions are available, the three-dot button is hidden (opening balances only).

**2. Three-dot menu UI**

A subtle vertical-dots button at the trailing edge of each register row. Clicking it opens a popover menu with the available actions. Only actions that apply to the specific row are shown.

Menu items:
- **Remove transaction** — destructive action, styled with red/danger text.
- **Reset category** — neutral action. Tooltip or subtitle: "Move back to review queue".
- **Undo match** — neutral action. Tooltip or subtitle: "Restore the original manual entry".

The menu closes on selection or outside click. The menu button must not interfere with the existing clearing-status toggle or the `<details>` expand/collapse.

**3. Delete transaction**

`POST /api/transactions/delete`

Request body:
```json
{
  "journalPath": "journals/2026.journal",
  "headerLine": "2026-03-15 * Grocery Store"
}
```

Backend logic:
1. Resolve `journalPath` against the workspace root. Validate the file exists and is inside the workspace.
2. `check_drift(workspace_root, journal_path)` — returns `hash_before`.
3. `backup_file(journal_path, "delete")` — create `.bak` file.
4. Read journal lines. Find the transaction block starting with `headerLine`.
5. Transaction block identification: match the exact header line, then include all subsequent lines until the next transaction header (`TXN_START_RE`) or end of file. Also consume trailing blank lines between this block and the next transaction.
6. Remove the entire block from the journal. Write the file.
7. `hash_file(journal_path)` — returns `hash_after`.
8. Emit event:
   - `event_type`: `"transaction.deleted.v1"`
   - `summary`: `"Deleted transaction: {payee} on {date}"`
   - `payload`: `{ "journal_path", "header_line", "deleted_block" }` — `deleted_block` is the full text of the removed lines (needed by 5e for undo).
   - `journal_refs`: `[{ "path", "hash_before", "hash_after" }]`
9. Return `{ "success": true }`.

Failure:
- Header line not found in journal → 404 with `"Transaction not found in journal"`.
- Multiple identical header lines → 409 with `"Ambiguous transaction — multiple matches"`. Do not delete.
- Drift check emits a drift event but does NOT block the delete (drift is advisory per §12).

**4. Re-categorize transaction**

`POST /api/transactions/recategorize`

Request body:
```json
{
  "journalPath": "journals/2026.journal",
  "headerLine": "2026-03-15 * Grocery Store"
}
```

Backend logic:
1. Resolve and validate `journalPath`.
2. `check_drift(workspace_root, journal_path)` — returns `hash_before`.
3. `backup_file(journal_path, "recategorize")` — create `.bak` file.
4. Read journal lines. Find the transaction block.
5. Identify the destination posting: the non-source-account posting line. The source account is the tracked account that owns this register (inferred from the posting that matches a tracked account's `ledger_account`). The destination is the other posting.
6. Validation: the transaction must have exactly one non-source posting that is an income/expense category (not a tracked account). If the destination is another tracked account (transfer), reject with 422: `"Cannot re-categorize a transfer"`. If the destination is already unknown (`Expenses:Unknown`), reject with 422: `"Transaction is already uncategorized"`.
7. Rewrite the destination posting's account to `Expenses:Unknown` using the existing `rewrite_posting_account()` helper from `transfer_service.py`. Preserve the amount and formatting.
8. Write the file.
9. `hash_file(journal_path)` — returns `hash_after`.
10. Emit event:
    - `event_type`: `"transaction.recategorized.v1"`
    - `summary`: `"Reset category: {payee} on {date} ({previous_account} → Expenses:Unknown)"`
    - `payload`: `{ "journal_path", "header_line", "previous_account", "new_account": "Expenses:Unknown" }`
    - `journal_refs`: `[{ "path", "hash_before", "hash_after" }]`
11. Return `{ "success": true, "previousAccount": "Expenses:Groceries" }`.

**5. Unmatch transaction**

`POST /api/transactions/unmatch`

Request body:
```json
{
  "journalPath": "journals/2026.journal",
  "headerLine": "2026-03-15 * Grocery Store",
  "matchId": "a1b2c3d4-..."
}
```

Backend logic:
1. Resolve and validate `journalPath`.
2. Locate the archived manual entry in `workspace/journals/archived-manual.journal` by scanning for a block with `; match-id: <matchId>`. If not found → 404: `"Archived manual entry not found for this match"`.
3. `check_drift(workspace_root, journal_path)` — returns `hash_before` for the main journal.
4. Also `check_drift(workspace_root, archive_path)` — returns `hash_before` for the archive journal.
5. `backup_file(journal_path, "unmatch")` and `backup_file(archive_path, "unmatch")`.
6. **Main journal modifications** — find the matched imported transaction block (by `headerLine`):
   a. Remove the `; :manual:` metadata line.
   b. Remove the `; match-id: <matchId>` metadata line.
   c. Rewrite the destination posting account to `Expenses:Unknown` (the match carried over the manual entry's category — resetting it returns the imported transaction to the unknowns queue, which is the correct pre-match state).
7. **Archive journal modification** — remove the archived manual entry block from `archived-manual.journal`. A block is identified by scanning for the header line that is immediately followed by `; match-id: <matchId>`. Remove the entire block including trailing blanks.
8. **Restore manual entry** — insert the archived manual entry block (with `; match-id:` tag removed) back into the main journal in date-sorted position. The restored entry should appear as it did before the match: an unmarked manual transaction with `; :manual:` tag and its original category.
9. Write both files.
10. Compute `hash_after` for both journals.
11. Emit event:
    - `event_type`: `"transaction.unmatched.v1"`
    - `summary`: `"Unmatched: {payee} on {date} (match-id: {matchId})"`
    - `payload`: `{ "journal_path", "archive_path", "header_line", "match_id", "restored_manual_block" }`
    - `journal_refs`: refs for both the main journal and the archive journal (each with `hash_before`/`hash_after`).
12. Return `{ "success": true }`.

Failure:
- Match-id not found in archive → 404.
- Header line not found in main journal → 404.
- Archive file does not exist → 404: `"No archived entries exist"`.

**6. RegisterEvent `matchId` field**

Add `match_id: str | None = None` to the `RegisterEvent` dataclass. Populate it from `transaction.metadata.get("match-id")` in `build_account_register()`. Serialize as `matchId` in the API response (consistent with existing camelCase convention).

The frontend `RegisterEntry` type adds `matchId?: string | null`.

### Outputs

- Three-dot menu visible on actionable register rows.
- Delete removes the transaction block from the journal.
- Re-categorize rewrites the destination to `Expenses:Unknown` (transaction reappears in unknowns review).
- Unmatch restores the archived manual entry and reverts the imported transaction to pre-match state.
- Each action emits a structured event to `events.jsonl`.
- Register reloads after each action to reflect the new state.

## System Invariants

- Journal mutations follow the established pattern: drift check → backup → modify → emit event.
- Events contain enough data for 5e to compute compensating actions (deleted block text, previous account, restored manual block).
- Opening balances are never actionable through this menu.
- The three-dot menu never appears on rows where no actions are available.
- Unmatch restores both the manual entry and the imported transaction to their pre-match states.
- The archive journal is kept consistent — entries are removed from it only during unmatch.
- Ambiguous transactions (duplicate header lines) are rejected, not guessed.

## States

- **Menu closed (default)**: three-dot button visible, no popover.
- **Menu open**: popover shows available actions for this row.
- **Confirmation dialog (delete/unmatch)**: modal overlay with action description and confirm/cancel.
- **Action in progress**: menu closes, row shows a brief loading indicator (optional — actions are fast). Disable the menu button during the request to prevent double-submission.
- **Action succeeded**: register reloads. A brief inline confirmation is acceptable (e.g., row briefly highlights or fades). No toast yet (5e).
- **Action failed**: error displayed in an alert or inline message. The register does not reload (state unchanged due to backup/rollback).
- **No actions available** (opening balance): three-dot button is hidden entirely.

## Edge Cases

- **Duplicate header lines**: two transactions with identical date and payee in the same journal. The backend rejects the action with 409 rather than guessing. The user must resolve ambiguity by editing the journal externally. This is rare — imported transactions have unique metadata comments that differentiate them.
- **Transaction already deleted externally**: header line not found → 404. Frontend shows "Transaction not found — it may have been modified outside the app." Register reloads.
- **Archive missing for unmatch**: if `archived-manual.journal` was deleted externally, unmatch returns 404. Frontend shows "The archived entry could not be found."
- **Unmatch when manual entry has been further modified in archive**: the archive is app-managed and should not be edited externally. If it was, the restored entry reflects whatever is in the archive. Drift detection on the archive file logs this.
- **Split transactions and re-categorize**: transactions with multiple non-source postings are not eligible for re-categorize. The action is hidden for these rows. Detection: count non-source-account postings in the register's `detailLines`.
- **Re-categorize a matched transaction**: allowed. The `:manual:` and `match-id:` tags remain on the transaction (they record history), but the category is reset to unknown.

## Failure Behavior

- All journal mutations are preceded by `backup_file()`. If the write fails mid-operation, the backup preserves the pre-mutation state.
- Event emission failure does not roll back the journal mutation (events are advisory per §12).
- Backend returns structured error responses (status code + detail message). Frontend displays the detail message.
- Network errors on the frontend side: show a generic "Something went wrong. Please try again." message. Do not reload the register on error.

## Regression Risks

- **Clearing status toggle**: the three-dot menu button must not capture click events meant for the clearing-status toggle. Both are in the row summary area. Test: clicking the clearing indicator still cycles the status.
- **Details expand/collapse**: the `<details>` element on each row must still expand on click. The three-dot button must stop event propagation to avoid toggling the details.
- **Register load performance**: adding `matchId` to every register entry requires reading `transaction.metadata` — this is already loaded and parsed, so no additional I/O. No performance impact.
- **Unknowns review after re-categorize**: a re-categorized transaction must appear in the unknowns scanner. Verify by re-categorizing a transaction, then navigating to `/unknowns` — it should appear.
- **Existing tests**: no test currently calls the new endpoints. Existing register, import, and unknowns tests must continue to pass.

## Acceptance Criteria

- Three-dot menu button appears on all register rows except opening balances.
- Menu shows only applicable actions based on transaction type.
- User can delete a transaction: transaction block is removed from the journal, event is emitted, register updates.
- User can re-categorize a transaction: destination account is rewritten to `Expenses:Unknown`, event is emitted, transaction appears in unknowns review.
- User can unmatch a matched transaction: manual entry is restored to the main journal, match tags are removed from the imported transaction, archived entry is removed from the archive journal, event is emitted.
- Delete and unmatch show a confirmation dialog before proceeding.
- Ambiguous transactions (duplicate headers) produce a clear error, not silent data corruption.
- `matchId` is present in the register API response for matched transactions.
- `uv run pytest -q` passes in `app/backend`.
- `pnpm check` passes in `app/frontend`.

## Proposed Sequence

1. **Backend: add `matchId` to register response.** Add `match_id` field to `RegisterEvent`. Populate from `transaction.metadata.get("match-id")` in `build_account_register()`. Verify the field appears in the API response. Test: register entry for a matched transaction includes the match-id value.

2. **Backend: delete endpoint.** `POST /api/transactions/delete` with the full mutation pattern (drift check, backup, block removal, event emission). Tests: transaction removed, event emitted, 404 on missing, 409 on ambiguous, backup created.

3. **Backend: re-categorize endpoint.** `POST /api/transactions/recategorize` — rewrite destination posting to `Expenses:Unknown`. Tests: posting rewritten, event emitted, 422 on transfer, 422 on already-unknown, transaction appears in unknowns scan.

4. **Backend: unmatch endpoint.** `POST /api/transactions/unmatch` — restore manual entry, remove match tags, clean archive. Tests: manual entry restored in main journal, match tags removed, archive entry removed, event emitted, 404 on missing archive.

5. **Frontend: three-dot menu component.** Add the overflow menu button and popover to register rows. Wire action visibility logic based on `isOpeningBalance`, `isUnknown`, `transferState`, `matchId`, and `detailLines` count. Add confirmation dialogs for delete and unmatch.

6. **Frontend: API integration and register reload.** Wire each menu action to its backend endpoint. Reload the register on success. Display errors on failure. Update `RegisterEntry` type with `matchId`.

7. **Integration test.** End-to-end: import a transaction, categorize it, delete it via the menu — verify journal state. Match a manual entry, unmatch it via the menu — verify both entries restored correctly.

## Definition of Done

- All three actions work end-to-end from the register UI.
- Events contain enough payload data for future undo (5e).
- No register regressions (clearing toggle, expand/collapse, pending transfers all still work).
- Transaction re-categorized via the menu appears in the unknowns review queue.
- Unmatch fully restores pre-match state for both the imported and manual transactions.
- All existing tests pass. New tests cover the three endpoints.

## UX Notes

- The three-dot button should be visually subtle — it's a secondary action surface. Use the existing icon/button patterns from the design system.
- Menu copy is finance-first: "Remove transaction", "Reset category", "Undo match". No technical terms.
- The delete confirmation should say something like: "Remove this transaction from your records? You'll be able to undo this soon." (Forward reference to 5e is acceptable as a trust signal.)
- The unmatch confirmation should explain the effect: "This will restore the original manual entry and move the imported transaction back to the review queue."
- Re-categorize needs no confirmation — it's easily reversible through unknowns review.

## Out of Scope

- Undo toast or compensating events (5e).
- Activity view actions (per-account register only).
- Batch/multi-select actions.
- Transaction field editing (deferred).
- Split transaction re-categorize.
- Actions on opening balances.
