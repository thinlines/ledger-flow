# Minimal, flat visual direction (extends ADR-0001)

The Phase 2 makeover sets the app's aesthetic target: **modern and minimal,
welcoming through restraint rather than decoration.** ADR-0001 already banned
`backdrop-filter` and mandated solid surfaces; this extends that ruling from "no
glass" to the full visual system. Linear is the north star (with Obsidian/VS Code
informing the keyboard model specifically).

The decisions:

- **Flat, solid, mostly-neutral surfaces.** Drop the body gradient washes and the
  decorative card gradients (brand / hero / pending / result). Collapse the
  card-in-card nesting (nav sections as cards inside the sidebar, view-cards inside
  those) into fewer, larger surfaces delineated by hairline borders and negative
  space, not stacked rounded boxes.
- **Tighter geometry.** Reduce the card radius (~1.15rem → ~0.5rem) and square off
  the pill buttons — reads "tool," not "consumer toy."
- **Color means something.** Reserve color for status, the single brand accent, and
  data visualization. Keep the existing teal→green brand *hue* as that one accent
  (blue-green reads trust + growth, right for finance); strip essentially all other
  decorative color.
- **Type.** Space Grotesk for large display headings only; Inter for everything
  else.
- **Density is not a goal.** The whole app stays airy with effective negative space
  and clear at-a-glance hierarchy. "Spacious for newcomers" means *discoverable*,
  not padded. Detail is reached by **progressive disclosure / drill-through** —
  each surface shows only what is in scope at its altitude (Overview → summary;
  drill to Transactions for the full picture).
- **Plain language for everyone.** Power-user keyboard support is additive; the
  default copy carries no domain jargon (`journal`, `posting`, ledger-CLI terms).
  Welcoming is carried by copy, empty/first-run states, whitespace, and a
  persistent "what's next" affordance — not by ornament.
- **Dark mode is deferred** but the token architecture must not preclude adding it
  later.

## Considered Options

- **Keep the current warm, decorative look** (gradient washes, gradient cards,
  pills, heavy rounding) — rejected; reads busy and undercuts the "professional /
  minimal" goal.
- **Go cool/corporate-neutral and drop the brand hue** (Mercury/Stripe register) —
  rejected; loses the warmth and identity the user wants for "welcoming."
- **Maximally dense pro-tool** — rejected; density is explicitly not a goal and
  works against welcoming and discoverability.

## Consequences

Every surface gets restyled, so this lands incrementally via tracer-bullet routes
(starting with Transactions), and the token/primitive set will refactor as later
routes reveal needs. Brand identity is now expressed through restraint plus one
confident accent, not decoration — so a future "modernization" must not reintroduce
decorative gradients or glass (cf. ADR-0001). Welcoming is a copy/empty-state/
whitespace responsibility, and reviewers should treat jargon leakage and missing
"what's next" affordances as defects, not polish.
