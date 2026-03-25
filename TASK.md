# Current Task

## Objective

Make transfer metadata trustworthy by separating transfer linkage from transfer matching state. A tracked-to-tracked transfer should always preserve its relationship metadata, but only transfers that truly expect a second imported counterpart should ever surface pending or matched workflow state.

## Current Failure

- On March 23, 2026, the product still mixes two different concepts: `this transaction is a transfer` and `this transfer is waiting for a counterpart`.
- The current register logic can show a manually tracked receiving account as pending if the journal carries legacy `transfer_state: pending` metadata, even when no imported counterpart should ever arrive.
- The review/write path already distinguishes import-backed destinations from manual tracked destinations, but readers and undo logic still treat shared transfer metadata as if matching always applies.
- This creates a trust problem: persisted metadata can imply "waiting" even when the product meaning is "already final."

## Product Outcome

- Users can move money between tracked accounts without seeing false pending states on manually tracked destination accounts.
- Import-backed transfer pairs still keep the review, pending, match, and undo behaviors needed for counterpart-aware workflows.
- Manual tracked transfers still keep enough linkage metadata for auditability, explanations, and future tooling without pretending a second import is required.

## Proposed Metadata Model

- `transfer_id`: stable transfer relationship identifier shared by related transactions when applicable.
- `transfer_peer_account_id`: tracked account on the other side of the transfer relationship.
- `transfer_type`: explicit transfer workflow type.
- `transfer_match_state`: explicit counterpart-matching state.

### Transfer Types

- `direct`: the current transaction is already the final accounting event for this transfer. No imported counterpart is expected.
- `import_match`: this transfer participates in a counterpart-aware import flow and may wait on or link to another imported transaction.

### Match States

- `none`: no counterpart-matching workflow applies.
- `pending`: a counterpart is expected but has not arrived yet.
- `matched`: the counterpart has arrived and the transfer pair is resolved.

## System Invariants

- Transfer linkage and transfer matching are modeled separately. Workers must not reintroduce a single overloaded field that means both.
- A transfer may keep linkage metadata even when no counterpart-matching workflow applies.
- `direct` transfers never surface as pending or matched in product behavior.
- `import_match` transfers are the only transfers allowed to use `pending` or `matched`.
- A manually tracked destination account writes or normalizes to `transfer_type: direct` and `transfer_match_state: none`.
- An import-backed destination account writes `transfer_type: import_match` and starts in `pending` unless a counterpart is resolved immediately.
- Register, dashboard, review, undo, and any other reader must derive pending behavior from the explicit matching fields, not from the mere presence of transfer metadata.
- Legacy journals that only contain `transfer_state` must be read safely. The product must not show a false pending state for manual tracked destinations during the transition.

## Scope Cut Line

### Must Have

- Define the canonical transfer metadata contract in backend read and write paths using separate linkage and matching fields.
- Update transfer creation in review/unknown handling so manual tracked destinations and import-backed destinations write the correct metadata shape.
- Update register and any other transfer readers so pending UI only appears for transfers whose type and match state explicitly require it.
- Update undo/history behavior so only `import_match` transfers can be downgraded back to `pending`.
- Add compatibility handling for legacy transactions that still only carry `transfer_state` so old data does not leak false pending states.
- Cover the main direct-transfer and import-match-transfer cases with service-level tests.

### Should Have

- Normalize or migrate legacy transfer metadata when the app rewrites affected transactions so old and new shapes do not coexist indefinitely.
- Add a compact helper or shared transfer-state parser so every backend reader applies the same compatibility rules.

### Later

- Backfill older journals proactively instead of relying on read compatibility and opportunistic rewrites.
- Add richer diagnostic or audit views for transfer linkage history.

## End-to-End Workflow

