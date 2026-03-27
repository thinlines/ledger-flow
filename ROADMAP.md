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
- Register readers suppress false pending work for balanced grouped ACH verification transfers.
- Guided manual resolution is shipped: a user can resolve an eligible one-sided pending transfer from the transactions page without editing files.
- Outstanding trust gap: when both sides of a transfer are independently imported and the dates differ by 1–7 days, the two pending rows are not linked. Both appear as separate negative-amount rows with identical-looking labels. The pending section is misleading and offers no clear resolution path.

### Decision

- Bilateral pending pairs (both sides imported, mutual peer references, same absolute amount, within date window) should be auto-reconciled at register read time with no journal writes, following the same read-time exclusion model as grouped-settlement detection.
- Ambiguous pairs (multiple same-amount candidates in the same window) must fail closed to pending.
- Manual link UI for ambiguous pairs is follow-on work after auto-reconciliation is proven safe.
- A broad freeform manual transaction system is follow-on work after the transfer-specific flows are trusted.

### Delivery Sequence

1. ✅ Ship and verify the grouped-settlement trust fix.
2. ✅ Add guided manual resolution for eligible one-sided pending imported transfers.
3. Fix bilateral pending auto-reconciliation: two independently-imported sides of the same transfer should resolve without user action.
4. Fix import-time matching so bilateral pairs do not arise (the pipeline should link them on the second import).
5. Manual link UI for ambiguous bilateral pairs that cannot be auto-reconciled.
6. Generalize into broader manual transaction entry only after transfer-specific flows are trusted.

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
