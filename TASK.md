# Match-Suggestion Ranking Fix (9a)

## Objective

Fix the unknowns review queue's match-suggestion heuristic so it stops surfacing implausible candidates — e.g., a manual entry with a >$400 amount delta and an unrelated payee appearing as a "Close amount" match.

## Scope

### Included

1. **Replace the 4-tier system in `find_match_candidates()` with continuous scoring.** The current tier model (`date_exact_amount` / `date_close_amount` / `date_payee` / `payee_only`) has two broken tiers:
   - **Tier 2 (`date_close_amount`):** accepts *any* amount delta as long as both amounts are non-null and the dates are within 3 days. A $50 manual entry matches a $500 import.
   - **Tier 4 (`payee_only`):** accepts case-insensitive substring matches with no date or amount constraint. "AT&T" matches "AT&T Payment" but also "BATTERY PLUS" via substring.
   Replace with a scored model where each signal contributes a weighted score and candidates below a minimum threshold are rejected.

2. **Upgrade payee matching from substring containment to normalized token-set similarity.** Reuse or extract the `_normalize_payee()` and `_payee_similarity()` functions from `reconciliation_duplicate_service.py` into a shared module. The reconciliation flow already demonstrates the correct approach: noise-word removal, plural normalization, token-set ratio, and a single-token `SequenceMatcher` fallback.

3. **Add amount-proximity scoring with tolerances.** Replace the binary `exact_amount` / `close_amount` split with a continuous score:
   - Exact match (delta = 0): full score.
   - Within tolerance (delta ≤ 5% of the smaller absolute value, capped at $5.00): partial score, decaying with delta size.
   - Outside tolerance: zero score — candidate rejected on amount alone.
   This prevents the $50-vs-$500 case while still allowing small rounding differences (e.g., $49.95 vs $50.00).

4. **Apply a minimum combined score threshold.** Candidates must clear a floor to appear in the list. The floor rejects low-confidence noise (weak payee + moderate date + no amount signal) without requiring every signal to be strong.

