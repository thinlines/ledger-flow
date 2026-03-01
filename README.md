# Ledger Flow

Ledger Flow is a GUI-first bookkeeping system backed by open, plain-text financial records.

## Core Principles

1. GUI-first interaction
- Users manage setup, import, reconciliation, and review through the app UI.
- CLI tooling is optional developer infrastructure, not a user requirement.

2. Open, plain-text source of truth
- Canonical financial data is stored in human-readable text files inside a workspace.
- The app is a control plane for that data, not a closed storage silo.

3. Zero-file bootstrapping
- A new install must work with no pre-existing ledger files or config.
- The app can initialize a workspace from scratch through Setup.

4. Safe import semantics
- Imports are idempotent and append-oriented.
- New transactions are appended; duplicates are skipped; conflicts are surfaced for review.
- Existing transaction content is not auto-rewritten.

5. Eventual consistency
- Financial history can be built incrementally.
- Choosing an initial year does not block importing older years later.
- Missing years can be backfilled over time without breaking workflow.

6. Separation of concerns
- Plain-text workspace files hold accounting truth.
- Operational indexes (e.g., SQLite/state files) exist for UX speed and workflow memory, and are non-canonical.

## Current Product Shape

- Setup: create/select workspace
- Import: preview and apply institution CSV imports
- Review: reconcile unknown account mappings

These workflows are designed to keep the canonical text data durable, portable, and user-owned.
