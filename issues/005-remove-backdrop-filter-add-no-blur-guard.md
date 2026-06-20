---
labels: [done-pending-hitl]
---

# Remove all `backdrop-filter` from the frontend; add no-blur guard test

> GitHub: https://github.com/thinlines/ledger-flow/issues/3 (`ready-for-agent`)

## Parent

- thinlines/ledger-flow#2 — `issues/004-flatten-shell-compositing-scroll-performance.md`
- `docs/adr/0001-solid-surfaces-no-backdrop-filter.md`
- `docs/adr/0002-no-js-virtualization-transactions.md`

## What to build

Remove every `backdrop-filter` / `backdrop-blur-*` in the frontend and replace each
affected surface with a **solid** (opaque) background, then lock the decision in place
with a static guard test. This is the entire Phase 1 performance fix in one vertical
slice: the app-wide scroll jank disappears because the compositor no longer re-blurs a
live backdrop on every scroll frame.

The five blur sites: the app-shell mobile top bar, the sidebar brand card, the sidebar
nav sections, the Transactions sticky totals footer, and the Reconcile mobile footer.

Scope is **blur removal only**. Do not touch the body background gradient, the decorative
card gradients (hero / pending / result / brand), box-shadows, or any layout — those are
deferred to the separate visual makeover (Phase 2). No backend changes.

Respect the governing decisions: ADR-0001 (solid surfaces, no `backdrop-filter`) and
ADR-0002 (no JS virtualization; `content-visibility` is the reserved escape hatch, not in
scope here).

## Acceptance criteria

- [x] No `backdrop-filter` or `backdrop-blur-*` remains anywhere in the frontend source — five blur sites removed, plus one `backdrop-filter: saturate(1.2)` on the Transactions day-group date row that was also subject to the per-scroll-frame cost.
- [x] Each affected surface (sidebar brand card, sidebar nav sections, mobile top bar, Transactions totals footer, Reconcile mobile footer) renders on a fully opaque solid background (`bg-white`) — no muddy gradient bleed-through.
- [x] No decorative or layout changes: body gradient, card gradients, shadows, and layout/IA are unchanged apart from the blur/opacity edits.
- [x] A static source-guard test (vitest) scans the frontend `src/` tree and fails if `backdrop-filter` or `backdrop-blur-*` is present; it passes on this change. (`src/lib/no-backdrop-filter.test.ts`.)
- [x] The full frontend test suite passes (`pnpm test`: 4 files, 55 tests), including the new guard.
- [x] On the Transactions register, running balance, day-group sums, the N-1 posting-collapse behavior, and the sticky totals footer are unchanged (no logic edits — only background classes and one CSS rule).
- [ ] HITL sign-off: the reporter scrolls the worst-case Transactions filter (All time, widest account) and one short page (e.g. Overview) and confirms scrolling feels smooth.

## Blocked by

- None - can start immediately.
