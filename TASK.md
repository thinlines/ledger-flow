# Shell, Copy, and Visual Polish (7c)

## Objective

Close out Feature 7 by removing implementation-leak language from the shell, fixing misleading copy and CTA states, demoting noisy secondary actions on the accounts page, adopting a consistent sign convention for money amounts, and making the mobile layout financial-data-first. The result: a polished, consumer-grade app shell where every word and visual hierarchy decision reflects the finance-first principle.

## Scope

### Included

1. **Sidebar copy cleanup** — rewrite the brand-card byline and nav notes to remove implementation language
2. **Hero CTA fallthrough** — fix the all-caught-up state so users don't see a weak "Open transactions" primary CTA
3. **`/rules` loading state** — replace the misleading "not initialized" copy shown while the page is loading
4. **Dashboard zero-row filtering** — suppress zero-vs-zero rows from cash flow and category trends panels
5. **Mobile nav drawer** — replace the stacked sidebar on `<980px` with a top bar plus drawer, so financial data is the first thing on mobile
6. **Demote "Edit" on accounts page** — "Transactions" becomes the primary action; "Edit" moves to a secondary/overflow position (folded in from UI backlog)
7. **Sign convention** — remove the `-` prefix from outflow amounts, use regular/muted text for outflows and green with `+` prefix for inflows, across the app (folded in from UI backlog)

### Explicitly Excluded

- Keyboard shortcuts (deferred until a dedicated design pass is greenlit)
- Pending/scheduled transfer entry (separate future task; not polish)
- Full nav reorganization — this task preserves the existing route grouping (Daily Use / Workflows / Automation / Workspace)
- Sidebar logo, font, or color changes
- Mobile-specific dashboard layout changes beyond the nav drawer
- Changes to the hero eyebrow, title, or subtitle copy — only the CTA fallthrough branch

## System Behavior

### 1. Sidebar Copy Cleanup

**Inputs:** Page load.

**Logic/Outputs:** In `app/frontend/src/routes/+layout.svelte`:

- Brand-card byline (line 80): replace
  > "Track balances, imports, and review work without exposing the accounting internals unless you need them."

  with finance-first copy. **Decision:** use:
  > "Your money, accounts, and spending — all in one place."

- Nav note for `/rules` (line 24): replace
  > "Matching and categorization logic"

  with:
  > "Automate how new transactions get categorized"

- All other nav notes already pass the finance-first bar. No changes to Overview, Accounts, Transactions, Import, Review, or Setup notes.

### 2. Hero CTA Fallthrough

**Current bug:** In `app/frontend/src/routes/+page.svelte`, `primaryAction()` falls through to `{ label: 'Open transactions', href: '/transactions' }` when no actionable state exists (lines 421–425). `secondaryActions()` then also emits `{ label: 'Open transactions', href: '/transactions' }` (line 438) when `hasReviewQueue()` is false, producing duplicate CTAs pointing to the same route.

**Logic:** When the app is in an "all caught up" state (initialized, has data, no review queue, no statement inbox, data not stale), the hero should:
- Show a softer primary CTA with encouragement-framed copy rather than a route push
- Not emit `/transactions` as both primary and secondary

**Decision:** When everything is caught up, the primary action becomes:
```
{ href: '/', label: 'Review your direction', note: 'No bookkeeping work is waiting. Take a moment to scan your financial direction panel.' }
```
The href is `/` so clicking it scrolls to or highlights the direction panel on the same page (implementation detail: `href="#direction"` with an `id="direction"` on the direction section). Secondary actions remain `[/accounts]` only — no duplicate `/transactions` link.

**Inputs:** Existing `state` / `dashboard` reactive dependencies.

**Outputs:** Hero primary CTA, hero secondary CTA list.

### 3. `/rules` Loading State

**Current bug:** In `app/frontend/src/routes/rules/+page.svelte` line 586, while `initialized` is still loading from `/api/app/state`, the page renders
> "Workspace not initialized yet."

This is shown even when the workspace IS initialized — just the state fetch hasn't resolved. The user sees a misleading error, then the page reloads with content.

