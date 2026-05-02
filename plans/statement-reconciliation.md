# Statement Reconciliation

A Camp 1 (Quicken/YNAB-style) reconciliation flow for Ledger Flow, expressed in the journal as a single zero-amount transaction with a balance assertion. The user picks an account, enters the period and closing balance from a paper or PDF statement, ticks transactions until the difference is zero, and finishes — at which point the app writes one assertion transaction to the journal.

This plan supersedes the deferred-list bullet that proposed per-posting `; reconciled: YYYY-MM-DD` metadata. The substrate moves to native balance assertions, which are cross-compatible with `ledger`/`hledger` and require no per-posting writes.

## Status

**Pulled forward from Deferred and slotted as Feature 8 in the delivery sequence, after Feature 5e (semantic undo + toast).** MVP scope and sub-feature breakdown are locked. Implementation does not begin until 5e ships.

## Why this feature, why now

Ledger Flow has no other mechanism for the user to attest "this account matches reality on this date." The closest substitutes — opening balances and import idempotency — only protect against import-time errors, not against drift caused by manual entries that never got matched, missed imports, or hand-edited journals.

The product already supports manual transaction entry. That's the entry point for drift: a manual coffee charge that never gets matched against the bank's import will sit in the journal forever, silently shifting the running balance away from what the bank says. Without a periodic reconciliation step, the user has no way to catch this short of staring at the bank's web UI.

Reconciliation is also a debugging tool. When the user spots a balance that disagrees with the bank, the reconciliation flow is the structured way to find the missing or duplicated transaction — especially once the subset-sum solver lands (8f).

## Camp choice and rationale

The personal-finance market splits into two reconciliation camps:

- **Camp 1 (Quicken / YNAB / QuickBooks):** explicit, statement-driven. Opening + closing balances, tick transactions, hunt difference to zero, finish.
- **Camp 2 (Monarch / Copilot):** no reconciliation; the aggregator feed is truth.

Camp 2 is incompatible with plain-text canon. Without an aggregator, the only honest balance source is a published statement.

Camp 1 fits Ledger Flow's posture: human-in-the-loop trust boundary (matches the existing import → review → confirm pattern), local-first, statement-attested. The vigilance value alone — catching unmatched manual entries and silent imports — justifies the feature.

## Architectural choice: balance assertion as the substrate

Reconciliation is recorded as a single zero-amount transaction with a balance assertion on the asserted account's posting:

```
2026-04-17 * Statement reconciliation · Wells Fargo Checking · ending 2026-04-17
    ; reconciliation_event_id: 01HGE...
    ; statement_period: 2026-03-18..2026-04-17
    Assets:Checking:Wells Fargo  $0 = $2,500.00
```

Why this shape:

- **Cross-compatible.** `ledger bal` and `hledger bal` both verify the assertion natively. A user who opens the journal in any tool gets the same correctness check the app gets.
- **No mutation of existing transactions.** No per-posting `; reconciled:` tags. Existing journal text remains authoritative ([DECISIONS.md §4](../DECISIONS.md)).
- **Undo is one delete.** Removing the assertion transaction (via the existing transaction actions menu) fully reverses the reconciliation. No special undo path required for MVP. The `account.reconciled.v1` event in the event log will produce the standard compensating event when 5e is in play.
- **Hand-written assertions still work.** If a user (or a journal imported from another tool) has hand-written `balance` directives or assertion postings, those still trigger the failure-detection layer. They just don't appear in the reconciliation history view.

The trade-off: assertion failures only surface when the journal is read by `ledger`/`hledger`, not at write time. Every reconciliation flow finish must verify the assertion before reporting success to the user.

## Journal-write invariants

These are non-negotiable for the assertion to mean what it claims:

