# Current Task

## Title

Manual transaction entry with import matching

## Objective

Users can add transactions manually on any tracked account to keep an up-to-date picture of their finances. When a CSV is later imported, the unknowns review offers to match imported transactions to existing manual entries — replacing the manual entry with the imported version while preserving the user's categorization and metadata.

## Scope

### Included

- Backend endpoint to create a new transaction on any tracked account, written to the journal with a `:manual:` tag and inserted in date order.
- UI entry point to add a transaction from the account register page.
- Backend detection of manual-entry match candidates during `scan_unknowns`, returned alongside existing transfer suggestions.
- Third toggle mode **{categorize, transfer, match}** on the unknowns review page.
- Match mode shows a combobox of ranked candidates, with the best pre-selected when the system finds a strong match.
- Match confirmation UI that surfaces amount deltas explicitly when the imported and manual amounts differ.
- Apply logic that replaces the manual entry with the imported transaction's posting, carrying over the destination account, `:manual:` tag, and any user metadata from the manual entry.
- Regression tests for creation, matching, replacement, and edge cases.

### Explicitly Excluded

- Transaction editing (Feature 2 — separate task).
- Configurable match window (deferred settings interface).
- Split transactions in the manual entry form (simple two-posting entries only; split editing is Feature 2).
- Automated/unconfirmed matching — user must always confirm via the review page.

## System Behavior

### 1. Creating a Manual Transaction

**Inputs**

- User action: clicks "Add transaction" on an account register page.
- Form fields, in tab order:
  1. **Date** — text input, defaults to today, accepts `YYYY-MM-DD` or common shorthands. Focused on open.
  2. **Payee** — text input with typeahead from existing payees in the journal.
  3. **Amount** — numeric input. Plain number; currency symbol is added automatically based on the account's commodity.
  4. **Destination account** — `AccountCombobox` (the same component used in the unknowns review). Filters as the user types, navigable with arrow keys, selects with Enter/Tab. `--strict`-style warning shown inline when the typed value doesn't match a known account (warn, not block).
- The entire form must be completable without the mouse. Tab advances between fields; Enter on the last field (or a submit shortcut) saves. Escape cancels and closes the form.
- Autofocus lands on the date field. If the user's most common flow is "today, type payee, type amount, pick category, Enter" — that path should require zero clicks after opening the form.

**Logic**

- Build a two-posting transaction block:
  ```
  2026/03/28 Uber
      ; :manual:
      Expenses:Transportation:Rides    $45.95
      Assets:Wells:Fargo:Checking
  ```
- The tracked account's `ledger_account` is the balancing posting (amount inferred by ledger).
- The `:manual:` tag is a standard ledger tag on the transaction header, not a KV pair.
- Insert into the journal in date order using the existing `_merge_transaction_blocks` pattern from `import_service.py`.
- Validate destination account against `accounts.dat`. Warn (do not block) on unknown accounts, matching the `--strict` principle.

**Outputs**

- Transaction appears immediately in the account register as normal posted activity.
- No import metadata is written (no `source_identity`, `import_account_id`, etc.) — the entry is purely manual.

### 2. Detecting Match Candidates During Unknowns Scan

**Inputs**

- `scan_unknowns` is called after a CSV import introduces new `Expenses:Unknown` transactions.

**Logic**

- New function `_populate_match_candidates(transaction_records, journal_transactions)`:
  - For each unknown transaction on an import-enabled tracked account, scan the journal for `:manual:`-tagged transactions on the **same** tracked account.
  - A manual entry is a candidate if its date is within ±`MAX_MANUAL_MATCH_DAYS` (3) of the imported transaction's date.
  - Rank candidates by match quality (highest to lowest):
    1. **Date + exact amount**: same absolute amount, dates within window.
    2. **Date + close amount**: dates within window, amounts differ.
    3. **Date + payee substring**: date within window, imported payee contains manual payee (case-insensitive) or vice versa.
    4. **Payee substring only**: payee match exists but dates are outside the window (show as low-confidence candidates).
  - Within each tier, sort by date proximity (closest first).
  - Each candidate record includes: manual transaction's date, payee, amount, destination account, line range, and the computed match quality tier.
- Attach `matchCandidates: [...]` to each unknown row that has at least one candidate.
- Pre-select: if exactly one candidate is tier 1 (date + exact amount), mark it as `suggestedMatchId`.