1. A user reviews an unknown transfer-like transaction from an import-backed source account.
2. The user selects a tracked destination account.
3. The backend decides whether the destination requires counterpart matching.
4. The journal write persists linkage metadata and the correct transfer workflow metadata for that destination type.
5. The workspace reloads or the register/dashboard API is queried later.
6. Readers interpret the stored transfer type and match state consistently.
7. The UI shows either a normal posted transfer or a pending transfer state, depending on the explicit workflow metadata and not on guesswork from older fields.
8. If an import-backed matched transfer is later undone, the surviving side downgrades only when counterpart matching still applies.

## Acceptance Criteria

- Given a transfer from an import-backed checking account to a manually tracked vehicle account, when the transfer is accepted in review, then the journal stores transfer linkage plus `transfer_type: direct` and `transfer_match_state: none`, and no transfer-clearing pending workflow metadata is written.
- Given that same manual tracked transfer, when the transactions register is queried after reload, then the destination account shows a normal posted transfer row and no pending section or pending pill appears.
- Given a transfer from an import-backed checking account to an import-backed savings account with no counterpart imported yet, when the transfer is accepted in review, then the journal stores `transfer_type: import_match` and `transfer_match_state: pending`.
- Given that import-backed pending transfer, when the destination account register is queried after reload, then the destination account shows the pending transfer state exactly as before.
- Given an import-backed transfer whose counterpart arrives later, when matching resolves, then both sides persist as `transfer_type: import_match` with `transfer_match_state: matched`.
- Given a matched `import_match` transfer, when undo removes one side, then the surviving side is downgraded only if it still represents a counterpart-aware import flow.
- Given a legacy transaction that only contains `transfer_state: pending` and targets a manually tracked destination account, when the register is queried after this fix, then the app does not show that destination account as pending.
- Given a legacy transaction that only contains `transfer_state: pending` and targets an import-backed destination account, when the register is queried after this fix, then the app preserves the pending behavior until the transaction is rewritten or resolved.

## Failure Behavior

- If transfer metadata is present in an invalid combination such as `direct + pending`, the backend must normalize or treat it as non-pending rather than surfacing a contradictory UI state.
- If a reader encounters partial transfer metadata, it must fail closed toward a non-pending direct presentation unless the data clearly indicates a valid counterpart-aware import flow.
- If undo or rewrite logic cannot preserve a valid transfer state combination, it must stop with a clear error instead of silently inventing a misleading pending state.

## Regression Risks

- Readers may accidentally keep checking legacy `transfer_state` first and bypass the new explicit model.
- Manual tracked transfers may still be rewritten into transfer-clearing accounts if only part of the review path is updated.
- Undo may continue to downgrade any shared `transfer_id` blindly, which would reintroduce false pending states after the initial write path is fixed.
- UI code may keep using `pending` as a proxy for "is a transfer" and hide or mislabel direct tracked transfers.
- Mixed old/new metadata in the same workspace could create inconsistent behavior unless compatibility rules are centralized.

## Proposed Sequence

1. Define a canonical transfer metadata helper that parses both legacy and new shapes into one internal model.
2. Update review/unknown write logic to emit `direct + none` for manual tracked destinations and `import_match + pending|matched` for import-backed destinations.
3. Update register and related readers to drive pending behavior from the canonical model only.
4. Update undo/history logic so only counterpart-aware transfers can downgrade to `pending`.
5. Add regression tests for manual direct transfers, import-backed pending transfers, matched transfers, undo, and legacy compatibility.

## Out of Scope

- Redesigning the review UI beyond what is required to reflect the corrected transfer semantics
- Removing transfer linkage metadata from manual tracked transfers
- Broad journal migration tooling beyond the minimum compatibility or opportunistic normalization needed for this cut

## Definition of Done

- The persisted transfer model makes transfer linkage and counterpart-matching semantics explicit.
- Manual tracked destination accounts no longer show false pending states after reload.
- Import-backed destination accounts still preserve pending and matched workflows across write, reload, read, and undo.
- Legacy transfer metadata is handled safely enough that workers can ship this change without forcing immediate manual journal cleanup.

## Replacement Rule

Replace this file when the next active engineering task begins.
