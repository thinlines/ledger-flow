# Transactions Page Decomposition Plan

The transactions page (`app/frontend/src/routes/transactions/+page.svelte`) is
1442 lines. It's the cleanest of the four large pages — concerns are reasonably
grouped and the script block is proportionate. This plan is lighter-touch,
focusing on the three sections that would benefit most from extraction.

## Current structure

```
Script block:   ~498 lines (types, 30 state vars, 23 functions)
Template block:  ~485 lines
Style block:     ~459 lines
```

### Concerns identified in the script block

| # | Concern                       | Lines (approx) | Key functions                                                  |
|---|-------------------------------|----------------:|----------------------------------------------------------------|
| 1 | Account selection & register  |             80 | `syncSelection`, `loadRegister`, `load`, `handleAccountChange` |
| 2 | Register display & clearing   |             50 | `toggleClearingStatus`, clearing constants                     |
| 3 | Pending transfers display     |             20 | Reactive derivations only                                      |
| 4 | Manual resolution dialog      |             80 | `openManualResolution`, `confirmManualResolution`, `resetManualResolutionDialog` |
| 5 | Add transaction form          |             80 | `openAddForm`, `closeAddForm`, `submitAddTransaction`, `loadAllAccounts`, `todayISO` |
| 6 | Primary/secondary actions     |             60 | `registerPrimaryAction`, `registerSecondaryActions`            |
| 7 | Formatting helpers            |             40 | `formatCurrency`, `formatStoredAmount`, `shortDate`, `titleCase`, `countLabel`, `selectedAccountTrust` |

### Template sections

| Section                    | Rough lines | Notes                                   |
|----------------------------|------------:|-----------------------------------------|
| Error + loading + guards   |          30 | Thin, fine where it is                  |
| Hero with account selector |          40 | Account picker + CTA                    |
| Success messages            |          15 | Resolution + add confirmations          |
| Add transaction form       |          70 | Date, payee, amount, destination        |
| Summary grid (4 cards)     |          45 | Balance, coverage, pending, activity    |
| Pending transfers section  |         100 | Pending table with expandable details   |
| Posted register section    |         105 | Main transaction table with expandables |
| Manual resolution dialog   |          65 | Modal for transfer resolution           |

## Extraction plan

This page is borderline — it works fine as-is. These extractions are
lower priority than the other three pages and should only happen
opportunistically when a feature requires modifying the relevant section.

### Step 1: Extract formatting helpers → shared `$lib/format.ts`

If `$lib/format.ts` already exists from the accounts-configure
decomposition (step 2 of that plan), this step is just importing from it
and deleting the local duplicates.

Functions to consolidate: `formatCurrency`, `formatStoredAmount`,
`shortDate`, `titleCase`, `countLabel`.

**Risk:** None. Pure functions.
**Test:** `pnpm check` passes.

### Step 2: Extract add transaction form → `AddTransactionForm.svelte`

Create `$lib/components/AddTransactionForm.svelte` containing:
- The form template (date, payee, amount, destination combobox)
- Form state: `addDate`, `addPayee`, `addAmount`, `addDestination`,
  `addError`, `addSubmitting`, `addDateEl`
- Functions: `openAddForm`, `closeAddForm`, `handleAddFormKeydown`,
  `todayISO`
- `loadAllAccounts` for the destination combobox

The page passes `selectedAccountId` and `baseCurrency` as props.
Submission dispatches an event; the page handles the API call and
register reload (or the component can own the API call and dispatch
`success` with the result).

**Risk:** Low. Self-contained form with clear inputs and outputs.
**Test:** `pnpm check` passes. Manual test of adding a transaction.

### Step 3: Extract manual resolution dialog → `ManualResolutionDialog.svelte`

Create `$lib/components/ManualResolutionDialog.svelte` containing:
- The dialog template (preview display, confirm/cancel buttons)
- State: `manualResolutionOpen`, `manualResolutionEntry`,
  `manualResolutionPreview`, `manualResolutionError`,
  `manualResolutionLoading`
- Functions: `openManualResolution`, `confirmManualResolution`,
  `resetManualResolutionDialog`, `handleManualResolutionOpenChange`

Props: `selectedAccountId`.
Events: `resolved` (page reloads register and shows success message).

**Risk:** Low. Self-contained modal with its own API calls.
**Test:** `pnpm check` passes. Manual test of the resolution flow.

### Step 4: Extract register action logic → `$lib/register-actions.ts`

Move `registerPrimaryAction`, `registerSecondaryActions`, and
`selectedAccountTrust` into a module. These are pure functions that
compute CTAs from account state.

This module could be shared if other pages need similar account-aware
action computation.

**Risk:** None. Pure functions.
**Test:** `pnpm check` passes.

## Expected outcome

After steps 1–4:

| Artifact                           | Lines (est) |
|------------------------------------|------------:|
| `+page.svelte`                     |    750–850  |
| `AddTransactionForm.svelte`        |     150–180 |
| `ManualResolutionDialog.svelte`    |     130–150 |
| `$lib/register-actions.ts`         |          60 |
| `$lib/format.ts` (shared)         |     +0 (already exists) |

The page drops from 1442 to ~800 lines. The reduction is more modest than
the other pages because the starting point is more manageable. The real
value is isolating the form and dialog — the two sections most likely to
gain complexity as features like transaction editing land.

## Execution guidance

- **Lower priority.** This page is functional at its current size.
  Prioritize unknowns, accounts-configure, and import-flow decompositions
  first.
- **Step 1 is free.** If `$lib/format.ts` exists from another extraction,
  just switch to imports.
- **Steps 2–3 become high-value before transaction editing.** The
  "transaction editing" feature (currently deferred) will add significant
  complexity to this page. Extracting the form and dialog beforehand
  creates room.
- **Verify after each step:** `pnpm check` must pass. Smoke-test the
  register view, add form, and resolution dialog.