**Logic:** Distinguish three states:
- Loading: state fetch has not resolved (`initialized` is still at its initial/sentinel value)
- Not initialized: fetch resolved, `initialized === false`
- Initialized: fetch resolved, `initialized === true`

**Decision:** Add a `loading: boolean` flag (parallel to the pattern already used in `/accounts`, `/transactions`, `/+page.svelte`). Render:
- Loading: "Loading rules…" with matching skeleton or hero treatment
- Not initialized: existing "Workspace not initialized yet." message
- Initialized: existing page content

**Inputs:** `/api/app/state` resolution.

**Outputs:** Conditional top-level content in `/rules`.

### 4. Dashboard Zero-Row Filtering

**Current behavior:** The cash flow series and category trends panels on the dashboard can render rows where both current and previous values are zero (e.g., a category that had no activity this month or last month still shows if it exists in the backend response).

**Logic:**
- Cash flow: the backend returns 6 months of `{ income, spending, net }`. When all three are zero for a row, suppress it from the rendered list. Do not suppress cash flow rows with a non-zero value in any field.
- Category trends: the backend returns category rows with `{ current, previous, delta }`. Suppress rows where `current === 0 && previous === 0`. Do not suppress rows where either value is non-zero (delta-only changes are still informative).

**Inputs:** Backend dashboard response.

**Outputs:** Filtered cash flow and category trend row arrays consumed by the existing templates. Use frontend reactive filters — no backend changes.

**Failure:** If all rows are zero-vs-zero, panel shows its existing empty state (already present: `{#if dashboard.categoryTrends.length > 0}` at line 727). Frontend filter must update the count used by that guard.

### 5. Mobile Nav Drawer

**Current behavior:** On screens `<980px`, the layout (`+layout.svelte`) stacks the sidebar above the main content (`max-shell:grid-cols-1`). This pushes the dashboard / accounts / transactions content below the brand card and nav tiles.

**Logic:** Under `<980px`:
- Replace the stacked sidebar with a top bar containing:
  - Compact brand mark (left)
  - A hamburger button (right) that opens a slide-in drawer
- The drawer contains the current nav sections (Daily Use / Workflows / Automation / Workspace) with the same links and notes
- The drawer opens with a slide-from-left animation, closes on link click, backdrop click, or Escape
- Main content is the first interactive element below the top bar

**Inputs:** Viewport width; user tap on hamburger / link / backdrop; Escape key.

**Outputs:** Top bar + conditional drawer markup; existing sidebar markup is hidden at `<980px` and rendered as-is at `>=980px`.

**Decision:** Use the existing `max-shell` breakpoint (`<980px`) defined in Tailwind config. No new breakpoints.

### 6. Demote "Edit" on Accounts Page

**Current behavior:** In `app/frontend/src/routes/accounts/+page.svelte` lines 610–613, each account card renders `Transactions` and `Edit` as sibling inline-link buttons with equal weight:

```svelte
<a class="inline-link" href={`/transactions?accounts=${account.id}`}>Transactions</a>
<a class="inline-link" href={`/accounts/configure?accountId=${account.id}`}>Edit</a>
```

**Logic:** `Transactions` becomes the single visible primary action. `Edit` moves into the existing `<details class="advanced-details">` block at the bottom of the card (line 662), which currently contains "Accounting details" — rename/restructure so the details disclosure reveals both the accounting details AND the Edit link.

**Decision:** Inside the `<details>` block, add a prominent "Edit account" button at the top of the disclosed content, above the existing ledger-account and profile detail paragraphs. Keep the summary label `Accounting details` for now — do not widen the scope of this task to rename the disclosure.

**Inputs:** User click on the account card, on "Accounting details", on "Edit account".

**Outputs:** Account card shows only `Transactions` as a visible quick action. "Edit account" accessible one click deeper via the details disclosure.

### 7. Sign Convention

**Current behavior:** Money amounts in the transactions list, detail sheet, dashboard cash flow, recent activity, and category trends display with a `-` prefix for outflows and either no prefix or a `+` for inflows, depending on the call site. Currency formatting utility (`formatCurrency` in `app/frontend/src/lib/format.ts`) has a `signed` option that always emits `+` or `-`.

