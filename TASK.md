# Current Task

## Title

Resolve pending imported transfers manually without file edits

## Objective

Let a user finish a genuinely unresolved pending transfer between two import-enabled tracked accounts from the transactions page. The product should create the missing counterpart entry, mark the existing imported side as matched, and remove the transfer from pending work without requiring journal editing in a text editor.

## Scope

### Included

- Add a guided `Resolve manually` flow for eligible pending transfer rows in `/transactions`.
- Allow the flow to start from either the imported pending row or the synthetic peer pending row, as long as both point to the same underlying pending transfer.
- Add backend preview and apply behavior for a single pending imported transfer resolution.
- Append one matched counterpart transaction using the existing transfer pair account and the same `transfer_id` as the original pending transfer.
- Update the original imported transaction from `pending` to `matched` without changing its postings or source import metadata.
- Write synthetic import identity metadata for the manually created counterpart so future imports on the peer account classify as duplicate or conflict instead of silently creating a second balance-moving transaction.
- Refresh register presentation so the resolved transfer disappears from pending sections and appears as normal activity on both accounts.
- Add compact detail copy that explains the transfer was resolved manually because no imported counterpart was expected.

### Explicitly Excluded

- A broad freeform manual transaction editor
- Manual resolution for grouped or many-to-many transfers
- Editing arbitrary imported transaction amounts or postings
- Principal-vs-interest or debt-payment decomposition
- Bulk resolution of multiple pending transfers at once
- New persistent account-link or relationship models

## Current Failure

- The product can already classify imported transfers, keep one-sided imports pending, auto-match a single imported counterpart, and suppress false pending work for balanced grouped ACH verification transfers.
- It still cannot finish the remaining case where one imported side exists, the peer account is import-enabled, and no real imported counterpart will arrive.
- In that case the user must edit the journal file manually: find the pending transaction, change match metadata, and add a balancing counterpart entry by hand.
- That workflow is easy to get wrong and bypasses the product’s normal safety rails.

## Product Outcome

- A user can clear a real pending transfer from the app instead of editing files.
- The original imported row remains visible as imported activity.
- The manually created counterpart is visible as normal account activity on the peer account.
- Pending counts and `Balance with pending` only reflect unresolved imported work.
- If a later CSV import would duplicate the manually created counterpart, the import flow fails safely as duplicate or conflict instead of silently adding a second transfer.

## Delivery Target

Solve the real unresolved pending-transfer gap first, using a transfer-specific guided flow, before broadening into general manual transaction entry.

## Eligibility Rule

The `Resolve manually` action is available only when all of the following are true:

- The register row represents an `import_match` transfer that is still `pending`.
- The pending transfer points to a tracked peer account that still has an import account configured.
- The backend can identify one underlying source transaction to mutate safely.
- The transfer is not already covered by grouped-settlement read-time logic.

If any of those checks fail, the action must be hidden or rejected fail-closed.

## System Behavior

### Inputs

- User opens a pending transfer row in `/transactions`.
- User chooses `Resolve manually`.
- Frontend sends a preview request using a backend-issued resolution token for the underlying pending transfer.
- User reviews the preview and confirms the apply action.

### Logic

- The register API must expose a stable resolution token for eligible pending transfers. The same token must be available whether the user is looking at the imported pending row or the synthetic pending peer row.
- Preview must reload the current workspace state and validate that the underlying source transaction still exists, still has `transfer_type: import_match`, still has `transfer_match_state: pending`, and still points to the same peer tracked account.
- Preview must derive the counterpart transaction from the existing pending transfer rather than from freeform user input:
  - same posted date as the source pending transfer
  - same payee as the source pending transfer
  - opposite signed amount on the peer import account
  - same transfer pair account
  - same `transfer_id`
  - `transfer_type: import_match`
  - `transfer_match_state: matched`
  - `transfer_peer_account_id` pointing back to the source tracked account
- Preview must compute synthetic import metadata for the manually created counterpart using the peer import account context and the rendered transaction body:
  - `import_account_id`
  - `source_identity`
  - `source_payload_hash`
  - `importer_version`
  - any existing normal import metadata needed to preserve duplicate/conflict behavior for that import account
- Preview must refuse to continue if the synthetic counterpart identity already exists in a way that would make the resolution immediately duplicate or conflict with existing journal/import state.
- Apply must update the original pending transaction metadata from `pending` to `matched` and append the counterpart transaction in journal date order using the existing append-safe journal merge model.
- Apply must not rewrite or normalize unrelated journal transactions.
- Apply must write both effects as one logical resolution. If the operation cannot complete safely, the original transfer must remain pending and no counterpart transaction should be left behind.

### Outputs

- Pending transfer disappears from pending sections on both account registers after reload.
- Both registers show normal activity rows for the resolved movement.
- Row details explain that the missing side was added manually because no imported counterpart was expected.
- Success feedback tells the user the transfer was resolved manually.
- Future import preview uses the synthetic import identity on the counterpart to classify matching bank rows as duplicate or conflict rather than new.

## System Invariants

- Pending UI must continue to represent unresolved imported work only.
- The original imported source transaction remains authoritative and keeps its source import metadata.
- Manual resolution must not change balances beyond the explicit counterpart transaction it adds.
- Manual resolution must not introduce transfer-clearing or journal-file terminology into primary UI copy.
- The product must preserve the existing `new` / `duplicate` / `conflict` import model for future imports.
- The product must not silently create a second balance-moving transaction if a later bank import overlaps the manually resolved counterpart.
- Backend services own transfer-resolution logic, metadata generation, and journal writes. Frontend code remains orchestration and presentation only.

