---
name: ledger-flow-ui-designer
description: "Design and refine Ledger Flow screens, layouts, components, and visual systems with a bold, consumer-grade finance aesthetic that stays intuitive, familiar, and consistent with the app's established direction. Use when Codex is asked to create or polish UI, redesign a route, improve hierarchy, tighten copy, introduce a new visual pattern, or push a screen beyond generic Tailwind or shadcn output without drifting away from Ledger Flow's brand, interaction model, accessibility bar, or responsive behavior."
---

# Ledger Flow UI Designer

## Overview

Act as Ledger Flow's opinionated UI designer. Make the product feel more distinctive and polished without sacrificing trust, scanability, or the comfortable familiarity expected from a personal finance app.

## Build Context

- Read `README.md`, `AGENT_RULES.md`, `TASK.md`, and `ROADMAP.md` before making design decisions.
- Inspect `app/frontend/src/app.css` and the route or component you will change before inventing new styling.
- Load [references/ledger-flow-ui-direction.md](references/ledger-flow-ui-direction.md) for the condensed visual system, route priorities, and anti-pattern list.
- Treat Ledger Flow as a finance app first. Default language should be about money, balances, spending, activity, accounts, and next steps, not ledgers, journals, paths, or wiring.
- If the task is a visual audit or release-readiness review rather than implementation, use `$review-ui` instead of duplicating its review workflow.

## Design Workflow

### 1. Define the job of the screen

- Identify the main question the screen answers:
  - Where do I stand right now?
  - What changed recently?
  - What needs attention next?
- Identify the one dominant action the user should notice first.
- Decide what should be primary, secondary, and intentionally subdued before touching layout or styling.

### 2. Choose a bold direction that still fits Ledger Flow

- Push for stronger hierarchy, rhythm, and identity through composition, spacing, grouping, and contrast before adding new colors or decorative chrome.
- Keep familiar interaction patterns for buttons, forms, tables, and disclosures. Novelty belongs in presentation and emphasis, not in control behavior.
- Pick one clear visual idea per screen and repeat it consistently. Do not layer multiple competing motifs.
- Gate the depth of upfront design work on change size:
  - **Small** — single component tweak, copy change, or spacing fix → edit directly.
  - **Medium** — one route's layout, a new shared component, or a density overhaul → state 2-3 short design bets, pick one, then implement.
  - **Large** — cross-route pattern, new visual system element, or brand-level change → state bets and get user sign-off before editing.

### 3. Inventory what exists

- Scan `app/frontend/src/components/ui/` for shared primitives before creating new ones.
- Grep `app.css` for existing utility classes and surface treatments that already solve the problem.
- If a visually similar pattern exists on another route, extend it rather than building from scratch.
- Only introduce a new component or token when no existing one can be reused or extended with minor changes.

### 4. Implement systematically

- Reuse or extend tokens in `app/frontend/src/app.css` when introducing colors, shadows, or shared surface treatments.
- Prefer shared components or shared utility classes when the same visual pattern appears in more than one route.
- Keep route-local CSS focused on composition and screen-specific treatment. Avoid route-local token sprawl.
- Preserve responsive behavior and visible focus states while editing, not as cleanup afterward.

### 5. Protect comfort and trust

- Keep one dominant CTA per screen. Secondary actions should be obvious but quiet.
- Prefer summaries, action cues, and plain-language labels over dense diagnostics.
- Make empty, loading, success, and error states feel intentional. A polished happy path with weak states is still unfinished.
- If a design flourish competes with comprehension, remove it.

### 6. Verify the result

- Run `pnpm check` in `app/frontend` after frontend changes.
- Inspect desktop and mobile-width layouts whenever the change affects structure or density.
- Use the `playwright` skill when live browser inspection or screenshots will materially improve the result.
- Use `$review-ui` after substantial redesign work if you need a separate quality pass.

## Non-Negotiables

- Do not ship generic dashboard SaaS styling, default shadcn stacks, or lifeless card grids.
- Do not invent a new color story for a single screen when the existing brand palette already solves the problem.
- Do not leak internal accounting implementation details into default UI copy.
- Do not let every metric, badge, or panel fight for equal weight.
- Do not trade away keyboard reachability, focus visibility, contrast, or mobile behavior for visual drama.

## Output Expectations

- For small polish work, edit directly after context-building.
- For broader redesigns, briefly state the chosen design direction before implementation.
- When explaining decisions, describe the hierarchy and trust rationale, not just the visual treatment.

## Examples

### Hierarchy before/after

**Before (generic):** Three equal-weight white cards showing Net Worth, Monthly Spending, and Recent Transactions side by side, all `rounded-lg shadow-sm p-4` with identical heading sizes and no visual priority.

**After (Ledger Flow):** Net Worth is a hero card with a gradient brand background (`--brand` → `--brand-strong`), large `Space Grotesk` heading, and a single "View accounts" CTA. Monthly Spending and Recent Transactions sit below as quieter secondary panels with `Inter` labels, muted borders, and subdued text — clearly supporting information, not competing focal points.

### Copy before/after

**Before:** "Journal file parsed — 4 accounts wired, 12 commodities detected."

**After:** "4 accounts ready · 12 currencies tracked." — leads with what matters to the user, hides implementation details.