1. **Last on its date.** The assertion transaction must appear after every other transaction on the assertion date (in file order) within the journal file that holds that date. Balance assertions check the running balance after all postings up to and including that posting in file order — putting the assertion earlier means it checks an intermediate balance, which is meaningless.
2. **Import-merge fence.** Once a date is reconciled, the import path can no longer silently insert new transactions on or before that date. The merge logic must detect the assertion and surface the new transaction as a conflict instead. (See "Conflict surface for reconciled dates" below.)
3. **Date sourced from the statement.** Use the user-entered statement end date as the assertion date. Wells Fargo and similar institutions only include posted transactions in their statements and use posting date, so end-of-statement-period assertions hold without an offset. If a real user reports otherwise, revisit with a smart-date offset like Beancount Reds uses (`min(statement_end - 2, last_posting_date)`).
4. **Single posting, single currency.** MVP supports one currency per account. Multi-currency accounts are out of scope.

## Conflict surface for reconciled dates

The current import pipeline classifies each transaction as `new`, `duplicate`, or `conflict` based on `source_identity` and `source_payload_hash` ([ARCHITECTURE.md §Import Pipeline](../ARCHITECTURE.md)). Feature 8 adds a fourth condition that triggers a conflict:

> A new import row's date is on or before the most recent reconciliation assertion for the target account.

When this triggers, the import flow must surface a conflict with copy along the lines of:

> *This import would change a balance you've already reconciled on April 17, 2026. Either delete the reconciliation and re-run it, or reject this row.*

This is fail-closed in the spirit of [DECISIONS.md §4](../DECISIONS.md): the system never silently rewrites a balance the user has personally attested to.

## Sub-feature breakdown

> **Re-sequenced 2026-04-28** after user testing of 8b. The modal worked for the simple case but cramped the work. The real recurring case is duplicate transactions in the journal causing zero-diff-but-assertion-fails — neither subset-sum nor adjustment buttons resolve that. The route conversion (8c) supersedes the modal; new 8d adds an attest-anyway recourse for the duplicate case; 8e (subset-sum) pulled forward; the rest renumbered. A sibling track (Feature 9) addresses the import-side concerns the duplicates surfaced (manual merge + match-ranking fix). See `ROADMAP.md` Feature 8 entry for the up-to-date sequence.

### MVP (shipped)

#### 8a. Backend — reconcile endpoint, assertion writer, fence, failure detection

**API:**
- `POST /api/accounts/{id}/reconcile`
  - **Inputs:** `period_start`, `period_end`, `closing_balance`, `currency`, `actor` (for the event log).
  - **Side effects:** writes one assertion transaction to the journal file that holds `period_end`; appends an `account.reconciled.v1` event with `journal_refs` and pre/post hashes.
  - **Outputs:** `{ ok: true, assertion_transaction_id, event_id }` on success; structured failure if the assertion does not hold after the write (writer rolls back).

**Assertion failure detection (read-side):**
- Existing account/dashboard endpoints gain a `reconciliation_status` field per account: `{ ok | broken: { date, expected, actual, raw_error? } }`. Source: parse `ledger`/`hledger` balance-assertion errors after each query. Translate to friendly copy on the way out.

**Import fence:**
- Import preview/apply consults the per-account "most recent reconciliation date" (computed from the journal). Any new transaction on or before that date is classified as a `conflict` with reason `reconciled_date_fence`. Existing `new`/`duplicate`/`conflict` model is preserved — the fence is one more reason a row can land in the conflict bucket.

**Writer ordering:**
- The journal writer locates the journal file containing `period_end`, then inserts the assertion transaction after every other transaction with `date == period_end` in that file. If new transactions on `period_end` are added later (via a successful reconcile-aware import), the import logic re-positions them before the assertion; the assertion may need to be re-validated.

**No PDF, no smart-date, no adjustment posting in 8a.**

#### 8b. Reconciliation modal on `/accounts` (SUPERSEDED by 8c)

Shipped as the MVP UI. Two-step `bits-ui` Dialog (Setup → Review) on every tracked balance-sheet account card. Worked for the simple "no duplicates, single statement, immediate close" case. User testing (2026-04-28) found it cramped for multi-month reconciliation work and lacking recourse when the assertion fails despite a zero ticked-diff. 8c replaces the modal with a route; 8d adds the recourse path. The modal code is removed in 8c.

### Active and queued

#### 8c. Reconciliation route + diff-prominent error (active)

