# TASK — UI rebuild, tracer bullet 1: Shell + Transactions

**Outcome:** Trash the old UI and recreate it in the ADR-0003/0004 direction —
modern-minimal, flat, keyboard-first. Ship ONE working feature end-to-end,
bottom-to-top, TDD: the **Transactions register** inside a new app shell.

**Why now:** Phase 2 makeover direction was grilled and recorded
(ADR-0003 keyboard model, ADR-0004 visual direction, CONTEXT.md IA terms).
This is the first tracer bullet; later slices rebuild Review, quick-add,
Import, Reconcile, Accounts, Dashboard route-by-route.

## Direction (fixed by ADRs — do not re-litigate)

- Flat solid neutral surfaces, hairline borders, negative space; no gradients,
  no glass, no card-in-card. Radius ~0.5rem. Squared buttons.
- One accent: the teal→green brand hue. Color otherwise = status + data only.
- Space Grotesk for large display headings only; Inter everything else;
  amounts in Inter `tabular-nums`.
- Keyboard: one key = one verb app-wide. `g` prefix nav, `j`/`k` roving focus
  on the register, `Enter` open, `Esc` close, `?` cheat sheet, Ctrl+K palette.
- Plain language; no ledger-CLI jargon in default copy.
- Dark mode deferred; tokens must not preclude it.

**Signature element (the one bold move):** the register reads like a modern
bank book — a date spine in the left gutter, one hairline vertical rule
separating the running-balance rail on single-account scope. Everything else
stays quiet.

## Scope — MVP feature: Transactions register

Keep (load-bearing, reuse):
- `lib/transactions/*` (types, filters, loadTransactions, actions, helpers).
  Note: N-1 categories, transfer states, and running balance are computed
  **server-side** (`unified_transactions_service.py`); the frontend renders
  `row.runningBalance` (single-account scope only) and `row.categories`.
- `lib/api.ts`, `lib/format.ts`, `lib/currency-*`, `lib/undo-toast.ts`.
- `lib/command-registry.ts` + CommandPalette + KeyboardListener (extended,
  restyled) and the `ui/` primitives (command, dialog, popover).
- Existing vitest suites for kept modules.

Build (TDD, bottom → top):
1. **Keymap dispatcher** (pure TS, new): global one-key-one-verb table,
   `g`-prefix sequences, input-field guards, `?` cheat-sheet data derived
   from the same table. Red → green first.
2. **Roving focus / list navigation** (pure TS, new): j/k/Home/End over
   flattened day-grouped rows, focus survival across reloads and filter
   changes, Enter/Esc intents.
3. **Register view-model** (pure TS): day grouping (reuse `groupByDate`),
   pending rows folded inline with a pending badge (no separate card).
4. **New shell** `+layout.svelte`: lean sidebar (durable surfaces + workspace
   identity + palette hint), new flat tokens in `app.css`.
5. **New Transactions page**: filter bar (accounts, period, search — URL
   remains source of truth), register with date spine + running-balance rail
   (single-account only), row detail panel with existing actions
   (recategorize, reassign, unmatch, delete, clearing toggle), empty/error
   states with "what's next" copy.
6. Browser verification (Playwright) + screenshot review.

Trash (git history preserves; routes return in later tracer bullets):
- Old shell chrome and all decorative CSS (gradients, view-card, pills).
- Routes: `/` overview, `/accounts`, `/accounts/configure`, `/import`,
  `/rules`, `/setup`, `/unknowns`, reconcile pages.
- Components: dashboard/*, ImportFlow, RuleEditor, SavedRuleAccordionItem,
  LedgerAccountsPanel, RecentActivitySheet, TransactionEntryModal,
  TransactionInsights, AccountStatusStrip, AddTransactionForm (manual entry
  returns as the quick-add slice).
- Tests that exercise only trashed UI helpers.

## Non-negotiables

- Per-account **running balance** on single-account scope (rail column).
- Row = user action: **N-1 posting rule** + **transfer-pair collapse** stay.
- No `backdrop-filter` (ADR-0001); `content-visibility: auto` on the register
  (ADR-0002). No jarring DOM shifts — reserve space, animate transitions.
- Tailwind v4 utilities; scoped CSS only for gradients (none now), state
  variants, sibling separators.
- Backend untouched.

## Acceptance

- `pnpm test` green (old + new suites); `pnpm check` clean.
- App boots with only the Transactions surface; user can scope to one
  account, scan running balance, j/k through rows, Enter a row, act on it,
  `?` shows the cheat sheet, Ctrl+K still works.
- HITL: user confirms the register feels faster/clearer/calmer.

## Deferred findings (name, don't build)

- Review, Import, Reconcile, Accounts, Dashboard: next tracer bullets.
- Quick-add (global manual entry): next slice after this one.
- Insights/cross-filter analytics: Dashboard direction (ADR-0005 wall).