5. **Preserve auto-suggestion behavior.** When exactly one candidate scores above a high-confidence threshold (equivalent to today's tier-1: exact amount + close date + strong payee), auto-populate `suggestedMatchId`. The threshold must be strict enough that auto-suggestion never fires on a dubious candidate.

6. **Update the frontend quality labels.** The unknowns page renders `matchQualityLabel()` with labels like "Exact match", "Close amount", "Payee match", "Payee only". Replace with score-derived labels: `"Strong match"`, `"Likely match"`, `"Possible match"`. Show a human-readable reason string (similar to 8d's `_candidate_reason()`) in the candidate row.

7. **Update or add backend tests.** Cover: exact-match scoring, amount-tolerance boundary (just inside and just outside 5%), payee-similarity edge cases (substring that should *not* match, token-set match that should), minimum-threshold rejection, auto-suggestion gating.

### Explicitly Excluded

- Changes to the reconciliation duplicate heuristic in `reconciliation_duplicate_service.py`. That code is already correct; this task backports its quality to the unknowns flow.
- Changes to the unknowns apply/stage flow. Only the candidate-finding and ranking logic changes.
- Multi-select or merge UI on the unknowns page.

## System Behavior

### Inputs

- User scans unknowns via `POST /api/unknowns/scan`.
- Backend calls `populate_match_candidates()` → `find_match_candidates()` for each unknown transaction.
- Each candidate is scored against the import transaction's date, amount, and payee.

### Logic

- **Payee similarity** is computed via the shared `_payee_similarity()` function (token-set ratio with noise-word removal). Score range: 0.0–1.0.
- **Amount proximity** is computed as a continuous score:
  - 0 delta → 1.0
  - Within tolerance → linear decay from 1.0 to 0.3
  - Outside tolerance → 0.0
- **Date proximity** decays from 1.0 (same day) toward 0.0 as `date_diff` approaches and exceeds `MAX_MANUAL_MATCH_DAYS` (3 days). Candidates beyond the window can still appear if amount + payee are strong, but date contributes zero.
- **Combined score** is a weighted sum of the three signals: `amount_score * W_AMT + payee_score * W_PAYEE + date_score * W_DATE`. Weights should favor amount (most reliable signal), then payee, then date.
- Candidates with combined score below `MIN_MATCH_SCORE` are dropped.
- Candidates are sorted by descending combined score (not ascending tier).
- Auto-suggestion fires when exactly one candidate scores above `AUTO_SUGGEST_THRESHOLD` (a high bar).

### Outputs

- `matchCandidates` array on each unknown transaction row, sorted by descending score.
- Each candidate gains: `matchScore` (float), `matchReason` (human-readable string), `matchQuality` (one of `"strong"`, `"likely"`, `"possible"`).
- `suggestedMatchId` populated only for high-confidence single candidates.
- The old `matchTier` field is removed (breaking change scoped to the unknowns scan response — no external consumers).

## System Invariants

- A candidate must never appear based on amount proximity alone when the delta exceeds the tolerance.
- Substring containment (e.g., "AT&T" in "BATTERY PLUS") must not produce a high payee similarity score.
- Auto-suggestion must never fire on a candidate that a human would consider dubious.
- The scoring function must be deterministic and produce identical results for identical inputs.

## States

- **No candidates:** "No manual entries found for this account." (unchanged)
- **Candidates below threshold:** same as no candidates — they are filtered out.
- **Candidates above threshold:** rendered in the match dropdown, sorted by score.
- **Single high-confidence candidate:** auto-suggested (dropdown pre-selected).

## Edge Cases

- **Identical amounts, unrelated payees, same day.** Should still appear (amount is the strongest signal) but at "Likely match" or "Possible match", not "Strong match".
- **Similar payees, wildly different amounts.** Rejected by the amount tolerance. Does not appear.
- **One-character payee overlap.** `_payee_similarity()` returns 0.0 for short substrings; candidate rejected.
- **Manual entry with no amount (elided posting).** Amount score is 0.0. Candidate can only qualify on payee + date, which requires a very strong payee match.
- **Multiple candidates above auto-suggest threshold.** No auto-suggestion — the user must choose.

## Failure Behavior

- If `_payee_similarity()` raises on malformed input, treat payee score as 0.0 and continue scoring.
- If `find_match_candidates()` raises, `populate_match_candidates()` catches per-transaction and continues (existing behavior).

## Regression Risks

- **Over-filtering.** If tolerances are too tight, legitimate matches that users previously relied on disappear. The amount tolerance (5% or $5) and payee threshold (reusing 8d's `SIMILAR_PAYEE_MIN = 0.72`) are intentionally generous — err toward showing a "Possible match" rather than hiding a real one.
- **Auto-suggestion regression.** If `AUTO_SUGGEST_THRESHOLD` is too low, the unknowns page pre-selects wrong matches. Keep it at least as strict as the old tier-1 requirement (exact amount + close date).
- **Frontend label breakage.** The `matchQualityLabel()` switch statement must be updated to handle the new quality strings; old strings removed.

## Acceptance Criteria

- `find_match_candidates()` no longer returns candidates with amount deltas exceeding 5% of the smaller value (capped at $5.00).
- `find_match_candidates()` no longer returns candidates on payee substring containment alone; payee scoring uses normalized token-set similarity.
- Candidates are sorted by a continuous combined score, not discrete tiers.
- Each candidate includes `matchScore`, `matchReason`, and updated `matchQuality` (`"strong"` / `"likely"` / `"possible"`).
- Auto-suggestion only fires for a single candidate above the high-confidence threshold.
- The unknowns page renders the new quality labels and reason strings.
- `pnpm check` passes and `uv run pytest -q` passes.
- At least 5 new or updated tests in `manual_entry_service` or a new test file covering: exact match, tolerance boundary, payee similarity edge cases, threshold rejection, and auto-suggestion gating.

## Proposed Sequence

1. **Extract shared payee utilities.** Move `_normalize_payee()`, `_normalize_payee_token()`, `_payee_similarity()`, and `PAYEE_NOISE_WORDS` from `reconciliation_duplicate_service.py` into a shared module (e.g., `app/backend/services/payee_similarity.py`). Update `reconciliation_duplicate_service.py` to import from the shared module. Verify existing reconciliation tests still pass.
2. **Rewrite `find_match_candidates()` scoring.** Replace the tier system with the continuous scoring model. Add amount tolerance, payee similarity, date decay, combined score, and minimum threshold. Remove `TIER_LABELS`. Update the return shape (`matchScore`, `matchReason`, `matchQuality` instead of `matchTier`).
3. **Update `populate_match_candidates()` auto-suggestion.** Replace the tier-1 check with the `AUTO_SUGGEST_THRESHOLD` check.
4. **Update frontend labels.** Rewrite `matchQualityLabel()` in `+page.svelte` for the new quality strings. Add the reason string to the candidate row display.
5. **Write tests.** Cover scoring boundaries, payee edge cases, auto-suggestion gating.
6. **Regression check.** Run full test suite. Verify the reconciliation duplicate flow is unaffected.

## Definition of Done

- All acceptance criteria pass.
- The >$400 wrong-candidate bug is structurally impossible under the new scoring.
- Payee substring matching is replaced by token-set similarity everywhere in the unknowns flow.
- The reconciliation duplicate heuristic is unchanged except for importing from the shared module.

## Out of Scope

- Reconciliation duplicate heuristic changes.
- Unknowns apply/stage flow changes.
- Multi-select or merge on the unknowns page.
- Machine-learning or statistical models.
