# Transactions Page Rethink

A UX-first redesign of [`app/frontend/src/routes/transactions/+page.svelte`](../app/frontend/src/routes/transactions/+page.svelte), modeled on Monarch Money's transactions screen with progressive-disclosure patterns from Copilot, and one deliberate divergence: per-account running balance is preserved as a power-user differentiator and shown in every scope.

This supersedes the earlier `plans/transactions-decomposition.md`, which planned a structural cleanup of the existing two-mode page. The current page has since grown to 2487 lines, the activity view shipped (Feature 7a), and consumer-app research has reframed the structural problem as a UX problem. Decomposition still happens here — it just happens in service of a different target shape, not the current one.

## Status

**Slotted as Feature 7d, ahead of 7b and 7c in the delivery sequence.** Backend Option A (single unified `/api/transactions`) is the chosen direction. Running balance is always shown — in single-account scope it's that account's balance, in cross-account scope it's the sum of tracked-account balances over time (a net-worth proxy). Postings are collapsed to one row per ledger transaction via the N-1 rule, and tracked-to-tracked transfer pairs collapse into a single row. The two-mode toggle is removed in Phase 4; phases 1–3 keep it as a transition aid. The active TASK is Phase 1 (Foundations) of this plan.

## Why redesign

The page is two products in one file, toggled by `activityMode` at line 164:

- **Account register** (~75% of script + template): single account, running balance, opening balance, manual transfer resolution dialog, add-transaction form, three-dot action menu, clearing status, transfer-state badges.
- **Activity view** (~20%): cross-account, period presets, category/month filters, explanation header, simple grouped rows.

They share a hero shell, a `view-toggle` button, and a few formatters. The data shapes (`AccountRegister` vs `ActivityResult`), loaders (`loadRegister` vs `loadActivity`), URL contracts, row layouts, and filter affordances are otherwise disjoint. The toggle pill in each hero is the only thing telling the user the two screens are related.

The consumer-app research from the prior conversation (Copilot, Monarch, Simplifi, Rocket, Empower, Mint, YNAB, Apple Card) returned one unanimous pattern: every serious product has *one* Transactions screen, and account scope is just another filter. Drill-downs from dashboard widgets, category clicks, and report bar-chart taps all land on the same screen with filters pre-applied.

Monarch's specific implementation is the closest fit for Ledger Flow's brand and audience. The user explicitly liked it and called out the patterns to copy:

- Day-grouped rows with a low-key header (date on the left, daily sum on the right).
- Inline category editing — tap the category in the row, get a searchable combobox, no round-trip.
- A right-side detail sidebar that slides in when a row is opened, with a three-dot overflow menu for less-frequent actions.
- Search + filter pills at the top of the list; filter modal grouped by Categories / Merchants / Accounts / Tags / Goals / Amount / Other.
- Transaction amount displayed in account-posting terms (negative = unsigned standard text, positive = green with `+`).

The one Monarch behavior we deliberately reject: Monarch does not show a running balance per account. Reddit users have asked Monarch for this; Ledger Flow gets it free from the ledger file, and that's a competitive edge worth keeping. **Running balance stays, and shows in every scope.**

## Design principles

1. **One screen, scoped by filters.** The `activityMode` boolean disappears. There is one Transactions screen. "Single account view" is the same screen with the Account filter set to one account.
2. **One row per user action, not per posting.** A row represents what the user did, not what the double-entry ledger recorded. See "Rows, postings, and double entry" below for the rules.
3. **Status circle is the leftmost element of every row.** It's the signpost for "is this transaction reviewed?" — present in every scope, every filter.
4. **Progressive disclosure of action complexity.** Common actions live in the row (recategorize via inline combobox). Less-common actions live in the detail sidebar (split, duplicate, create rule, edit metadata). Destructive or rare actions live behind the three-dot menu inside the detail sidebar (delete, unmatch).
5. **Manage where it lives.** Row-level edits never lose filter state. The detail sidebar is a sibling of the list, not a replacement for it — the list stays visible behind it on desktop.
6. **Filter chips, not tabs.** All scope (account, category, period, month, status) is expressed as filter pills above the list. The pill bar is the page's table of contents.
7. **Day groups as the structural rhythm.** Transactions group by day, with a low-contrast header showing the date and the daily sum.
8. **Power-user moves on the surface.** Running balance, clearing status, transfer state, manual-resolution affordances, and the per-account opening balance line all stay — they're what differentiates Ledger Flow from consumer apps.