**Replaces 8b's modal.** The reconciliation flow becomes a dedicated route at `/accounts/:accountId/reconcile` with proper breathing room. Two entry points: the existing Reconcile button on `/accounts` cards, plus a new top-right Reconcile button on `/transactions` when the active filter is a single tracked balance-sheet account.

The flow is the same Setup → Review → Finish, but laid out as page panels instead of a stacked modal. The Review panel can show more rows without scroll fatigue and leaves room for diagnostics (8d, 8e) to land later.

**Diff-prominent error copy** is the other half of this task. On 422 the panel leads with `Off by $X.XX` (the magnitude of the discrepancy — what the user needs to scan transactions for) instead of expected/found. Expected/found shown as supporting context; raw ledger error behind a `View details` disclosure. The ledger-perspective wording is preserved in raw error but never the headline.

The modal code (`ReconcileModal.svelte` and its mounting) is removed.

#### 8d. Duplicate review + durable resolution (zero-diff-but-assertion-fails)

When the user clicks Reconcile, the ticked-diff is zero, but ledger still rejects the assertion, the route should treat that as a *possible duplicate* workflow, not a bulk-delete workflow.

The route keeps lightweight review controls (`Remaining`, `Checked`, `All`) and, in the zero-diff 422 state, surfaces likely duplicate groups by comparing checked rows against unchecked rows with a tightened heuristic slice from the unknowns/manual-match flow:

- exact absolute amount match required
- narrow date window
- payee similarity only as a ranking signal
- no `close amount`-only candidate tier

The duplicate-review view shows each checked transaction with matching unchecked transactions, source badges (`Imported`, `Manual`), and a plain-language reason the pair was suggested.

Resolution is source-aware:

- **Checked imported + unchecked manual:** `Remove manual duplicate`
- **Checked manual + unchecked imported:** `Use imported transaction`
- **Checked imported + unchecked imported:** `Merge imported duplicates`
- **Checked manual + unchecked manual:** `Remove manual duplicate`

`Use imported transaction` follows the same durability principle as the unknowns/manual-match flow: the imported row survives, the manual duplicate is archived/removed, user-authored categorization or notes carry over as appropriate, and the imported survivor becomes the checked row in the reconciliation view.

`Merge imported duplicates` pulls forward the minimum durable merge substrate from Feature 9: one imported survivor keeps both transactions’ import identity metadata so either bank-row variant is recognized on future imports. This task does **not** include the full transactions-page multi-select merge UI; that remains 9b.

If no sufficiently strong duplicate candidates exist, the route falls back to the 8c rejection copy and ordinary transaction review. A generic “delete all remaining” shortcut is intentionally absent, and generic adjustment posting remains 8i.

#### 8e. Subset-sum diagnostic — "Find the difference" (was 8f)

For the *non-zero* ticked-diff case. Pulled forward from old 8f because once 8c lands the user has the room to host diagnostics inline. Button on the route's Review panel shown when ticked-diff ≠ 0. Bounded combinatoric search (≤ 5 transactions per combination, ≤ 1 s wall-clock) over unticked rows for sums equal to the missing diff; presents top N candidates as one-click "Tick these N to close the gap."

Inspired by YNAB Toolkit's Reconciliation Assistance. Cheap to build, near-magical UX.

#### 8f. Assertion rendering across surfaces (was 8c)

The display work the original 8c covered, now sequenced after the route lands so the route sets the visual baseline first. Three surfaces:

- **Transactions list (`/transactions`):** assertion rows render as a distinct, low-key style — muted background, single line, reconciliation glyph, `Reconciled · ending <date> · balance verified $X` copy. Excluded from filter totals and daily sums.
- **Account card (`/accounts`):** `Last reconciled: <date>` line below balance when at least one reconciliation exists. Replaced with red failure copy when `reconciliationStatus.broken`.
- **Loose-ends aggregator (dashboard):** a new entry kind, `Reconciliation broken on <account> as of <date>`, drilling into the affected account's transactions list scrolled to the broken assertion.

#### 8g. Reconciliation history (was 8e)

