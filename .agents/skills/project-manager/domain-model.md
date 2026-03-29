# Domain Model

This reference defines the project's domain vocabulary. Use it when writing task definitions, system behavior descriptions, or acceptance criteria. Precise language here prevents incorrect implementations.

## Account Types

**Tracked account**: A real-world financial account (asset or liability) whose balance the product tracks. Created in the Accounts UI. Examples: checking, savings, credit card, car loan.

**Import account**: Configuration that maps a CSV statement format to a tracked account. Defines how institution CSV rows are normalized into journal transactions.

**Transfer pair account** (transfer-clearing account): An internal system account used to balance transfers between two tracked accounts. Not a real-world account. Created automatically when wiring two accounts for transfer tracking. Hidden from default UI.

**Equity account**: Used for opening-balance entries (default: `Equity:Opening-Balances`). Not surfaced directly — users choose in plain language where the starting balance comes from.

**Income/expense category**: A classification for transaction activity. Not a balance-sheet account. Managed via Rules and Unknown Review. Do not conflate with tracked accounts.

## Transaction States

**`new`**: An imported transaction not yet seen — eligible to add to the journal.

**`duplicate`**: Matches an existing transaction's `source_identity` with the same or unknown payload hash — skipped silently.

**`conflict`**: Matches `source_identity` but has a different `source_payload_hash` — skipped and surfaced for user review.

**`unknown`**: An imported transaction whose payee/category has not been resolved — surfaces in Unknown Review.

**`pending`**: An imported transfer row whose counterpart on the other tracked account has not yet arrived. Represents genuinely unresolved work. Contributes to pending counts and `Balance with pending`. Must only reflect real missing activity, not a failed 1:1 match.

**`posted`**: Normal settled activity — direct transfers and non-pending transactions.

**`settled_grouped`**: Multiple imported transfer rows that jointly settle across the same tracked-account pair (e.g., two microdeposits + one withdrawal summing to zero). A read-time presentation state only — not persisted to journals. Detection must be conservative; fail closed to `pending` if uncertain.

## Clearing Status

The ledger format's native transaction status flag, appearing between the date and the payee on the header line, or between the date and the code (in parentheses) if a code is present. Represents data provenance — how confident we are that a transaction occurred — not reconciliation state.

**`cleared` (`*`)**: Bank-confirmed. Written by `ledger convert` during CSV import. Indicates the transaction originates from an institution statement.

**`pending` (`!`)**: Flagged for attention. Set by the user via the register toggle. Indicates the user wants to revisit this transaction.

**`unmarked` (no flag)**: Manual entry. Written by the manual transaction creation flow. Indicates the transaction was entered by the user without bank confirmation.

These are orthogonal to transfer states (`pending`, `settled_grouped`, `bilateral_match`). A transaction can be transfer-pending and clearing-cleared simultaneously. Do not conflate the two systems.

UI copy must use plain language: "Bank-confirmed", "Flagged", "Manual entry". Do not expose "cleared", "pending", or "unmarked" in default surfaces.

## Import Identity

Each imported transaction carries metadata that makes import idempotent. These fields are written as comments in journal transaction blocks and are never rewritten after import:

- **`source_identity`**: SHA-256 of institution, transaction date, normalized payee, and institution-side posting amount. The primary deduplication key.
- **`source_payload_hash`**: SHA-256 of the normalized transaction body. Used to detect conflicts (same identity, changed content).
- **`source_file_sha256`**: Hash of the source CSV file.
- **`importer_version`**: Version of the import logic that produced this transaction.

## Workspace Structure

**`workspace/`** — Canonical truth. Never disposable.
- `settings/workspace.toml`: workspace config and account wiring
- `journals/*.journal`: financial history in hledger plaintext format
- `rules/*`: account rules, tags, payee aliases
- `opening/*`: opening-balance records
- `imports/processed/`: archived source CSVs

**`.workflow/`** — Operational/disposable. Rebuild from workspace if lost.
- `app_state.json`: active workspace selection
- `stages/*.json`: resumable staged review payloads
- `state.db`: SQLite import index (provenance, idempotency, undo support)

**Rule**: If `.workflow/` and `workspace/` disagree, workspace wins.

## System Boundaries

**Backend** (FastAPI): owns all accounting logic, import pipeline, rule management, journal reads/writes, and hledger CLI integration. Business rules live here, not in the frontend.

**Frontend** (SvelteKit/Svelte 5): renders the finance workspace, calls `/api/*` endpoints. Must remain thin — no import logic, no journal semantics, no accounting rules.

**API contract**: shared between frontend and backend. If a payload shape changes, update backend models/handlers, frontend callers/types, and tests together.

## Workflow Relationships

```
Setup → Import → Unknown Review → Rules
                                      ↘
                         Dashboard / Accounts / Transactions  ← daily home
```

- **Setup**: bootstrap from zero files to first useful financial activity; hands off to normal product surfaces
- **Import**: bring in new statement activity from CSV; idempotent and conflict-visible
- **Unknown Review**: resolve uncategorized transactions; may create income/expense categories
- **Rules**: turn repeated review decisions into automation
- **Dashboard / Accounts / Transactions**: the product's identity — daily finance visibility

Import, review, and rules support the finance workspace. They should not eclipse it.

## Transfer Matching Models

**1:1 match**: One imported row on each side of a transfer pair. Standard direct transfer case.

**Grouped transfer** (1:2, 2:1, N:M): Multiple imported rows on one or both sides that together net to zero across the transfer pair account. Example: two microdeposits (+$0.12, +$0.34) matching one withdrawal (-$0.46) in ACH account verification. Grouped settlement must be derived from actual loaded journal transactions, not inferred from guesswork.

**Synthetic peer event**: A placeholder entry the system generates to represent the expected counterpart of a pending transfer before the real imported row arrives. Must be suppressed when real imported activity already settles the group.

## Key Invariants

These apply across all tasks. Cross-reference `AGENT_RULES.md` for implementation-level enforcement:

- `workspace/` is canonical. `.workflow/` is disposable operational memory.
- Preview must precede apply for all import flows.
- Import never rewrites existing journal text after the fact.
- Conflicts surface for user review; they are never silently resolved.
- Balance-sheet accounts (assets, liabilities) belong in the Accounts UI. Rules and Review handle income/expense categories only.
- Internal/system accounts (transfer-clearing accounts, equity) are hidden from default UI.
- Pending UI must represent genuinely unresolved work only — not merely the absence of a 1:1 match.
- Detection logic must be conservative: when in doubt, fail closed to pending rather than hiding activity.
- Finance-first language in all UI copy: money, accounts, balances, spending, activity, next steps. No plaintext accounting terms in default surfaces.