## Target screen anatomy

```
┌─ Header ──────────────────────────────────────────────────────────────────┐
│  Transactions                                              [+ Add]        │
│  $1,247.32 spent · $5,210.00 in · –$320 net           ← live filter totals │
└───────────────────────────────────────────────────────────────────────────┘
┌─ Filter bar ──────────────────────────────────────────────────────────────┐
│  [🔍 Search]  [📅 Last 3 months ▾]  [Account: Wells Fargo CC ✕]            │
│  [Category: Groceries ✕]  [+ Filters]                                     │
└───────────────────────────────────────────────────────────────────────────┘
┌─ Explanation header (only when a meaningful filter is active) ─────────── ┐
│  $1,247 across 32 transactions · avg $39 each                             │
│  Prior 3 months: $980 across 28 — ↑27%                                    │
│  6-month average: $1,050/mo                                               │
│  Biggest: $312 at Costco on Mar 22                                        │
└───────────────────────────────────────────────────────────────────────────┘
┌─ List ────────────────────────────────────────────────────────────────────┐
│  Mar 24 · Wednesday                                          –$87.40      │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ ●  🛒 Groceries ▾  Trader Joe's  Wells Fargo CC  $42.10  $1,210.50 ›│  │
│  │ ●  🛒 Groceries ▾  Whole Foods   Wells Fargo CC  $45.30  $1,168.40 ›│  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│  Mar 23 · Tuesday                                          +$2,200.00     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ ●  💰 Income ▾     Acme Payroll   Checking      +$2,400.00 $5,683.40│› │
│  │ ●  ↔ Transfer      —              Checking → Savings  $200  $5,483.4│› │
│  └─────────────────────────────────────────────────────────────────────┘  │
│  Mar 22 · Monday                                            –$100.00      │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ ●  🛒 Groceries · 🏠 Household   Costco         $100.00  $5,583.40 ›│  │
│  │   (split: $60 Groceries, $40 Household — expand in detail sheet)    │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

The leftmost `●` on each row is the status circle (cleared / pending / unmarked). The `↔ Transfer` row is one row representing both legs of a tracked-to-tracked transfer pair (two ledger transactions in the backend, one row in the UI). The split row shows two category pills inline; expanding the row's detail sheet reveals the full leg breakdown.

## Row anatomy

| Element | Position | Affordance | Notes |
|---|---|---|---|
| Status circle | Leftmost | Click → cycle cleared/pending/unmarked | Always present, every scope |
| Category pill (icon + label) | After status | Click → inline combobox | Hidden when a category filter is active. Splits show multiple pills inline. Transfers show `↔ Transfer`. |
| Payee | Center, primary text | Click → opens detail sheet | Truncated at ~50 chars; raw bank descriptor in sheet. Transfers show `—` here. |
| Account label | Center, secondary text | Click → adds account filter | Single account in normal cases. Tracked-to-tracked transfers show `Source → Destination`. Hidden when single-account scope eliminates ambiguity. |
| Amount | Right of center | Click → opens detail sheet | Always the *tracked-account leg's* signed amount. Negative = neutral text, positive = green with `+`. |
| Running balance | Right of amount | Static | **Always present.** In single-account scope = that account's balance. In cross-account scope = sum of tracked-account balances. |
| Disclosure chevron `›` | Far right | Click → opens detail sheet | Always present |
| `Needs review` pill | Inline near payee | Link → `/unknowns` | All scopes |
| Transfer-direction glyph (`↔`) | Inside category pill slot | Visual only; click opens manual resolution if pending | Replaces the category pill on transfer rows |

The category-pill combobox is a `Popover` containing the existing `Command` palette pre-populated with the user's chart of accounts. Picking a category POSTs to `/api/transactions/recategorize` with the new target, emits an undo toast (existing pattern), and reloads the visible row only. The undo toast also surfaces "Create a rule from this" as a secondary action, matching Monarch's "after recategorize, offer the rule" flow.

## Rows, postings, and double entry

This is the structural heart of the redesign. A row represents one user action, not one ledger posting. Two rules govern how postings collapse into rows:

### Rule 1: N-1 posting rule

A ledger transaction has N postings (legs). Display N-1 of them, suppressing the *tracked-account leg* because the row's account column already shows it. For a normal 2-leg expense:

```
2026-03-24 Trader Joe's
    Liabilities:Wells Fargo CC   $-42.10
    Expenses:Groceries           $42.10