**Rule:** **Green `+` for "good" balance changes; unsigned dark text for everything else.** A "good" change is one that improves the user's position on that account:

- **Asset account balance increases** → good → green `+` (e.g., paycheck deposit shows as `+$1,000.00` green)
- **Asset account balance decreases** → not good → unsigned dark text (e.g., coffee charge shows as `$5.00` neutral)
- **Liability account balance decreases** → good → green `+` (e.g., credit card payment shows as `+$200.00` green)
- **Liability account balance increases** → not good → unsigned dark text (e.g., new credit card charge shows as `$5.00` neutral)
- **Zero** → unsigned, neutral

In accounting terms: debits to assets and debits to liabilities get green `+`; credits to assets and credits to liabilities are unsigned. In practical terms, the user's mental test is "is this a change I'd be happy about?" If yes, green `+`. If no, neutral.

The old convention used `-` for any decrease (spending or credit card payment) which is visually noisy and doesn't distinguish outflows-of-wealth (spending) from transfers that don't change net worth (paying a card from checking). The new convention highlights the "good direction" movements per account so scanning a mixed list surfaces positive movements visually.

**Decision:** Add a new option to `formatCurrency`: `signMode: 'negative-only' | 'good-change-plus' | 'always'`. The app standardizes on `'good-change-plus'` for transaction amounts in list contexts. The caller must supply the account kind (asset or liability) so the formatter knows which direction counts as "good".

`formatCurrency` signature extension:
```typescript
formatCurrency(amount: number, currency: string, opts?: {
  signed?: boolean;                                // existing; kept for back-compat
  signMode?: 'negative-only' | 'good-change-plus' | 'always';
  accountKind?: 'asset' | 'liability';             // required when signMode === 'good-change-plus'
})
```

When `signMode === 'good-change-plus'`:
- If `accountKind === 'asset'`: positive amount → `+` green; negative amount → unsigned neutral
- If `accountKind === 'liability'`: positive amount (balance down) → `+` green; negative amount (balance up) → unsigned neutral
- If `accountKind` is missing, fall through to `negative-only` behavior

