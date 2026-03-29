# Accounts Configure Page Decomposition Plan

The accounts configuration page
(`app/frontend/src/routes/accounts/configure/+page.svelte`) is 1807 lines with
a combined listing + editor + CSV profile inspector in a single file. This plan
breaks it into focused components and modules, designed to be executed
incrementally.

## Current structure

```
Script block:   ~843 lines (types, 20 state vars, 45+ functions)
Template block:  ~558 lines
Style block:     ~406 lines
```

### Concerns identified in the script block

| # | Concern                          | Lines (approx) | Key functions                                                    |
|---|----------------------------------|----------------:|------------------------------------------------------------------|
| 1 | Types (local)                    |             80 | AccountDraft, CustomProfileDraft, CsvInspection, etc.            |
| 2 | Currency & formatting helpers    |             40 | `defaultCurrencySymbol`, `formatCurrency`, `formatStoredAmount`, `shortDate` |
| 3 | Draft/form state management      |            120 | `newDraft`, `updateDraft`, `setDraftKind`, `setDraftSubtype`, `editAccount` |
| 4 | Subtype sync logic               |             60 | `syncDraftSubtype`, `subtypeHelperText`, `subtypeBadgeLabel`, `subtypeBadgeTone` |
| 5 | Opening balance & offset         |             60 | `openingBalanceOffsetOptions`, `openingBalanceOffsetHint`, `openingBalanceDateLabel` |
| 6 | Institution template logic       |             50 | `templateById`, `templateKind`, `updateInstitution`, `suggestedLedgerAccount` |
| 7 | CSV profile management           |            140 | `newCustomProfileDraft`, `updateCustomProfile`, `guessProfileFromHeaders`, `inspectSample`, `customProfilePayload` |
| 8 | Account persistence & API        |            100 | `load`, `saveAccount`, `syncFromRoute`, `startManualAccount`, `startInstitutionAccount`, `startCustomAccount` |
| 9 | Balance trust & display          |             40 | `balanceTrust`, `balanceMeta`, `currentBalance`, `modeLabel` |

### Template sections

| Section                       | Rough lines | Notes                                  |
|-------------------------------|------------:|----------------------------------------|
| Error + loading + init guards |          30 | Thin, fine where it is                 |
| Hero with stats               |          30 | Account count, import-enabled, needs setup |
| Editor card (left column)     |         410 | The bulk — kind, institution, name, subtype, opening balance, CSV profile, save/cancel |
| Account inventory (right col) |          90 | Grid of account cards with edit buttons |

## Extraction plan

Each step is an independent, shippable unit. Steps are ordered by isolation and
impact.

### Step 1: Extract types → `$lib/types/accounts.ts`

Move local type aliases (`AccountDraft`, `CustomProfileDraft`,
`CsvInspection`, `TrackedAccount`, `InstitutionTemplate`,
`DashboardOverview`) into a shared type file. This unblocks subsequent
extractions.

**Risk:** None. Pure type movement.
**Test:** `pnpm check` passes.

### Step 2: Extract formatting helpers → `$lib/format.ts`

Move `defaultCurrencySymbol`, `normalizeStoredCurrency`, `formatCurrency`,
`formatStoredAmount`, `shortDate` into a shared formatting module. These are
pure functions used across multiple pages (transactions page has duplicates).

This also deduplicates — the transactions page has its own copies of
`formatCurrency`, `formatStoredAmount`, and `shortDate`.

**Risk:** None. Pure functions, no component coupling.
**Test:** `pnpm check` passes.

### Step 3: Extract CSV profile inspector → `CsvProfileInspector.svelte`

Create `$lib/components/CsvProfileInspector.svelte` containing:
- The custom CSV profile template section (encoding, delimiter, column
  mapping, amount config, sample table)
- Functions: `newCustomProfileDraft`, `updateCustomProfile`,
  `guessProfileFromHeaders`, `applyHeaderGuesses`, `inspectSample`,
  `normalizeDelimiterLabel`, `headerMatches`, `firstHeader`,
  `amountConfigInvalid`
- State: `inspection`, `selectedSampleFile`, `inspecting`

The page passes the current `customProfile` draft as a prop and receives
updates via events. `customProfilePayload()` stays in the page since it's
used at save time.

**Risk:** Low. Self-contained UI section with clear data boundary (the
custom profile object).
**Test:** `pnpm check` passes. Manual test of custom CSV account creation
with sample file inspection.

### Step 4: Extract account inventory list → `AccountInventoryCard.svelte`

Create `$lib/components/AccountInventoryCard.svelte` containing:
- The inventory card template (account grid with balance, trust pill,
  subtype pill, mode label, edit button)
- Display functions: `balanceTrust`, `balanceMeta`, `currentBalance`,
  `modeLabel`, `subtypeBadgeLabel`, `subtypeBadgeTone`
- Quick-action buttons that dispatch events to the page for
  `startManualAccount`, `startInstitutionAccount`, `startCustomAccount`

Props: `trackedAccounts`, `dashboardBalances`, `baseCurrency`,
`institutionTemplates`.
Events: `edit`, `start-manual`, `start-institution`, `start-custom`.

**Risk:** Low. Read-only display with event dispatching.
**Test:** `pnpm check` passes. Manual test of account list display and
edit button navigation.

### Step 5: Extract opening balance logic → `$lib/opening-balance.ts`

Move `openingBalanceOffsetOptions`, `selectedOpeningBalanceOffsetAccount`,
`openingBalanceOffsetLabel`, `openingBalanceOffsetOptionLabel`,
`openingBalanceOffsetHint`, `openingBalanceHint`,
`openingBalancePlaceholder`, `openingBalanceDateLabel` into a module.

All are pure functions that take tracked accounts and draft state as
parameters and return display values.

**Risk:** None. Pure functions.
**Test:** `pnpm check` passes.

### Step 6: Extract subtype sync → `$lib/account-subtype-sync.ts`

Move `syncDraftSubtype`, `subtypeHelperText`, and the auto-sync tracking
logic (`lastAutoSubtype`) into a module that accepts draft state and
returns updated draft + subtype metadata.

This concern is subtle and bug-prone — isolating it makes the sync rules
easier to reason about and test.

**Risk:** Low. The sync logic is currently scattered across `setDraftKind`,
`updateDraft`, and `setDraftSubtype` — extraction clarifies the flow.
**Test:** `pnpm check` passes. Manual test of subtype auto-suggestion
when switching kind and institution.

## Expected outcome

After steps 1–6:

| Artifact                         | Lines (est) |
|----------------------------------|------------:|
| `+page.svelte` (editor + page)  |    700–850  |
| `$lib/types/accounts.ts`        |          80 |
| `$lib/format.ts`                |          50 |
| `CsvProfileInspector.svelte`    |     350–400 |
| `AccountInventoryCard.svelte`   |     150–200 |
| `$lib/opening-balance.ts`       |          80 |
| `$lib/account-subtype-sync.ts`  |          60 |

The page drops from 1807 to ~750 lines with a clear responsibility: the
account editor form, draft lifecycle, save/load, and section composition.

## Execution guidance

- **One step per task.** Each extraction is a self-contained commit.
- **No behavior changes.** Every step is a pure refactor.
- **Opportunistic attachment.** When a feature task touches accounts
  configuration, perform the most relevant extraction step first.
- **Verify after each step:** `pnpm check` must pass. Smoke-test the
  affected flow.
- **Step 2 has cross-page value.** Extracting `$lib/format.ts` eliminates
  duplicates in the transactions page too — consider doing it first when
  either page is touched.
