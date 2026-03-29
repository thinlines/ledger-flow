# Unknowns Page Decomposition Plan

The review page (`app/frontend/src/routes/unknowns/+page.svelte`) is 2535 lines
with 10+ concerns in a single file. This plan breaks it into focused components
and modules, designed to be executed incrementally — one extraction per task,
each independently shippable.

## Current structure

```
Script block:   ~1425 lines (types, state, 50+ functions)
Template block:  ~590 lines
Style block:     ~520 lines
```

### Concerns identified in the script block

| # | Concern                     | Lines (approx) | Functions                                                              |
|---|-----------------------------|---------------:|------------------------------------------------------------------------|
| 1 | Types (local)               |            100 | 7 type aliases                                                         |
| 2 | Stage persistence           |             70 | `rememberUnknownStage`, `rememberedUnknownStage`, `clearRemembered…`   |
| 3 | Stage hydration & autosave  |            100 | `hydrateStage`, `refreshUnknownStage`, `persistStageSelections`, `queueStageAutosave`, `flushStageAutosave` |
| 4 | Review row builder          |            120 | `buildReviewRows`, `buildDefaultSelection`, `selectionFor`, `groupStatus`, `groupStatusLabel`, helpers |
| 5 | Selection mutators          |            100 | `setGroupMode`, `setCategoryForGroup`, `setTransferTargetForGroup`, `setMatchForGroup`, `stageSelectionPayload` |
| 6 | Rule modal orchestration    |            200 | `openRuleModal`, `persistRule`, `saveRule`, `loadRuleIntoEditor`, `setRuleAccount`, `openExistingRuleCandidate`, `findExistingRulesForAccount`, `scoreRuleForPayee`, `summarizeRuleCondition`, `appendDraftConditionsForEditedRule` |
| 7 | Rule history review         |             80 | `toggleHistoryCandidate`, `setAllHistoryCandidates`, `applyHistoryStage`, `cancelHistoryReview`, `finalizeHistoryApply`, `buildHistoryApplyRedirect` |
| 8 | Create account modal        |             60 | `openCreateAccountModal`, `closeCreateAccountModal`, `openCreateAccountForGroup`, `openCreateAccountForRule`, `createAccountAndContinue`, `inferAccountType`, `updateInferredTypeFromName` |
| 9 | Apply / scan / load         |             80 | `scan`, `applyMappings`, `loadStageFromRoute`, `openSelectedJournalReview`, `loadRules` |
| 10| Display helpers             |             50 | `pathLabel`, `parseJournalDate`, `formatShortDate`, `sourceAccountPrimary`, `groupLabel`, `warningGroupLabel`, `matchQualityLabel`, `transferPeerLabel`, `transferHelperText`, `transferDestinationAccounts` |
| 11| ~45 `let` state variables   |             50 | Scattered across concerns                                              |

### Template sections

| Section                    | Rough lines | Notes                                   |
|----------------------------|------------:|-----------------------------------------|
| Hero + error + init guard  |          30 | Thin, fine where it is                  |
| Rule history review queue  |         120 | Self-contained card                     |
| Unknown groups review list |         250 | Largest block; contains mode switcher, category/transfer/match sub-UIs |
| Rule modal (dialog)        |         100 | Includes existing-rule suggestions      |
| Create account modal       |          40 | Reuses `CreateAccountModal` already     |
| Apply bar / summary        |          50 | Bottom action bar                       |

## Extraction plan

Each step is an independent, shippable unit. Steps are ordered by impact and
isolation — earlier steps have fewer cross-dependencies and clear boundaries.

### Step 1: Extract types → `$lib/types/unknowns.ts`

Move the 7 local type aliases (`TrackedAccount`, `TransferSuggestion`,
`MatchCandidate`, `TxnRow`, `UnknownGroup`, `GroupSelection`, `UnknownStage`,
`RuleHistoryStage`, `RuleHistoryCandidate`, `Rule`, `ExistingRuleCandidate`,
`ReviewRow`) into a shared type file. This unblocks all subsequent extractions
since they need shared types.

**Risk:** None. Pure type movement, no runtime change.
**Test:** `pnpm check` passes.

### Step 2: Extract stage persistence → `$lib/stage-persistence.ts`

Move `unknownStageStorageKey`, `rememberUnknownStage`,
`rememberedUnknownStage`, `clearRememberedUnknownStage` into a pure module.
These functions depend only on `workspacePath` (pass as argument) and
`window.localStorage`.

**Risk:** Minimal. Pure functions with no component coupling.
**Test:** `pnpm check` passes.