New section on each account page: a list of past reconciliations (date, closing balance, link to the assertion row, PDF link once 8h ships). Hand-written assertions are excluded from this view (no `reconciliation_event_id` metadata) but still trigger failure detection.

### Phased follow-ups

#### 8h. Statement PDF attachment (was 8d)

Optional PDF upload at the Finish step of the route. Stored at `workspace/statements/<account-slug>/statement-ending-YYYY-MM-DD.pdf`. Metadata added to the assertion transaction: `; statement_pdf:` and `; statement_pdf_sha256:`. The assertion row in the transactions list, the account card, and the history view (8g) all expose a "View statement" link.

#### 8i. Adjustment-transaction button (was 8g)

When the user has a non-zero ticked-diff they can't resolve and don't want to use 8e to hunt for it, "Post adjustment and finish" writes a single transaction debiting/crediting `Equity:Reconciliation Discrepancies` (configurable; default path), then proceeds to write the assertion. The adjustment carries `; reconciliation_adjustment_for: <event_id>` so it's discoverable.

#### 8j. Confirmation modal for edits/deletes of pre-reconciliation transactions (was 8h)

When the user attempts to delete or re-categorize a transaction dated on or before the most recent reconciliation, prompt:
> *This transaction is part of a reconciliation completed on <date>. Editing it may cause the reconciliation to fail. Continue?*

"Don't ask again this session" and "Don't ask again ever" toggles. The "ever" preference is persisted to `workspace/settings/workspace.toml` once that file accepts user preferences (or a sibling file).

## Decisions to land in DECISIONS.md when 8a ships

- **§14. Statement reconciliation is Camp 1 (explicit, statement-driven).** Why: vigilance + debugging value, especially because the product accepts manual entries that can desync from imports.
- **§15. Reconciliation = zero-amount transaction with native balance assertion.** No per-posting `; reconciled:` tag in this cut. Undo is deletion of the assertion transaction.
- **§16. Statement-end date as assertion date; assertion writes as last entry of its date in the journal file.** Smart-date offsets are not needed for the institutions Ledger Flow currently serves; revisit if a real user hits a lagging-postings issue.
- **§17. Reconciled dates are import-fenced.** New imports on or before a reconciled date surface as conflicts, never silent inserts. Mirrors §4's non-rewriting principle.
- **§18. PDFs as reconciliation evidence, stored under `workspace/statements/`.** Optional in MVP; structurally supported from 8d.
- **§19. No hard lock on reconciled transactions.** Trust is enforced by event-sourced undo and, in 8h, a confirmation modal — not by Quicken/QuickBooks-style locking.

## Out of scope for Feature 8 (this plan)

- Multi-currency accounts.
- Electronically downloaded statement files (OFX/QFX) — the human-attested PDF/print model is the entire scope here.
- Auto-reconciliation against an "online balance" feed. Ledger Flow has no aggregator; the only honest target is a published statement.
- Reconciliation of income/expense or equity accounts. Feature 8 reconciles balance-sheet accounts only.
- Statistical anomaly detection. Subset-sum (8f) is bounded combinatorics, not statistics.

## 8a Implementation Notes (shipped)

Captured during 8a implementation to feed forward into 8b–8c. No deviations from the plan; the items below are clarifications that surfaced during the build.