```

Two postings, N=2. We display N-1 = 1 leg's worth of information per row, but the row aggregates the data:
- **Amount**: from the tracked-account leg (`-42.10`).
- **Category**: from the non-tracked-account leg (`Groceries`).
- **Account**: from the tracked-account leg (`Wells Fargo CC`).

For a 3-leg split:

```
2026-03-22 Costco
    Liabilities:Wells Fargo CC   $-100.00
    Expenses:Groceries           $60.00
    Expenses:Household           $40.00
```

N=3, displayed N-1 = 2 categories in the row (`Groceries · Household` as inline pills), with the full breakdown visible when the detail sheet is opened.

**Why this matters:** Without the N-1 rule, every posting would render as its own row in cross-account scope. The user would see "$10 to Groceries" and "$10 from Checking" as two separate rows that net to zero. Running balance would always net to zero. The screen would double-count every dollar.

### Rule 2: Tracked-to-tracked transfer pair collapse

When the user transfers $200 from Checking to Savings, both sides of the transfer get imported (because both accounts are configured for import). The backend matches them via a `match-id:` tag and stores two ledger transactions:

```
2026-03-23 Transfer to Savings   ; match-id: abc-123
    Assets:Checking              $-200.00
    Assets:Savings               $200.00

2026-03-23 Transfer from Checking ; match-id: abc-123
    Assets:Savings               $200.00
    Assets:Checking              $-200.00