**Outputs**

- Unknown rows gain `matchCandidates` array and optional `suggestedMatchId`.
- Existing transfer suggestion and category suggestion logic is unchanged.

### 3. Match Mode in Unknowns Review UI

**Inputs**

- User toggles to "Match" in the three-way toggle on an unknown row that has `matchCandidates`.

**Logic**

- The toggle becomes `{categorize, transfer, match}`. The "Match" button is only enabled when `matchCandidates` is non-empty.
- Match mode renders a combobox of candidates. Each option shows: date, payee, amount, and match quality indicator.
- If `suggestedMatchId` exists, that candidate is pre-selected.
- When the selected candidate's amount differs from the imported amount, a helper line shows: `"Manual entry: $45.95 · Import: $47.95 · Difference: $2.00"`. This is a trust moment — the user must see the delta before confirming.
- The imported amount is canonical (bank wins). The manual entry's destination account carries over.

**Outputs**

- `GroupSelection` gains `selectionType: 'match'` with `matchedManualTxnId` and `matchedManualLineRange`.

### 4. Applying a Match

**Inputs**

- User clicks Apply with one or more groups set to `selectionType: 'match'`.

**Logic**

- For each match selection:
  1. Read the manual entry's destination account and user metadata (tags, KV pairs, freeform comments — everything except system metadata like `source_identity`, `transfer_id`, etc.).
  2. Replace the unknown posting's `Expenses:Unknown` account with the manual entry's destination account.
  3. Add the `:manual:` tag to the imported transaction as provenance.
  4. Copy user metadata from the manual entry to the imported transaction.
  5. Remove the manual entry from the journal.
- Operations are ordered: replacements before removals to maintain line stability.
- If the manual entry has already been removed (race condition or stale scan), fail closed with a warning — do not apply a partial match.

**Outputs**

- The imported transaction is now categorized with the manual entry's destination.
- The manual entry is gone from the journal.
- The imported transaction carries the `:manual:` tag and any user metadata from the original manual entry.

## System Invariants

- A manual entry is a standard ledger transaction. It must be valid ledger syntax with a `:manual:` tag.
- The `:manual:` tag is provenance — it records that the entry originated from manual input, even after import matching.
- The imported amount is always canonical after matching. The manual amount is informational for match ranking only.
- Match confirmation is mandatory. The system must never auto-match without user review.
- Manual entries on non-import-enabled accounts are never match candidates. They are ordinary transactions.
- The zero-sum posting invariant holds for all created transactions.

## States

### Add Transaction Form
- **Default**: form visible with date pre-filled to today, other fields empty.
- **Validation error**: destination account unknown — show warning, allow save.
- **Submitting**: button disabled, spinner.
- **Success**: form clears, register refreshes, new transaction visible.
- **Error**: inline error message, form remains populated for retry.

### Match Mode in Unknowns Review
- **Default (candidates exist)**: "Match" button enabled in toggle. Combobox shows ranked candidates.
- **Default (no candidates)**: "Match" button disabled in toggle. Tooltip: "No manual entries found for this account."
- **Candidate selected, amounts match**: standard confirmation state.
- **Candidate selected, amounts differ**: delta helper displayed as trust cue.
- **Apply success**: row resolved, manual entry removed.
- **Apply error (stale manual entry)**: warning message, row remains unresolved.

## Edge Cases

- **Multiple manual entries match the same import**: all appear in the combobox, ranked by quality. User picks one. The others remain in the journal.
- **One manual entry matches multiple imports**: each import's combobox shows the manual entry as a candidate independently. If the user matches the first import, the manual entry is removed. Subsequent imports will show a stale-entry warning on apply. The scan should be re-triggered after each apply batch to reflect current state.
- **Manual entry with no destination (only tracked-account posting + unknown)**: not a valid candidate — a matched manual entry must have a non-unknown destination to carry over.
- **Manual entry on a non-import-enabled account**: never a candidate. It is a regular transaction.
- **Amount is zero**: valid for both manual entry and matching (e.g., refund that nets to zero). No special treatment.
- **Payee is empty**: valid. Payee match tier does not apply; date + amount still works.

## Failure Behavior

- If transaction creation fails (file write error, invalid journal syntax), the endpoint returns an error and the journal is unchanged.
- If match apply encounters a removed manual entry, that group fails with a warning. Other groups in the same batch proceed.
- If the journal cannot be parsed during `scan_unknowns`, match candidates are empty (fail open to no candidates, not fail open to bad matches).

