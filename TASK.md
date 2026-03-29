# Current Task

## Title

Overview dashboard facelift: fix data bugs, reorder for daily use, compress layout

## Objective

The overview page becomes a trustworthy daily home that answers "where do I stand, what changed, what needs attention" without scrolling past broken cards or stale CTAs. Two data-visibility bugs are fixed, sections are reordered to prioritize recent activity, and the layout is compressed to reduce scroll depth.

## Scope

### Included

- Fix: balance sheet card renders tracked accounts from the dashboard API (currently shows 0 accounts despite non-zero tracked balance total).
- Fix: hero CTA reflects actual workspace state instead of showing "Open setup" after setup is complete.
- Reorder dashboard sections: recent activity and category trends move above cash flow and balance sheet.
- Compress cash flow section: reduce vertical height by ~50%.
- Merge snapshot band metrics into the hero section to eliminate redundancy.
- Remove coverage strip from the hero (setup/accounts concern, not daily overview).
- Compress the Today rail in the hero to a tighter layout.

### Explicitly Excluded

- Transaction register changes (owned by clearing-status branch).
- Backend services touched by clearing-status: `header_parser.py`, `journal_query_service.py`, `import_service.py`, `manual_entry_service.py`, `unknowns_service.py`, `rule_reapply_service.py`, `opening_balance_service.py`, `account_register_service.py`.
- Date group headers in recent activity (follow-up polish).
- Empty cash flow month filtering (follow-up polish).
- Changes to the sidebar, layout shell, or other routes.

## System Behavior

### 1. Fix: Balance Sheet Card Data

**Inputs**

- `build_dashboard_overview()` in `dashboard_service.py` builds the `balances` list by iterating `config.tracked_accounts`.
- The frontend `buildOverviewAccounts()` maps `dashboard.balances` into renderable rows.

**Logic**

- Investigate why `dashboard.balances` returns an empty list when `summary.trackedBalanceTotal` is non-zero. The `balances` loop (line 220–252) and the `tracked_total` accumulator share the same `config.tracked_accounts` source — if one produces data, the other should too.
- Likely causes to check: (a) `config.tracked_accounts` is empty while journal-derived `account_balances` contains real asset/liability data — meaning net worth is computed from journals but tracked balances are not; (b) a mismatch between ledger account names in `config.tracked_accounts` and actual journal account names; (c) `trackedBalanceTotal` is incorrectly sourced from `netWorth` rather than `tracked_total`.
- After fix: the balance sheet card must show every tracked account with its current balance. If the user has no tracked accounts configured but does have journal data, the card should show an empty state with guidance to add accounts — not a header with zero content.

**Outputs**

- Balance sheet card displays account rows matching `config.tracked_accounts`.
- Snapshot stat "Tracked balances" and the account count are internally consistent.
- If no tracked accounts exist, the card shows an explicit empty state.

### 2. Fix: Hero CTA State Awareness

**Inputs**

- `primaryTask()` and `secondaryActions()` in `+page.svelte` read the module-level `state` variable.
- Svelte 4 reactive declarations: `$: activeTask = primaryTask()` and `$: secondary = secondaryActions()`.

**Logic**

- The reactive declarations compute when `state` is still `null` (before `onMount` completes), producing the `!state?.initialized` result ("Open setup" / "Use existing workspace"). The template's `{:else}` block correctly evaluates `state` inline, so the overview hero renders — but the CTA inside it uses the stale reactive value.
- Fix by ensuring the reactive declarations re-evaluate when `state` and `dashboard` change. Options:
  - Pass `state` and `dashboard` as explicit parameters: `$: activeTask = primaryTask(state, dashboard)`. This makes the dependency explicit to Svelte's compiler.
  - Or restructure so the CTA is computed inline in the template rather than via a reactive declaration.
- After fix: the CTA must reflect the actual workspace condition. For a user with completed setup, imported data, and no review queue or inbox: the CTA should be "Open transactions" with secondary links to "Manage accounts".

**Outputs**

- Hero CTA matches the current workspace state on every render.
- CTA labels follow the existing priority ladder: review queue → statement inbox → open transactions.
- No "Open setup" or "Use existing workspace" in the populated overview hero.

### 3. Reorder Dashboard Sections

**Inputs**

- Current section order (top to bottom): hero → snapshot band → balance sheet → cash flow → detail grid (category trends + recent activity).

**Logic**

- New section order: hero → detail grid (recent activity + category trends) → cash flow → balance sheet.
- The detail grid answers "what changed recently" and "what needs attention" — the two most actionable daily-use questions. These belong immediately after the "where do I stand" hero.
- Balance sheet and cash flow are structural/historical — useful for periodic review, not daily scanning.

**Outputs**

- Recent activity and category trends appear directly below the hero.
- Cash flow and balance sheet follow.
- All existing content remains; only the DOM order changes.

### 4. Merge Snapshot Band into Hero

**Inputs**

- Snapshot band: 4-column card showing tracked balances, income this month, spent this month, net this month.
- Hero: net worth headline + subtitle + Today rail.