### Step 3: Extract review row builder → `$lib/review-rows.ts`

Move `buildReviewRows`, `buildDefaultSelection`, `selectionFor`, `groupMode`,
`categoryAccountFor`, `transferTargetAccountIdFor`, `groupStatus`,
`groupStatusLabel`, `isCategoryAccountName`, `groupTransferSuggestion`,
`groupMatchCandidates`, `groupSuggestedMatchId`, and the display helpers
(`matchQualityLabel`, `transferHelperText`, `transferDestinationAccounts`,
`transferPeerLabel`) into a builder module.

These are all pure functions that take data and return data. The page's reactive
declarations (`$: reviewRowsData = buildReviewRows(…)`) stay in the page
component and call into this module.

**Risk:** Low. All pure functions.
**Test:** `pnpm check` passes. Manual smoke-test of the review list.

### Step 4: Extract rule history review → `UnknownRuleHistoryCard.svelte`

Create `$lib/components/UnknownRuleHistoryCard.svelte` containing:
- The history review template section (candidate list, select all, apply bar)
- `toggleHistoryCandidate`, `setAllHistoryCandidates`
- History-specific display state

The page passes `historyStage`, `historySelectedCandidateIds`, and dispatches
events for `applyHistoryStage` and `cancelHistoryReview` (which stay in the
page because they modify top-level stage state and navigate).

**Risk:** Low. Self-contained UI section with clean data boundary.
**Test:** `pnpm check` passes. Manual test of rule history review flow.

### Step 5: Extract review group card → `UnknownReviewRow.svelte`

Create `$lib/components/UnknownReviewRow.svelte` containing:
- The per-group review card template (mode switcher, category combobox,
  transfer selector, match selector, transaction details)
- Selection mutators: `setGroupMode`, `setCategoryForGroup`,
  `setTransferTargetForGroup`, `setMatchForGroup`
- Relevant per-row styles

The page renders `{#each filteredReviewRows as row}` and passes each row's data
as props. Selection changes dispatch events that the page handles by updating
`selections` and calling `queueStageAutosave`.

This is the highest-impact extraction — it removes ~350 lines of interleaved
template + logic from the page.

**Risk:** Medium. The mode switcher and selection mutators touch shared
`selections` state. Clean event interface needed.
**Test:** `pnpm check` passes. Full manual test of all three selection modes
(category, transfer, match) and autosave.

### Step 6: Extract rule modal logic → `$lib/rule-modal.ts` + simplify inline dialog

Move rule modal orchestration functions into a module:
`loadRuleIntoEditor`, `appendDraftConditionsForEditedRule`,
`summarizeRuleCondition`, `scoreRuleForPayee`,
`findExistingRulesForAccount`, `openExistingRuleCandidate`.

The modal template stays in the page (it's already using `RuleEditor`
component) but the preparation and persistence logic becomes importable.
`openRuleModal` and `persistRule` stay in the page as thin wrappers that
call into the module and manage component state.

**Risk:** Medium. Several functions reference `rules`, `stage`, and
`selections` — these become explicit parameters.
**Test:** `pnpm check` passes. Manual test of rule create, edit, and
existing-rule suggestion flows.

### Step 7: Consolidate state into a reactive store (optional)

If after steps 1–6 the page is ~800–1000 lines and manageable, stop here. If
it's still unwieldy, consolidate the remaining ~45 `let` variables into a
Svelte store or context object (`unknownsPageState`) so state flows through a
single reactive surface rather than individual bindings.

This step is optional and should only happen if the page still feels hard to
reason about after the component extractions.

## Expected outcome

After steps 1–6:

| Artifact                           | Lines (est) |
|------------------------------------|------------:|
| `+page.svelte`                     |    800–1000 |
| `$lib/types/unknowns.ts`          |         100 |
| `$lib/stage-persistence.ts`        |          70 |
| `$lib/review-rows.ts`             |         200 |
| `UnknownRuleHistoryCard.svelte`   |         200 |
| `UnknownReviewRow.svelte`         |         400 |
| `$lib/rule-modal.ts`              |         150 |

The page drops from 2535 to ~900 lines with clear responsibility: top-level
state, lifecycle, stage loading/applying, and section composition.

## Execution guidance

- **One step per task.** Each extraction is a self-contained commit.
- **No behavior changes.** Every step is a pure refactor — the UI must be
  identical before and after.
- **Opportunistic attachment.** If a feature task touches the unknowns page,
  perform the most relevant extraction step first, then build the feature on
  the cleaner foundation.
- **Verify after each step:** `pnpm check` must pass. Smoke-test the affected
  UI flow.
