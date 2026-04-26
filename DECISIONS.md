# Decisions

This document records stable product and architecture choices that explain why the repo works the way it does today.

## 1. Optimize for a GUI-First Finance Product

**Decision:** The primary experience is a polished personal finance app, not a thin UI over plaintext accounting tools.

**Why:** Most users should be able to manage their finances without learning developer tooling or accounting internals.

**Implication:** Primary UI copy talks about money, accounts, spending, activity, and next steps. Technical accounting language belongs in advanced surfaces or documentation.

## 2. Keep Plain Text as the Foundation, Not the Default Mental Model

**Decision:** Canonical financial data lives in open, human-readable files, but the default product path hides that storage model.

**Why:** Durability and portability matter, but they should not dominate the user experience.

**Implication:** Paths, journals, postings, and ledger-account mappings stay behind explicit reveals, advanced workflows, or docs.

## 3. Make Workspace Files Canonical and Operational State Disposable

**Decision:** `workspace/` is the source of truth. `.workflow/` exists for speed, resumability, and import memory only.

**Why:** Accounting truth should remain portable, inspectable, and recoverable outside the app.

**Implication:** If `.workflow/` is lost or stale, rebuild it from the workspace. Never let it override journals or workspace config.

## 4. Keep Imports Idempotent, Conflict-Visible, and Non-Rewriting

**Decision:** Importing adds only new transactions, skips duplicates, and surfaces conflicts instead of rewriting history.

**Why:** This preserves rich journals:

- Manual comments, tags, and edits remain untouched.
- Rerunning an import stays safe when identity fields are stable.
- Journal text remains authoritative, while the import index acts as audit and idempotency memory.

**Implication:** Preserve source identity and payload metadata, require preview before apply, and never auto-modify transactions that already exist in journals. New transactions may be merged into journal date order, but existing transaction text remains unchanged.

## 5. Treat Eventual Consistency as a Product Principle

**Decision:** Users can build financial history and account coverage incrementally over time.

**Why:** Real users often begin with incomplete imports, unsupported institutions, opening balances, or partial historical backfill.

**Implication:** Adding accounts later, seeding opening balances, and backfilling older years should not break the current picture.

## 6. Make the Dashboard the Daily Home

**Decision:** The default landing experience should emphasize financial state, recent change, and next actions instead of system status.

**Why:** Once setup and import work, the product should still be useful when there is little maintenance work to do.

**Implication:** Import, review, and rules support the dashboard and accounts experience instead of defining the product identity.

## 7. Use Setup for Momentum, Not Permanent Administration

**Decision:** Setup exists to get a user from zero to first useful result quickly, then hand off to normal product surfaces.

**Why:** First-run should feel guided and lightweight instead of becoming the permanent home for account management or diagnostics.

**Implication:** Account management, import work, and review must all remain available outside setup, and advanced bootstrap detail should stay hidden by default.

## 8. Keep Balance-Sheet Setup in Accounts, Not Rules

**Decision:** Tracked balance-sheet accounts belong in Accounts flows. Rules and review remain focused on income/expense categorization and automation, not as the primary place to create or manage tracked assets and liabilities.

**Why:** Once the product separates tracked accounts from categories, users need a first-class, finance-first way to create liabilities such as car loans without learning ledger prefixes or accounting internals.

**Implication:** Accounts UI must expose asset-vs-liability choice directly, subtype state must be trustworthy instead of silently inferred, and balance-sheet workflows belong in Accounts rather than being pushed into rules or review.

## 9. Require Human Confirmation for Transfer Matching

**Decision:** The import pipeline must not auto-link bilateral transfer pairs. All transfer matches flow through the unknowns review queue for user confirmation.

**Why:** Import-time auto-linking was considered when both sides of a transfer are independently imported with different dates. It was rejected because skipping the review step removes the human confirmation checkpoint, reducing trust. The unknowns review page is the trust boundary for categorization and matching decisions.

