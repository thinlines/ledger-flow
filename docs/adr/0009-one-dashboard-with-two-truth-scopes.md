# One Dashboard with two truth scopes

Ledger Flow combines the former Overview and Explore destinations into one
Dashboard. The Dashboard presents global book health alongside interactive
analysis, but only analytical measures participate in cross-filtering;
operational facts about Import, Review, and Reconcile always retain their global
scope.

## Considered Options

- **Separate Overview and Explore destinations** — rejected because book health
  and understanding the books belong in one primary workspace.
- **Cross-filter the entire Dashboard** — rejected because filtering away
  incomplete data could make the books appear healthier than they are.

## Consequences

The Dashboard must visually distinguish global book health from filter-scoped
analysis. Analytical selections may change measures and visuals, but they cannot
alter or hide outstanding accounting work.
