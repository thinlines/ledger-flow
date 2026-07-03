# Transaction lists: no JS virtualization — `content-visibility` is the escape hatch

The Transactions register renders every row of the current filter into the DOM with no
windowing. The obvious scaling fix — JS virtualization (row recycling / windowing
libraries) — pulls rows *out* of the DOM, which breaks everything that assumes the full
row set is present: the per-account running balance, the N-1 posting-collapse rule,
day-group sums, and the sticky totals footer. The running balance in particular is a
load-bearing power-user feature and a fragile invariant.

We have therefore **ruled out JS virtualization**. If removing the shell's compositing
cost (see ADR-0001) leaves Transactions janky on a worst-case filter, the sanctioned next
step is **`content-visibility: auto` with a tuned `contain-intrinsic-size`** on rows — a
CSS-only technique that skips layout/paint for off-screen rows while keeping every node in
the DOM, so the running-balance math never even notices. Full windowing is reconsidered
only if `content-visibility` is insufficient, which is unlikely at personal-finance data
scale (thousands of rows, not millions).

## Consequences

A future engineer tempted to add a virtualization library should stop: the running-balance
invariant is the reason it's off the table. Reach for `content-visibility` first.