**Implication:** Bilateral pairs that arise from separate imports are handled by read-time auto-reconciliation (display-only, no journal writes) and resolved permanently when the user confirms the match through the unknowns review. The flow is: import → review → confirm → reconcile.

## 10. Prefer Journal-Derived Opening Balance Offsets Over New Link State

**Decision:** For the current financed-liability cut, the product should let users choose an opening-balance offset account without introducing a new persistent pairing or account-relationship model.

**Why:** The user problem is immediate accounting correctness for the starting entry, not long-term account-link semantics. A lighter implementation solves the blocker faster and avoids prematurely hardening a product concept the app may not need yet.

**Implication:** Opening-balance edit flows should derive the current offset from the existing opening-balance transaction, default to `Equity:Opening-Balances`, and only branch to another tracked account when the user explicitly chooses that accounting treatment.

## 11. Inline Signals Over Action Cards

**Decision:** Dashboard status signals (review queue, staleness, missing data) live inline where the relevant data already appears — the Today rail, transaction badges, per-account indicators — rather than in a centralized "needs attention" card section or notification center.

**Why:** Action card patterns assume a steady stream of heterogeneous alerts (bill due dates, budget alerts, sync failures, anomaly flags). Ledger Flow's data model produces 0–2 actionable signals at any given time. A dedicated section that's usually empty creates anxiety ("should something be here?") and imposes an abstraction tax: every future feature must decide whether it generates a card, cards need priority weights, and dismissal state needs persistence. Inline signals are cheaper to build, contextually richer, and avoid the empty-state problem entirely.

**Implication:** New features that surface actionable state should embed indicators next to the data they relate to (e.g., staleness next to account balance, review badge next to transaction) rather than registering with a centralized action-card system. The Today rail remains the single CTA surface for the dominant next action.

## 12. Event Sourcing for Undo; Journals Remain Canonical State

**Decision:** Journal mutations are recorded as events in an append-only log at `workspace/events.jsonl`. Events capture user intent and enable undo via compensating events. Journals remain canonical state. Git serves as periodic snapshots — an escape hatch and future file-sync substrate — not as the undo mechanism.

**Why:** Git auto-commits were initially positioned as the primary safety layer and undo mechanism. In practice they give file-level text diffs, not user-facing undo: `git revert` does not match the granularity users expect (per-transaction, partial, drift-aware), and per-mutation commits duplicate what an event log captures more faithfully. Event sourcing separates causality (why a change happened) from state (what the journal currently is), enables partial undo when some affected transactions have drifted, records user intent as first-class data, and generalizes cleanly to future multi-user sync.

**Implication:**
- `workspace/events.jsonl` holds append-only events with UUIDv7 identifiers, an `actor` field, a `compensates` link, and `journal_refs` with content hashes.
- Compensating events are first-class event types (e.g., `unknowns.reverted.v1`) linked back to the forward event via `compensates`.
- Undo walks the log backward, applies inverse actions, checks per-event `hash_after` against current state, and produces a partial-undo report when drift is detected.
- External edits to journals (outside the app, while running or down) are detected by pre-mutation and startup hash checks, which append `journal.external_edit_detected.v1` marker events. The system does not attempt to reconstruct what the user did externally.
- Git commits become periodic snapshots (on server shutdown or daily), not per-mutation. They preserve a file-level recovery path and remain the substrate for future multi-user file sync.
- Precedence when sources disagree: journals > events > git. The app never overwrites journal content on the basis of the event log alone.

## 13. Dashboard Insight Loop: Explanation Over Data, Direction Over Chores

**Decision:** The dashboard's third question is reframed from "What needs my attention next?" to "Where should I go next?". Every dashboard insight (category trend, cash flow row, health signal) drills into an explanation view that decomposes the change before showing transactions. The dashboard gains a dedicated "direction" section for derived health signals (runway, net worth trend, recurring vs discretionary spending) and low-code investigation hooks, distinct from the inline bookkeeping signals described in §11.

