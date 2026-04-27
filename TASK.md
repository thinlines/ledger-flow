# Reconciliation Modal (8b) — Setup, Review, Finish

**Status: COMPLETED — 2026-04-26**

## Delivery Notes

- QA verdict: PASS WITH FINDINGS. 659 tests pass (600 prior + 59 new across context endpoint and currency parser); `pnpm check` clean across 841 files; 28 Vitest cases for parser parity.
- Code review verdict: SHIP. All 13 acceptance criteria mapped to real production code paths (not vacuous tests). Reviewer flagged two minor non-blocking observations (parser regex narrower than backend `Decimal()` accepts; `periodStart` initial seed is today rather than earliest journal posting on the account).
- Findings worth follow-up:
  1. **Setup-screen Continue gating doesn't enforce the `periodStart >= last_reconciliation_date + 1 day` floor on first open** — context fetches only on entering Review, so `minPeriodStart` is empty during Setup. The flow self-corrects (`periodStart` snaps after fetch and Reconcile only runs in Review), but a strict reading of AC #5 expected the floor enforced from Setup. Fix path: trigger an initial context fetch on modal open, or add a lighter probe for `lastReconciliationDate` alone.
  2. **Server-side fence enforced on `period_end`, not `period_start`** — inherited from 8a (`main.py:1386-1404`). Combined with `period_start <= period_end`, the most-likely collision shapes are blocked, but a user could submit `period_start` earlier than the latest reconciliation; the assertion verifier would catch it but the journal write goes through first. Tighten in a small 8a follow-up by adding a `period_start <= existing_latest` 409 alongside the existing `period_end` checks.
  3. **Frontend parser regex is stricter than backend `Decimal()`** — rejects `.5`, `+100`, scientific notation that backend would accept. Lower-risk than the inverse drift; documented in the plan note.
- Spec ambiguities resolved during implementation (recorded in `plans/statement-reconciliation.md` "8b Implementation Notes"):
  - `_resolve_tracked_account` doesn't exist; the new endpoint inlines `config.tracked_accounts.get(account_id)` + 404, matching the established pattern.
  - The "refresh failure surfaces a toast" line in the spec lands as a fixed-position banner in this iteration because the repo's only general-purpose toast pipeline is undo-toast; a future general toast lands as a one-line swap.
  - `parse_closing_balance` retains its custom error-message wrapper around the new shared `parse_amount` because downstream callers depend on the `Invalid closing balance: ...` wording.

## Objective

A user clicks **Reconcile** on a tracked-account card in `/accounts`, enters the statement period and closing balance, ticks transactions until the difference is zero, and clicks **Reconcile** to finish. The flow calls 8a's `POST /api/accounts/{id}/reconcile`. The modal closes on success; on validation or assertion failure it stays open with a banner. No other UI lands here — assertion-row rendering, broken-status surfacing, history view, loose-ends entries, and pre-reconciliation edit confirmation are all 8c / 8e / 8h.

## Scope

### Included

1. New backend endpoint `GET /api/accounts/{accountId}/reconciliation-context?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD` returning the openings, transactions, and currency the modal needs in one round-trip.
2. **Reconcile** button on each tracked-account card on `/accounts` (`app/frontend/src/routes/accounts/+page.svelte`). Placement: secondary action alongside the demoted Edit affordance under the Accounting details disclosure (per `feedback_component_patterns.md` and the 7c shell-polish convention).
3. New component `ReconcileModal.svelte` (desktop dialog) / bottom-sheet variant (<980px) with two steps: **Setup** and **Review**.
4. Setup step: `periodStart` (date), `periodEnd` (date), `closingBalance` (text). Defaults: `periodStart` = day after the most recent reconciliation date for this account (or earliest journal posting on the account if none); `periodEnd` = today; `closingBalance` empty. Continue is disabled until all three parse.
5. Review step: list of transactions on the asserted account in `[periodStart, periodEnd]`, each with a checkbox. A live diff strip at the top: `Opening · $X · Ticked · $Y · Closing · $Z · Difference · $W`. **Reconcile** button is disabled until `Difference == 0`.
6. Finish handler: `POST /api/accounts/{accountId}/reconcile` with `{periodStart, periodEnd, closingBalance, currency}`. On 200 → close modal and re-fetch the accounts list. On 422 / 409 / 400 → stay open, render the structured error in a banner.
7. Cancel: closes the modal, no network calls.
8. Backend currency-parser consolidation: extract a single shared helper (e.g. `app/backend/services/currency_parser.py` exposing `parse_amount(raw: str) -> Decimal`) that both `manual_entry_service._parse_amount_str` and `reconciliation_service.parse_closing_balance` call. No new behavior — same accepted shapes (optional `$`, comma group separators, optional minus, optional whitespace), same `ValueError` on reject. Existing call sites switch to the shared helper; the two old wrappers can be deleted or reduced to thin re-exports if any external test imports them.
9. Frontend currency parser used in the modal accepts the same shapes as the shared backend helper. A shared JSON fixture (e.g. `app/backend/tests/fixtures/currency_parser_cases.json`) drives both pytest and Vitest parity tests — every input either parses identically on both sides or rejects on both sides.
10. Backend test for the context endpoint. Vitest unit tests for the diff math and the parser parity. One Playwright-or-equivalent end-to-end test is **not** required; manual verification covers the integration path.

