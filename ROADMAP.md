# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Delivery Focus

Eliminate the remaining transfer cases that still force users to edit journal files by hand, while preserving import safety and keeping the default UI finance-first.

### Current Status

- Unknown review already supports:
  - direct transfers to manually tracked destination accounts
  - pending import-match transfers when only one imported side exists
  - automatic matching when one safe imported counterpart is available
- Register readers now suppress false pending work for balanced grouped ACH verification transfers instead of treating them as permanent pending work.
- The remaining product gap is narrower: a genuinely unresolved pending transfer between two import-enabled tracked accounts when no real imported counterpart will arrive.

### Decision

- Pending-transfer resolution should be a guided manual-transaction mode launched from an existing pending transfer.
- This should not become a separate transfer workbench.
- A broad freeform manual transaction system is follow-on work, not the first slice.

### Delivery Sequence

1. Ship and verify the grouped-settlement trust fix already in progress.
2. Add guided manual resolution for eligible pending imported transfers from the transactions view.
3. Generalize that authoring path into broader manual transaction entry only after the transfer-specific flow proves safe and understandable.

### Constraints

- Preserve the existing `new` / `duplicate` / `conflict` import model.
- Keep `workspace/` canonical and `.workflow/` disposable.
- Keep transfer-resolution logic, import-identity generation, and journal writes in backend services.
- Hide transfer-clearing and journal-file details from default UI copy.
- Fail closed when the system cannot safely protect against future duplicate imports.
- Do not solve this by broadening into many-to-many transfer matching or debt-payment decomposition.

## Deferred for Now

These are valid ideas, but they are not current priorities:

- Merchant management UI
- Expanding the rule language beyond the current limited matching model
- debt-payment decomposition and richer liability servicing workflows such as principal-vs-interest splits, amortization guidance, and lender-specific debt management beyond pure transfer handling
- Declarative CSV import row rules for advanced conditional parsing or categorization, inspired by hledger-style `if` matching, unless they can be introduced without making account setup feel heavy or surprising
- Full budgeting system
- Zero-based/envelope budgeting workflow
- Long-range forecasting and goals
- Detailed FI planner with retirement-timeline modeling
- Advanced reconciliation features beyond the current safe-edit workflow
