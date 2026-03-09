# Ledger Flow

Ledger Flow is a GUI-first bookkeeping app designed to feel like a polished, professional personal finance workspace.
Its open plain-text foundation matters for durability and portability, but that implementation detail should stay behind the curtain unless the user wants to engage with it.

## Core Principles

1. User-facing product first
- Primary UI language should talk about money, accounts, spending, activity, and next steps.
- Terms like ledger, journal, postings, workspace files, or rule stores belong in advanced views, diagnostics, or documentation.

2. GUI-first interaction
- Users manage setup, import, categorization, and review through the app UI.
- CLI tooling is optional developer infrastructure, not a user requirement.

3. Plain-text as an open foundation, not a required mental model
- Canonical financial data is stored in human-readable text files inside a workspace.
- The app is a control plane for that data, not a closed storage silo.
- Most users should never need to think about file layout or plaintext accounting in routine workflows.

4. Polished, efficient workflow design
- The app should feel approachable to non-specialists without becoming shallow.
- Common tasks should be obvious, safe, and fast, with technical detail available only when needed.

5. Zero-file bootstrapping
- A new install must work with no pre-existing ledger files or config.
- The app can initialize a workspace from scratch through Setup.

6. Safe import semantics
- Imports are idempotent and append-oriented.
- New transactions are appended; duplicates are skipped; conflicts are surfaced for review.
- Existing transaction content is not auto-rewritten.

7. Eventual consistency
- Financial history can be built incrementally.
- Choosing an initial year does not block importing older years later.
- Missing years can be backfilled over time without breaking workflow.

8. Separation of concerns
- Plain-text workspace files hold accounting truth.
- Operational indexes (e.g., SQLite/state files) exist for UX speed and workflow memory, and are non-canonical.

## Current Product Shape

- Setup: staged first-run flow for create/select workspace, add tracked accounts, and complete the first import
- Import: shared preview/apply account-linked CSV workflow, available both inside setup and on `/import`
- Review: reconcile unknown account mappings
- Account setup: add or edit import accounts after workspace bootstrap

These workflows are the current foundation, not the full product identity.
The app should ultimately feel like a daily finance workspace where import and review are supporting workflows that keep the user's financial picture current.