### Explicitly Excluded

- Statement PDF upload (8d).
- Subset-sum solver — "Find the difference" button (8f).
- Adjustment-transaction button — "Post adjustment and finish" (8g). The MVP workaround stays documented inline (cancel → post a manual transaction to `Equity:Reconciliation Discrepancies` → reopen).
- Pre-checked locked rows for transactions in prior reconciliations. Locking `periodStart >= last_reconciliation_date + 1 day` removes the need.
- Transactions list rendering of the new assertion row (8c).
- Account card "Last reconciled" line and broken-status copy (8c).
- Loose-ends entry for broken reconciliation (8c).
- Reconciliation history view (8e).
- Edit/delete confirmation modal for pre-reconciliation transactions (8h).
- Multi-currency reconciliation. The endpoint already rejects with 400.
- Reconciliation of income / expense / equity accounts. The endpoint already rejects with 400; the modal hides the **Reconcile** button on non-balance-sheet accounts.
- Success toast. Constructive action — modal closing is the confirmation. Saved feedback `feedback_undo_toast_scope.md` reserves toasts for destructive / non-obvious reversals.

## System Behavior

### Inputs

- Click **Reconcile** on a tracked-account card → opens the modal scoped to that account.
- User edits `periodStart` / `periodEnd` / `closingBalance` in Setup; clicks **Continue** to advance to Review.
- User toggles row checkboxes in Review; live diff updates synchronously.
- User clicks **Reconcile** (Finish) or **Cancel**.

### Logic

- On open, the modal calls `GET /api/accounts/{id}/reconciliation-context` with the current Setup values. Refetches when `periodStart` or `periodEnd` changes (debounce 250ms).
- Diff math: `difference = parsed(closingBalance) - (openingBalance + sum_signed(ticked_rows, asserted_account))`.
- Diff comparison uses string-decimal equality after parsing (no floating point). Match 8a's parser exactly: strip leading `$`, strip commas, optional minus, then `Decimal()`. Empty string is invalid.
- **Reconcile** disabled while `difference != 0`, while a fetch is in flight, or while `closingBalance` is invalid.
- On click → `POST /api/accounts/{accountId}/reconcile` with body matching the 8a contract.
- On 200, the modal calls the accounts list refresh hook and closes. (8c will render the now-populated `reconciliationStatus`.)
- On 422 (assertion failed — defense-in-depth, should be unreachable when `difference == 0`), render `message`, `expected`, `actual` from the structured response in a banner. Keep modal open. Do not auto-clear; the user re-reads inputs.
- On 409 (existing reconciliation collision), render the server `detail` and re-enable the date inputs.
- On 400 (validation), render the `detail` and let the user edit.
- On 5xx or network error, render a generic banner with the underlying message; user can retry.

### Outputs

- New endpoint response shape:
  ```json
  {
    "openingBalance": "1240.50",
    "currency": "USD",
    "lastReconciliationDate": "2026-03-17",
    "transactions": [
      {
        "id": "abc123",
        "date": "2026-03-22",
        "payee": "Coffee Shop",
        "category": "Expenses:Food:Coffee",
        "signedAmount": "-4.75"
      }
    ]
  }
  ```
  `signedAmount` is the asserted account's posting amount (positive when the account balance increases). Transfer rows surface only their effect on the asserted account.
