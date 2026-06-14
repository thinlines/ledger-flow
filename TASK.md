# Replace inline transaction entry with modal on transactions page

**Status: TODO**

## Objective

When a user clicks "Add transaction" on the transactions page (single-account view), the app opens the global `TransactionEntryModal` prepopulated with the in-context account — instead of expanding the inline `AddTransactionForm` into the DOM.

## Scope

### Included

- Wire the "Add transaction" button in `AccountStatusStrip` to call `openEntryModal(accountId)` instead of toggling `showAddForm`
- Remove the inline `AddTransactionForm` block and its supporting state (`showAddForm`, `addSuccess`, `handleAddSuccess`) from `+page.svelte`
- Remove the "Transaction Added" success card that currently renders below the strip
- Ensure the modal opens with `lastAccountId` set to the single filtered account so the account combobox is prepopulated
- After the modal saves a transaction, reload the transactions list (the modal already invalidates; verify the page picks up the change)

### Explicitly excluded

- Deleting `AddTransactionForm.svelte` — it may be reused for the future transaction-editing feature (ROADMAP item 11). Leave the file in place; just remove the import and usage from `+page.svelte`.
- Changes to the modal's internal behavior, layout, or fields
- Changes to the Alt+N keyboard shortcut flow
- Changes to any other page that uses `openEntryModal`
- Mobile-specific bottom-sheet adaptation

## System Behavior

### Inputs

- User navigates to `/transactions?accounts=<id>` (single-account view)
- User clicks "Add transaction" in the `AccountStatusStrip`

### Logic

1. The `onAddTransaction` callback in `+page.svelte` calls `openEntryModal(filters.accounts[0])` (the tracked-account ID currently in context).
2. `openEntryModal` sets `entryModal.lastAccountId` to that ID and `open: true`.
3. The `TransactionEntryModal` (mounted in `+layout.svelte`) opens. Its `resetForm()` reads `$entryModal.lastAccountId` and preselects the matching tracked account in the account combobox.
4. The user fills out the form and submits. The modal posts to `/api/transactions/create`, shows the success state, and can be closed or used for another entry.
5. On modal close (or on successful save if the page watches for it), the transactions list reloads to reflect the new entry.

### Outputs

| User action | Result |
|-------------|--------|
| Click "Add transaction" (single-account) | Modal opens with account prepopulated |
| Save transaction in modal | Transaction created; transactions list reloads on next navigation or modal close |
| Cancel / close modal | No change; page state unchanged |

## System Invariants

- The modal is the single entry point for manual transaction creation across the entire app. No inline form on any page.
- The account prepopulation uses the same `openEntryModal(preselectedAccountId)` mechanism already used by other callers — no new API surface.
- Running balance, totals strip, and account meta all reflect the new transaction after reload.

## States

| State | Behavior |
|-------|----------|
| Single-account view, no modal open | "Add transaction" button visible in AccountStatusStrip |
| Modal open (from button click) | Account combobox shows the in-context account; all fields available |
| Modal open (from Alt+N elsewhere) | Unchanged — uses `lastAccountId` or first tracked account |
| Multi-account / no-account view | No "Add transaction" button (AccountStatusStrip not rendered — unchanged) |

## Edge Cases

1. **`openEntryModal` receives the account `id` (e.g. `"wells_fargo_checking"`), but the modal resolves accounts by matching against `trackedAccounts`**: Verify that `lastAccountId` matches the shape the modal expects. The store uses a plain string; the modal's `resetForm()` sets `selectedAccountId = $entryModal.lastAccountId`. The modal's account combobox iterates `trackedAccounts` and matches on `.id`. Confirm the `filters.accounts[0]` value is the same `.id` field — it is, both come from `/api/tracked-accounts`.

2. **Reload after modal save**: The modal does not currently call back to the transactions page. The page must detect that a transaction was added. Options: (a) the page subscribes to `entryModal` and reloads when `sessionCount` increments, or (b) the page reloads when the modal closes. Option (a) is more precise — reload on `sessionCount` change means the page refreshes only when a save actually happened, not on cancel.

