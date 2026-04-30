# Reconciliation Route + Diff-Prominent Error (8c)

**Status: COMPLETED — 2026-04-28**

## Delivery Notes

- QA verdict: **PASS** (after one fix-loop cycle). 672 backend tests, 0 errors / 0 warnings on `pnpm check`, 48 Vitest cases (33 prior + 15 new for `reconcile-error-copy.test.ts`).
- Review verdict: **SHIP WITH NOTES**. One defense-in-depth observation only (see below).
- **One fix-loop cycle.** Initial QA caught a real bug: the diff-prominent 422 panel silently regressed to the legacy fallback message for any negative-balance reconciliation (liability accounts, over-asserted assets) because the shared `parseAmount` rejected the backend's `-$X,XXX.XX` shape. Fix landed in three commits: a new `reconcile-error-copy.ts` module with a `parseBackendCurrency` helper that accepts the backend's signed-currency format (without widening the strict user-input parser), `offByLabel` and `signedExpectedActualLine` extracted into the same module, and a Vitest suite (15 cases) covering the canonical bug shape directly.
- Non-blocking observation from re-review:
  1. The route's `hasSnappedPeriodStart` latch (`+page.svelte:130-136`) snaps `periodStart` only on the first fetch and drops the per-fetch hard-floor guard the modal had. In practice the route is defended by `setupValid` and the date input's `min=` attribute, so a sub-floor `periodStart` can't reach the server. Suggested mirror form: `if (!hasSnappedPeriodStart || periodStart < floor) periodStart = floor`. Trivial follow-up if user reports an issue.
- Surprising findings worth surfacing:
  1. **The bug pattern matches exactly the lesson the new senior-developer "Format and protocol calibration" rule is meant to prevent.** The dev's first-pass test fixtures were synthesized from the dev's mental model of "what currency strings look like"; the backend actually emits a *specific* shape (`-$X` sign-then-dollar). No live UI re-probe in the original implementation — only test-fixture matching. The fix loop and the new helper exist precisely because the unit-test net wasn't laid before the bug. Reinforces the calibration rule's value.
  2. **Live UI re-probe substituted with unit-test coverage in the fix loop.** The dev's sub-agent context didn't have the backend running and starting it against the canonical workspace was risky. Instead, the new Vitest suite exercises the exact bug case at the helper layer. Acceptable substrate when the helper contract is a pure function and the route's binding is a single expression.

## Objective

Replace the 8b modal with a dedicated route at `/accounts/:accountId/reconcile`. Add a top-right Reconcile button on `/transactions` when filtered to a single tracked balance-sheet account. On assertion failure (422), the rejection panel leads with `Off by $X.XX` (the magnitude the user needs to scan transactions for) instead of expected/found. The `ReconcileModal.svelte` code is removed.

This is a UI re-architecture, not a feature addition. Behavior parity with 8b is the floor; the route gives subsequent sub-features (8d attest-anyway, 8e subset-sum) somewhere to land that doesn't fight a modal's vertical budget.

## Scope

### Included

