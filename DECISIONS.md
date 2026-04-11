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
