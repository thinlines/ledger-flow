# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Delivery Focus

Give users full control over their financial data through the UI — manual transaction entry for real-time tracking, and transaction editing for corrections, metadata, and splits — without sacrificing import safety or data trust.

### Current Status

- Transfer-specific flows are complete:
  - Unknown review supports direct transfers, pending import-match transfers, and automatic matching.
  - Grouped-settlement trust fix is shipped.
  - Guided manual resolution is shipped.
  - Bilateral auto-reconciliation is shipped (read-time detection, no journal writes).
  - Transfer suggestion matching works correctly after the CSV comment parsing fix.
- Import-time auto-linking (bypassing the unknowns review queue) was considered and rejected — it reduces trust by removing the human confirmation step. The current flow (import → review → confirm → auto-reconcile display) is the correct trust model.

### Delivery Sequence

1. **Manual transaction entry** — users can insert new transactions on any tracked account, including import-enabled ones. Manually entered transactions are tagged with `:manual:` (standard ledger tag). On subsequent import, the importer offers to match manual entries to their imported counterparts via a new "match" mode in the unknowns review.
2. **Transaction editing** — users can edit any transaction (imported or manual): payee, date, posting amounts, splits (add/remove/rebalance postings), and user metadata (tags, KV pairs, comments). System metadata stays hidden. Full split management from the first pass.

### Feature 1: Manual Entry + Import Matching

- New transactions are written to the journal with a `:manual:` tag (ledger standard tag syntax, not a KV pair).
- Supported on all tracked accounts, including import-enabled ones.
- Import matching uses a ±3-day date window. (Long-term, this becomes configurable via a settings interface — not currently planned.)
- The unknowns review page gains a third mode: **{categorize, transfer, match}**. "Match" shows a combobox of candidate manual entries, pre-selected if the system finds a strong match.
- Match candidates are ordered by quality: date + exact amount (highest), date + close amount, payee substring + date, payee substring only (lowest).
- When amounts differ (e.g., tip added, fee adjusted, authorization vs. posted), the confirmation UI surfaces the delta explicitly — this is a trust moment.
- After match confirmation, the imported transaction replaces the manual entry. The `:manual:` tag carries over as provenance, and any user metadata from the manual entry transfers to the imported version.

### Feature 2: Transaction Editing

- Users can edit payee, date, and posting amounts on existing transactions.
- Full split management: add, remove, and rebalance postings. The UI enforces the zero-sum constraint interactively.
- User metadata: tags (`:vacation:`), KV pairs (`; project: kitchen-remodel`), and freeform comments are visible and editable.
- System metadata (import identities, transfer state, source hashes) stays hidden from the UI.
- `--strict`-style validation at the UI layer: autocomplete for accounts, tags, and metadata keys drawn from the journal; warn before writing unknown values. Preventive, not after-the-fact.

### Constraints

- Preserve the existing `new` / `duplicate` / `conflict` import model.
- Keep `workspace/` canonical and `.workflow/` disposable.
- Keep transfer-resolution logic, import-identity generation, and journal writes in backend services.
- Hide transfer-clearing and journal-file details from default UI copy.
- Fail closed when the system cannot safely protect against future duplicate imports.
- The `:manual:` tag is standard ledger metadata — no custom extensions to the format.

## Deferred for Now

These are valid ideas, but they are not current priorities:

- Settings interface for configurable parameters (e.g., match date window)
- Merchant management UI
- Expanding the rule language beyond the current limited matching model
- Debt-payment decomposition and richer liability servicing workflows such as principal-vs-interest splits, amortization guidance, and lender-specific debt management beyond pure transfer handling
- Declarative CSV import row rules for advanced conditional parsing or categorization, inspired by hledger-style `if` matching, unless they can be introduced without making account setup feel heavy or surprising
- Full budgeting system
- Zero-based/envelope budgeting workflow
- Long-range forecasting and goals
- Detailed FI planner with retirement-timeline modeling
- Advanced reconciliation features beyond the current safe-edit workflow