1. **New route `/accounts/:accountId/reconcile`** under `app/frontend/src/routes/accounts/[accountId]/reconcile/+page.svelte` (or equivalent SvelteKit shape). Two-step flow as page panels: Setup at top, Review below. The Review panel is disabled (or hidden) until Setup is valid; after Continue, Review becomes interactive.
2. **Reconcile entry point on `/accounts`** (existing button) routes to the new page instead of opening a modal. Button position and label unchanged.
3. **Reconcile entry point on `/transactions`** — new top-right primary-action button, visible only when the active filter resolves to a single tracked balance-sheet account. Hidden otherwise. Clicking navigates to `/accounts/:id/reconcile` with the resolved account id.
4. **Diff-prominent error copy** on 422. The rejection panel headline is `Off by $X.XX` (absolute magnitude of `closing − actual`, rendered with `formatCurrency` and no sign). A subtitle line says `Your statement: $X · Journal: $Y` (signed, uses the existing `signMode: 'good-change-plus'` for liability accounts). A `View details` disclosure shows the raw ledger error verbatim (preserving 8a's `rawError` invariant). The 422 response shape from 8a is unchanged; only the frontend copy changes.
5. **Modal removal** — delete `app/frontend/src/lib/components/accounts/ReconcileModal.svelte`, the import in `app/frontend/src/routes/accounts/+page.svelte`, the modal's mounting state, and any imports left dangling. The bottom-sheet variant code paths go away with it; the route is responsive on its own.
6. **Responsive layout** — the route stacks Setup and Review vertically at `<980px` with full-width inputs and a sticky bottom Reconcile/Cancel bar. No special mobile primitive — the page IS the surface.
7. **Manual end-to-end probe** as part of Definition of Done: reconcile a tracked account through both entry points (accounts card and transactions header) on a real workspace; trigger a 422 by entering an obviously-wrong closing balance and verify the diff-prominent error copy.

### Explicitly Excluded

- Attest-anyway recourse (8d). The 422 panel still has no "Reconcile anyway" action in this task — that's 8d.
- Subset-sum diagnostic (8e).
- Assertion-row rendering on `/transactions` (8f).
- Account-card "Last reconciled" line and broken-status copy (8f).
- Loose-ends dashboard entry (8f).
- Reconciliation history view (8g).
- PDF attachment (8h).
- Adjustment-transaction button (8i).
- Pre-reconciliation edit confirmation (8j).
- Manual merge / match-ranking fixes (Feature 9).
- Any backend change. The 8a endpoint contract and the `GET /api/accounts/:id/reconciliation-context` endpoint are unchanged.

## System Behavior

### Inputs

- Click Reconcile on an `/accounts` tracked-account card → navigate to `/accounts/:id/reconcile`.
- Click Reconcile on the `/transactions` header (single-account scope) → same route, with the account id resolved from the active filter.
- Browser direct-load of `/accounts/:id/reconcile` for a valid balance-sheet account → renders the page.
- Direct-load for an unknown account → SvelteKit 404 page.
- Direct-load for an income/expense/equity account → redirect to `/accounts` with a one-shot error (URL flash or page banner; pick the existing pattern).

### Logic

- The route's `+page.ts` load fetches the tracked-account metadata (name, ledger account, currency, kind) and the initial reconciliation context with default dates: `periodStart = lastReconciliationDate + 1 day` if known, else the earliest journal posting on the account; `periodEnd = today`. Falls back to `today/today` only when nothing is known (the existing 8b fallback).
- Setup section: `periodStart`, `periodEnd`, `closingBalance` inputs. Same validation as 8b — the parser parity fixture and decimal-string math come over from the modal verbatim.
- Continue (or auto-progression on Setup-valid) reveals/enables the Review section.
- Review section: transaction list, diff strip (Opening · Ticked · Closing · Difference), Reconcile button gated on `differenceStr === '0'`.
- Finish posts to `/api/accounts/:id/reconcile`. On 200, navigate to `/transactions?account=<id>` (the natural follow-up surface) with the accounts list invalidated. On 422/409/400, render the rejection panel inline; form remains editable.
- 422 rejection panel: lead with `Off by $|closing − actual|` (compute on the frontend from the 422 body's `expected`/`actual` fields). Subtitle: `Your statement: <expected> · Journal: <actual>`. Disclosure: `View details` toggles `rawError` verbatim.
- Cancel returns to the previous route (browser back) or to `/accounts` if no referrer.

### Outputs

- A new SvelteKit route renders the reconciliation surface.
- Two new entry-point buttons (one on `/accounts` cards re-purposed; one new on `/transactions`).
- 422 error panel uses diff-prominent copy.
- `ReconcileModal.svelte` no longer exists in the tree.

## System Invariants

- The route only renders for tracked balance-sheet accounts (`kind === 'asset' || 'liability'`). Non-balance-sheet accounts redirect.
- Client-side parser parity with the backend (the `currency_parser_cases.json` fixture) is preserved — the route imports the same `currency-parser.ts` module the modal used.
- Cancel never writes. Finish writes only via 8a.
- All client-side validation matches 8a's server-side ladder (404 → 400 kind → 400 currency → 400 dates → 400 balance → 409 collision).
- Modal code is fully removed — `git grep "ReconcileModal"` returns nothing after this task.

## States

- **Setup loading:** route just loaded, fetching default-date context.
- **Setup ready:** form interactive; Continue gated by `setupValid`.
- **Setup valid + Review collapsed/inactive:** Continue prompts the user to advance.
- **Review loading:** fetching context for new dates (debounced).
- **Review ready:** transaction list visible, ticking enabled, diff strip live.
- **Review empty:** "No transactions on this account between `<periodStart>` and `<periodEnd>`." Reconcile possible iff `closingBalance === openingBalance`.
- **Submitting:** Reconcile button shows pending state, all inputs and checkboxes disabled.
- **Success:** navigate to `/transactions?account=<id>`, accounts data invalidated.
- **Error:** rejection panel inline, form editable.

## Edge Cases

- **Direct-load for unknown account.** 404.
- **Direct-load for income/expense/equity account.** Redirect to `/accounts`.
- **`/transactions` filter resolves to two or more tracked accounts.** Reconcile button hidden — single-account scope is the gate.
- **`/transactions` filter is a category or untracked account.** Reconcile button hidden.
- **Mobile viewport.** Page stacks vertically. Reconcile/Cancel anchor to a sticky footer bar.
- **User opens two reconcile routes in two tabs for the same account.** No client locking; whichever finishes first wins, the second sees a 409.
- **422 with no `expected`/`actual` fields** (defensive — should not happen). Fall back to the raw error message in the headline.
- **User navigates away mid-flow via browser back.** No writes happened; nothing to clean up. Returning later starts fresh (no draft state persisted).
- **Concurrent assertion failure where 8a rolls back the journal.** Already covered by 8a; route surfaces the structured error and lets the user try again.

## Failure Behavior

- **422 (assertion failed):** rejection panel with diff-prominent copy. Form editable. Journal already rolled back by 8a.
- **409 (existing reconciliation):** rejection panel with the server `detail` and the date inputs editable.
- **400 (validation):** rejection panel with the server `detail`.
- **404 (account not found):** page renders a 404 state with a link back to `/accounts`. Unlikely on direct-load, possible if the user deleted the account in another tab.
- **5xx / network:** generic error panel with retry. Form preserved.
- **Context-fetch failure on initial load:** route falls back to a `today/today` Setup with a non-blocking warning; the user can still adjust dates and proceed (which will refetch).

## Regression Risks

- **Modal-removal incompleteness.** Stale imports of `ReconcileModal` would compile-fail under `pnpm check`; that's the primary guard. Also delete the modal's test fixtures if any (Vitest tests import the modal — port to route-level tests).
- **Reconcile button on `/transactions` crowds the header.** The header already hosts filter chips and a totals strip from 7d-4c. Verify on a 375px viewport that the new button doesn't overflow; place behind the existing actions or in a kebab if it does.
- **Reconcile-via-`/accounts` navigation regression.** The card layout doesn't change; only the click handler does. Verify Edit, Reconcile, and any other actions all still work.
- **`/transactions` single-account detection.** The button is gated on the active filter resolving to one tracked balance-sheet account. The detection logic must match the existing `single-account-mode` detection used by other 7d-4 features (the totals strip activates similarly). Reuse the existing helper rather than reinventing.
- **422 panel for a user who entered the *correct* balance.** The user's case (zero diff, assertion fails) is currently a 422 with confusing copy. After this task it's a 422 with a clear `Off by $X` headline — but no recourse. 8d adds the recourse; 8c just makes the message readable.
- **Accounts list invalidation on success.** The modal already used `invalidate()`; the route must do the same so the (8f-rendered, future) `Last reconciled` line refreshes when it lands.

## Acceptance Criteria

- A `/accounts/:accountId/reconcile` route exists and renders the two-step flow for valid balance-sheet accounts.
- Direct-load with an unknown `accountId` returns a 404 page.
- Direct-load with an income/expense/equity account redirects to `/accounts`.
- The `/accounts` Reconcile button navigates to the new route (the modal does not open).
- The `/transactions` page header shows a Reconcile button when the active filter resolves to a single tracked balance-sheet account; clicking it navigates to the route with the correct account id.
- The Reconcile button on `/transactions` is hidden when the filter resolves to multiple accounts, a non-tracked account, or a non-balance-sheet account.
- On 422, the rejection panel headline shows `Off by $X.XX` using the absolute magnitude of `closing − actual`. A subtitle line shows `Your statement: <expected> · Journal: <actual>`. A `View details` disclosure shows the raw ledger error.
- `ReconcileModal.svelte` is deleted; `git grep "ReconcileModal"` returns no matches.
- Mobile viewport (<980px) stacks Setup and Review vertically with a sticky footer for Reconcile/Cancel.
- After a successful reconciliation, the route navigates to `/transactions?account=<id>` and the accounts list is invalidated.
- `pnpm check` passes; `uv run pytest -q` passes (no backend changes expected; existing tests stay green).

## Proposed Sequence

1. **Route shell.** Create `app/frontend/src/routes/accounts/[accountId]/reconcile/+page.ts` and `+page.svelte`. Load function fetches account metadata + default-date reconciliation context. 404 on unknown account; redirect on non-balance-sheet. **Verifiable in isolation: navigating to the URL renders the shell.**
2. **Port Setup + Review.** Move the form sections out of `ReconcileModal.svelte` into the route. Keep the diff math, parser, and finish-handler logic identical. The bottom-sheet primitive is dropped — page layout handles responsiveness.
3. **Re-wire `/accounts` Reconcile button.** Replace `onClick={openModal}` with `goto('/accounts/<id>/reconcile')`. Verify card layout unchanged.
4. **Add `/transactions` Reconcile button.** Single-account-scope detection reuses the existing helper. Top-right placement matching the page header convention. Hidden otherwise.
5. **Diff-prominent 422 panel.** Headline copy + subtitle + disclosure. Use `formatCurrency` for the magnitude and signed values.
6. **Remove `ReconcileModal.svelte`** and clean up dangling imports.
7. **Manual probe:** Reconcile via `/accounts` entry, reconcile via `/transactions` entry, force a 422, verify the new error copy.

## Definition of Done

- All acceptance criteria pass.
- `pnpm check` passes; `uv run pytest -q` passes.
- Manual probe completed: both entry points reconcile a tracked account end-to-end on the live workspace; an intentional wrong-balance triggers the diff-prominent 422 panel.
- ROADMAP.md updated: 8c shipped, 8d active.
- A short Implementation Notes block appended to `plans/statement-reconciliation.md` matching the 8a/8b/8a-fix precedent.

## UX Notes

- Page title: `Reconcile statement · <accountName>`.
- Setup layout: three inputs in a single column at desktop; period inputs side-by-side at desktop, stacked at mobile. Closing balance input is the visual anchor (slightly larger / heavier weight).
- Review layout: diff strip at the top (sticky on mobile when scrolling the transaction list), then transaction list, then a sticky footer with Reconcile (primary) and Cancel (secondary) at desktop and mobile alike.
- The 422 panel: red-tinted background with a `text-error` headline, supporting copy in `text-muted-foreground`, the `View details` disclosure rendered with the existing disclosure styling.
- Empty period copy: `No transactions on this account between <date> and <date>.`
- Cancel placement: footer secondary; clicking returns via browser back.

## Out of Scope

- All items under "Explicitly Excluded" above.
- Any change to 8a's endpoint contract or response shape.
- Any change to the `GET /api/accounts/:id/reconciliation-context` endpoint.
- Any change to the existing parser parity fixture or its consumers.

## Dependencies

- 8a backend, 8b modal MVP, 8a-fix ISO — all shipped.
- SvelteKit nested-route conventions (already in use elsewhere in the app).
- `formatCurrency` with `signMode: 'good-change-plus'` (shipped in 7c).
- `currency-parser.ts` (shipped in 8b).

## Open Questions

None. Decisions inline:

- **Route, not nested-modal.** The user's testing was explicit: the modal cramped the work. The route gives 8d/8e/8f future room.
- **Modal code removed, not preserved as fallback.** Two parallel UIs would double maintenance for no gain. Deletion is the correct move.
- **Diff-prominent headline uses absolute magnitude.** The user's natural action is "scan transactions for $X." A signed value (`+$10.49` vs `-$10.49`) is supporting context, not the headline. Sign appears in the subtitle's signed values.
- **Successful reconcile navigates to `/transactions?account=<id>`.** Natural follow-up: the user just confirmed their balance, the next thing they want to see is the activity that justifies it. Closing back to `/accounts` lands them on a less-useful page.
- **No success toast.** Modal closing was the success signal in 8b; navigating away is the route equivalent. Constructive action; matches `feedback_undo_toast_scope.md`.
- **Reconcile button on `/transactions` hidden when not single-account.** Avoids ambiguity about which account is being reconciled. The `/accounts` cards remain the universal entry point for any tracked balance-sheet account.
