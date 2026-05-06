# Manual Transaction Merge (9b)

> Queued after 9a. This plan defines the full generic merge workflow on the transactions page, building on the reconciliation-scoped merge substrate from 8d.

## Objective

Give users a way to merge two duplicate transactions on the transactions page into one, preserving import identity so future imports of either bank-row variant are recognized as duplicates. This is the generic counterpart to 8d's reconciliation-scoped merge.

## Background

8d shipped the merge substrate in `reconciliation_duplicate_service.py`:
- `resolve_duplicate_candidate()` handles three actions: `remove_manual_duplicate`, `use_imported_transaction`, `merge_imported_duplicates`.
- `_upsert_import_identity_metadata()` preserves both transactions' identity variants on the survivor.
- Events are emitted for each action, enabling undo.

The gap: this substrate is only reachable from the reconciliation route's duplicate-review mode. Users who spot duplicates on the transactions page have no way to merge them without starting a reconciliation.

## Scope

### Included

1. **Multi-select on the transactions page.** The transactions page gains a selection mode: long-press or a dedicated "Select" toggle reveals checkboxes on each non-assertion row. Selecting exactly two rows enables a "Merge" action in a floating action bar.

2. **Merge confirmation sheet.** Clicking "Merge" opens a right-side sheet (matching the existing `TransactionDetailSheet` pattern) showing the two selected transactions side by side:
   - Date, payee, amount, account, source badge (`Imported` / `Manual`), category.
   - The sheet identifies which transaction will survive and which will be removed, based on source-aware logic (same rules as 8d: imported preferred over manual; first-imported preferred for imported/imported).
   - User metadata differences are highlighted so the user can see what carries over.
   - A "Merge" confirmation button and a "Cancel" to exit.

3. **Backend merge endpoint.** `POST /api/transactions/merge` accepts two transaction identifiers (selection keys or equivalent), determines the source-aware action, delegates to a generalized version of `resolve_duplicate_candidate()`, and returns the survivor's identity. The endpoint:
   - Validates that both transactions exist and belong to the same ledger account.
   - Applies the same action logic as 8d (`_action_for_pair()` equivalent).
   - Emits a structured event (`transaction.merged.v1`) for undo.
   - Returns the survivor's updated row for the frontend to refresh.

4. **Undo support.** The merge event is undoable through the existing undo infrastructure. The undo handler restores the removed transaction from the event payload and strips the merged identity variant from the survivor.

5. **Generalize the merge substrate.** Extract the reconciliation-scoped merge logic from `reconciliation_duplicate_service.py` into a shared service (e.g., `transaction_merge_service.py`) that both the reconciliation route and the new endpoint can call. The reconciliation route continues to use its own duplicate-review UI and action flow; only the underlying merge/remove/replace operations are shared.

### Explicitly Excluded

- Merging more than two transactions at once. Two-at-a-time is sufficient and keeps the UX simple.
- Auto-detection of duplicates on the transactions page. The user selects the rows they want to merge. (The unknowns review queue and reconciliation route handle auto-detection in their respective contexts.)
- Bulk operations beyond merge (bulk delete, bulk recategorize). Those are separate features.
- Changes to the unknowns review queue's match flow.
- Changes to the reconciliation duplicate-review UI.

## System Behavior

### Inputs

- User enables selection mode on the transactions page.
- User selects exactly two transaction rows.
- User clicks "Merge" in the floating action bar.
- User reviews the merge preview sheet and confirms.

### Logic

- **Survivor selection** follows the same priority as 8d:
  1. Imported + Manual → imported survives, manual is archived.
  2. Imported + Imported → first-by-date survives; import identity metadata from both preserved on the survivor.
  3. Manual + Manual → first-by-date survives; second is removed.
- **Metadata carryover:** user-authored metadata (notes, tags, category) from the removed transaction carries over to the survivor if the survivor lacks them. System metadata is never duplicated. Category on the survivor takes precedence.
- **Import identity preservation:** for imported transactions, all `source_identity*` and `source_payload_hash*` variants from the removed transaction are added to the survivor (via `_upsert_import_identity_metadata()`). The ImportIndex is updated.
- **Validation:**
  - Both transactions must be in the same ledger account (same tracked account).
  - Assertion transactions cannot be merged.
  - Transactions in included files (`line_number < 0`) cannot be modified.

### Outputs

