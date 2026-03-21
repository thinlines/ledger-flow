# Architecture

This document describes the current system as implemented today. It explains where truth lives, how the major subsystems fit together, and which invariants future changes must respect.

## System Overview

- `app/frontend` is a SvelteKit 2 / Svelte 5 client. It renders the finance workspace and calls backend `/api/*` endpoints through shared fetch helpers.
- `app/backend` is a FastAPI service. It owns workspace bootstrap, import/review workflows, rule management, account/register queries, and the `ledger` / `hledger` CLI integration used for health and financial queries.
- `workspace/` is the durable user workspace. It stores configuration, journals, rules, opening-balance files, and import artifacts.
- `.workflow/` is app-only operational state. It stores the active workspace pointer, resumable staged workflow payloads, and the SQLite import index used for idempotent import and undo.

## Canonical vs Operational Data

Primary workspace truth lives in:

- `workspace/settings/workspace.toml` for workspace config and account wiring
- `workspace/journals/*.journal` for financial history
- `workspace/rules/*` for account, tag, rule, and payee-alias data
- `workspace/opening/*` for opening-balance records

Supporting workspace artifacts also live under `workspace/`, including archived imports in `workspace/imports/*`.

Operational state lives in:

- `.workflow/app_state.json` for the active workspace selection
- `.workflow/stages/*.json` for resumable staged flows such as unknown-review work
- `.workflow/state.db` for import identity memory, provenance, and undo support

If operational state is lost or stale, rebuild it from the workspace. The workspace wins any disagreement.

## Frontend Surface

The frontend is a sectioned finance workspace. The current shell groups routes into daily use, workflows, automation, and workspace administration.

- `/setup`: staged first-run flow for creating or selecting a workspace, adding the first account, running the first import, and handing off to review or overview
- `/`: finance-first overview dashboard with net worth, balances, cash flow, recent activity, and action cues
- `/accounts`: tracked account inventory, balance coverage, and opening-balance visibility
- `/accounts/configure`: add and edit tracked/import accounts
- `/transactions`: per-account register view and running balances
- `/import`: statement inbox plus preview/apply import workflow
- `/unknowns`: uncategorized transaction review with staged apply
- `/rules`: rule authoring, reordering, and automation management

The setup and import flows share the same import interaction model. Import and review are important supporting loops, but the product identity remains the dashboard and account-centric finance workspace.

## Backend Responsibilities

The backend is the source of workflow and accounting logic.

- Workspace/bootstrap: select or initialize a workspace, create required directories/files, keep journal include directives and commodity files in place, and derive setup readiness state
- Account foundation: manage tracked accounts, import accounts, opening balances, account subtypes, and register/dashboard balance queries
- Import pipeline: discover candidate CSVs, inspect custom profiles, upload statements, preview/apply imports, archive processed files, track import history, and support undo
- Review and automation: scan unknowns, stage mappings, create accounts during review, manage payee aliases, perform rule CRUD/reorder, and reapply rules to historical transactions
- Query/reporting: serve dashboard overview data and per-account transaction register data through explicit API endpoints

The frontend should remain thin. File mutation, import identity, matching logic, and journal semantics live in backend services rather than route components.

## Import Pipeline and Identity Model

The import system is designed to be idempotent, conflict-visible, and respectful of existing journal text.

1. CSV candidates are discovered from the configured inbox directory in the workspace.
2. An import account or custom CSV profile determines how the CSV is normalized into intermediate transactions.
3. The backend renders journal transaction blocks and computes two hashes:
   - `source_identity`: SHA-256 of institution, transaction date, normalized payee text, and the institution-side posting amount
   - `source_payload_hash`: SHA-256 of the normalized transaction body, with the institution posting canonicalized to `__IMPORT_ACCOUNT__`
4. New transactions receive metadata comments:
   - `source_identity`
   - `source_payload_hash`
   - `source_file_sha256`
   - `importer_version`
5. The backend checks journal metadata plus `.workflow/state.db` to classify each transaction as:
   - `new`: unseen and eligible to add
   - `duplicate`: same identity and matching or unknown payload hash, so it is skipped
   - `conflict`: same identity with a different payload hash, so it is skipped and surfaced
6. Apply only adds new transaction blocks and records provenance. Existing transaction content is not rewritten or normalized after the fact.
7. New blocks are merged into the target journal in date order while leaving existing transaction text authoritative and unchanged.
8. Processed CSVs are archived under `workspace/imports/processed/...`, and the import index preserves provenance for history and undo.

## Workflow Relationships

- Setup is the bootstrap path from zero files to first useful financial activity.
- Accounts make the balance-sheet inventory durable outside setup.
- Import brings in new statement activity.
- Unknown review resolves uncategorized transactions created by imports.
- Rules and payee aliases turn repeated review decisions into reusable automation.
- Dashboard and transactions views turn current books into daily visibility.

This relationship matters: setup, import, review, and rules support the finance workspace, but they should not eclipse it.

## Architectural Invariants

- Primary UI language stays finance-first. Technical accounting terms belong in advanced surfaces or documentation, not default UI copy.
- `workspace/` remains canonical. `.workflow/` remains disposable operational memory.
- Preview must precede apply for import flows, and staged review data must remain resumable.
- Import behavior must stay idempotent and conflict-visible. Existing journal text is never silently rewritten.
- Frontend and backend share API contracts. If a payload changes, update backend models/handlers, frontend callers/types, and tests together.