- On finish-success: account list payload is re-fetched; the existing `reconciliationStatus` field (8a) reflects the new state.

## System Invariants

- Modal cannot finish with `difference != 0`. Defense-in-depth against 8a's assertion check.
- `periodStart >= last_reconciliation_date + 1 day` when a previous reconciliation exists. Modal locks `periodStart` to that floor; the date input refuses lower values.
- `periodStart <= periodEnd`. Backend already validates; modal disables Continue when violated.
- Closing-balance parser is byte-equivalent to 8a's. Vitest test asserts a shared fixture of inputs returns the same Decimal on both sides (or symmetric reject).
- Cancel never writes. Finish writes via 8a only. No client-side journal mutation.
- The context endpoint is read-only. It does not emit events or backup anything.

## States

- **Closed:** modal not mounted.
- **Setup:** period inputs and `closingBalance` editable. **Continue** enabled when all three parse and ranges are valid.
- **Review (loading):** fetching context. Transaction list area shows a skeleton or spinner; **Reconcile** disabled.
- **Review (loaded):** transaction list with checkboxes, live diff strip. **Reconcile** enabled iff `difference == 0`.
- **Review (empty period):** "No transactions on this account between `<periodStart>` and `<periodEnd>`." Diff still computable from openings + closingBalance alone. **Reconcile** enabled iff `closingBalance == openingBalance`.
- **Submitting:** **Reconcile** shows pending state, all inputs and checkboxes disabled.
- **Success:** modal closes; accounts list refreshes.
- **Error:** modal stays open, banner shows the structured error or fallback copy. User can edit and retry.

## Edge Cases

- **First reconciliation for an account.** `lastReconciliationDate` is `null`. `periodStart` defaults to the earliest journal posting on the asserted account, or the account's opening-balance date, whichever exists. `openingBalance` may be `0`.
- **Account with no transactions in the period.** Empty list message. Reconcile still possible if `closingBalance == openingBalance` (catches the "I attest nothing happened" case).
- **`periodEnd` in the past.** Allowed; reconciling a historical statement.
- **Closing balance with `$` and commas (`$2,500.00`).** Parser strips both and accepts. Must match 8a server-side.
- **Negative closing balance** (liability account, e.g., credit card statement of `$1,234.56` owed represented as a negative asset balance). Parser accepts leading `-`. Must match 8a's posting-side semantics — reuse the existing convention.
- **Transfer row in the period.** Endpoint returns the transfer with `signedAmount` reflecting only the asserted account's posting. Two sides of a tracked-to-tracked transfer collapse to one row per the existing N-1 / transfer-pair rules; the modal does not need to dedupe.
- **Two reconciliation modals open in two browser tabs.** No client locking. Whichever finishes first wins; the second sees 409 if the date collides, otherwise its own assertion check rules.
- **Account renamed or deleted while modal is open.** On Finish, 8a returns 404; modal banner shows the message. User cancels.
- **Mobile viewport (<980px).** Modal renders as a bottom sheet using the same `bits-ui` Sheet primitive `RecentActivitySheet.svelte` uses, with the same right-side / bottom variant switch keyed on the existing breakpoint store.
- **Income / expense / equity account.** **Reconcile** button is hidden on these account cards. Defense-in-depth: 8a returns 400 if it ever gets called.

## Failure Behavior

- Context fetch fails: stay in Review with a retry button. **Reconcile** disabled until the fetch succeeds (without `openingBalance` the diff math is meaningless).
- 8a 422 (assertion failed): render translated copy plus the disclosure of `rawError` for diagnosis. Modal stays open. Journal already rolled back by 8a; no client cleanup needed.
- 8a 409: render `detail`, re-enable date inputs, leave checkboxes intact.
- 8a 400: render `detail`, allow edit.
- 8a 5xx or network: generic banner with retry. Journal state on the server is whatever 8a left it — for the 500 path 8a rolled back.
- Accounts-list refresh failure after a successful reconcile: do not block the close. Show a non-blocking refresh-error toast (one of the few uses of toast here, and only because the data desync is a trust issue).

