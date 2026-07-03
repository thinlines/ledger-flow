# Solid surfaces in the shell — no `backdrop-filter`

The app shell used five stacked `backdrop-blur-lg` cards (sidebar brand card + nav
sections, mobile topbar) plus blurred sticky footers on Transactions and Reconcile.
`backdrop-filter` forces the compositor to re-sample and re-blur its backdrop every
scroll frame, which produced uniform app-wide scroll jank — a Firefox profile showed
the main thread 96% idle, confirming the cost is compositing/GPU-bound, not JS.
We removed every `backdrop-filter` and replaced the translucent-blurred surfaces with
**solid** backgrounds. The frosted-glass look is deliberately abandoned for scroll
performance.

## Considered Options

- **Keep the glass, mitigate** (`will-change`, layer promotion, snapshotting) — rejected;
  these rarely fully fix `backdrop-filter` and add their own complexity.
- **Translucent without blur** (`bg-white/90`, drop blur only) — viable and cheap, but
  we chose fully solid because the makeover is heading flat anyway.

## Consequences

Do **not** reintroduce `backdrop-filter` / `backdrop-blur-*` during the visual makeover.
"Modern" here means flat, solid surfaces (cf. Monarch, Copilot), not glassmorphism. If a
future surface genuinely needs blur, it must come with a profiled scroll trace showing it
does not regress frame rate.