- **Verification spans every year journal.** The plan didn't specify how multi-year journals are stitched for the `bal --strict` check. Implementation: `ledger -f <each year journal>` is invoked with one `-f` per file in `workspace/journals/*.journal` (excluding the `archived-manual.journal` sidecar). This matches how the existing `load_transactions` reader composes the user's books.
- **`reconciliationStatus` on the dashboard balance sheet.** The dashboard builds its own balance-row shape and does not call `_tracked_account_ui`. The status field was added to the dashboard service's row builder directly, with the same `{"ok": true}` / `{"ok": false, "broken": {...}}` contract.
- **Line numbers are zero-indexed in the API response.** The writer returns the asserted transaction's header line as a zero-indexed offset to match the contract used by `locate_header_at` (and therefore `transactions_delete`). Round-trip "reconcile then delete the assertion via `/api/transactions/delete`" works without the caller having to translate.
- **`emit_event` accepts a caller-supplied id.** The least-invasive option: the reconcile handler pre-allocates a UUIDv7, threads it into the journal metadata, and passes it to `emit_event(event_id=...)`. Both the journal `; reconciliation_event_id:` line and the event log row reference the same id.
- **Frontend type surface.** `app/frontend/src/lib/api/types.ts` does not exist in this codebase — the canonical shared `TrackedAccount` type lives at `app/frontend/src/lib/transactions/types.ts`. Optional `reconciliationStatus`, `conflictReason`, `reconciledThrough` fields landed there so `pnpm check` accepts the new payload shape across consumers.
- **Closing-balance format.** The asserted balance reuses `manual_entry_service._format_currency_amount` (commas, two decimal places). The zero half of the posting renders as `$0` for USD per the plan example, not `$0.00` — both forms are valid ledger syntax.

## 8b Implementation Notes (shipped)

Captured during 8b implementation to feed forward into 8c–8h. No deviations from the spec; the items below are clarifications and choices that surfaced during the build.

- **Currency parser lives in its own module.** `services/currency_parser.py` exposes `parse_amount(raw) -> Decimal`. Both `_parse_amount_str` (manual entry) and `parse_closing_balance` (reconciliation) collapse to thin wrappers — the wrappers stay because external test imports reference them by name and the closing-balance wrapper preserves its custom `Invalid closing balance: ...` error wording the endpoint depends on.
- **Parser parity fixture.** `app/backend/tests/fixtures/currency_parser_cases.json` is consumed by `test_currency_parser.py` (pytest) and `app/frontend/src/lib/currency-parser.test.ts` (Vitest). Both sides accept and reject the same inputs. The fixture is intentionally narrow — only the shapes the modal can encounter — so we don't accidentally lock in `Decimal()`'s scientific-notation surface area, which the user-facing parser doesn't promise.
- **No JS Number for diff math.** The frontend parser returns a normalized decimal *string* and `currency-parser.ts` ships `decimalAdd` / `decimalSub` / `decimalEquals` over BigInt. This was load-bearing: floating-point drift on a `1234567.89` opening + `-0.01` tick would let the modal enable Reconcile when 8a would 422.
- **Vitest is new to the repo.** Added as a dev dep with a standalone `vitest.config.ts` (no SvelteKit plugin during tests) and a `pnpm test` script. `@types/node` came in alongside so the fixture loader can use `node:fs`. `pnpm check` is unchanged.
- **Context endpoint excludes assertion transactions.** `GET /api/accounts/{id}/reconciliation-context` filters out reconciliation-event transactions (zero-amount postings, identified by `; reconciliation_event_id:`) from the visible row list. They contribute zero to the running balance regardless; including them would render as visual noise in the modal.
- **Generated opening-balance transactions show as "Opening balance".** When `periodStart` is the earliest journal posting on the asserted account, the opening-balance transaction itself falls inside the period. The endpoint surfaces it as a row labeled `Opening balance` so the user can tick it and the diff still works for the first-reconciliation case.
- **Modal reaches into Dialog primitive directly for the bottom-sheet variant.** No new wrapper component — TASK called for following `RecentActivitySheet`'s pattern, which uses `bits-ui` `Dialog` with positioning baked into a single `class=` on `Dialog.Content`. The modal swaps between center-card (≥980px, `shell:`) and bottom-sheet (<980px, `max-shell:`) via Tailwind responsive utilities on the same primitive.
- **Refresh-error surface is a dismissible page banner, not a real toast.** The repo doesn't have a general-purpose toast — `undo-toast` is a single-channel store wired to one specific flow. Building a parallel toast pipeline for one rare path was over-spec; the page mounts a fixed-position banner instead, which the user can dismiss. If a generalized toast lands later, this is a one-line swap.
- **`onReconciled` propagates throw, parent owns the error UI.** The modal closes regardless of refresh outcome (modal closing is the success signal). The parent's `onReconciled` hook calls `load()` and re-throws on failure; the modal swallows the throw after closing, the parent has already set its own page banner. This keeps modal state and page state cleanly separated.
- **`_resolve_tracked_account` does not exist.** TASK referenced it as an existing helper, but `main.py` inlines the `config.tracked_accounts.get(account_id)` + 404 lookup at every call site. The new context endpoint follows that same pattern for consistency rather than introducing a one-call helper.

