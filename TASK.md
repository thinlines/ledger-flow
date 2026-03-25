# Current Task

## Objective

Stop balanced grouped ACH verification transfers from surfacing as permanent pending work. When multiple imported transfer rows between the same tracked accounts settle through the same transfer-clearing pair account, the UI should treat them as settled even if the current matcher cannot map them 1:1.

## Current Failure

- On March 24, 2026, the product still treats pending transfer UI as a pure 1:1 matching problem.
- ACH account verification often lands as `2:1` or `1:2` imported rows, such as two microdeposits on one side that sum to one imported withdrawal on the other.
- The journals and transfer-clearing pair account can already balance correctly, but the register still labels those rows as pending forever and tells the user they are still waiting to import.
- This creates false pending work, misleading `Balance with pending` summaries, and weakens trust because the ledger truth and the UI story disagree.

## Product Outcome

- Users no longer see ACH verification transfers as permanently pending once both sides are already present and the grouped movement is financially settled.
- The register keeps showing the real imported rows and amounts instead of inventing a fake merged transaction.
- Pending sections, pending pills, and `Balance with pending` are reserved for genuinely unresolved transfer imports.

## Delivery Target

Protect UX trust and scope discipline by fixing the misleading pending presentation without opening a full many-to-many matching project.

### In Scope

- Detect conservative grouped transfer settlements from loaded journal activity.
- Remove grouped settled transfers from pending UI and pending totals.
- Show those rows as normal imported activity with a compact explanation that they settled as part of a grouped transfer.

### Out of Scope for This Cut

- Rewriting journal metadata to create explicit many-to-many transfer links
- A manual grouped-transfer resolution tool
- Expanding unknown review into a general transfer-matching workbench

## Derived Presentation Model

- `pending`: imported transfer activity is still missing, incomplete, or too ambiguous to treat as settled safely.
- `settled_grouped`: multiple imported transfer rows jointly settle across the same tracked-account pair and should no longer surface as pending work.
- `posted`: direct transfers and ordinary non-pending activity.

`settled_grouped` is a read-time presentation state, not a new journal persistence contract.

## System Invariants

- Pending UI must represent unresolved work, not just the absence of a 1:1 match.
- A grouped transfer may settle as `1:2`, `2:1`, or another small zero-sum combination; exact pairwise linkage is not required for the UI to stop calling it pending.
- Grouped settlement must be derived from actual loaded journal transactions for the relevant transfer pair account, not from guesswork or manual memory.
- The product must not synthesize a merged replacement transaction. Original imported rows, dates, and amounts remain visible.
- Grouped settlement must not rewrite journals, change import history, or change account balances.
- Synthetic pending peer events must not remain visible once the corresponding grouped transfer is already settled by real imported activity.
- Detection must be conservative. If multiple plausible groupings exist or the system cannot prove a coherent zero-sum settlement safely, the rows stay pending.
- `Balance with pending` and any pending counts must exclude grouped-settled transfers.

## End-to-End Workflow

1. A user reviews imported ACH verification activity between two tracked accounts.
2. The first imported row is accepted as a transfer and initially surfaces as pending because its counterpart has not arrived yet.
3. Additional imported transfer rows later arrive on one or both sides, and together they fully offset through the same transfer pair account.
4. The workspace reloads or the account register API is queried.
5. Backend readers detect a conservative grouped settlement from the loaded journal transactions for that tracked-account pair.
6. The register API exposes those rows as grouped-settled rather than pending.
7. The transactions page shows the original imported rows in normal activity, removes them from pending sections and pending totals, and explains that they settled as part of a grouped transfer.

## Acceptance Criteria

- Given two imported savings-account transfer rows of `+$0.12` and `+$0.34` on March 12, 2026 and one imported checking-account transfer row of `-$0.46` on March 12, 2026, when all three rows are loaded and they share the same transfer pair account, then neither account register shows any of those rows in a pending section.
- Given that same grouped ACH verification example, when the savings register is queried, then the two imported savings rows remain visible as separate activity rows with their original amounts and dates rather than being collapsed into one synthetic entry.
- Given that same grouped ACH verification example, when the checking register is queried, then the `-$0.46` imported row remains visible as normal activity and `Balance with pending` equals imported balance if there are no other unresolved pending transfers.
- Given a grouped-settled transfer row in the register, when the user expands details, then the UI explains that the row settled as part of a grouped transfer instead of saying it is still waiting to import.
- Given a transfer pair where the imported rows do not net to zero, when the register is queried, then only the unresolved residue remains pending and still contributes to pending totals.
- Given multiple same-account-pair transfers inside the match window that do not yield one safe grouped settlement, when the register is queried, then the product fails closed and keeps those rows pending instead of hiding them.
- Given an ordinary `1:1` import-matched transfer, when the register is queried after this change, then existing non-grouped pending and matched behavior remains unchanged.
- Given a direct transfer to a manually tracked destination account, when the register is queried after this change, then it still shows as normal posted activity with no new grouped-transfer labeling.

## Failure Behavior

- If grouped-settlement detection cannot partition candidate rows into a safe zero-sum group, the product must leave them pending rather than declaring them settled.
- If grouped-settlement presentation would cause a synthetic pending peer event and a real imported row to both remain visible for the same settled movement, the reader must suppress the synthetic pending event.
- If a grouped transfer is treated as settled in UI, it must not change `currentBalance`, transaction counts, or imported activity ordering relative to the underlying journal rows.
- If a candidate group spans beyond the supported matching window, the product must fail closed to pending until a broader design is explicitly implemented.

## Regression Risks

- Over-grouping unrelated same-day transfers between the same tracked accounts could hide real unresolved work.
- Under-grouping would leave the original trust problem in place and keep ACH verification rows pending forever.
- Register summaries could double-count or misstate pending totals if grouped-settled rows are removed from the pending list but still included in pending math.
- UI copy may continue promising that grouped-settled rows are `waiting to import` unless the explanatory text is updated alongside the backend state.
- This cut could accidentally bleed into unknown-review suggestion logic or journal metadata writes if workers try to solve the problem by broadening matching instead of fixing read-time presentation.

## Proposed Sequence

1. Define a conservative grouped-settlement detector in backend read paths using transfer pair account, tracked peers, amounts, and the existing transfer match window.
2. Extend the account register read model so grouped-settled rows are exposed separately from true pending rows, and synthetic pending peer events are suppressed when real imported activity already settles the group.
3. Update the transactions page to exclude grouped-settled rows from pending sections and pending totals while showing a compact grouped-settlement explanation in row details.
4. Add regression coverage for `2:1`, `1:2`, unresolved residue, ambiguous same-window groups, and existing direct/ordinary `1:1` transfer behavior.

## Definition of Done

- Balanced grouped ACH verification transfers no longer appear as permanent pending work after reload.
- Original imported rows remain visible with unchanged balances and ordering.
- Pending counts and `Balance with pending` only reflect genuinely unresolved transfer imports.
- Ambiguous cases fail closed to pending instead of silently hiding activity the product cannot explain confidently.

## Replacement Rule

Replace this file when the next active engineering task begins.
