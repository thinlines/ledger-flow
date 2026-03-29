# Current Task

## Title

Transaction clearing status: parse, display, and toggle

## Objective

Users can see at a glance which transactions are bank-confirmed versus manually entered, and can toggle a transaction's clearing status directly from the register. The codebase gains a shared transaction-header parser, eliminating duplicated regex across six services.

## Scope

### Included

- Shared header-parsing module that extracts the clearing flag (`*`, `!`, or unmarked) alongside date and payee. Replaces the duplicated `HEADER_RE` in `journal_query_service.py`, `import_service.py`, `manual_entry_service.py`, `unknowns_service.py`, `rule_reapply_service.py`, and `opening_balance_service.py`.
- `ParsedTransaction` gains a `status` field (enum: `unmarked`, `pending`, `cleared`).
- Register API returns the clearing status for each entry.
- Register UI displays a visible status indicator per transaction row.
- Backend endpoint to toggle a transaction's clearing status by rewriting the header line in the journal.
- Frontend toggle control: clicking the status indicator cycles through states.

### Explicitly Excluded

- Changing what the import pipeline writes (`ledger convert` already outputs `*`; no change).
- Changing what manual entry writes (already outputs no flag; no change).
- Migrating existing journal data.
- Statement reconciliation (future sprint — will use metadata, not the clearing flag).
- Bulk status operations (select multiple → mark cleared).

## System Behavior

### 1. Shared Header Parser

**Inputs**

- A transaction header line (e.g., `2026/01/15 * UBER TRIP` or `2026/03/28 Coffee Shop`).

**Logic**

- New module `app/backend/services/header_parser.py` exports:
  - `HEADER_RE` — compiled regex with named groups: `date`, `status` (optional `*` or `!`), `code` (optional parenthesized code), `payee`.
  - `TransactionStatus` — string enum with values `unmarked`, `pending`, `cleared`.
  - `parse_header(line: str) -> ParsedHeader | None` — returns a dataclass with `date: str`, `status: TransactionStatus`, `code: str | None`, `payee: str`.
  - `set_header_status(line: str, new_status: TransactionStatus) -> str` — rewrites the header line with the new flag, preserving date, code, and payee.
- All six services import from `header_parser` instead of defining their own `HEADER_RE`.
- `TXN_START_RE` (used only for line-type detection, not parsing) may remain local or also be shared — implementer's judgment.

**Outputs**

- No user-visible change from this step alone. Foundation for steps 2–4.

### 2. ParsedTransaction Status Field

**Inputs**

- Journal lines parsed by `journal_query_service._parse_transaction`.

**Logic**

- `_parse_transaction` uses `parse_header` to extract the status.
- `ParsedTransaction` gains `status: TransactionStatus` (default `unmarked`).
- The status is derived from the header flag:
  - `*` → `cleared`
  - `!` → `pending`
  - no flag → `unmarked`

**Outputs**

- `ParsedTransaction` instances now carry their clearing status.

### 3. Register API: Surface Status

**Inputs**

- `account_register_service.build_account_register` builds register rows.

**Logic**

- `RegisterEvent` gains `clearing_status: str` (one of `unmarked`, `pending`, `cleared`).
- The status is read from the `ParsedTransaction` and passed through to the register row dict as `clearingStatus`.

**Outputs**

- Register API response includes `clearingStatus` on each entry.
- `ledger` CLI queries using `--cleared`, `--pending`, `--uncleared` produce results consistent with the flags in the journal. This is inherently true since we are reading and preserving the native ledger flags — no additional work required, but it is a system invariant to verify.

### 4. Register UI: Display Status

**Inputs**

- `RegisterEntry` in the frontend gains `clearingStatus: 'unmarked' | 'pending' | 'cleared'`.

**Logic**

