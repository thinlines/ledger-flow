# Reconciliation Duplicate Review + Durable Resolution (8d)

**Status: ACTIVE — 2026-05-02**

## Objective

When reconciliation reaches a zero ticked diff but the backend still rejects the assertion, the route should help the user review likely duplicate transactions and resolve them durably. Manual-only duplicates may be removed. Imported duplicates must be resolved in a way that prevents the same bank rows from reappearing on the next import.

## Scope

### Included

1. **General review filters on `/accounts/:accountId/reconcile`.** Keep route-level review controls for `Remaining`, `Checked`, and `All` so the user can inspect what was included versus left out before and after an assertion failure.
2. **Zero-diff 422 duplicate-review mode.** On `assertion_failed` when the review diff was zero at submit time, the route computes and surfaces *possible duplicate* groups instead of jumping straight to a delete suggestion.
3. **Shared duplicate-candidate heuristic slice.** Reuse and tighten the existing unknowns/manual-match logic for reconciliation review:
   - same account only
   - exact absolute amount match required
   - narrow date window
   - payee similarity as a supporting signal
   - no `close amount`-only candidate tier in this flow
   This heuristic slice must be strict enough that the route never suggests an obviously unrelated pair.
4. **Duplicate groups anchored on checked rows.** The duplicate-review view shows each checked transaction alongside matching unchecked transactions, sorted by confidence. Each row shows:
   - date
   - payee
   - signed amount
   - source badge: `Imported` or `Manual`
   - why it was paired, in plain language
5. **Source-aware resolution actions.** The route offers different actions depending on the source mix:
   - **Checked imported + unchecked manual:** `Remove manual duplicate`
   - **Checked manual + unchecked imported:** `Use imported transaction`
   - **Checked imported + unchecked imported:** `Merge imported duplicates`
   - **Checked manual + unchecked manual:** `Remove manual duplicate`
6. **Manual-to-import replacement path.** `Use imported transaction` reuses the existing unknowns-style match semantics where practical: the imported transaction survives, user-authored categorization/metadata carries over as appropriate, the manual duplicate is archived/removed through the established match substrate, and the imported survivor becomes the checked row in the reconciliation view.
7. **Minimal imported-duplicate merge path.** `Merge imported duplicates` lands the core durable merge substrate now, but only for reconciliation duplicate-review groups in this task. The surviving imported transaction preserves both transactions’ import identity metadata so either bank-row variant is recognized in future imports. The generic transactions-page multi-select merge UI remains Feature 9b.
8. **Route refresh and tick preservation after resolution.** After a delete, replace, or merge action, the route refetches context and preserves the user’s reconciliation intent:
   - surviving checked rows remain checked
   - when a checked manual row is replaced by an unchecked imported row, the imported survivor is checked automatically
   - removed rows disappear from the tick set
9. **Single-row delete from the general list.** Outside duplicate-review mode, a deletable row can still be removed from its row menu, but the route does not offer a bulk “delete all remaining” shortcut.

### Explicitly Excluded

- A blanket `Delete remaining unreconciled transactions` action.
- A generic non-zero-diff completion dialog with `Add adjustment`. Adjustment posting remains **8i**.
- Full generic transactions-page merge UI or multi-select merge workflow. That remains **9b** after the reconciliation-scoped merge substrate lands.
- Subset-sum assistance (**8e**).
- Assertion rendering across surfaces (**8f**).
- Root-cause analytics or blame-oriented UI explaining *why* a duplicate exists. This task resolves the bookkeeping problem; it does not diagnose whether the cause was bank CSV drift, missed review matching, or user error.

## System Behavior

### Inputs

- User filters the reconciliation list by `Remaining`, `Checked`, or `All`.
- User clicks `Reconcile` with a zero diff.
- Backend returns 422 `assertion_failed`.
- User opens duplicate-review mode from the rejection state.
- User chooses one of the source-aware resolution actions on a duplicate candidate.
- User confirms the destructive or merge action.