- The merged survivor replaces both rows in the transactions list.
- The removed transaction disappears from the list.
- An undo toast appears (following the established 8s auto-dismiss pattern).
- Selection mode exits after a successful merge.

## System Invariants

- Merged import identity must prevent re-import of either bank-row variant.
- The survivor must remain a valid ledger transaction (parseable, balanced).
- The merge event must contain enough payload for full undo.
- Two transactions from different ledger accounts cannot be merged.

## States

- **Default:** transactions page, no selection mode.
- **Selection mode:** checkboxes visible, floating action bar shows count. "Merge" disabled until exactly 2 rows selected.
- **Merge preview:** right-side sheet showing the two transactions and the proposed outcome.
- **Merging:** confirmation in progress, UI disabled.
- **Merged:** toast shown, list refreshed, selection mode exited.
- **Error:** inline error in the merge sheet; selection preserved.

## Edge Cases

- **Both transactions have the same payee and amount but different dates.** Merge proceeds; survivor keeps its own date.
- **One transaction has notes, the other doesn't.** Notes carry over to the survivor.
- **Both transactions have notes.** Survivor's notes take precedence; removed transaction's notes are appended with a separator or discarded (prefer appending to avoid data loss).
- **Transactions in different journal files (same account).** Merge should work across files as long as the account matches. The removed transaction's journal is modified; the survivor's journal gains any carried-over metadata.
- **One transaction is a transfer.** Merge is blocked — transfers have bilateral semantics that merge doesn't handle. Show a clear message.

## Failure Behavior

- **Merge fails (journal write error):** rollback via backup; show inline error; preserve selection.
- **Undo of merge fails (drift):** standard drift error; the original merge event is not marked compensated.

## Regression Risks

- **Import-idempotency regression.** If the survivor doesn't retain both identities, the removed transaction's bank-row variant will reappear on the next import.
- **Event payload incompleteness.** If the merge event doesn't capture the full removed transaction block, undo cannot restore it.
- **Reconciliation regression.** Extracting shared merge logic must not change reconciliation behavior. Reconciliation tests must continue to pass.

## Acceptance Criteria

- The transactions page supports selecting exactly two rows and merging them.
- Merge confirmation shows both transactions with source badges and highlights the survivor.
- After merge, the removed transaction is gone and the survivor carries both import identities.
- Undo restores the removed transaction and strips the merged identity variant.
- Transfers cannot be merged (clear blocking message).
- Assertion rows cannot be selected for merge.
- `pnpm check` passes and `uv run pytest -q` passes.

## Proposed Sequence

1. **Extract shared merge substrate.** Move the action-determination logic, journal manipulation helpers (`_read_block`, `_rewrite_posting_account`, `_upsert_import_identity_metadata`, etc.), and the three resolution paths from `reconciliation_duplicate_service.py` into `transaction_merge_service.py`. Update reconciliation to import from the shared module. Verify reconciliation tests pass.
2. **Add `POST /api/transactions/merge` endpoint.** Accept two transaction identifiers, validate, determine action, delegate to the shared service, emit event, return survivor.
3. **Add undo handler for `transaction.merged.v1`.** Register in the undo dispatch table. Restore removed transaction from event payload, strip merged identity variants.
4. **Add selection mode to the transactions page.** Checkbox UI, floating action bar, "Merge" button gated on exactly 2 selected.
5. **Add merge preview sheet.** Side-by-side view, survivor indication, confirm/cancel.
6. **Wire merge confirmation to the endpoint.** Call, handle success (toast + refresh + exit selection), handle error (inline).
7. **Write tests.** Backend: merge logic for each source combination, identity preservation, undo round-trip, transfer blocking. Frontend: selection mode interaction, merge sheet rendering.

## Dependencies

- **9a (match-suggestion ranking fix):** must ship first. 9a extracts the shared payee similarity module, which 9b may use for the merge preview's "why these look like duplicates" hint (optional, not required for merge mechanics).
- **8d (reconciliation duplicate resolution):** shipped. Provides the merge substrate to generalize.

## Open Questions

- **Should the merge preview suggest which transaction to keep, or let the user choose?** 8d's reconciliation flow auto-determines the survivor. For a general-purpose merge, the user might want control. Recommendation: auto-determine but allow the user to swap survivor/removed before confirming.
- **Should notes from the removed transaction be appended to the survivor's notes?** Recommendation: yes, with a `---` separator, to avoid silent data loss.
