# Agent Rules

This file captures repo-specific rules for agents and contributors. Use it with `README.md` for product purpose, `ARCHITECTURE.md` for current implementation, `DECISIONS.md` for rationale, `TASK.md` for the active task, and `ROADMAP.md` for direction.

## Product and Copy Rules

- Write primary UI copy in terms of money, accounts, balances, spending, activity, and next steps.
- Do not expose `ledger`, `journal`, postings, workspace files, intermediary accounts, or rule-store terminology in default UI copy.
- Assume the user is nontechnical and may know little accounting.
- The purpose of each control should be self-evident. Do not explain internal implementation structure in field labels.
- Keep one dominant action per screen. Secondary actions should be sparse and obviously secondary.
- Prefer summaries and action cues over dense diagnostics.
- Advanced details belong in explicit reveals, secondary screens, or diagnostic surfaces.

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
- Hide internal/system accounts such as equity or transfer-clearing accounts from default UI unless the user is in an advanced or audit-oriented path.

## Import Safety Rules

- Preserve the `new` / `duplicate` / `conflict` model.
- Preserve or deliberately migrate the metadata that makes import idempotent and auditable:
  - `source_identity`
  - `source_payload_hash`
  - `source_file_sha256`
  - `importer_version`
- Keep preview before apply.
- Never auto-rewrite or normalize transactions that already exist in journals.
- Surface conflicts for review instead of silently resolving them.
- Preserve the audit trail: journal metadata plus the SQLite import index should continue to explain why an import was applied, skipped, or undoable.

## Verification Rules

- Run `pnpm check` in `app/frontend` when changing frontend code or shared API expectations.
- Run `uv run pytest -q` in `app/backend` when changing backend behavior, import semantics, or API contracts.
- When changing root docs, verify links, file/path claims, and source-of-truth boundaries against the repo.
- If a change touches import, review, or rule flows, confirm that the append-only and conflict-visible invariants still hold.