- Each transaction row displays a status indicator. Placement: leading position in the row, before the date.
- Visual treatment:
  - `cleared` (`*`): solid filled indicator — this transaction is bank-confirmed.
  - `pending` (`!`): outlined or hollow indicator — flagged for attention.
  - `unmarked`: subtle dot or empty — manual entry, no bank confirmation.
- The indicator is a clickable toggle (see step 5).
- Hover tooltip explains the state in plain language:
  - `cleared`: "Bank-confirmed"
  - `pending`: "Flagged"
  - `unmarked`: "Manual entry"
- Do not use the words "cleared", "pending", or "unmarked" in the default UI. Use finance-first language per `AGENT_RULES.md`.

**Outputs**

- Users can see at a glance which transactions come from bank imports versus manual entry.

### 5. Toggle Clearing Status

**Inputs**

- User clicks the status indicator on a transaction row.

**Logic**

- Cycle order: `unmarked` → `pending` → `cleared` → `unmarked`.
- Frontend calls `POST /api/transactions/toggle-status` with the transaction's identifying information.
- Backend endpoint:
  1. Reads the journal file.
  2. Locates the transaction header line. The transaction is identified by date + payee + line content match (using the same approach as other journal-line-targeting operations in the codebase). The API payload must include enough context for unambiguous identification — at minimum the journal path and the exact header line text.
  3. Calls `set_header_status(header_line, next_status)` to produce the rewritten line.
  4. Writes the updated journal.
  5. Returns the new status.
- Frontend updates the indicator optimistically, rolls back on error.

**Outputs**

- The journal file reflects the new status flag.
- The register row updates immediately.
- `ledger` CLI queries reflect the change.

## System Invariants

- The clearing flag is a native ledger format feature. The app must never write a flag value that `ledger` or `hledger` would not recognize.
- The flag is positional: it appears between the date and the payee on the header line, separated by whitespace. No other position is valid.
- Toggling status must not alter any other part of the transaction: not the date, payee, code, metadata, postings, or whitespace in non-header lines.
- The shared header parser must produce identical parse results to the existing per-service regexes for all transaction headers currently in the journal. This is a migration safety invariant.
- Import pipeline output is not modified. `ledger convert` produces `*`; this is preserved as-is through `_annotated_raw_txn`.
- Manual entry output is not modified. `build_manual_transaction_block` produces no flag; this is preserved.

## States

### Status Indicator
- **Cleared**: solid indicator, tooltip "Bank-confirmed".
- **Pending**: outlined indicator, tooltip "Flagged".
- **Unmarked**: subtle/empty indicator, tooltip "Manual entry".

### Toggle Interaction
- **Default**: indicator shows current status, clickable.
- **Optimistic update**: indicator changes immediately on click.
- **Success**: server confirms, no further change.
- **Error**: indicator rolls back to previous state, brief inline error.

## Edge Cases

- **Transaction with parenthesized code**: `2026/01/15 * (1234) UBER`. The toggle must preserve the code. `set_header_status` handles this via regex groups.
- **Transaction with no payee**: `2026/01/15 *`. Valid ledger syntax. Toggle must handle empty payee without corruption.
- **Multiple transactions with identical headers on the same date**: the API must use exact line content (or line number) for disambiguation. If ambiguous, fail closed — do not toggle the wrong transaction.
- **Concurrent journal edit**: if the journal has changed between read and write (e.g., an import ran), the toggle should detect the mismatch and return an error rather than corrupting an unrelated line.

## Failure Behavior

- If the header line cannot be found in the journal (stale data), the toggle endpoint returns an error. The frontend shows a brief message and prompts a page refresh.
- If `set_header_status` produces invalid ledger syntax (should not happen with correct regex, but defensive), the endpoint must validate the output line against `HEADER_RE` before writing.
- If the journal file cannot be written (permissions, disk), the endpoint returns an error and the journal is unchanged.

## Regression Risks

