# Explore analytics aggregate server-side (deferred); makeover ships only the cross-filter substrate

Explore (the analytical surface) is meant to cross-filter by default, Power-BI
style: click a mark in one visual and every other visual on the page re-scopes to
that selection. The user requires this to stay performant from six months to six
*years* of daily transactions.

The decisive fact: **Power BI does not aggregate in the browser.** In both Desktop
and the Service, the VertiPaq engine holds the fact table, each visual issues a DAX
query, and the *engine* returns small aggregated results that the browser merely
renders. In the Service that engine runs server-side. So the scalable architecture
is "server crunches, client renders small aggregates" — and that is backend work,
which the Phase 2 makeover puts out of scope.

Therefore the **performant, arbitrary cross-filter Explore is inherently a backend
effort and is deferred** to a named backend-inclusive track (the "flexible, uniform
analytical interface" already noted as future work). It should be built Power-BI
style: server-side aggregation over fact table(s) at sensible grains, with the
cross-filter selection passed as a query parameter the server aggregates against
(the user's multi-grain instinct applies here).

The frontend-only makeover delivers only two things in this area:

1. **The cross-filter interaction substrate** — a page-level **cross-filter context**
   (shared reactive selection store), ECharts click/select/brush event wiring, and
   the cross-filter-vs-drill-through split — built over the data that already
   exists (the current pre-aggregated dashboard payloads / existing dimensions). The
   interaction model is established now so a future server-side aggregation backend
   slots in behind the same substrate (selection → query).
2. **`content-visibility: auto` on the Transactions register** (per ADR-0002), which
   is what actually fixes the present DOM bog and keeps the register smooth at
   six-year scale. This is a Transactions-tracer requirement, independent of Explore.

## Considered Options

- **Client-side fact table + browser aggregation** — rejected; this reproduces
  exactly the in-browser Power BI bog the user has witnessed, and fails the
  six-years-of-daily-data scale bar.
- **Reopen the backend now to build the real Explore engine** — rejected *for now*;
  it keeps the makeover bounded, and the register's present pain is independently
  fixable with `content-visibility`. Legitimate to revisit as its own track.
- **Cross-filter only over already-pre-aggregated dimensions** — accepted as the
  *interim* behavior the substrate provides until the backend engine lands.

## Consequences

"Register stays fast at six years" is a `content-visibility` task on the
Transactions tracer, not a cross-filter concern. The cross-filter substrate must be
designed selection-first so the deferred server-side backend can slot behind it
without reworking the interaction layer. When Explore graduates to real analytics,
follow Power BI's model — server aggregates, client renders small results, possibly
multiple fact tables at different grains — never ship the raw fact table to the
browser.