## 8a-fix Implementation Notes (shipped)

Captured after the live-data probe in 8b surfaced an assertion-placement bug. The fix is environmental, not algorithmic — the writer's "last on its date" invariant in `_insertion_index_for_date` was always ISO-dependent (`block_date = line[:10]` is a string compare, and `period_end.isoformat()` is ISO), but pre-existing journals carried slash-formatted headers, so the comparison silently mismatched and assertions landed at the top of the file. 8a's tests never caught it because every fixture was hand-authored ISO. This task makes the dependency explicit: the runner exports `LEDGER_DATE_FORMAT="%Y-%m-%d"`, every writer emits ISO, the existing workspace was migrated, and a regression test scans fixtures for slash drift.

- **Single chokepoint for the env overlay.** `services/ledger_runner.run_cmd` copies `os.environ`, overlays `LEDGER_DATE_FORMAT`, and passes `env=` to `subprocess.run`. Every other call site (verify, reconciliation_status, import convert) inherits the setting automatically — no per-caller threading needed.
- **Writer audit caught two latent slash emitters.** `manual_entry_service.build_manual_transaction_block` was doing `txn_date.replace("-", "/")` to format the header; the matching `undo_service._undo_manual_entry_created` was reversing the slash to look up the entry. Both flipped to ISO in lock-step so the round-trip still works. The reconciliation writer (`_build_assertion_block`) was already ISO-correct from 8a, but the test suite had no per-writer header-format assertion — added one each in `test_journal_date_format.py`.
- **Migration is one-shot, not continuous.** `Scripts/migrate_journal_dates_to_iso.py` runs once per workspace, anchors with `^…\s` under `re.MULTILINE` so inline slash dates inside `; CSV: …` metadata stay verbatim, and skips `*.bak.*` files (historical record). The writer-side invariant prevents regression — there's no need for a continuously-running normalizer.
- **No `LEDGER_INPUT_DATE_FORMAT`.** Ledger's default parser tolerates both formats. Forcing strict ISO input would break user-imported third-party journals; we only constrain *our* writers.
- **Real-data probe.** Wells Fargo Credit Card, periodEnd `2026-01-18`, closing `$-1,491.71` — the exact 8b bug — reconciles cleanly post-migration. Probe rolls back via the same backup-restore path the endpoint uses on failure, so the journal is byte-equivalent before and after.

## 8c Implementation Notes (shipped)

Captured during 8c implementation. The route conversion was largely a port of the 8b modal's setup/review logic onto a SvelteKit nested route, plus the diff-prominent error rebuild. The notes below are clarifications and choices that surfaced during the build.