- **Header parser migration**: replacing six independent regexes with one shared parser could surface edge cases where the regexes diverged. Verify that all existing tests pass after the migration.
- **Register payload change**: adding `clearingStatus` to the register API could break frontend code that destructures or iterates over entry keys. The field is additive (new key), so risk is low, but verify `pnpm check` passes.
- **Toggle line targeting**: rewriting a header line in the journal is a new mutation pattern. Ensure it does not shift line numbers for other operations (import, match-apply, manual entry) that may reference line positions.
- **Transfer state display**: the register already shows transfer states (pending, settled, bilateral). Clearing status is orthogonal — ensure the two indicators do not conflict visually or semantically. A transfer can be "pending" (transfer sense) and "cleared" (clearing sense) simultaneously.

## Acceptance Criteria

- Imported transactions (those with `*` in the journal) display as bank-confirmed in the register.
- Manual transactions (those with no flag) display as manual entries in the register.
- User can click a transaction's status indicator to cycle through unmarked → flagged → bank-confirmed → unmarked.
- After toggling, the journal file reflects the new flag and `ledger bal --cleared` / `--pending` / `--uncleared` produces matching results.
- The toggle preserves all other transaction content (date, code, payee, metadata, postings).
- All six services use the shared header parser. No service defines its own `HEADER_RE`.
- All existing tests pass (`uv run pytest -q` and `pnpm check`).
- Transfer state indicators continue to display correctly alongside clearing status.
- Hover tooltips use plain language, not accounting terminology.

## Proposed Sequence

1. **Shared header parser module** — create `header_parser.py` with `HEADER_RE`, `TransactionStatus` enum, `ParsedHeader` dataclass, `parse_header()`, and `set_header_status()`. Write unit tests for all header variations (with/without flag, with/without code, empty payee).
2. **Migrate consumers** — update all six services to import from `header_parser`. Remove their local `HEADER_RE` definitions. Run `uv run pytest -q` to verify no regressions.
3. **ParsedTransaction status** — add `status: TransactionStatus` to `ParsedTransaction`. Update `_parse_transaction` in `journal_query_service.py` to populate it from `parse_header()`.
4. **Register API** — add `clearing_status` to `RegisterEvent`, propagate to the register row dict as `clearingStatus`. Verify with a manual API call or test.
5. **Register UI: display** — add `clearingStatus` to `RegisterEntry` type. Render the status indicator in each row with appropriate visual treatment and tooltip.
6. **Toggle endpoint** — `POST /api/transactions/toggle-status`. Accepts journal path and header line text, locates the line, rewrites with `set_header_status`, returns new status.
7. **Toggle UI** — wire the status indicator click to the toggle endpoint. Implement optimistic update with rollback.
8. **Verification** — run `uv run pytest -q`, `pnpm check`, and manually verify register display and toggle behavior on both imported and manual transactions.

## Definition of Done

- Users can distinguish bank-confirmed from manually entered transactions at a glance in the register.
- Users can toggle a transaction's clearing status from the register.
- The journal reflects toggles correctly and `ledger` CLI queries match.
- Six duplicated header regexes are consolidated into one shared module.
- All existing tests pass. Transfer state display is unaffected.
- No accounting terminology in default UI copy.

## UX Notes

- The status indicator should be visually lightweight — it's informational, not a call to action. It should not compete with the payee, amount, or transfer state for attention.
- The click target should be generous (at least the size of the indicator plus padding) for comfortable toggling.
- The tooltip is the primary explanation mechanism. The indicator itself is a learned affordance — keep it simple and consistent.
- Consider the mobile/narrow viewport: the indicator should not be hidden or truncated. It may collapse to just the icon without tooltip on small screens.

## Out of Scope

- Statement reconciliation (future sprint — will use metadata like `; reconciled: YYYY-MM-DD`, not the clearing flag).
- Bulk status operations.
- Import pipeline changes.
- Manual entry pipeline changes.
- Configurable status cycle order.
- Status-based filtering or grouping in the register (valid future enhancement, not this task).

## Replacement Rule

Replace this file when the next active engineering task begins.