### Logic

- The primary `Reconcile` button remains gated on the same backend-safe condition as 8c: setup valid, context loaded, not submitting, and diff exactly zero.
- After a zero-diff 422, the route computes possible duplicate groups by comparing **checked** rows against **unchecked** rows in the current period using the tightened heuristic slice.
- A duplicate candidate requires an exact absolute amount match. Payee similarity and date proximity rank candidates; they do not rescue mismatched amounts.
- The route labels candidate groups as **possible duplicates**, not certain duplicates.
- Resolution is source-aware:
  - If the unchecked row is manual-only and safe to delete, the route offers removal.
  - If the unchecked row is imported and the checked row is manual, the route offers `Use imported transaction`, not raw delete.
  - If both rows are imported, the route offers `Merge imported duplicates`, not raw delete.
- `Use imported transaction` keeps the imported row as the durable survivor because future imports can only dedupe against import metadata, not a deleted imported row.
- `Merge imported duplicates` keeps one imported survivor, removes the extra imported row, and preserves both transactions’ import identity metadata on the survivor so future imports of either bank-row variant collapse safely.
- If the route finds no sufficiently strong duplicate candidates, it falls back to the 8c-style rejection copy plus the normal `Remaining` / `Checked` / `All` review controls. No destructive shortcut appears.

### Outputs

- The reconcile route gains a duplicate-review mode for zero-diff 422 failures.
- The duplicate-review mode presents checked rows paired with likely unchecked duplicates.
- Manual duplicates can be removed safely.
- Imported duplicates can be resolved durably through replace or merge actions.

## System Invariants

- The app must never suggest a duplicate candidate on `close amount` alone.
- Imported duplicates are not resolved by a default raw delete action if doing so would allow the same import to come back later.
- `Use imported transaction` and `Merge imported duplicates` must preserve future import idempotency.
- The route must not claim certainty when it only has heuristics; use `Possible duplicate` language.
- The user must review and confirm every destructive or merge action before it writes.
- The route does not surface internal terms such as `ledger`, `journal`, or `source_payload_hash` in default-path copy.

## States

- **Review ready:** normal route with `Remaining`, `Checked`, and `All` filters.
- **Assertion failed, generic:** zero-diff or non-zero-diff failure with no safe duplicate candidates; show 8c rejection copy only.
- **Assertion failed, duplicate-review available:** zero-diff 422 with one or more likely duplicate groups; show a `Possible duplicates` review surface.
- **Candidate action confirm:** user is confirming remove, replace, or merge for one candidate.
- **Resolution in progress:** route is applying the chosen duplicate-resolution action.
- **Resolution applied:** route refreshed, candidate groups recomputed, tick state preserved around the survivor.

## Edge Cases

- **Checked manual + unchecked imported duplicate.** The durable action is `Use imported transaction`, not delete the imported row.
- **Two imported duplicates with changed bank descriptions.** Merge is the only durable route-level fix in this task; deleting one imported row is insufficient.
- **Multiple unchecked candidates match one checked row.** Show them ranked; do not auto-resolve.
- **A row qualifies for duplicate review but is not safely mutable.** Show it in the review surface without an action.
- **User resolves one candidate and others remain.** Refresh context, preserve the surviving checked rows, and recompute duplicate groups.
- **User changes tick selections after seeing duplicate review.** Duplicate groups recompute from the new checked/unchecked split.

## Failure Behavior

- **Remove manual duplicate fails:** show inline error, preserve current state, and do not alter the tick set.
- **Use imported transaction fails:** show inline error, preserve both rows, and do not change which row is checked.
- **Merge imported duplicates fails:** show inline error, preserve both rows, and do not partially rewrite import metadata.
- **Context refresh fails after a successful resolution:** show a recoverable error banner and disable further destructive actions until the route is refreshed.

## Regression Risks

