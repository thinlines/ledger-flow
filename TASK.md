# Current Task

## Objective

Make tracked-account balances trustworthy when opening balances offset other tracked accounts. The workspace's start-year journal must load generated opening-balance data, and dashboard/register balances must be derived from the same effective journal a user can query manually.

## Current Failure

- On March 22, 2026, opening-balance files are generated under `workspace/opening/*.journal`, but the start-year journal does not include them.
- Dashboard and register balance code derives some balance state from `workspace/opening` directly instead of from the main journal load path.
- When one tracked account's opening balance offsets another tracked account, the offset account balance shown in the UI can be wrong or incomplete.
- A user running `ledger -f workspace/journals/2026.journal` can miss generated opening-balance data that the product wrote elsewhere.

## System Invariants

- The start-year journal is the manual-query entry point for workspace books and includes generated opening-balance data.
- Generated opening-balance data is never allowed to exist without being reachable from the journal graph the app queries.
- Dashboard tracked balances and per-account register balances are derived from the effective loaded journal data, not from a parallel balance-only path.
- Opening-balance transactions affect balances but do not inflate imported-activity metrics such as recent activity, transaction counts, spending, or income.
- Offsetting one tracked account against another updates both accounts' balances from the same journal transaction.

## Scope Cut Line

### Must Have

- Ensure the start-year journal automatically includes generated opening-balance journal data for existing and new workspaces.
- Keep the opening-balance include wiring in sync as opening-balance files are created, updated, renamed, or removed.
- Update backend journal loading so balance queries follow journal includes instead of ignoring them.
- Derive dashboard balances and register balances from the loaded journal transactions so tracked-account offsets are reflected on both sides.
- Preserve opening-balance metadata in account configuration UI while preventing opening-balance rows from being double-counted as normal activity.

### Should Have

- Repair older workspaces automatically when the app loads them so users do not need to hand-edit include lines.
- Cover the tracked-to-tracked offset case with end-to-end tests at the service level.

### Later

- Broader support for arbitrary user-authored include graphs beyond the current workspace conventions
- Reworking opening-balance editing so manually authored journal entries round-trip through the account configuration UI

## Acceptance Criteria

- Given a tracked liability account with an opening balance offset to a tracked asset account, when the workspace overview loads, then both tracked account balances reflect the same generated opening transaction and net worth remains correct.
- Given a workspace with only generated opening balances and no imported activity, when overview and register data are queried, then balances are present while imported-activity metrics remain zero and recent-activity lists stay empty.
- Given a tracked account whose opening balance is offset by another tracked account, when that offset account's register is queried, then the balance impact is present even though the account has no imported transactions.
- Given an existing workspace created before this fix, when the app loads the workspace, then the start-year journal is rewritten to include the generated opening-balance index without duplicate include lines.
- Given a user runs `ledger -f workspace/journals/2026.journal` after the fix, then generated opening-balance data is reachable from that journal file.

## Regression Risks

- Including opening-balance files in more than one yearly journal would double-count balances across multi-year loads.
- Opening-balance transactions could pollute spending, income, recent activity, or transaction counts if they are not filtered from non-balance metrics.
- Register views could show duplicate opening rows if old special-case opening-balance injection remains in place after journal-include loading is added.

## Proposed Sequence

1. Add durable opening-balance include wiring for the start-year journal and auto-repair it for existing workspaces.
2. Expand backend journal loading to follow workspace include directives.
3. Rework dashboard and register balance derivation to use loaded journal transactions as the single source of truth.
4. Tighten metadata and UI trust states for accounts whose balances come from opening-balance journal entries without imported activity.
5. Verify the tracked-offset, opening-only, and existing-workspace repair cases with targeted tests.

## Out of Scope

- Replacing the yearly journal layout
- Rewriting the import pipeline
- Broad ledger CLI feature work beyond making the generated opening balances reachable from the main journal entry point

## Replacement Rule

Replace this file when the next active engineering task begins.