**Logic**

- The snapshot band duplicates data visible elsewhere: net this month appears in both the snapshot and the cash flow header; income and spending appear in both the snapshot and the cash flow bars.
- Merge the four metrics into the hero as compact inline stats below the net worth figure. Replace the full-width snapshot card with a row of small stat chips inside the hero.
- Remove the standalone snapshot band section entirely.

**Outputs**

- Hero displays net worth prominently with tracked balances, income, spending, and net as secondary stat chips.
- No standalone snapshot band card.
- ~120px of vertical space reclaimed.

### 5. Remove Coverage Strip from Hero

**Inputs**

- Coverage strip: 3-item row inside the hero showing coverage count, "needs a start" count, and import-ready count.

**Logic**

- Coverage metrics (balance source coverage, import readiness) are setup and account-management concerns. They are useful during onboarding but not for daily overview use.
- Remove the coverage strip from the overview hero. Users who need this information find it in the Accounts page, which already shows per-account trust indicators.

**Outputs**

- No coverage strip in the hero.
- Coverage data remains available on the Accounts page (no data loss).

### 6. Compress Cash Flow Section

**Inputs**

- Current: 6 months × (month label row + 2 separate bar tracks + 2 currency value labels) = ~900px.

**Logic**

- Replace the double-bar layout (separate income and spending rows) with a single stacked or side-by-side bar per month.
- Show only the month label and the net value inline with the bar. Drop the separate income/spending currency labels below the bars — users who want exact figures can see them in the bar tooltip or the snapshot stats.
- Show 3 months by default. Add a "Show more" toggle that expands to the full 6-month window.
- Months with zero income and zero spending may still appear in the collapsed view if they fall within the 3-month window — empty-month filtering is a follow-up item.

**Outputs**

- Cash flow section height reduced by approximately 50%.
- 3 months visible by default; 6 months on expand.
- Income and spending still visually distinguishable via bar color.

### 7. Compress Today Rail and Fix Stale-Data Status

**Inputs**

- Current Today rail: heading + description + 3 signal cards + primary CTA button + secondary links.
- `dashboard.lastUpdated`: ISO date string of the most recent transaction in the books.

**Logic**

- The Today rail's intent is strong (surface the dominant next action) but it's too dense.
- Compress to: a single status line + primary CTA button + secondary links. Remove the individual signal cards — the hero stat chips (from step 4) already show month cash flow, and the review/inbox counts can fold into the status line.
- Keep the Today rail as a distinct zone within the hero but reduce its height.
- **Stale-data awareness**: `heroRailTitle()` currently falls through to "Books look current" whenever there is no review queue and no inbox. This is misleading when the most recent transaction is weeks old. Fix: compare `dashboard.lastUpdated` against today's date. If the gap exceeds 7 days, show "Last activity [date] — import a fresh statement" and point the primary CTA at `/import` instead of `/transactions`. The `primaryTask()` function must apply the same staleness check so the CTA label and href are consistent with the status line.
- Staleness threshold: 7 days. This is a frontend-only constant — no backend or settings change needed.

**Outputs**

- Today rail is tighter: status summary + CTA + links.
- No signal cards within the rail.
- Status line dynamically reflects review queue, inbox, stale data, or caught-up state.
- When data is stale (>7 days since last transaction), the status line warns and the CTA directs to import.

## System Invariants

- The dashboard must not modify files owned by the clearing-status branch. Scope is limited to `+page.svelte`, `dashboard_service.py`, and the `/api/app/state` endpoint path in `main.py` if needed.
- Finance-first language only. No ledger, journal, posting, or file-path terminology in UI copy.
- The hero CTA must always reflect the actual workspace state. It must never show setup-oriented labels when setup is complete.
- Balance sheet data must be internally consistent: if `trackedBalanceTotal` is non-zero, the balance list must contain the accounts that produce that total.
- Responsive behavior preserved: desktop grid layouts collapse to single-column on narrow viewports.

## States

### Hero CTA
- **Setup incomplete**: CTA directs to setup with appropriate step label.
- **Review queue non-empty**: "Review transactions" pointing to `/unknowns`.
- **Statement inbox non-empty**: "Import statements" pointing to `/import`.
- **Data stale** (>7 days since last transaction): status line shows "Last activity [date] — import a fresh statement", CTA points to `/import`.
- **Caught up**: "Open transactions" pointing to `/transactions`.

### Balance Sheet Card
- **Has tracked accounts**: renders account rows grouped by kind (asset/liability) with name and balance.
- **No tracked accounts, has journal data**: empty state explaining that tracked accounts need to be configured, with a link to Accounts.
- **No data at all**: handled by the onboarding hero (existing behavior, unchanged).

### Cash Flow
- **Default (collapsed)**: 3 most recent months.
- **Expanded**: full 6-month window.

## Edge Cases