## Regression Risks

- **Account card layout shift on mobile.** Adding **Reconcile** alongside Edit must not push card content off-screen at 375px. Test by visually confirming the accounts page on a narrow viewport before and after.
- **Currency-parser drift between client and server.** If the modal accepts `$2 500,00` (European format) but 8a rejects it, **Reconcile** could be enabled when the backend will 422. Vitest fixture asserts shared inputs round-trip identically.
- **Transfer-row signed amount.** A transfer between two tracked accounts shows up as one row in the unified transactions endpoint. The modal must use the asserted-account posting amount, not the row's display amount, or the diff math is wrong. Backend test covers this on a fixture journal containing a tracked-to-tracked transfer.
- **Sheet primitive z-index.** Opening Reconcile while the recent-activity sheet (5e) is open must not stack incorrectly. Reuse the existing dialog mutex.
- **Refetch after success.** If the accounts list is cached client-side (likely via load function), the cache must invalidate after a successful reconcile or the new `reconciliationStatus` won't appear until the next navigation. Use the existing `invalidate()` hook used elsewhere on /accounts after Edit.

## Acceptance Criteria

- `manual_entry_service` and `reconciliation_service` both call a single `parse_amount` from a shared currency-parser module. The two old wrapper functions either delegate or are removed; no parser code is duplicated.
- A `currency_parser_cases.json` fixture lives under `app/backend/tests/fixtures/` and is consumed by both pytest and Vitest. Every input in the fixture has the same accept/reject outcome on both sides.
- A **Reconcile** button is visible on every tracked-account card on `/accounts` whose ledger account starts with `Assets:` or `Liabilities:`. Hidden on income / expense / equity accounts.
- Clicking opens a modal titled `Reconcile statement · <accountName>` with two steps.
- Setup step shows three inputs with the documented defaults; **Continue** is disabled until all three parse and `periodStart >= last_reconciliation_date + 1 day` (when one exists).
- Review step shows a transaction list filtered to the asserted account in `[periodStart, periodEnd]`, with checkboxes per row and a live diff strip showing Opening, Ticked, Closing, Difference. **Reconcile** is disabled while `Difference != 0` or while a fetch is in flight.
- On **Reconcile** with `Difference == 0`, the modal POSTs to `/api/accounts/{id}/reconcile` with the documented payload and closes on 200. On 422 / 409 / 400, the modal stays open with a banner reflecting the structured error.
- The new `GET /api/accounts/{id}/reconciliation-context` endpoint returns `openingBalance`, `currency`, `lastReconciliationDate`, and a `transactions` array with `signedAmount` reflecting the asserted account's posting (transfers included).
- **Cancel** closes the modal without any network call.
- Mobile viewport (<980px) renders the modal as a bottom sheet using the existing `bits-ui` Sheet primitive.
- After a successful reconciliation, the accounts list payload is invalidated and re-fetched so the existing `reconciliationStatus` field reflects the new state.
- Currency parser used by the modal accepts the same shapes as 8a's `parse_closing_balance`. A Vitest fixture asserts parity.
- `pnpm check` passes; `uv run pytest -q` passes including the new context-endpoint test.

## Proposed Sequence