- **Heuristic trust failure.** Reusing the old `close amount` behavior would recreate the >$400 wrong-candidate bug that triggered 9a.
- **Survivor-selection drift.** Manual-to-import replacement must leave the imported survivor checked or the route will silently lose the user’s reconciliation intent.
- **Import-idempotency regression.** Imported-duplicate merge is pointless if the survivor does not retain both identities needed to suppress future re-imports.
- **Scope bleed from 9b.** The reconciliation route only needs the merge substrate and reconciliation-scoped UI, not the full generic merge surface.

## Acceptance Criteria

- The reconcile route keeps `Remaining`, `Checked`, and `All` list filters.
- On a zero-diff 422 `assertion_failed`, the route surfaces possible duplicate groups when strong candidates exist.
- Each duplicate group shows a checked transaction and one or more matching unchecked transactions with source badges and plain-language match reasons.
- The duplicate-review heuristic requires an exact amount match and does not surface `close amount`-only candidates.
- Checked imported + unchecked manual pairs offer `Remove manual duplicate`.
- Checked manual + unchecked imported pairs offer `Use imported transaction`.
- Checked imported + unchecked imported pairs offer `Merge imported duplicates`.
- `Use imported transaction` leaves the imported survivor checked after refresh.
- `Merge imported duplicates` preserves future import dedupe for both bank-row variants.
- The route does not offer a blanket `Delete remaining unreconciled transactions` action.
- `pnpm check` passes and `uv run pytest -q` passes.

## Proposed Sequence

1. **Heuristic tightening.** Extract or reuse the unknowns/manual-match candidate logic, then narrow it for reconciliation duplicate review so exact-amount matching is mandatory.
2. **Context expansion.** Add the row metadata the route needs for source badges and source-aware actions.
3. **Duplicate-review UI.** Add the zero-diff 422 candidate surface grouped by checked row.
4. **Manual duplicate actions.** Implement route-level manual delete and manual-to-import replacement.
5. **Imported merge substrate.** Land the reconciliation-scoped imported-duplicate merge path that preserves both import identities on the survivor.
6. **Regression verification.** Exercise manual/imported mixed pairs, imported/imported pairs with changed payees, no-candidate fallback, and tick-preservation after every action.

## Definition of Done

- All acceptance criteria pass.
- Zero-diff 422 no longer funnels the user toward a blunt delete-everything choice.
- Imported duplicates can be resolved durably enough that the same bank-row variant does not simply reappear on the next import.
- The task leaves the full transactions-page merge UI for 9b instead of over-expanding reconciliation.

## UX Notes

- The rejection state should lead with the user’s money question, then the likely cause:
  `Your checked balance matches the statement, but we found transactions you left out that look like duplicates.`
- Use `Possible duplicate` language, not definitive or accusatory language.
- Source badges should be plain: `Imported` and `Manual`.
- Do not explain root cause in-product beyond what the data supports. The user needs a repair path more than a theory.

## Out of Scope

- Generic non-zero-diff completion escape hatches.
- Full transactions-page merge UX.
- Investigating or logging why the duplicate was not resolved earlier.

## Dependencies

- 8a backend reconcile endpoint and 8c route are shipped.
- Unknowns/manual-match heuristics are the starting point, but must be tightened for reconciliation use.
- 9a’s heuristic-fix concern is effectively a prerequisite slice of this task.
- 9b’s full merge UX remains later, but this task pulls forward the minimum merge substrate needed for reconciliation.

## Decisions

- **Decision:** In zero-diff 422, the primary recovery surface is duplicate review, not bulk cleanup.
- **Decision:** Imported duplicates require durable resolution, not raw delete.
- **Decision:** The reconciliation route may pull forward a minimal merge substrate from 9b, but not the full generic merge UI.
- **Decision:** The product should not try to answer “why wasn’t this merged earlier?” in the task copy. Resolve the bookkeeping problem first.
