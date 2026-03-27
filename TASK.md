# Current Task

## Title

Auto-reconcile bilateral pending import-match transfers

## Objective

When both sides of a transfer between two import-enabled tracked accounts have already been imported and are both showing as pending, the product should automatically recognize them as the same transfer, remove both from pending sections, and display them as normal matched activity — without the user needing to do anything.

## Current Failure

The screenshot shows two separate -$2,000.00 pending rows on the Wells Fargo Checking register:

1. The WF-side imported transaction (Mar 2): the actual debit that left WF.
2. A synthetic peer entry generated from the ICCU-side imported transaction (Mar 4): money that arrived at ICCU.

Both rows show as negative. Both say "Transfer · ICCU Checking (Pending)". There is no sign, label, or directionality cue to distinguish them. The user has no way to understand the state and no way to resolve it without editing files.

### Root Cause

The import pipeline assigns a `transfer_id` independently per import run. When the WF CSV was imported first, a transfer was created with `transfer_match_state: pending`. When the ICCU CSV was imported later, the importer failed to find and link the WF pending transaction — likely because the dates differ by two days — so ICCU got its own `transfer_id` and its own `pending` state.

Both transactions now carry `transfer_match_state: pending` and each correctly identifies the other's account as `transfer_peer_account_id`. But because they have different `transfer_id`s, no existing code path recognizes them as a matched pair.

The display then compounds the trust damage: `_pending_transfer_event_for_peer_account` generates a synthetic peer entry for the ICCU transaction on the WF register. This creates two -$2,000.00 pending rows, both from WF's perspective, with nearly identical labels.

### Why "Resolve manually" Does Not Help

The existing "Resolve manually" flow is for the case where NO imported counterpart will arrive. Here, both counterparts are already imported. Offering "Resolve manually" is incorrect — it would create a third duplicate transaction and would likely fail the duplicate-identity check.

## Scope

### Included

- Add a read-time bilateral-match detection pass (analogous to `_grouped_settled_pending_transfer_orders`) that identifies pending import-match transaction pairs where:
  - Both transactions are classified `import_match` with `transfer_match_state: pending`.
  - Each transaction's `transfer_peer_account_id` points to the other transaction's source tracked account.
  - The absolute posting amounts are equal.
  - The posted dates are within `MAX_TRANSFER_MATCH_DAYS` of each other.
  - The pair is unambiguous: exactly one candidate on each side.
- Exclude bilaterally-matched pairs from all pending sections, pending counts, and Balance with pending — identical to how grouped-settled transfers are excluded today.
- Display bilaterally-matched transactions as posted matched-transfer activity on both account registers, not as pending rows.
- Suppress the synthetic peer event for any transaction whose bilateral match is detected; the real peer transaction will appear directly in the peer account's register.
- Add regression tests covering: bilateral match removes both rows from pending, bilateral match appears as posted activity on both registers, ambiguous pair (two same-amount transfers in the same window between the same accounts) fails closed to pending, date-gap boundary.

### Explicitly Excluded

- Any journal writes to update `transfer_match_state` or `transfer_id` metadata (read-time resolution only, following the grouped-settlement pattern).
- Manual link UI for ambiguous pairs.
- Fee-adjusted transfer matching (amounts differ slightly due to bank fees).
- Import-time matching improvements (fixing the pipeline that created this state in the first place — separate task).
- Editing or reordering transfer pair display in the UI beyond what is needed to fix the trust issue.

## Eligibility Rule

A bilateral match is recognized when all of the following are true:

1. Transaction A is `import_match` / `pending` on tracked account X, with `transfer_peer_account_id = Y`.
2. Transaction B is `import_match` / `pending` on tracked account Y, with `transfer_peer_account_id = X`.
3. A's absolute amount equals B's absolute amount.
4. A and B are within `MAX_TRANSFER_MATCH_DAYS` of each other.
5. No other pending import-match transaction on either account X or account Y has the same absolute amount and the same transfer pair account and a date within `MAX_TRANSFER_MATCH_DAYS` of A or B (unambiguous).

If condition 5 fails (ambiguous), the pair must remain pending with no bilateral match applied.

## System Behavior

### Inputs

- Any call to `build_account_register` loads all transactions and computes bilateral matches as part of the pending-state pass.

### Logic