1. **Currency-parser consolidation.** Extract `parse_amount` to a shared module. Switch `manual_entry_service` and `reconciliation_service` to call it. Pytest fixture (`tests/fixtures/currency_parser_cases.json`) covers the accepted/rejected shapes. All existing tests continue to pass — no behavior change. **Verifiable in isolation: 600 backend tests still green.**
2. **Backend context endpoint.** Add `GET /api/accounts/{accountId}/reconciliation-context` to `app/backend/main.py`. Use existing helpers (`_resolve_tracked_account`, `_account_kind`, the running-balance computation from `transaction_helpers.py`, `latest_reconciliation_date` from `reconciliation_service.py`). Tests: opening balance equals the running balance at `periodStart - 1 day`; transaction list contains only postings on the asserted account; transfer rows surface the asserted-account amount; income/expense accounts return 400.
3. **Reconcile button on the account card.** Add the affordance under the Accounting details disclosure on `app/frontend/src/routes/accounts/+page.svelte`. No-op handler. Verify mobile layout.
4. **ReconcileModal scaffolding (Setup step).** New component under `app/frontend/src/lib/components/accounts/ReconcileModal.svelte`. Three inputs with defaults computed from the account's `lastReconciliationDate`. Continue gating. Cancel.
5. **Review step.** Fetch context on entering Review and on date-input changes (debounced 250ms). Render transaction list with checkboxes. Live diff strip with `formatCurrency` (use the existing helper). Finish gating.
6. **Finish wiring.** POST to 8a, error banner on non-2xx, accounts-list invalidation on 200. Surface 422 with `expected` / `actual` translated; show `rawError` behind a disclosure.
7. **Mobile sheet variant.** Switch primitive at <980px following `RecentActivitySheet.svelte`'s pattern. Verify on a 375px viewport.
8. **Parser parity test.** Vitest reads the same `currency_parser_cases.json` fixture and asserts the frontend parser accepts/rejects identically.

## Definition of Done

- All 13 acceptance criteria pass.
- `uv run pytest -q` passes (new context-endpoint test plus the existing 600).
- `pnpm check` passes.
- Manual end-to-end on a fixture workspace: reconcile a tracked account with the correct closing balance — modal closes, accounts list shows the updated `reconciliationStatus`. With a wrong balance: 422 banner appears with translated copy. With a colliding date: 409 banner.
- ROADMAP.md: 8b marked shipped; 8c promoted to current focus.
- A short follow-up note appended to `plans/statement-reconciliation.md` capturing any deviations encountered (matching the 8a precedent).

## UX Notes

- Modal title: `Reconcile statement · <accountName>`.
- Setup layout: three inputs in a single column, labels above. Period inputs side-by-side at desktop, stacked at mobile. Closing-balance input is the visual anchor — slightly larger / a heavier weight, since it's the typed-in value the user is attesting to.
- Diff strip layout: horizontal row of four labeled values. Difference auto-styles: red when non-zero, green/neutral when exactly zero. Use `formatCurrency` with `signMode: 'good-change-plus'` to stay consistent with 7c.
- **Reconcile** button label is the verb, not "Submit" or "Finish". Cancel sits secondary in the footer.
- Transaction row in the review list: date · payee (truncated, raw bank text demoted per 7a hierarchy) · signed amount · checkbox. No category pill — the modal isn't an editing surface, it's a verifying one.
- Empty period copy: `No transactions on this account between <date> and <date>.`
- Banner copy on 422: `Reconciliation rejected — expected $X, found $Y.` plus a `View details` disclosure showing the raw `ledger` error verbatim (per 8a's invariant on `rawError`).

## Out of Scope

- All items under "Explicitly Excluded" above.
- Any change to the 8a endpoint contract.
- Any change to `_tracked_account_ui` or the dashboard balance row builder (8a already wired the read-side).

## Dependencies

- 8a (backend) — shipped.
- `bits-ui` Dialog and Sheet primitives — already in use (`RecentActivitySheet.svelte`, `TransactionDetailSheet.svelte`, `ManualResolutionDialog.svelte`).
- The accounts page shell and tracked-account card layout from 7c — shipped.
- `formatCurrency` with `signMode: 'good-change-plus'` from 7c — shipped.

## Open Questions

None. Decisions inline:

- **Opening balance derivation.** New context endpoint returns it via the running-balance helper at `periodStart - 1 day`. Reuses existing infrastructure; avoids the modal computing it client-side from a transaction list (which is brittle on partial pages).
- **No success toast.** Modal closing is sufficient; matches saved feedback `feedback_undo_toast_scope.md`.
- **`periodStart` locked to `last_reconciliation_date + 1 day`.** Avoids the "pre-checked locked rows" UI complexity in MVP. Users who genuinely want to redo an earlier period delete the prior reconciliation first (8a's 409 path is the breadcrumb).
- **Cancel does not warn.** No network calls have been made; nothing to lose. Saved feedback `feedback_undo_toast_scope.md` extends here: no friction on trivially reversible actions.
- **Refetch failure surfaces a toast.** One of the rare toast uses — the data desync is a trust issue and the user needs to know to reload manually.