**Why:** The original framing — "What needs my attention next?" — produced an inbox-of-chores mental model. The Today rail surfaced one rotating bookkeeping signal at a time and the rest of the third question was scattered across inline pills. Activity drilldowns from category trends and cash flow rows landed on raw filtered transaction lists with no comparison, decomposition, or top-mover context, so every insight was a dead end. The product was very good at "your books are in order" and silent on "your money is in order" — those are different products living at the same URL. The bookkeeping layer should be fast enough that the user has time to ponder bigger questions about their finances; the dashboard is the place where those questions get raised and where the first answer lives.

**Implication:**
- The activity view renders an explanation header (period total, prior-period comparison, 6-month rolling average, frequency, top mover) above the transaction list whenever a filter is active. The same explanation applies whether the user arrived from a dashboard insight or opened the activity view directly.
- Activity rows promote category to a leading visual position (a pill before the payee). Raw bank payees are truncated. Category is the most useful dimension for scanning a cross-account list and was previously the quietest element.
- The dashboard gains a "Where should I go next?" section with the same visual weight as Recent Activity and Category Trends. It contains derived health signals (runway, net worth trend, recurring vs discretionary), low-code notable signals (largest transaction, category spikes, spending streaks), and a loose-ends aggregator at the bottom.
- Health signals are derived metrics only. Goals, targets, and budgets remain deferred. Runway is `spendable cash / 6-month average monthly spending`. Net worth trend is a sparkline of month-end balances. Recurring vs discretionary is a heuristic split based on category frequency. None require user input.
- Notable signals are low-code arithmetic only. No statistical models, no anomaly detection, no ML. Largest transaction, category-above-average, spending-exceeds-income streaks. Future GenAI analysis (Ollama, ChatGPT API) is a possible direction but requires data-privacy planning and is not in scope for the current cut.
- Investment tracking (401(k), HSA, pretax contributions) is explicitly out of scope. These accounts don't appear in tracked balances and the health signals reflect only what the workspace knows about.
- This decision complements §11 rather than replacing it. §11's "inline signals over action cards" still holds for bookkeeping tasks (review queue badges, staleness notes, opening-balance hints). The new direction section is not a notification center: signals are computed each load from current data, there is no dismissal state, no priority weights, no persistent alert infrastructure. The loose-ends aggregator at the bottom of the direction panel collapses what was previously scattered across inline locations into one view, but it is one component of a panel whose primary purpose is financial direction, not an alert inbox.
- Comparisons across the app gain a 6-month rolling baseline alongside "vs last month" framing. A one-month comparison treats whichever month happens to be "last" as the source of truth, which makes every reading noisy. The rolling baseline anchors comparisons to typical behavior so signals stop crying wolf.

## 14. Statement Reconciliation Is Camp 1 (Explicit, Statement-Driven)

**Decision:** Reconciliation in Ledger Flow follows the Quicken/YNAB/QuickBooks pattern: the user opens an account against a published statement, enters opening + closing balances, ticks transactions until the difference is zero, and finishes — at which point the app records a single zero-amount transaction with a balance assertion to attest the result.

**Why:** The product accepts manual transaction entry, which means real account balances drift from bank reality whenever a manual entry isn't matched on import. Without a periodic reconciliation step the user has no structured way to find a missing or duplicated transaction. Camp 2 (Monarch/Copilot) substitutes an aggregator feed for reconciliation, which is incompatible with the plain-text canon Ledger Flow stands on. Camp 1 fits the existing import → review → confirm trust boundary and gives the same vigilance value the rest of the bookkeeping layer is already delivering.

**Implication:** Reconciliation is statement-driven, human-in-the-loop, single-currency, balance-sheet only. There is no auto-reconciliation against an "online balance" — the only honest target is a published statement.

## 15. Reconciliation = Zero-Amount Transaction with Native Balance Assertion

**Decision:** A successful reconciliation writes one transaction of the form

```
2026-04-17 * Statement reconciliation · <account> · ending 2026-04-17
    ; reconciliation_event_id: <uuidv7>
    ; statement_period: <start>..<end>
    <ledger_account>  $0 = $<closingBalance>
```