3. **Success feedback**: The current inline flow shows a "Transaction Added" card on the page after save. The modal has its own success state (it shows the created transaction details and offers "Add another"). The page-level success card is removed; the modal's built-in feedback is sufficient.

## Failure Behavior

- Modal submission errors (422, 409, network) are handled inside the modal — no change needed.
- If `filters.accounts[0]` is somehow undefined when the button is clicked (shouldn't happen — the strip only renders when `isSingleAccount`), `openEntryModal(undefined)` falls back to `lastAccountId` from the store, which is the existing behavior.

## Regression Risks

1. **Transaction list not refreshing after modal save**: The inline form called `handleAddSuccess` which triggered a reload. The modal doesn't have that callback. Must add a reactive reload on `$entryModal.sessionCount` change, or equivalent.
2. **Alt+N shortcut changes behavior**: Must not change. The shortcut already calls `openEntryModal()` without an account ID. Only the "Add transaction" button path should pass the account ID.
3. **AccountStatusStrip "Add transaction" button disappears or changes position**: The button stays; only its click handler changes. No DOM or styling changes to the strip.
4. **Dead code left behind**: Ensure `showAddForm`, `addSuccess`, `handleAddSuccess`, and the `AddTransactionForm` import are all removed — no orphaned variables that trigger `pnpm check` warnings.

## Acceptance Criteria

1. Clicking "Add transaction" in the single-account `AccountStatusStrip` opens the `TransactionEntryModal`.
2. The modal's account combobox is prepopulated with the account currently filtered on the transactions page.
3. After saving a transaction in the modal, the transactions list reloads and shows the new entry.
4. The inline `AddTransactionForm` no longer renders on the transactions page.
5. The "Transaction Added" success card no longer renders on the transactions page.
6. The Alt+N shortcut continues to open the modal without an account prepopulation (unless one was previously used).
7. No orphaned imports, variables, or dead code in `+page.svelte`.
8. `pnpm check` passes with 0 errors and 0 warnings.
9. `pnpm build` succeeds.

## Proposed Sequence

1. **Wire the button to the modal**: In `+page.svelte`, change the `onAddTransaction` callback from `{ addSuccess = ''; showAddForm = true; }` to `openEntryModal(filters.accounts[0])`. Add the `openEntryModal` import from `$lib/stores/entry-modal`.

2. **Add reactive reload on modal save**: Subscribe to `$entryModal.sessionCount` in `+page.svelte`. When it increments, call the existing `loadData()` (or equivalent reload function) to refresh the transactions list.

3. **Remove inline form and success card**: Delete the `{#if showAddForm && isSingleAccount}` block (line ~441), the `{#if addSuccess}` block (lines ~433–439), the `handleAddSuccess` function, and the `showAddForm` / `addSuccess` variables. Remove the `AddTransactionForm` import.

4. **Verify and clean up**: Run `pnpm check` and `pnpm build`. Confirm no unused imports or variables remain.

## Definition of Done

- All acceptance criteria pass
- A user on a single-account transactions view can click "Add transaction", see the modal open with the correct account preselected, save a transaction, and see it appear in the list
- Alt+N behavior unchanged
- No dead code, type errors, or build warnings

## UX Notes

- The "Add transaction" button in the `AccountStatusStrip` remains visually unchanged — same label, same position. Only the behavior changes (modal instead of inline expansion).
- The modal's account combobox showing the preselected account provides immediate confirmation that the user is adding to the right account.
- The page no longer shifts layout when adding a transaction — the modal overlays without displacing content. This is a direct improvement per the no-jarring-DOM-shifts principle.

## Out of Scope

- Deleting `AddTransactionForm.svelte` (future reuse for editing)
- Changes to the modal component itself
- Mobile bottom-sheet adaptation
- Transaction editing feature
