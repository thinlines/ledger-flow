# Agent Rules

This file captures repo-specific rules for agents and contributors. Use it with `README.md` for product purpose, `ARCHITECTURE.md` for current implementation, `DECISIONS.md` for rationale, `TASK.md` for the active task, and `ROADMAP.md` for direction.

## Product and Copy Rules

- Write primary UI copy in terms of money, accounts, balances, spending, activity, and next steps.
- Do not expose `ledger`, `journal`, postings, workspace files, intermediary accounts, or rule-store terminology in default UI copy.
- Assume the user is nontechnical and may know little accounting.
- The purpose of each control should be self-evident. Do not explain internal implementation structure in field labels.
- Do not make a user choose asset vs liability by editing an advanced account name or learning account prefixes. Primary account setup must expose that choice directly.
- Do not present inferred account subtypes as if they were saved state. Suggestions must be explicit, or the subtype must be deliberately persisted.
- Keep one dominant action per screen. Secondary actions should be sparse and obviously secondary.
- Prefer summaries and action cues over dense diagnostics.
- Advanced details belong in explicit reveals, secondary screens, or diagnostic surfaces.
- When a user needs to create a tracked asset or liability, route that work into Accounts. Rules and Review may create income/expense categories, but they should not become the default place to create loans, credit cards, vehicles, or other balance-sheet accounts.
- For the opening-balance offset task, use plain-language labels such as where the starting balance comes from or what it offsets. Do not imply a durable account link if the product is only choosing how to write the opening entry.

## Screen and Visual Rules

- Preserve the finance-first app shell and route grouping: overview, accounts, transactions, import, review, rules, and setup.
- Treat import and review as supporting workflows, not the core product identity.
- Default to the current visual direction unless a task explicitly calls for a broader redesign:
  - `Space Grotesk` for headings
  - `Inter` for body text
  - cool neutral backgrounds with a mint tint
  - deep blue-green as the main brand color
  - amber for attention and red for errors
  - elevated cards, soft borders/shadows, and rounded controls
- Maintain responsive layouts: desktop grids and mobile single-column stacking.
- Maintain keyboard reachability, visible focus states, and contrast-safe status colors.

## Data and Architecture Rules

- `workspace/` holds accounting truth. `.workflow/` is operational memory and may be rebuilt.
- Keep business rules in backend services. Frontend components should orchestrate flows, not own import/accounting logic.
- Treat `/api/*` payloads as shared contracts. If they change, update backend models, handlers, frontend callers, local types, and tests together.
- Preserve the product distinction between tracked accounts as balance-sheet items and categories as income/expense classification.
- Keep Accounts as the primary home for tracked balance-sheet account creation and management. Rules and review should not become the default path for creating liabilities or other tracked accounts.
- Hide internal/system accounts such as equity or transfer-clearing accounts from default UI unless the user is in an advanced or audit-oriented path.
- For the current opening-balance offset cut, do not add a persistent paired-account or relationship field unless the task explicitly expands. Derive edit state from the opening-balance transaction itself and keep the scope focused on writing the correct starting entry.

## Import Safety Rules

- Preserve the `new` / `duplicate` / `conflict` model.
- Preserve or deliberately migrate the metadata that makes import idempotent and auditable:
  - `source_identity`
  - `source_payload_hash`
  - `source_file_sha256`
  - `importer_version`
- Apply imports optimistically with an undoable toast. Interrupt the user only when a row would fall in a reconciled period (`conflictReason === 'reconciled_date_fence'`). Identity-collision conflicts silently skip and emit `import.identity_collision.v1` for diagnostic visibility. Trust is preserved at the write layer (`apply_import` never writes non-`new` rows) and via undo (toast + history `Undo Import`); not via a preview-before-apply screen.
- Never auto-rewrite or normalize transactions that already exist in journals.
- Preserve the audit trail: journal metadata plus the SQLite import index should continue to explain why an import was applied, skipped, or undoable.

## Verification Rules

- Run `pnpm check` in `app/frontend` when changing frontend code or shared API expectations.
- Run `uv run pytest -q` in `app/backend` when changing backend behavior, import semantics, or API contracts.
- When changing root docs, verify links, file/path claims, and source-of-truth boundaries against the repo.
- If a change touches import, review, or rule flows, confirm that the append-only and conflict-visible invariants still hold.