with one zero-amount posting carrying a native balance assertion. Existing transactions are never mutated (no per-posting `; reconciled:` tag). Undo is deletion of this transaction via the existing transaction-actions menu — no dedicated undo handler is required, because the existing `transaction.deleted.v1` handler reverses the assertion in place.

**Why:** Native balance assertions are cross-compatible with `ledger`/`hledger`, so a user opening the journal in any tool gets the same correctness check the app gets. Per-posting metadata would have required mutating every reconciled row, which violates §4. One write, one undo, zero schema overhead.

**Implication:** Hand-written or imported balance-assertion transactions still trigger the read-side failure-detection layer; only assertions carrying the `reconciliation_event_id` metadata participate in the import fence and the future reconciliation history view. The `reconciliation_event_id` is generated before `emit_event` is called and threaded through both the journal metadata and the event log so the two references stay byte-identical.

## 16. Statement-End Date Is the Assertion Date — Verbatim, No Smart-Date Offset

**Decision:** Use the user-entered `periodEnd` as the assertion date and as the position the writer inserts at. The assertion transaction must always be the last transaction with date `periodEnd` in the journal file that holds it, so the assertion checks the running balance after every other transaction on that day.

**Why:** Beancount Reds and similar tools use a "smart-date" offset (`min(statement_end - 2, last_posting_date)`) to absorb posting lag where institutions report transactions on dates after the statement end. The institutions Ledger Flow currently serves (Wells Fargo and similar) only include posted transactions in their statements and use posting date, so end-of-statement-period assertions hold without an offset. Keeping the date verbatim keeps the math simple, the import fence boundary unambiguous, and the reconciliation history view trivial. Revisit if a real user reports lagging-postings issues.

**Implication:** The writer enforces "last on its date" within the year-derived journal file. Future imports must respect that ordering — covered by §17 below. If smart-date offsets become necessary they layer on top of this rule, not in place of it.

## 17. Reconciled Dates Are Import-Fenced

**Decision:** Once a reconciliation assertion exists for tracked account `X` with `periodEnd = D`, any new import row mapped to `X` whose date is on or before `D` is classified as a `conflict` with `conflictReason: "reconciled_date_fence"` and `reconciledThrough: D`. The existing `new`/`duplicate`/`conflict` model is preserved — fence rows simply land in the conflict bucket alongside identity-collision rows. The apply path refuses any conflict row regardless of reason.

**Why:** The user has personally attested to a balance on a date. Silently inserting a transaction on or before that date would change a balance the user already signed off on, which violates §4's non-rewriting principle. Fail closed: surface the would-be insert as a conflict, force an explicit "delete the reconciliation, then re-import or reject the row" choice.

**Implication:** Hand-written balance assertions don't participate in the fence (no `reconciliation_event_id`); they only show up in failure detection. The fence treats `date == reconciled_date` as fenced (i.e. the boundary is `<=`). Concurrent reconcile-while-import is not locked: classifications taken before a reconciliation lands won't see the new fence and may be applied. Acceptable for MVP.

## 19. No Hard Lock on Reconciled Transactions

**Decision:** The app does not lock pre-reconciliation transactions against editing or deletion. Trust is enforced by event-sourced undo (§12) and, in 8h, a confirmation modal that asks the user before they edit/delete a transaction whose date falls before the most recent reconciliation. There is no Quicken/QuickBooks-style "this transaction is reconciled and cannot be edited" hard lock.

**Why:** Hard locks add a second mutation surface (toggle a flag on each posting) and pose their own undo problem. The event log already gives full history and undo, the import fence already protects against silent re-imports, and the reconciliation assertion itself fails loudly the moment its underlying balance changes — so the "did anything drift" signal is already present without locking. A confirmation modal at the edit/delete moment captures the user's intent without freezing the journal.

**Implication:** Edits and deletes that happen to break a prior reconciliation cause the assertion to fail at next read; the broken state is visible on the account card and dashboard, and the user can either re-reconcile or undo the change. This matches the rest of the product's posture: human-in-the-loop, evidence-rich, no irreversible UI states.