- **Tracked accounts configured but no journal activity**: balance sheet shows accounts with $0 balances. This is correct — the accounts exist but have no history yet.
- **All signal conditions clear (no review, no inbox), data fresh**: Today rail shows "Books look current" and "Open transactions" CTA.
- **All signal conditions clear, data stale (>7 days)**: Today rail shows "Last activity [date] — import a fresh statement" and CTA points to `/import`. This prevents false confidence when manual entries mask import staleness.
- **Only 1–2 months of data**: cash flow shows available months without padding empty months in the collapsed view.

## Failure Behavior

- If the dashboard API returns an error, the existing error state renders (unchanged).
- If `dashboard.balances` is empty but `trackedBalanceTotal` is non-zero after the fix, this indicates a regression — log a warning in the backend and render the balance total without individual rows rather than showing contradictory data.

## Regression Risks

- **Snapshot band removal**: any code that references `.snapshot-band` or `.snapshot-metric` CSS classes must be removed completely. Partial removal could leave orphaned styles.
- **Section reorder**: the `detail-grid` CSS currently sets `grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr)`. Verify this still works when the grid moves above the cash flow section.
- **CTA reactivity fix**: ensure the reactive declarations also correctly handle the loading, onboarding, and error states — not just the populated overview.
- **Cash flow compression**: the bar color legend (income = green, spending = blue) must remain visually clear in the compressed single-bar format.
- **Coverage strip removal**: verify no other component or page references the coverage data from the dashboard API. If coverage fields are unused after removal, they can be dropped from the API response.

## Acceptance Criteria

- Balance sheet card shows all tracked accounts with current balances when tracked accounts are configured.
- Balance sheet card shows an empty state with guidance when no tracked accounts exist.
- "Tracked balances" stat and account count are internally consistent.
- Hero CTA shows "Open transactions" (or appropriate queue-based label) when setup is complete — never "Open setup".
- When the most recent transaction is more than 7 days old and no review/inbox items exist, the status line warns about stale data and the CTA directs to import.
- Recent activity and category trends appear directly below the hero, above cash flow and balance sheet.
- Cash flow section shows 3 months by default with an expand toggle for 6 months.
- No standalone snapshot band — metrics are inline in the hero.
- No coverage strip in the hero.
- Today rail is a compact status line + CTA, not a stack of signal cards.
- All existing responsive breakpoints still function (1100px, 720px).
- `pnpm check` passes.
- `uv run pytest -q` passes.

## Proposed Sequence

1. **Fix balance sheet data** — investigate and fix the `dashboard.balances` / `config.tracked_accounts` data path in `dashboard_service.py`. Add an empty state to the balance sheet card in `+page.svelte`. Verify the snapshot stat is consistent.
2. **Fix hero CTA reactivity** — make `primaryTask()` and `secondaryActions()` dependencies explicit to Svelte's reactive system. Verify the CTA is correct across all workspace states (uninitialized, onboarding, populated with queue, populated caught-up).
3. **Reorder sections** — move the detail grid (recent activity + category trends) above cash flow and balance sheet in the template. Adjust any CSS dependencies.
4. **Merge snapshot band into hero** — add stat chips to the hero, remove the standalone snapshot band section and its styles.
5. **Remove coverage strip** — delete the coverage strip markup and styles from the hero. Leave coverage data in the API for the Accounts page.
6. **Compress cash flow** — replace double-bar rows with a single-bar-per-month layout. Add 3-month default with expand toggle.
7. **Compress Today rail** — replace signal cards with a compact status summary. Keep CTA and secondary links.
8. **Verification** — run `pnpm check`, `uv run pytest -q`. Visually verify all four hero states (uninitialized, onboarding, populated with queue, caught-up). Check responsive behavior at 1100px and 720px breakpoints.

## Definition of Done

- The two data bugs are fixed: balance sheet card shows real accounts, hero CTA reflects actual state.
- Dashboard section order prioritizes daily-use content (recent activity, trends) over structural summaries (cash flow, balance sheet).
- Layout is compressed: no standalone snapshot band, no coverage strip, tighter cash flow, tighter Today rail.
- No regressions in existing tests or responsive behavior.
- No accounting terminology in UI copy.

## UX Notes

- The hero stat chips should be visually secondary to the net worth headline — small text, muted color, inline layout. They inform at a glance without competing for attention.
- The compressed cash flow bars should use the existing brand colors (green for income, blue for spending) and be thick enough to compare visually at the compressed height.
- The "Show more" toggle for cash flow should be a text link, not a button — it's a disclosure control, not a primary action.
- The balance sheet section, now lower on the page, can afford slightly more detail per account than the compressed version described in the review — name + balance + subtype pill is the right density.

## Out of Scope

- Transaction register changes (clearing-status branch).
- Transaction editing (deferred).
- Date group headers in recent activity (follow-up polish).
- Empty cash flow month filtering (follow-up polish).
- Sidebar or layout shell changes.
- Mobile-specific redesign beyond maintaining existing responsive breakpoints.
- Changes to the Accounts, Import, Review, Rules, or Setup pages.

## Replacement Rule

Replace this file when the next active engineering task begins.