- **Load function lives at `+page.ts`.** The route is `app/frontend/src/routes/accounts/[accountId]/reconcile/+page.{ts,svelte}`. The load function fetches `/api/tracked-accounts`, finds the matching account, and either: throws `error(404)` for an unknown id, throws `redirect(303, '/accounts')` for non-balance-sheet kinds, or returns `{ account, accountKind, initialPeriodStart, initialPeriodEnd, initialContext, initialContextError }`. The initial context fetch is best-effort — a failure surfaces a non-blocking warning on the page and the user can adjust dates and refetch (matches the spec's failure-behavior table).
- **`apiGet` lives in `$lib/api`, not the load.** The load uses SvelteKit's framework `fetch` directly with an inline JSON helper because `apiGet` only takes a fetch via `opts.signal`, not a `fetch` argument. Threading `apiGet` through the load would require a wider signature change for one caller; the inline helper is a small price for keeping the public API stable. Inside the route's reactive code (debounced refetches on date change), `apiGet` is reused unchanged.
- **`accounts=` URL parameter, not `account=`.** TASK called for `/transactions?account=<id>` after success. The existing `transactionFilters` URL convention is plural `accounts=` (a comma-separated list) — using a single value with the same param name resolves to the same single-account scope and avoids reinventing parsing for one route. This matches what `filtersToUrl` produces for a single-account selection.
- **Single-account-scope detection reuses `filteredAccountKind`.** `/transactions/+page.svelte` already derives `filteredAccountKind` from `accountKindById` (built from `trackedAccounts` filtered to asset/liability). The new Reconcile button gates on `isSingleAccount && filteredAccountKind && selectedAccount`, which is exactly the same shape used by the totals strip introduced in 7d-4c. No new helper module.
- **Diff-prominent panel parses backend currency strings.** The 422 envelope's `expected` and `actual` fields are formatted strings (`-$99,999.00`, `$500.01`) — `parseAmount` strips `$` and `,` so the panel can pass them through `decimalSub` for the magnitude and `Number.parseFloat` for the signed display. This is the only place the route consumes pre-formatted backend numbers; everywhere else the decimal-string contract holds.
- **Successful reconcile invalidates two URLs.** `invalidate('/api/tracked-accounts')` for the account-status refresh that 8f will consume; `invalidate('/api/dashboard/overview')` for the home dashboard's balance-sheet status row. Both are best-effort — failures are swallowed because navigation away is the primary success signal (no toast, per `feedback_undo_toast_scope.md`).
- **Setup commit, not step replacement.** The modal hid Step 2 entirely until Continue advanced from setup. The route renders both panels at all times — Setup always visible, Review collapsed-and-disabled until `setupCommitted` is true (Continue commits, Edit reverts). The Continue button disappears once setupCommitted; the Edit button replaces it inside the Setup card's header. This shape is the foundation 8d's "Reconcile anyway" recourse will land on, where Setup needs to remain visible and editable while a rejection panel shows.
- **Mobile sticky footer; desktop in-flow.** A single `<footer>` with `max-shell:fixed max-shell:bottom-0` utilities — desktop renders it inline at the bottom of the page; mobile (<980px) anchors it to the viewport bottom. A spacer div with `hidden max-shell:block h-20` prevents the sticky bar from covering the last input. No bottom-sheet primitive — the route is the surface, as the spec called for.
- **Cancel uses browser back.** `window.history.back()` if there's history, else `goto('/accounts')` as the fallback. The previous-route guarantee was load-bearing for both entry points: `/accounts` users want their list back; `/transactions` users want their filtered register back.
- **Modal removal is total.** The 8b modal file, the import, the `reconcileTarget` mount state, the `reconcileRefreshError` banner, the `handleReconciled` hook, and the `reconcileAccountKind` helper all came out of `/accounts/+page.svelte` in one pass. The bottom-sheet variant code paths (`shell:` / `max-shell:` Dialog positioning) went with the file.
- **No success toast, no banner.** Constructive action; navigating away to `/transactions?accounts=<id>` is the success signal. The modal-era refresh-error banner (which surfaced when `load()` re-fetch failed after a successful reconcile) is gone with the modal — `invalidate()` is the route equivalent, and a failed invalidation doesn't block the navigation. If the user lands on `/transactions` with stale account status, the next render fixes it.
- **Manual probe results.** Probe 1 (accounts entry → route → form): PASS. Probe 2 (transactions entry, single tracked balance-sheet account scope): PASS. Probe 3 (force 422 with `closingBalance: "-99999.00"` against `wells_fargo_savings`): PASS — backend returns the structured `{outcome: assertion_failed, expected: "-$99,999.00", actual: "$500.01", rawError: ...}` envelope; the route's panel renders `Off by $100,499.01` as the headline, `Your statement: -$99,999.00 · Journal: +$500.01` as the subtitle, and the raw ledger error behind View details. Probe 4 (direct-load unknown account): PASS — server returns 404. Probe 5 (direct-load income/expense): the load function unconditionally redirects 303 to `/accounts` for any kind that isn't `asset` or `liability`; verified by reading the load and the existing tracked-accounts schema (no income/expense tracked-account fixture exists in the live workspace to exercise end-to-end, so this probe is implementation-verified rather than runtime-verified).