## Regression Risks

- Manual entry creation must not interfere with import duplicate detection. Manual entries have no `source_identity` — the importer must not treat them as duplicates of imported transactions.
- The `:manual:` tag must not break any existing journal parsing (posting detection, metadata extraction, amount inference).
- Match apply must not corrupt transfer metadata on unrelated transactions. The removal of a manual entry must not shift line numbers for other queued operations.
- The three-way toggle must not break existing category and transfer selection state or autosave behavior.
- Existing transfer suggestion logic must be unaffected — match candidates are a parallel detection path, not a replacement.

## Acceptance Criteria

- User can add a transaction from the WF Checking register page with date, payee, amount, and destination account. The transaction appears in the register immediately.
- The created transaction has the `:manual:` tag in the journal and valid ledger syntax.
- After importing a CSV that contains a transaction matching the manual entry (same account, ±3 days, same amount), the unknowns review shows the "Match" toggle enabled for that row.
- The match combobox shows the manual entry as a candidate with a "date + exact amount" quality indicator, pre-selected.
- When the user confirms the match and applies, the manual entry is removed from the journal and the imported transaction is categorized with the manual entry's destination account and carries the `:manual:` tag.
- When amounts differ ($45.95 manual vs $47.95 import), the delta is displayed before confirmation. After apply, the imported amount ($47.95) is in the journal.
- A manual entry on a non-import-enabled account never appears as a match candidate.
- After matching, the `:manual:` tag is present on the imported transaction in the journal.
- Existing category and transfer flows on the unknowns page continue to work identically.
- All existing tests pass.

## Proposed Sequence

1. **Define constants and helpers**: add `MAX_MANUAL_MATCH_DAYS = 3` to `transfer_service.py` (or a new `manual_entry_service.py` if cleaner). Add a helper to detect the `:manual:` tag on a parsed transaction.
2. **Backend: create transaction endpoint** — `POST /api/transactions/create` accepting `{ journalPath, trackedAccountId, date, payee, amount, destinationAccount }`. Builds a two-posting transaction block with `:manual:` tag, inserts in date order using `_merge_transaction_blocks`, validates destination against `accounts.dat`. Returns the created transaction.
3. **Frontend: add transaction form** — button on account register page opens a form. Date defaults to today. Destination uses `AccountCombobox` with unknown-value warning. On submit, calls the create endpoint and refreshes the register.
4. **Backend: match candidate detection** — add `_populate_match_candidates()` in `unknowns_service.py`. During `scan_unknowns`, for each unknown row on an import-enabled account, find `:manual:` entries on the same account within ±3 days, rank by quality tier, attach as `matchCandidates` with optional `suggestedMatchId`.
5. **Frontend: match toggle and combobox** — extend `GroupSelection` with `selectionType: 'match'`. Add third toggle button (disabled when no candidates). Render combobox with candidates and amount-delta helper.
6. **Backend: apply match** — extend `apply_unknown_mappings` to handle `selectionType: 'match'`: replace the unknown posting with the manual entry's destination, add `:manual:` tag and user metadata to the imported transaction, remove the manual entry from the journal.
7. **Tests** — creation (valid syntax, date ordering, `:manual:` tag present), matching (exact match pre-selected, close-amount ranked, no candidates on non-import account), apply (replacement + removal, stale-entry warning, metadata carryover), regression (existing category/transfer flows unaffected, import duplicate detection ignores manual entries).

## Definition of Done

- Users can create manual transactions from the register page on any tracked account.
- The unknowns review page offers a "Match" mode when manual-entry candidates exist.
- After matching, the manual entry is replaced by the import with correct categorization and `:manual:` provenance.
- Amount deltas are surfaced before confirmation.
- All existing tests pass. New tests cover creation, matching, apply, and edge cases.
- Import duplicate detection is unaffected by manual entries.

## Out of Scope

- Transaction editing, split management, and metadata editing (Feature 2).
- Keyboard shortcut to open the add-transaction form (needs a broader keyboard shortcut plan first).
- Configurable match window (deferred settings interface).
- Automated matching without user confirmation.
- Automated transactions (ledger's `=` syntax).

## Replacement Rule

Replace this file when the next active engineering task begins.
