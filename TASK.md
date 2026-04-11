# Current Task

## Title

Transactions screen rethink — Phase 1 foundations

## Objective

Begin Feature 7d (transactions screen rethink) by extracting the easy pieces from `app/frontend/src/routes/transactions/+page.svelte` (currently 2487 lines, two products in one file toggled by `activityMode`) into focused components and modules. Phase 1 ships **no UX changes** — its job is to drop the page's line count and create the seams that Phases 2–4 will fill in. The two-mode toggle and dual-data-shape architecture remain in place; they die in Phase 4.

See [`plans/transactions-rethink.md`](plans/transactions-rethink.md) for the full design and the phased delivery sequence.

## Scope

### Included

- **Lift the activity-view explanation header** into `app/frontend/src/lib/components/transactions/TransactionsExplanationHeader.svelte`. Props: `summary: ActivitySummary | null`, `category: string | null`, `period: string | null`, `month: string | null`. Behavior unchanged.
- **Lift the add-transaction form** into `app/frontend/src/lib/components/transactions/AddTransactionForm.svelte`. Props: `selectedAccountId`, `baseCurrency`, `trackedAccounts`. Dispatches a `success` event the page handles by reloading the register. Behavior unchanged.
- **Lift the manual transfer resolution dialog** into `app/frontend/src/lib/components/transactions/ManualResolutionDialog.svelte`. Props: `selectedAccountId`, `entry: RegisterEntry | null`, `open`. Dispatches `resolved` and `closed` events. Behavior unchanged.
- **Consolidate shared formatters** in `app/frontend/src/lib/format.ts` (creating it if it does not yet exist). Move `formatCurrency`, `formatStoredAmount`, `shortDate`, `titleCase`, `countLabel` from the page into the shared module. Replace local references with imports. If `$lib/format.ts` already exists from another decomposition, just import from it.
- **Extract types** to `app/frontend/src/lib/transactions/types.ts`: `RegisterEntry`, `AccountRegister`, `ActivityTransaction`, `ActivityResult`, `ActivitySummary`, `ActivityDateGroup`, `ActivityTopTransaction`, `TrackedAccount`, `ActionLink`, `RegisterAction`, `ManualResolutionPreview`, `ManualResolutionApplyResult`. Page imports from there.
- All other frontend code remains in place. The page still toggles between activity mode and account-register mode via `activityMode`. Both views render and behave exactly as they do today.

### Explicitly Excluded

- The unified `TransactionRow.svelte` component → Phase 2.
- `TransactionDayGroup.svelte` → Phase 2.
- The leftmost status circle in the activity view → Phase 2.
- `TransactionDetailSheet.svelte`, inline category combobox, three-dot menu inside the sheet → Phase 3.
- The unified `/api/transactions` backend endpoint, the N-1 posting rule, and tracked-to-tracked transfer-pair collapse → Phase 4.
- Account-as-filter, removal of `activityMode`, the unified loader, URL-param migration → Phase 4.
- Live totals strip, daily-sum group headers, search formula syntax, mobile bottom sheet, keyboard shortcuts → Phase 5.
- Any new UX patterns. This phase is structural.
- Any changes to dashboard drill-down URLs or to the activity service backend.
- Any changes to the unknowns page, accounts page, or other consumers of the formatters being lifted into `$lib/format.ts`. If those pages already define the same helpers locally, leave their copies alone for this phase — consolidating them is a separate decomposition step.

## System Behavior

The page's external behavior is **identical** to before this task:

- Loading `/transactions` shows the account register for the first tracked account (or the previously selected one).
- Loading `/transactions?view=activity` shows the cross-account activity view.
- The view-toggle pill in the hero switches between modes.
- The dashboard drill-down URLs (`?view=activity&category=...`, `?view=activity&month=...`) continue to land on the activity view with filters pre-applied.
- The Add transaction form, manual transfer resolution dialog, and explanation header all render and function exactly as they do today.
- The undo toast continues to work for delete / recategorize / unmatch actions.
- The account selector dropdown, primary CTA, and secondary actions in the register hero are unchanged.

The internal structure changes:

- The page imports `TransactionsExplanationHeader`, `AddTransactionForm`, `ManualResolutionDialog` from `$lib/components/transactions/`.
- The page imports types from `$lib/transactions/types.ts`.
- The page imports formatters from `$lib/format.ts`.
- The page's script block drops by roughly 600 lines.

## Acceptance Criteria

- `app/frontend/src/routes/transactions/+page.svelte` drops below 1900 lines (from 2487).
- `app/frontend/src/lib/components/transactions/TransactionsExplanationHeader.svelte` exists and is the only place rendering the explanation card. The page imports it and passes the existing reactive values as props.
- `app/frontend/src/lib/components/transactions/AddTransactionForm.svelte` exists, replaces the inline form, and adding a transaction works identically. The component owns its form state; the page handles the success event by reloading the register.
- `app/frontend/src/lib/components/transactions/ManualResolutionDialog.svelte` exists, replaces the inline dialog, and resolving a manual transfer works identically. The component owns its preview/apply state; the page handles the resolved event by reloading the register and showing the success message.
- `app/frontend/src/lib/format.ts` exists (or already exists) and exports `formatCurrency`, `formatStoredAmount`, `shortDate`, `titleCase`, `countLabel`. The page imports them. No duplicate definitions remain in the page.
- `app/frontend/src/lib/transactions/types.ts` exists and exports the listed types. The page imports them. No duplicate type definitions remain in the page.
- `pnpm check` passes in `app/frontend`.
- `uv run pytest -q` in `app/backend` passes (no backend changes, but verify nothing broke via shared fixtures or state).
- Manual smoke test:
  - Load `/transactions` and confirm the register view renders the same.
  - Switch to the activity view via the hero toggle and confirm the explanation header still appears.
  - Click a category trend on the dashboard and confirm the drill-down still lands on the activity view with filters applied.
  - Add a manual transaction via the Add transaction form and confirm it lands in the register.
  - Open a row with a manual transfer resolution token and confirm the dialog still opens, previews, and applies.
  - Trigger delete / recategorize / unmatch from the three-dot menu and confirm the undo toast still appears.
- Git diff is reviewable: each lift is a separate commit (5 commits total) so the structural change is easy to verify.

## Definition of Done

- The page is meaningfully smaller and the lifted components are independently importable from `$lib/components/transactions/`.
- No UX has changed. No backend has changed.
- Phase 1 of `plans/transactions-rethink.md` is fully checked off.
- A short PR description references this task, points at the plan, and notes the line-count drop.

## Out of Scope

See "Excluded" above. Anything from Phases 2–5 of `plans/transactions-rethink.md` is out of scope for this task. The dashboard, accounts pages, and unknowns page are not touched.

## Notes

- This task is structural decomposition only. Resist the urge to "fix" any UX issues encountered while moving code — file them as Phase 3 / Phase 4 follow-ups in the plan instead.
- The `$lib/components/transactions/` directory may not yet exist. Create it.
- The `$lib/transactions/` directory (for non-component modules) may not yet exist. Create it.
- If `$lib/format.ts` already exists from the accounts-configure decomposition (its step 2), prefer using its definitions over the page's. If signatures differ, reconcile in favor of the existing module's API.
