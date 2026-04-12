# Current Task

## Title

Transactions screen rethink — Phase 3: detail sheet + inline category combobox

## Objective

Introduce progressive disclosure to the transactions screen. Today, the register view hides transaction details behind a `<details>` accordion and puts all actions in a three-dot popover menu on the row itself. The activity view has no detail affordance at all. This phase adds two components that change how users interact with transactions:

1. **Transaction detail sheet** — a right-side panel that slides in when the user clicks a row. It replaces the `<details>` accordion in register mode and provides the first detail surface in activity mode. Actions (delete, unmatch) move from the row's three-dot menu into the sheet's overflow menu.
2. **Inline category combobox** — the static category pill in activity rows becomes a clickable combobox. Picking a category recategorizes the transaction via the existing `/api/transactions/recategorize` endpoint and shows an undo toast. This is the "category icon = category button" pattern from Copilot/Monarch.

After Phase 3, the progressive-disclosure UX from the plan is in place. The two-mode toggle still exists (dies in Phase 4).

See [`plans/transactions-rethink.md`](plans/transactions-rethink.md) for the full design.

## Scope

### Included

- **`TransactionDetailSheet.svelte`** — right-side sheet (bits-ui `Dialog` in side-anchored mode) that opens when a row is clicked. Works in both activity and register modes. Shows:
  - Header: payee, amount, account label, close button, three-dot overflow menu.
  - Body: date (read-only), category (read-only for now), original bank descriptor (entry `summary`), detail lines (register mode), transfer state and manual-resolution note (register mode).
  - Three-dot menu: Delete (dispatches callback), Unmatch (dispatches callback, only when `matchId` is present).
- **Wire row clicks to open the sheet.** In activity mode, clicking the payee or amount opens the sheet. In register mode, clicking the row summary opens the sheet instead of toggling the `<details>` accordion. The `<details>` element is replaced with a flat row that opens the sheet on click.
- **`TransactionCategoryCombobox.svelte`** — a `Popover` + `Command` combobox that replaces the static `.activity-category-pill` in activity rows. Clicking the pill opens a searchable list of accounts from `/api/accounts`. Selecting one calls `/api/transactions/recategorize` with the new target. An undo toast fires on success. The row updates in place.
- **Move action-menu items from the row into the sheet.** The register row's inline three-dot popover menu is removed. Actions live in the sheet's overflow menu instead. The row becomes simpler (no popover, no action menu state).
- **Remove the `<details>` accordion from register rows.** The expandable detail section is replaced by the sheet. Register rows become flat summary lines (like activity rows) with a click-to-open-sheet affordance.
- **Update `TransactionRow.svelte`** — remove the action-menu template and the `<details>` wrapper. Both modes render as flat rows. Add an `onRowClick` callback prop. Remove the action-menu callback props (`onOpenActionMenu`, `onConfirmDelete`, `onRecategorize`, `onConfirmUnmatch`).

### Explicitly Excluded

- "Create rule from transaction" in the sheet's three-dot menu — deferred to a follow-up if `RuleEditor.svelte` integration is complex.
- Backend changes — all existing endpoints are used as-is.
- Inline category editing in register mode — register rows don't have a category pill. The category combobox is activity-mode only for now.
- Account-as-filter, removal of `activityMode`, filter bar, running balance everywhere — Phase 4.
- Notes, tags, attachments fields in the sheet — deferred per plan.
- Split transaction editing in the sheet — deferred per plan.
- Transaction editing (date, payee, amount) — deferred Feature 9.

## System Behavior

### Inputs

- User clicks an activity row → sheet opens with that transaction's data.
- User clicks a register row → sheet opens with that entry's data.
- User clicks the category pill on an activity row → combobox opens with searchable account list.
- User selects a category from the combobox → recategorize API call fires.
- User clicks Delete/Unmatch in the sheet's overflow menu → page-level confirmation dialog opens (existing flow).
- User clicks `✕` or presses Escape or clicks backdrop → sheet closes.

### Logic

**Detail sheet data flow:**
- The page owns a `selectedEntry: RegisterEntry | null` and `selectedTransaction: ActivityTransaction | null` state. Setting either opens the sheet.
- The sheet reads from whichever is non-null and renders mode-appropriate content.
- Closing the sheet clears both.
- The sheet dispatches `onDelete(entry)` and `onUnmatch(entry)` — the page handles confirmation dialogs.

**Category combobox flow:**
1. User clicks category pill → Popover opens with Command combobox.
2. Combobox shows `/api/accounts` list filtered by search input.
3. User selects an account → POST `/api/transactions/recategorize` with `{ journalPath, headerLine, newCategory }`.
4. On success: undo toast fires, activity view reloads.
5. On error: error toast or inline error.

Note: the existing `/api/transactions/recategorize` endpoint resets a transaction's category to unknown (moves it back to the review queue). For Phase 3, the combobox calls this existing endpoint. A future iteration may add a `newCategory` parameter to set a specific category directly. If the current endpoint doesn't support setting a specific category, the combobox is deferred and the pill stays static.

### Outputs

- Sheet panel slides in from the right on row click. On desktop (≥ 1100px) the list stays visible; on narrower screens the sheet covers it.
- Category pill becomes interactive in activity mode with a popover combobox.
- Register rows become flat (no accordion expand).
- Action menu disappears from register rows (lives in sheet now).

## Acceptance Criteria

- Clicking any activity row opens a detail sheet showing payee, amount, account, date, and category.
- Clicking any register row opens a detail sheet showing payee, amount, date, running balance, summary, detail lines, and transfer/resolution notes.
- The sheet's three-dot menu shows Delete (for non-opening-balance entries) and Unmatch (when `matchId` is present). Clicking either dispatches to the page's existing confirmation flow.
- The sheet closes via `✕` button, Escape key, or backdrop click.
- Register rows no longer have the `<details>` accordion or inline action menu.
- In activity mode, clicking a category pill opens a searchable combobox. (If the recategorize endpoint doesn't support setting a new category, this item is deferred and the pill stays static.)
- `pnpm check` passes.
- `uv run pytest -q` passes (no backend changes, but verify nothing broke).

## Definition of Done

- Progressive disclosure is in place: rows are flat, details live in the sheet, actions live in the sheet's overflow menu.
- The category combobox (if shipped) recategorizes transactions inline with an undo toast.
- No regressions in existing flows: manual resolution, add transaction, clearing status toggle, dashboard drill-downs.
- The page's line count continues to decrease (or at minimum doesn't increase).

## Out of Scope

See "Excluded" above. Anything from Phase 4–5 of `plans/transactions-rethink.md` is out of scope.