```

(Or, more realistically, the auto-reconciliation suppresses the duplicate at read time.) Either way, **one user action = one row**, regardless of how many transactions the backend stores. The row shows:
- Category slot: `↔ Transfer`
- Account slot: `Checking → Savings`
- Amount: $200 (unsigned, since it's a transfer that nets to zero on the net-worth axis)
- Running balance: unchanged from the previous row (transfers between tracked accounts don't move net worth)

### Why both rules together make running balance coherent

In every scope, every visible row impacts the user's tracked-account total by exactly the row's amount (and zero for transfers). Summing them down the page produces a coherent running balance:

- **Single-account scope**: running balance is that account's balance over time. Same as today's per-account register view.
- **Cross-account scope**: running balance is the sum of all tracked-account balances over time, i.e., a net-worth proxy that updates with every row. Transfers between tracked accounts net to zero so they pass through unchanged.
- **Mixed scope** (e.g., two accounts filtered): running balance is the sum of those accounts' balances over time. Transfers between those two accounts still net to zero. Transfers to a third (out-of-scope) tracked account move the balance.

### Caveats to think through during implementation

The user flagged that transfer-pair collapse may have implementation caveats. Surfacing the ones I see:

1. **Mismatched dates.** The two ledger transactions in a transfer pair can have different posted dates if the import timing differs. Use the earlier date (the user-facing "when the transfer happened"), or store a `effective_date` on the matched pair.
2. **Mismatched clearing status.** One side might be cleared and the other pending. The row's status circle should show the *less-cleared* state (conservative: pending wins over cleared). Cycling the circle should affect both legs.
3. **Account label format.** `Checking → Savings` is fine when the row is in cross-account scope. When the user has filtered to one of the two accounts, the label should reorient: filtered to Checking → "Transfer to Savings" or "→ Savings"; filtered to Savings → "Transfer from Checking" or "← Checking". The amount sign also reorients (the visible account's perspective).
4. **Detail sheet ambiguity.** Opening the row's detail sheet shows... which side? The user-facing answer is "the transfer," so the sheet shows both legs visually but treats them as one logical thing — both `headerLine`s are needed to delete or unmatch. Unmatching a transfer pair undoes the link but preserves both transactions (the existing pattern from Feature 5d).
5. **Linking discovery.** The backend already links pairs via the `match-id:` tag (Feature 5a) and via auto-reconciliation. The new unified `/api/transactions` endpoint must surface these links — likely by returning the row with a `transferPairId` and an embedded `legs[]` array carrying both `journalPath`/`headerLine` references for action-menu operations.
6. **Single-side transfers (one leg out of scope).** A transfer from Checking (tracked) to a credit card the user does not import shows as a single-leg row (`Liabilities:CreditCard` is just a category from the system's view). It does not collapse — there's nothing to collapse with. The `↔ Transfer` glyph is reserved for tracked-to-tracked pairs.
7. **Manual transfer resolution.** Today's "manual resolution" UI solves the case where the system can't auto-link two halves. After Phase 4 it lives inside the detail sheet of the unmatched transaction, exposed when the row is in a transfer state without a paired peer.

These caveats are noted; the resolution belongs in Phase 4 when the unified backend endpoint and row component are designed.

## Filter UX

Filter chips render in a single bar above the list:

- **Search** — text + Simplifi-style formula syntax (`>50`, `<-20`, `~costco`). Cheap to add over the unified endpoint.
- **Date** — preset dropdown (This month / Last 30 / Last 3 months / Last 6 months / This year / Custom range).
- **Account** — combobox; selecting one account triggers single-account-scope features (clearing toggles, transfer-state badges, manual resolution affordance, "Add transaction" CTA bound to that account, opening-balance line in the explanation header).
- **Category** — multi-select combobox grouped by parent category, similar to Monarch's filter modal.
- **Status** — multi-select for `cleared`, `pending`, `unreviewed`, `transfer`, `manual`. Hidden behind `+ Filters` until first use.
- **Tags** — once tag UX exists; placeholder for now.
- **Amount** — operator + value (Simplifi pattern); behind `+ Filters`.

Active filters render as pills with `✕` to clear individually. A `Clear all` button appears when more than one is active. URL params mirror filter state so dashboards keep deep-linking.

The `+ Filters` button opens a modal modeled on Monarch's filter modal screenshot — left rail of categories, search, checkbox tree, Cancel/Apply footer. We can use the existing `Dialog` + `Command` primitives.

## Detail sheet

A right-side `Sheet` (or `Dialog` in side-anchored mode) that slides in when a row is clicked. The list stays visible behind it on screens ≥ 1100px; on narrower screens it covers the list. Contents:

- Header: merchant logo placeholder + payee, amount, account chip, "Reviewed" toggle (when applicable), three-dot overflow menu, close `✕`.
- Body:
  - **Date** — read-only for now; editable when transaction editing lands.
  - **Category** — same combobox as the row, plus a `↔ Split` link to the right.
  - **All postings** — for splits, lists every leg with its amount and category. For transfers, lists both linked transactions.
  - **Original bank descriptor** — full untruncated raw text, low-contrast.
  - **Account** — chip linking to single-account scope.
  - **Notes** — textarea (deferred; placeholder for now).
  - **Tags** — chip input (deferred; placeholder for now).
  - **Attachments** — drop zone (deferred; placeholder for now).
  - **Transfer details** — visible when the transaction is a transfer; shows the paired account, the resolution token, and the manual-resolution CTA when applicable.
- Three-dot menu items (not all available in v1):
  - Split transaction — deferred; ledger supports splits natively, this is a real future feature.
  - Duplicate transaction — deferred until manual editing lands.
  - Create rule from transaction — wires to existing `RuleEditor.svelte`.
  - Edit metadata — deferred until manual editing lands.
  - Recategorize — already in the row, redundant here; omit.
  - Unmatch (when matched to a manual entry or transfer pair) — existing action.
  - Delete — existing action; double-confirm.

The sidebar reads from a single `selectedTransaction` store on the page. Closing it via `✕`, clicking the backdrop on mobile, or hitting `Escape` clears the store. Its open state is reflected in the URL as `?tx=<id>` so the back button closes it.

## Backend shape

**Decision: Option A.** Replace `/api/accounts/{accountId}/register` and `/api/transactions/activity` with a single `/api/transactions` endpoint that returns the unified row shape and applies the N-1 + transfer-pair-collapse rules server-side.

Request params:
- `accounts[]` — list of tracked-account IDs. Empty = all tracked accounts.
- `categories[]` — list of category account names.
- `period` — preset (`this-month`, `last-30`, `last-3-months`, `last-6-months`, `this-year`, `custom`).
- `from`, `to` — date range when `period=custom`.
- `month` — `YYYY-MM` shorthand for a single calendar month.
- `status[]` — `cleared`, `pending`, `unreviewed`, `transfer`, `manual`.
- `search` — text + formula syntax.

Response shape:
```ts
type TransactionsResponse = {
  baseCurrency: string;
  filters: { /* echoed back */ };
  rows: TransactionRow[];
  summary: ActivitySummary | null;
  // Per-row running balance is included on each row, computed across the
  // visible row set in date order. The frontend never recomputes it.
};