## States

- Default: eligible pending rows show a `Resolve manually` secondary action.
- Preview loading: the confirmation surface shows a loading state while the backend validates the pending transfer and builds the counterpart preview.
- Preview ready: the user sees the source account, destination account, date, payee, amount, and the warning that this should be used only when no imported counterpart is expected.
- Applying: confirm actions are disabled while the backend updates the pending transfer and appends the counterpart.
- Success: the register refreshes, the pending row disappears, and a success message confirms the transfer was resolved manually.
- Error: the confirmation surface stays open, no partial resolution is kept, and the user sees a concrete message explaining why the transfer could not be resolved safely.
- Empty: when an account has no eligible pending transfers, no manual-resolution controls are shown.

## Edge Cases

- The pending transfer was already matched, deleted, or reclassified by another workflow before apply.
- The peer tracked account was removed or no longer has an import account configured before preview or apply.
- The register row is a synthetic pending peer event rather than the original imported row; the same underlying transfer must still be resolvable safely.
- The synthetic counterpart identity already matches an existing journal transaction for the peer import account.
- The synthetic counterpart identity collides with an existing transaction but the payload differs, which should surface as a conflict-style refusal rather than creating the manual resolution.
- The pending transfer belongs to a grouped or ambiguous set that this task does not support.
- The workspace contains stale UI state; preview and apply must always re-read current files before mutating anything.

## Failure Behavior

- If preview cannot prove that the transfer is still eligible and uniquely identifiable, the product must reject manual resolution and leave the transfer pending.
- If the system cannot compute safe synthetic import metadata for the counterpart, it must reject manual resolution and leave the transfer pending.
- If writing the updated source metadata or the new counterpart transaction would fail, the product must leave the transfer pending with no partial counterpart left behind.
- If a future import matches the manual counterpart identity and payload, it must classify as duplicate.
- If a future import matches the manual counterpart identity but not the payload, it must classify as conflict.

## Regression Risks

- Incorrect synthetic import metadata could let a later bank import create a duplicate transfer.
- Over-broad eligibility could let users manually resolve transfers that should stay pending.
- Register actions wired only to imported pending rows could strand the same transfer when the user starts from the peer account’s synthetic pending event.
- Copy could imply that all pending transfers are safe to resolve manually, weakening trust in ambiguous cases.
- Journal write paths could accidentally normalize or rewrite unrelated transaction text if the implementation bypasses the existing merge model.
- Transactions-page labels such as `Imported register` or `Imported balance` could become misleading once manually authored counterparts appear in the same view.

## Acceptance Criteria

- Given a pending imported transfer from checking to savings with no imported savings-side counterpart, when the user confirms `Resolve manually` from the checking register, then the checking row no longer appears in pending and is shown as a matched transfer after reload.
- Given that same transfer, when the savings register is queried after apply, then it shows one new activity row for the savings side with the opposite amount, the same date, and transfer details pointing back to checking.
- Given a synthetic pending peer row on the savings register for that same transfer, when the user starts `Resolve manually` from savings instead of checking, then the product resolves the same underlying pending transfer safely and produces the same result.
- Given a successful manual resolution, when `Balance with pending` and pending counts are recomputed on both affected registers, then they exclude that transfer entirely.
- Given a successful manual resolution, when the user expands row details, then the product explains that the missing side was added manually because no imported counterpart was expected.
- Given a manual resolution on an import-enabled peer account, when a later import preview contains a matching peer-side bank row with the same identity and payload, then that row is classified as `duplicate`, not `new`.
- Given that same scenario but the later imported row has the same identity and a different payload, when import preview runs, then that row is classified as `conflict`, not `new`.
- Given a pending transfer that is no longer eligible because it was already matched or changed, when the user tries to resolve it manually from stale UI state, then apply fails with no journal mutation.
- Given a pending transfer whose counterpart identity would immediately collide with existing journal/import state, when preview runs, then the product refuses the manual resolution and explains why.

## Proposed Sequence

1. Extend the register read model to expose an eligibility flag and stable resolution token for pending imported transfers, including synthetic peer pending rows.
2. Add backend preview/apply services that validate the source pending transfer, derive the counterpart transaction, compute synthetic import metadata, and fail closed on duplicate/conflict hazards.
3. Reuse the existing journal merge model to append the counterpart transaction in date order and update the source transaction metadata from `pending` to `matched`.
4. Add the transactions-page confirmation flow, success/error messaging, and detail copy for manually resolved transfers.
5. Add regression coverage for source-row launch, synthetic-peer launch, duplicate protection, conflict protection, stale-state rejection, and ineligible-transfer rejection.
6. Revisit transactions-page summary labels so the screen remains trustworthy once manually authored counterpart rows can appear in the register.

## Definition of Done

- A user can resolve an eligible pending imported transfer from `/transactions` without editing files.
- The original imported side becomes matched and the missing side appears as normal activity on the peer account.
- Pending sections, pending totals, and `Balance with pending` stop counting the resolved transfer.
- Future overlapping imports are protected by duplicate/conflict classification instead of silently creating duplicate balance movement.
- Ineligible or stale pending transfers fail closed with no partial write.

## Out of Scope

- General manual transaction entry from overview, accounts, or transactions
- Editable amount/date/payee fields for manual resolution
- A standalone transfer-repair workbench
- Bulk actions across multiple pending transfers

## Replacement Rule

Replace this file when the next active engineering task begins.
