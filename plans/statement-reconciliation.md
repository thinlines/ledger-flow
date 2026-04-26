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

### MVP

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

#### 8b. Reconciliation modal on `/accounts`

Triggered from each account card via a "Reconcile" affordance (placement: secondary action, alongside the existing demoted Edit). Modal flow:

1. **Setup.** Period start (default: day after the most recent reconciliation, or account creation date), period end (default: today), closing balance (free text, parsed). PDF upload deferred to 8d.
2. **Review.** Filtered list of transactions on the asserted account in `[period_start, period_end]`. Each row has a checkbox; rows already cleared by previous reconciliations are pre-checked and locked. A live difference indicator at the top: `Closing balance · $X · Ticked total · $Y · Difference · $Z`. The interaction is "tick until the difference is zero."
3. **Finish.** Disabled until difference is zero. On click, calls 8a. On success, modal closes and the account card shows the new reconciliation status. On assertion failure (which should be impossible if the diff is zero, but fail-closed), the modal stays open with an error banner.

**Escape hatches in MVP:**
- "Cancel" closes the modal without writes.
- If the user has an unresolvable diff and wants to finish anyway, the documented workaround is: cancel, post a manual transaction to `Equity:Reconciliation Discrepancies` covering the diff, reopen the modal. 8g replaces this with a one-click button.

#### 8c. Assertion rendering + failure surfacing

**Transactions list (`/transactions`):**
- Assertion transactions render as a distinct, low-key row style — single-line, muted background, with a small reconciliation glyph and copy like `Reconciled · ending Apr 17, 2026 · balance verified $2,500.00`. They do not count toward filter totals or daily sums.
- Day groups containing a reconciliation row show it last for the day, mirroring the journal-write invariant.

**Account card (`/accounts`):**
- "Last reconciled: Apr 17, 2026" line below balance for accounts with at least one reconciliation. Absent if none. If `reconciliation_status.broken`, replace with the failure copy (red, prominent).

**Loose-ends aggregator (dashboard):**
- A new entry kind: "Reconciliation broken on <account> as of <date>." Drills into the account's transactions list scrolled to the broken assertion.

**Failure copy:**
- Translated form: `Reconciliation broken on April 17, 2026 — expected $2,500.00, found $2,487.43.`
- Raw `ledger` error available behind a "details" disclosure for the curious or for support diagnosis.

### Phased follow-ups

#### 8d. Statement PDF attachment

- Optional PDF upload at the finish step of 8b.
- Stored at `workspace/statements/<account-slug>/statement-ending-YYYY-MM-DD.pdf`. Filename uses the user-entered statement end date (statement boundaries rarely align with month end).
- Metadata added to the assertion transaction: `; statement_pdf: statements/wells-fargo-checking/statement-ending-2026-04-17.pdf` and `; statement_pdf_sha256: <hash>`.
- The reconciliation row in the transactions list and the account card both expose a "View statement" link.

#### 8e. Reconciliation history view

- New section on each account page: "Reconciliation history" — list of past reconciliations (date, closing balance, link to the assertion row, PDF link if 8d shipped).
- Hand-written or imported assertions are excluded from this view (no `reconciliation_event_id` metadata) but remain functional for failure detection.

#### 8f. Subset-sum solver — "Find the difference"

- Button in the 8b review step shown when difference is non-zero.
- Bounded combinatoric search over unticked transactions for combinations whose sum equals the diff. Cap at e.g. 5 transactions per combination, 1-second wall-clock budget, return top N candidates.
- Each candidate is presented as "Tick these N transactions to close the gap" with one-click apply.
- Cheap to build, near-magical UX. Inspired by YNAB Toolkit's "Reconciliation Assistance."
- Also covers the case where a manual entry is recorded as a multi-posting split but the bank line is a single row (relevant once split transactions ship; today the existing N-1 posting collapse on the transactions screen handles display, not creation).

#### 8g. Adjustment-transaction button

- Replaces the manual workaround documented in 8b. When the diff is non-zero, "Post adjustment and finish" writes a single transaction debiting/crediting `Equity:Reconciliation Discrepancies` (configurable in workspace settings, defaulting to that path), then proceeds to finish.
- The adjustment transaction carries `; reconciliation_adjustment_for: <event_id>` metadata so it's discoverable.

#### 8h. Confirmation modal for edits/deletes of pre-reconciliation transactions

- When a user attempts to delete or re-categorize a transaction whose date is on or before the most recent reconciliation for the affected account, prompt:
  > *This transaction is part of a reconciliation completed on April 17, 2026. Editing it may cause the reconciliation to fail. Continue?*
- "Don't ask again this session" and "Don't ask again ever" toggles. The "ever" preference is persisted to `workspace/settings/workspace.toml` (or a sibling preferences file).

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