type TransactionRow = {
  id: string;                          // stable across reloads
  date: string;                        // ISO; transfers use the earlier of the pair
  payee: string;
  amount: number;                      // tracked-account leg's signed amount
  runningBalance: number;              // cumulative sum across the visible set
  account: { id: string; label: string };
  // For transfers: `account` is the row-perspective account (filtered side, or
  // arbitrary one if neither is filtered) and `transferPeer` carries the other.
  transferPeer?: { id: string; label: string } | null;
  categories: Array<{ account: string; label: string; amount: number }>;
  // categories.length === 1 for normal transactions
  // categories.length >= 2 for splits
  // categories.length === 0 for transfers
  status: 'cleared' | 'pending' | 'unmarked';
  isTransfer: boolean;
  isUnknown: boolean;
  isManual: boolean;                   // imported from a :manual: tag
  legs: Array<{                        // for action-menu operations
    journalPath: string;
    headerLine: string;
  }>;
  matchId?: string | null;
};
```

The two legacy endpoints stay in place during Phases 1–3 and are deleted in Phase 4 once `/api/transactions` is feature-complete. Existing dashboard drill-down URLs (`?view=activity&category=...`, `?view=activity&month=...`) are translated to the new filter param names by a small URL-migration helper that runs on page load.

## Component decomposition

```
app/frontend/src/routes/transactions/+page.svelte           ~250 lines (orchestrator)
app/frontend/src/lib/components/transactions/
  TransactionsHeader.svelte                                 hero + live totals
  TransactionsFilterBar.svelte                              chip bar + + Filters button
  TransactionsFilterDialog.svelte                           Monarch-style filter modal
  TransactionsExplanationHeader.svelte                      lifted from current activity view
  TransactionsList.svelte                                   day-grouped list shell
  TransactionDayGroup.svelte                                date header + daily sum + rows
  TransactionRow.svelte                                     unified row (status, pills, amount, balance, chevron)
  TransactionDetailSheet.svelte                             right-side detail sidebar
  TransactionCategoryCombobox.svelte                        inline category picker (popover)
  TransactionActionsMenu.svelte                             three-dot overflow inside detail sheet
  AddTransactionForm.svelte                                 lifted from current register view
  ManualResolutionDialog.svelte                             lifted unchanged