Balance *totals* remain unchanged — overdrawn checking still shows `-$50.00` as a current balance, because a negative balance on an asset is a data-integrity signal (something's wrong), not a transaction. The running-balance column on the transactions list follows the balance rule, not the transaction rule.

**Inputs:** All money-rendering call sites. Each call site must pass the `accountKind` of the account whose perspective is being shown.

**Outputs:** Consistent sign convention in:
- `TransactionRow` amount column (per-row `accountKind` derived from `row.account.id` → tracked account lookup)
- `TransactionDayGroup` `dailySum` (passes through the account kind of the currently-filtered account, or neutral-only treatment in cross-account views — see Open Question below)
- `TransactionDetailSheet` amount display
- Recent Activity rows on the dashboard (per-row lookup by account)
- Category Trends current/previous/delta values (these are expense totals, not per-account — use `signMode: 'negative-only'` and display as neutral unsigned amounts)
- Cash flow series bars and labels (income and spending are already split into two series — display both unsigned with their existing color coding)
- Totals strip on the transactions page (follows the filtered-account kind in single-account view; in cross-account view, see Open Question)
- Activity view explanation header amounts (follows category/period totals; unsigned)

Balance displays (account cards, hero current balance, running balance column) keep current signing.

**Transfers between tracked accounts render as neutral** (unsigned, no green `+`) regardless of direction. Transfers don't change net worth, so neither side qualifies as a "good" change. This applies to both the collapsed transfer-pair row in cross-account views and the individual leg in single-account views. In code: when a row's `isTransfer` flag is true, use `signMode: 'negative-only'` and strip the `-`.

To distinguish transfers from ordinary outflows visually (since both now render unsigned and neutral), transfer rows prepend an `ArrowLeftRight` icon from `@lucide/svelte` (already installed at `^0.561.0`, not yet used in-tree) to the amount. The icon uses `text-muted-foreground` color and `h-4 w-4` sizing so it reads as a subtle marker, not an action affordance. Example rendering:

- Transfer row: `↔ $200.00` (icon + unsigned amount, all neutral)
- Spending row: `$5.00` (just unsigned amount, neutral)
- Deposit row: `+$1,000.00` (green plus-signed amount)

The icon is placed to the left of the amount within the amount cell. It should not be a separate column — the alignment of the amount's numeric value remains consistent across rows (right-aligned), with the icon sitting just before the digits when present.

### System Invariants

- All UI copy must be finance-first (AGENT_RULES): money, accounts, balances, spending, activity, next steps. No "accounting internals", "matching logic", "journal", "posting" in default surfaces.
- Dashboard must never show a misleading loading-state error ("not initialized" while state is still loading).
- Hero primary CTA must not duplicate its own secondary action link.
- Mobile layout must show financial data above nav chrome.
- Sign convention: for each rendering site, one and only one format — no mixing `-$50` and `$50.00` in the same context.
- The CTA fallthrough must not bypass real actionable state. If review queue, statement inbox, or stale-data branches match, they win over the "caught up" message.

### States

- **Loading (shell / /rules):** neutral "Loading…" messaging, not error copy.
- **Initialized, caught up (dashboard hero):** encouragement-framed CTA pointing at the direction panel.
- **Initialized, review queue present:** existing behavior (unchanged).
- **Mobile (`<980px`):** top bar + drawer; main content first.
- **Desktop (`>=980px`):** existing sidebar layout unchanged.

### Edge Cases

- **All cash flow rows are zero:** cash flow panel shows existing empty state (already guards on series length; update the guard to use the filtered length).
- **All category trends are zero-vs-zero:** panel's `{#if dashboard.categoryTrends.length > 0}` guard uses the filtered array so the empty state renders correctly.
- **Mobile drawer open when route changes:** drawer auto-closes on navigation so the new page is visible immediately.
- **Account card with zero transactions:** `Transactions` link still primary; no behavior change (route will show empty state).
- **Sign convention on $0.00:** displayed as `$0.00` in neutral text with no `+` or `-`.

### Failure Behavior

- If `formatCurrency` is called with an unknown `signMode`, default to existing behavior (`'negative-only'`) to preserve backwards compatibility with any call sites not yet migrated. No thrown errors.
- Mobile drawer: if the hamburger is clicked during a route transition, the drawer state still toggles cleanly. Disable drawer animation under `prefers-reduced-motion`.

### Regression Risks

- **Sign convention scope creep:** changing `formatCurrency` behavior in the balance-column context by mistake. Mitigate by migrating call sites explicitly (opt-in via `signMode: 'positive-plus'`), not by flipping the default.
- **Mobile nav drawer:** accidental hijack of scroll or focus. Mitigate by using the existing bits-ui primitives (same pattern as the filter dialog and detail sheet) rather than hand-rolled open/close logic.
- **Hero CTA change:** users may be trained on "Open transactions" as the default primary. The new "Review your direction" should feel like an upgrade, not a lost shortcut. Keep `/transactions` available via the secondary action list.
- **Zero-row filtering cutting non-zero months:** cash flow could over-filter if a month with tiny rounding shows as effectively zero. Mitigate by filtering only when all three fields (`income`, `spending`, `net`) are exactly zero.
- **`/rules` loading state:** introducing a `loading` flag without initializing it correctly would flash the wrong state. Follow the exact pattern already in `/accounts` and `/transactions`.

## Acceptance Criteria

- Sidebar brand-card byline reads: `Your money, accounts, and spending — all in one place.`
- `/rules` nav note reads: `Automate how new transactions get categorized`
- Dashboard hero CTA in the all-caught-up state reads `Review your direction` and points at `/#direction` (or equivalent scroll target on the direction panel)
- Dashboard hero in all-caught-up state does not include `Open transactions` as a secondary action
- `/rules` page shows `Loading rules…` while `/api/app/state` is fetching, not `Workspace not initialized yet.`
- Dashboard cash flow panel excludes months where `income === 0 && spending === 0 && net === 0`
- Dashboard category trends panel excludes rows where `current === 0 && previous === 0`
- On viewports `<980px`, the sidebar is replaced by a top bar with a hamburger; tapping the hamburger opens a drawer with the same nav sections; main content appears immediately below the top bar
- Account cards on `/accounts` show only `Transactions` as a visible quick action; `Edit account` is reached via the `Accounting details` disclosure
- Transaction amounts in the transactions list, detail sheet, recent activity, and totals strip display `+$X` in green for asset-balance-up and liability-balance-down changes, and `$X` in neutral text for the opposite direction — no `-` prefix
- Transfer rows (where `isTransfer === true`) display `↔ $X` (ArrowLeftRight icon from `@lucide/svelte`, neutral color, preceding the unsigned amount)
- Balance displays (account cards, hero current balance, running balance when negative) retain existing `-` for negative balances
- `pnpm check` passes
- No visual regressions on desktop or mobile layouts beyond the intended changes

## Proposed Sequence

Order chosen to minimize cross-cutting risk: smallest / most isolated first, most cross-cutting last.

1. **`/rules` loading state** — isolated to one file. Small diff. Start here.
2. **Sidebar copy cleanup** — two literal string changes in `+layout.svelte`.
3. **Demote Edit on accounts** — isolated to `/accounts/+page.svelte`. Rearrange existing markup.
4. **Hero CTA fallthrough** — isolated to dashboard `+page.svelte`. Update `primaryAction()` and `secondaryActions()`. Add `id="direction"` anchor to direction section.
5. **Dashboard zero-row filtering** — isolated to dashboard `+page.svelte`. Add reactive filters for cash flow and category trends.
6. **Sign convention** — cross-cutting. Add `signMode` to `formatCurrency`. Migrate call sites one file at a time. Keep balances untouched. Verify each call site after migration.
7. **Mobile nav drawer** — largest single change. Rebuild layout responsive structure. Verify on desktop, tablet, and mobile widths.

## Definition of Done

- All 7 acceptance criteria visibly confirmed in the running app at desktop and mobile widths
- No remaining copy leaks for the targeted strings anywhere in default UI surfaces (grep check: `accounting internals`, `matching and categorization` return no matches)
- `pnpm check` passes
- Manual verification: dashboard, transactions list, accounts list, `/rules`, `/import`, `/setup` all render cleanly at 360px, 768px, 980px, and 1440px viewport widths
- No existing tests fail (`uv run pytest -q` if any backend change leaked in; frontend has no regression tests to run — verify manually)

## UX Notes

- **Sidebar copy** must sound like a product pitch, not a developer changelog. Test: a non-technical reader should not see the word "journal", "matching", or "internals" in the shell.
- **Hero CTA** in the caught-up state should feel like an invitation to reflect, not a leftover default. The copy `Review your direction` explicitly references the new direction panel (shipped in 7b) so it's an intentional pointer, not filler.
- **Mobile drawer** must feel like a standard consumer app pattern (Google / Apple / Monarch) — slide in from left, backdrop dim, close on link tap. Don't invent novel gestures.
- **Sign convention** on inflows should use green sparingly and meaningfully. `+$1,000` for a paycheck should pop; neutral `$42.17` for a coffee charge should fade into the background. This maps to how consumer finance apps (Simplifi, Copilot, Monarch) display amounts — list views are scanned, and reducing visual noise on the common outflow case is the whole point.

## Out of Scope

- Keyboard shortcuts
- Pending/scheduled transfer entry (separate future task)
- Changes to sidebar logo, fonts, or colors
- Changes to hero eyebrow, title, or subtitle copy
- Nav reorganization / reordering
- Changes to how the running balance column signs negative values (those stay as-is)
- Changes to `formatCurrency`'s default behavior for non-migrated call sites

## Dependencies

None. 7d-4c, 7b, and the CSV parser refactor are all shipped. This task closes out Feature 7.

## Open Questions

None. All scope decisions resolved.