- Load all transactions.
- Collect all pending import-match candidates, grouped by their `transfer_pair_account`.
- For each group, identify candidate pairs (one from each side of the pair account) where amounts are equal-and-opposite and dates are within window.
- A pair is promoted to bilateral-matched only if each side has exactly one eligible candidate in the window; if either side has multiple, the group fails closed and both remain pending.
- Bilateral-matched orders are excluded from pending sections the same way grouped-settled orders are excluded today.
- For transactions in a bilateral-matched pair, suppress the synthetic peer event; the real peer transaction will appear as matched activity on the peer register instead.
- The matched display on each account shows the transaction as posted, with summary "Transfer · {peer account name}" (no "(Pending)" suffix), and with correct directionality (the source account's posting amount, sign preserved).

### Outputs

- Pending sections on both affected registers no longer show either row of a bilaterally-matched pair.
- Both registers show the matched transfer as normal posted activity.
- Balance with pending excludes bilaterally-matched transfers.
- Pending counts exclude bilaterally-matched transfers.

## System Invariants

- Pending UI must represent genuinely unresolved work only. Bilaterally-matched pairs are not unresolved work.
- No journal text may be written or rewritten by this change.
- Ambiguous pairs must remain pending; the system must not silently match the wrong transactions.
- The grouped-settlement detection path is unchanged.
- The manual-resolution eligibility check must exclude bilaterally-matched pairs (they are already resolved and should not offer "Resolve manually").

## States

- **Default (bilateral match detected)**: neither row appears in pending; both appear in posted activity.
- **Default (no match / ambiguous)**: rows remain in pending as today, "Resolve manually" remains available on the eligible row.
- **Empty**: no change from today.

## Edge Cases

- Two same-amount transfers between the same two accounts in the same seven-day window (e.g., two $500 transfers in March). The system cannot safely determine which WF row matches which ICCU row. Both pairs must remain pending. Neither should be auto-matched.
- One side of the pair is a grouped-settled transfer. The bilateral match check must not apply to orders that are already grouped-settled.
- A bilaterally-matched pair where one transaction has already been manually resolved (metadata shows `transfer_match_state: matched`). The bilateral check only applies to pairs where both sides are still `pending`; a matched transaction is ineligible.
- Date boundary: two transactions exactly `MAX_TRANSFER_MATCH_DAYS` apart should still match; `MAX_TRANSFER_MATCH_DAYS + 1` should not.
- The "Resolve manually" token must not be exposed on a bilateral-match row. The eligibility function must check for bilateral-match status the same way it checks for grouped-settled status.
- A pending transfer whose peer account has been removed from config since import. The bilateral match requires both accounts to be resolvable in current config; if either is missing, fail closed to pending.

## Failure Behavior

- If the bilateral match cannot be computed safely (missing account config, ambiguous candidates, amounts do not balance), the transactions must remain pending.
- If detection logic throws, the register must still load with both transactions in pending rather than failing the page.

## Regression Risks

- Over-broad matching could silently remove genuinely unresolved transfers from the pending view.
- The synthetic peer suppression must be tightly scoped: only suppress the synthetic peer when the source transaction is bilaterally matched. An unmatched peer transaction must still generate a synthetic event on the other account's register.
- Pending counts and Balance with pending are trust-critical; the bilateral exclusion must use the same mechanism as grouped-settlement exclusion.
- The grouped-settlement detection remains unchanged; bilateral logic must not interfere with it.
- "Resolve manually" must not appear on bilateral-matched rows; the eligibility check must gate on bilateral match the same way it gates on grouped settlement.

## Acceptance Criteria

- Given a WF transaction dated Mar 2 (debit -$2,000, peer: ICCU, pending) and an ICCU transaction dated Mar 4 (credit +$2,000, peer: WF, pending), when either register is loaded, neither row appears in the pending section and both registers show the transaction as posted matched-transfer activity.
- Given that same pair, when Balance with pending and pending counts are computed, neither transaction contributes to pending totals.
- Given that same pair viewed from the WF register, the posted row shows the correct debit amount and a description indicating the transfer went to ICCU.
- Given that same pair viewed from the ICCU register, the posted row shows the correct credit amount and a description indicating the transfer came from WF.
- Given two $500 pending transactions from WF to ICCU on the same day and two $500 pending transactions from ICCU to WF two days later, when the register is loaded, all four remain pending (ambiguous — system cannot determine which pairs correspond).
- Given a bilateral match that falls exactly `MAX_TRANSFER_MATCH_DAYS` apart, both rows are matched. Given a pair `MAX_TRANSFER_MATCH_DAYS + 1` apart, both remain pending.
- Given a bilateral-matched pair, "Resolve manually" is not shown on either row.
- Given a single-sided pending transfer (ICCU has no matching pending row), the WF register continues to show the existing synthetic peer event and "Resolve manually" button.

## Proposed Sequence

1. Add `_bilateral_matched_pending_transfer_orders(config, transactions) -> set[int]` in `account_register_service.py`, following the structure of `_grouped_settled_pending_transfer_orders`. Returns the set of transaction orders that are part of unambiguous bilateral matches.
2. Merge the bilateral-matched orders with the grouped-settled orders in the single exclusion set used throughout `build_account_register`. No other caller changes needed for correctness.
3. Update `_pending_transfer_event_for_peer_account` to suppress the synthetic peer event when the source transaction's order is bilateral-matched (same guard as grouped-settled).
4. Update `_manual_resolution_token` to return `None` for bilateral-matched transactions (same guard as grouped-settled).
5. Update the register's posted-activity path to display bilateral-matched transactions with the correct matched-transfer summary and without "(Pending)" suffix.
6. Add regression tests for: standard bilateral match, ambiguous same-amount pair, date-boundary cases, single-sided pending still generates synthetic peer, "Resolve manually" absent on bilateral-match rows.

## Definition of Done

- Both sides of a bilaterally-matched transfer disappear from pending on both registers.
- Both sides appear as posted matched-transfer activity on their respective registers with correct amounts and directionality.
- Pending counts and Balance with pending exclude the pair.
- Ambiguous pairs remain pending.
- All existing tests continue to pass.
- "Resolve manually" is hidden on bilateral-match rows.

## Out of Scope

- Journal metadata writes for bilateral match resolution
- Import-time fix to prevent this state from arising in the first place
- Manual link UI for ambiguous pairs
- Fee-adjusted transfer matching

## Replacement Rule

Replace this file when the next active engineering task begins.