app/frontend/src/lib/transactions/
  loadTransactions.ts                                       single loader against /api/transactions
  transactionFilters.ts                                     filter ↔ URL serialization, validation
  transactionFormulas.ts                                    Simplifi-style search parser
  types.ts                                                  unified row + filter types
```

## Delivery sequence

Each phase is independently shippable behind no flags. Each leaves the screen in a working state.

### Phase 1 — Foundations (no UX change yet)

1. Lift the activity-view explanation header into `TransactionsExplanationHeader.svelte`. Behavior unchanged.
2. Lift `AddTransactionForm.svelte` out of the page. Behavior unchanged.
3. Lift `ManualResolutionDialog.svelte` out of the page. Behavior unchanged.
4. Move shared formatters to `$lib/format.ts` if not already there.
5. Extract types to `$lib/transactions/types.ts`.

After phase 1: page drops by ~600 lines, two-mode toggle still exists, no user-visible changes.

### Phase 2 — Unified row component

1. Build `TransactionRow.svelte` rendering both register entries and activity transactions from a single normalized shape.
2. Add a `mode: 'register' | 'activity'` prop initially so behavior matches the current pages exactly.
3. Replace both existing row templates with the new component.
4. Add `TransactionDayGroup.svelte` and use it in both views.
5. Add the leftmost status circle to every row, including the activity view (which currently lacks it).

After phase 2: visual deduplication, the status circle now appears in cross-account view, otherwise no UX change.

### Phase 3 — Detail sheet + inline category combobox

1. Build `TransactionDetailSheet.svelte` with read-only fields and the existing action-menu items (delete, recategorize, unmatch). Wire the row's chevron + payee click to open it.
2. Build `TransactionCategoryCombobox.svelte` and replace the row's category pill with it. Recategorize moves from the three-dot menu to the inline combobox.
3. Move "Create rule from transaction" into the detail sheet's three-dot menu, wired to the existing `RuleEditor.svelte`.

After phase 3: progressive-disclosure UX is in place. The two-mode toggle still exists.

### Phase 4 — Backend unification, one screen

1. **Backend.** Build `/api/transactions` returning the unified `TransactionRow[]` shape. Implement the N-1 posting rule server-side. Implement transfer-pair collapse using `match-id:` tags. Compute `runningBalance` per row across the visible set in date order. Compute the `summary` block (lifted from the existing activity service).
2. **Frontend.** Build `loadTransactions.ts` against the new endpoint. Replace the two legacy loaders.
3. Build `TransactionsFilterBar.svelte` and `TransactionsFilterDialog.svelte`. The bar shows current filters as chips; the dialog adds new ones.
4. Replace the `view-toggle` pill with an Account filter chip. Single-account scope is a filter, not a mode. Features that only make sense in single-account scope (manual transfer resolution, "Add transaction" defaulting to that account, opening-balance line) auto-activate when the filter narrows to one account.
5. Migrate URL params via the URL-migration helper.
6. Delete the `activityMode` branch, the duplicate hero, and the legacy endpoints.

After phase 4: one screen, Monarch-shaped, running balance on every row, transfer pairs collapsed, two-mode toggle gone.

### Phase 5 — Polish

1. Live totals strip in the header (current filter totals).
2. Day-group daily sums in the date headers.
3. Search formula syntax (`>50`, `<-20`, `~text`) in the search field.
4. Mobile sidebar → bottom sheet adaptation.
5. Keyboard shortcuts (Copilot-style: `R` review, `C` category, `F` filter, `Escape` close sheet).

Phase 5 items are individually scoped — pick the ones that earn their keep.

## What this plan does NOT do

- It does not introduce merchant management. The "View N transactions from this merchant" link in the detail sheet is deferred until merchant management exists.
- It does not introduce tags, notes, or attachments. The detail sheet has placeholders for these as a forcing function for future work, but they are read-only "Coming soon" affordances in v1.
- It does not implement split editing in the UI, even though ledger supports splits. The split affordance in the detail sheet is a `Split` link that is disabled in v1. The N-1 display rule is read-only.
- It does not introduce transaction editing (date, payee, amount). That's the deferred Feature 9 from the roadmap — this plan creates the surface for it but does not implement it.
- It does not introduce Apple Card's stacked category bar as the explanation header. That's a Tier 2 idea from the research; the existing text-based explanation header is sufficient for v1.
- It does not introduce a Monarch-style household / shared-views feature. Single-user product.

## Resolved questions

1. **Backend Option A vs Option B?** → **A.** Single unified `/api/transactions`. Cleaner long-term, and the unified row shape is needed anyway for the N-1 + transfer-collapse rules. Phase 1–3 ship against the legacy endpoints; Phase 4 unifies.
2. **Conditional running balance?** → **Always shown.** In single-account scope it's the account's balance; in cross-account scope it's the sum of tracked-account balances over time (a net-worth proxy). The N-1 + transfer-collapse rules make this coherent in every scope.
3. **Auto-bind features to single-account scope?** → **Yes.** When the account filter narrows to one account, manual transfer resolution affordances appear, "Add transaction" defaults to that account, and the opening-balance line shows in the explanation header. No separate toggles. (Asking the user to confirm — the original question was "Should single-account scope hide cross-account features automatically, or should those be separate toggles?" and the answer "I guess so" is interpreted as auto-activate.)
4. **Keep the explicit toggle through phases 1–3?** → **Yes.** As a transition aid. Removed in Phase 4.
5. **Slotting?** → **Feature 7d**, ahead of 7b and 7c in the delivery sequence. Updated in `ROADMAP.md`.
6. **TASK.md target?** → **This rethink.** Updated to point at Phase 1 of this plan.

## Open implementation questions for Phase 4

These don't block the plan but need answers when Phase 4 is scoped:

1. **Date conflict in transfer pairs.** If the two legs have different `posted_on` dates, which date does the row show? Earliest? User-facing date stored on the match metadata? Most likely answer: the earlier of the two, with the later available in the detail sheet.
2. **Clearing-status conflict in transfer pairs.** Similar question for cleared/pending/unmarked. Likely answer: the less-cleared status wins (pending > unmarked > cleared, conservative). Cycling the circle from the row affects both legs in lockstep.
3. **Running balance ordering.** When multiple transactions share a date, what's the secondary sort? Probably journal-file order, which is what `ledger` itself uses. Needs verification against the existing register endpoint.
4. **Backend cost of N-1 + transfer-collapse on the unfiltered set.** A workspace with thousands of transactions runs the collapse logic on every request. Worth profiling in Phase 4 before declaring done. The existing activity endpoint already iterates everything so the floor is similar.

## Appendix: Monarch screenshots referenced

- [`monarch_money_transactions_filter.png`](../monarch_money_transactions_filter.png) — Filter modal: left rail of filter types, search, checkbox tree of categories grouped by parent (Income / Housing / Auto & Transport / …), Cancel/Apply footer. Drives `TransactionsFilterDialog.svelte`.
- [`monarch_money_transaction_split.png`](../monarch_money_transaction_split.png) — Split transaction dialog: original transaction at top, multiple split rows below with Tags / Goals / Review status / Notes per split, By Amount / By Percent toggle, "Add a split", "Remove all splits", "Split into N transactions" CTA. Reference for the deferred split-editing feature; not built in v1 but informs the row display rules above.
