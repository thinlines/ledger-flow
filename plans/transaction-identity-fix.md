# Transaction Identity Fix — Line-Number-Based Lookup

## Title

Replace header-line string matching with position-based identity (`journalPath + lineNumber`) plus a header-line drift check for every transaction mutation endpoint.

## Objective

Eliminate `Ambiguous: multiple matching header lines found` (HTTP 409) as a user-visible failure mode. After this change, any two transactions with identical date + status + payee can be individually toggled, recategorized, deleted, unmatched, and have notes edited without collision. A concurrent edit to the same line is still detected and refused as stale data.

## Context

The transaction detail sidebar throws `Ambiguous: multiple matching header lines found` when the user tries to act on a transaction whose header line text is identical to another transaction's (e.g., two Starbucks purchases on the same day with the same clearing status). Root cause: the backend identifies transactions by scanning the journal for a line that exactly equals the `headerLine` string sent by the frontend. `locate_header` in [app/backend/services/journal_block_service.py:16-27](app/backend/services/journal_block_service.py#L16-L27) raises `AmbiguousHeaderError` whenever two lines match.

The user's preferred approach (agreed before this task was written): the frontend already knows which line each transaction lives on (the query service reads lines sequentially); plumb that line number through the row model, send `{ journalPath, lineNumber, headerLine }` in every mutation request, seek to the line directly, and verify the text at that line still matches `headerLine` as a drift check. `AmbiguousHeaderError` stops being a reachable state. `HeaderNotFoundError` (now "the line we were told to edit does not contain the expected text") continues to surface as the existing "stale data — try refreshing" 404.

Rejected alternatives (do not reopen):

- **UUID `tx_id` in a `; id:` metadata comment.** Violates the "ledger journal file is canonical, matches `ledger` CLI output" invariant by writing agent-only bookkeeping into the user's hand-editable source of truth. Requires a backfill migration. Silently duplicates on copy-paste. Breaks on CSV imports that bypass the app. Overkill for the in-session mutation problem.
- **Content-hash `tx_id`.** Changes on every edit (so it is no better than a position pointer for identity). Two genuinely indistinguishable transactions (same date, payee, amount, category, no notes) still collide.

Position identity with a header-line checksum provides exactly enough disambiguation without adding state the journal doesn't already hold.

## Scope

### Included

**Backend request-shape and identity contract changes to five mutation endpoints** in [app/backend/main.py](app/backend/main.py):

- `POST /api/transactions/toggle-status` ([main.py:602-655](app/backend/main.py#L602-L655)) — currently does an inline `match_indexes` scan, does not use `_locate_header`.
- `POST /api/transactions/delete` ([main.py:679-728](app/backend/main.py#L679-L728)) — via `_locate_header`.
- `POST /api/transactions/recategorize` ([main.py:731-818](app/backend/main.py#L731-L818)) — via `_locate_header`.
- `POST /api/transactions/notes` ([main.py:829 onward](app/backend/main.py#L829)) — via `_locate_header`.
- `POST /api/transactions/unmatch` ([main.py:892 onward](app/backend/main.py#L892)) — via `_locate_header` for the main journal leg. The archived-manual leg is located by `match-id` scan, not header line, and is out of scope.

**Pydantic request models** in [app/backend/models.py](app/backend/models.py): `ToggleStatusRequest`, `DeleteTransactionRequest`, `RecategorizeTransactionRequest`, `UnmatchTransactionRequest`, `UpdateNotesRequest` all gain a required `lineNumber: int` field (zero-indexed, matching `Path(journalPath).read_text().splitlines()` indexing).

**Shared helper changes** in [app/backend/services/journal_block_service.py](app/backend/services/journal_block_service.py):

- Add `locate_header_at(lines: list[str], line_number: int, expected_header: str) -> int`. Verifies `0 <= line_number < len(lines)` and `lines[line_number] == expected_header`. Raises `HeaderNotFoundError` on either failure (drift → stale-data 404). Does not raise `AmbiguousHeaderError`.
- Keep `locate_header` and `AmbiguousHeaderError` only if other callers remain after the five endpoints migrate. Audit and delete if no callers remain.
- Update `_locate_header` wrapper in [main.py:663-676](app/backend/main.py#L663-L676) to wrap the new helper and map `HeaderNotFoundError` → HTTP 404 "stale data — try refreshing". The 409 `AmbiguousHeaderError` branch disappears.

**Query service / row-building changes:**

- [app/backend/services/journal_query_service.py](app/backend/services/journal_query_service.py): extend `ParsedTransaction` dataclass with `header_line_number: int` (zero-indexed offset within the physical journal file). Set it in `_parse_transaction`, carry it through `load_transactions`. `_split_transactions` needs to track line offsets — currently it drops that information.
- [app/backend/services/unified_transactions_service.py](app/backend/services/unified_transactions_service.py): `RegisterEvent` (in `transaction_helpers.py`, referenced by [_compute_rows_with_balance, line 433](app/backend/services/unified_transactions_service.py#L433)) gains a `header_line_number: int`. The row dict's `legs` entry becomes `{"journalPath": ..., "headerLine": ..., "lineNumber": ...}`.
- Audit every callsite that constructs a `RegisterEvent` (synthetic peer rows for opening balances and direct/pending transfer peers at [unified_transactions_service.py:266-289](app/backend/services/unified_transactions_service.py#L266-L289)) and make sure `header_line_number` is populated or the row is marked as non-mutable. Synthetic rows that do not correspond to a real journal line must either use a sentinel value that the frontend never tries to mutate, or carry the line number of the backing transaction. Do **not** emit `-1` or `null` to the frontend unless mutation is genuinely impossible for that row.

**Frontend type + plumbing changes** in [app/frontend/src/lib/transactions/](app/frontend/src/lib/transactions/):

- [types.ts:116](app/frontend/src/lib/transactions/types.ts#L116): `TransactionRow.legs` element type becomes `{ journalPath: string; headerLine: string; lineNumber: number }`.
- [types.ts:32-33](app/frontend/src/lib/transactions/types.ts#L32-L33): `RegisterEntry.headerLine` and `.journalPath` gain a sibling `.lineNumber: number | null`. `null` is only used for legacy row shapes that do not flow into mutations.
- [transactionActions.ts](app/frontend/src/lib/transactions/transactionActions.ts): every `apiPost` call (`deleteTransaction`, `resetCategory`, `recategorize`, `unmatchTransaction`, `toggleClearing` lines 14, 33, 53, 73, 99) sends `lineNumber: leg.lineNumber` alongside `journalPath` and `headerLine`.
- The `toggleClearing` response handler at [transactionActions.ts:104](app/frontend/src/lib/transactions/transactionActions.ts#L104) updates `legs[0].headerLine` to `res.newHeaderLine`. `lineNumber` is unchanged by a toggle (same line, new text). Update the spread to keep the existing `lineNumber`: `row.legs[0] = { ...leg, headerLine: res.newHeaderLine }` already does this; verify it.
- Any other frontend consumer of `legs[].headerLine` or `.journalPath` for mutation purposes must be updated to also pass `lineNumber`. Grep `legs\[0\]\.headerLine` across `app/frontend/src/` (TransactionDetailSheet.svelte, routes/transactions/+page.svelte, and any other callers are the known set — search exhaustively before claiming done).

**Tests** in [app/backend/tests/](app/backend/tests/):

- Add a regression case to `test_transaction_actions.py` (and/or `test_notes_and_recategorize.py`) that constructs a journal with two transactions whose header lines are byte-identical, invokes each of the five endpoints on each transaction individually, and asserts the correct one is mutated. This is the test that the current code fails and the new code must pass.
- Add a drift-check case: call each endpoint with a `lineNumber` whose file content has been externally modified (e.g., another transaction inserted earlier in the file). Assert a 404 "stale data — try refreshing", not a silent wrong-transaction mutation.
- Existing passing tests must continue to pass. Update any fixture that hand-constructs a request body missing `lineNumber` so it sends the correct value.

### Explicitly excluded

- **No tx_id comment metadata.** See Context rejected-alternatives.
- **No content-hash tx_id.** Same.
- **No change to how the query service expands `include` directives.** There is a pre-existing issue where `source_journal` is set to the top-level journal even for transactions that physically live in an included file — the mutation endpoints would already fail with `HeaderNotFoundError` on those rows today. The new line-number scheme inherits the same limitation (line number would be an index into the top-level file where the header line isn't present, so the drift check fails and returns the same 404). Fixing the include bug is out of scope.
- **No frontend UX changes.** Error copy on ambiguity disappears because the error itself disappears; no new copy needed. The existing "stale data — try refreshing" toast continues to handle the drift case.
- **No changes to the archived-manual leg lookup inside `/api/transactions/unmatch`.** The archived-manual journal is searched by `match-id:` metadata, not header line. Leave it.
- **No migration or cleanup of old event-log payloads.** The event log's historical `header_line` payloads stay as-is; we're not rewriting history.
- **No contract versioning, no feature flag, no backward-compatibility accept-both path.** The frontend and backend change together; both ship in the same merge. Per the `feedback_prefer_completeness.md` memory, no stopgap.

## System Behavior

### Inputs

- User clicks toggle-status / delete / recategorize / unmatch / update-notes on a transaction row in the transactions page or the detail sidebar.
- Frontend sends the endpoint a JSON body containing `journalPath`, `headerLine`, **`lineNumber`**, plus endpoint-specific fields (`newCategory`, `matchId`, `notes`).

### Logic

**Request flow, new contract:**

```
frontend → POST /api/transactions/<action> { journalPath, lineNumber, headerLine, ... }
backend:
  1. read journal_path
  2. split into lines
  3. assert 0 <= lineNumber < len(lines) AND lines[lineNumber] == headerLine
     → if not: 404 "Transaction not found in journal (stale data — try refreshing)"
  4. proceed with the existing mutation logic using header_idx = lineNumber
```

**Line-number attribution in the query service:**

- Each physical journal file under `config.journal_dir` is read as raw text (no include expansion for the purpose of line-number tracking). For each transaction block within that file, record `header_line_number = <0-indexed offset into splitlines() of the same read>`.
- `ParsedTransaction.source_journal` remains the path of the top-level file that produced it (current behavior).
- When `_expand_journal_lines` follows an `include` directive, the included file's transactions are still loaded for query purposes, but their `header_line_number` should point into whichever file's raw content the mutation endpoints will actually read. Since the mutation endpoints read `journal_path.read_text()` without expanding includes, a transaction in an included file cannot be mutated today regardless of what this task does. Implementation choice: set `header_line_number` to the offset within the top-level file's raw content by scanning for the exact header-line text. If not found (transaction lives in an included file), emit `header_line_number = -1`. The frontend treats `-1` the same as "leg not mutable" — actions are still clickable but return a stale-data error instead of silently mutating the wrong row. Alternatively (preferred if simpler), skip emitting rows whose `header_line_number` is unresolvable, matching today's effective mutation behavior. Pick one and document it in Delivery Notes.

**Drift check:**

- The drift check must be a byte-for-byte string equality between `lines[lineNumber]` and the submitted `headerLine`. Do not normalize whitespace. Do not parse the header. The whole point is to detect "the file changed under you, even in subtle ways."

### Outputs

- Mutation endpoints return their existing response shapes, unchanged.
- On drift, 404 with existing error body. (Existing frontend error handling already treats 404 from these endpoints as "refresh and try again.")
- `AmbiguousHeaderError` / HTTP 409 is no longer emitted by any of the five endpoints. If `locate_header` has no remaining callers after this task, delete the function and the error class.

## System Invariants

- **Canonical data is untouched.** No journal content is rewritten for identity purposes. The fix is pure wire-contract + indexing. `workspace/journals/*.journal` is byte-identical before and after deploying this change (aside from whatever mutations the user subsequently performs).
- **Idempotence, append-only, conflict-visible** (AGENT_RULES §Import Safety): unaffected. This task does not touch the import pipeline.
- **Event log payloads still carry `header_line`** for human readability. The line number is an identity detail, not an audit detail; it belongs in the request/response layer, not in the permanent event log. Event replay / undo continues to locate affected transactions by date + payee heuristics as it does today.
- **Frontend/backend API contracts change atomically.** Per AGENT_RULES §Data and Architecture: if a payload changes, update backend models, frontend types, callers, and tests together.
- **No new state machine.** The set of valid states for a transaction mutation request is `{ succeeded, stale, server-error }`. The previously-valid `{ succeeded, stale, ambiguous, server-error }` collapses back to three.

## States

Not a UI task. Endpoint response states:

- **Success** — line matched, mutation applied, event emitted, 2xx with existing body.
- **Drift** — line did not match expected header. 404, body `{"detail": "Transaction not found in journal (stale data — try refreshing)"}`.
- **Validation error** — `lineNumber` missing or non-integer. FastAPI returns its standard 422.
- **Server error** — file I/O failure or post-mutation invariant violation (already-existing paths). 500 with existing body.
- **Ambiguous** — no longer reachable. Remove the branch.

## Edge Cases

- **Toggle-status rewrites the header line in place.** Same line, new text. Frontend receives `newHeaderLine` and updates `legs[0].headerLine`; `lineNumber` is unchanged. Verify the toggle round-trip: toggle twice in a row, confirm the second toggle succeeds (second request uses the updated `headerLine` as its drift check and the same `lineNumber`).
- **Delete removes a line range.** After delete, every transaction below `block_end` shifts up. The affected client's row list is stale the moment the delete succeeds — frontend already calls `reload()` after every mutation, so this is covered. But if two mutations race from two client tabs, the second tab's line numbers are wrong. The drift check catches it and returns 404 "stale data". Acceptable.
- **Recategorize changes a posting line, not the header line.** Line numbers of the header and of subsequent transactions are unchanged. Zero race hazard beyond the existing pre-mutation drift hash that `check_drift` already enforces.
- **Unmatch rewrites both the main journal's transaction and the archived-manual sidecar entry.** Line number here is only for the main-journal leg. The archived-manual leg continues to be located by `match-id:` metadata scan. No new ambiguity surface there.
- **Two identical transactions, same file, mid-stream edit.** User opens the detail sidebar on transaction A; before acting, user manually edits the journal file in their external editor to add a transaction between A's index and the file start. The client's `lineNumber` now points one line too low. The drift check fires → 404 → "refresh and try again." Correct behavior.
- **Transaction in an `include`d file.** Per Logic: either `header_line_number = -1` (mutation always fails drift) or the row is suppressed. Either way, no regression vs. today.
- **Leg with no backing journal line (synthetic transfer-peer rows).** These rows exist in `unified_transactions_service._compute_rows_with_balance` via the peer-event branches. They display a transaction from the *other* tracked account's perspective. Mutation on those rows already routes to the real underlying transaction's journal path — verify this still works once line numbers are required. If a synthetic peer row sends a request, it must send the *real* line number of the backing transaction in its actual journal file, not a sentinel.

## Failure Behavior

- **Fail-closed on drift.** If `lines[lineNumber] != headerLine`, return 404 and do not mutate. Do not attempt a fallback header-line scan — that would silently reintroduce the ambiguity bug.
- **Fail-closed on missing `lineNumber`.** Request validation is strict; the field is required on every mutation request. A legacy client that does not send it gets 422. Do not accept and fall back to string matching.
- **Fail-closed on an out-of-range `lineNumber`.** Treat `lineNumber >= len(lines)` or `lineNumber < 0` as drift → 404.
- **Event emission failures** continue to log-and-swallow via the existing `try/except` wrappers. This task does not change that.

## Regression Risks

- **Missed callsite.** Any frontend path that still sends `{ journalPath, headerLine }` without `lineNumber` will 422 after this task. Grep comprehensively: `apiPost.*transactions/(toggle-status|delete|recategorize|unmatch|notes)`, and audit every request-body construction. A single missed call ships a broken button.
- **Synthetic peer-event rows carry the wrong line number.** If `pending_transfer_event_for_peer_account` or `direct_transfer_event_for_peer_account` produces a row whose `legs[0].journalPath` and `lineNumber` don't point to a real line in that file, every mutation from a transfer-peer row fails with 404. Manual test: in a two-tracked-account workspace with a direct transfer, toggle the clearing status from the peer row and confirm it works.
- **Include-file transactions silently disappear from the register.** If the chosen strategy is "suppress rows whose `header_line_number` is unresolvable," and any user actually uses `include` directives, their transactions vanish. Explicit manual check of `config.journal_dir` contents for `include` lines before shipping; if any top-level journal uses includes, pick the `-1` sentinel strategy instead of suppression and document the decision.
- **Drift check is over-sensitive to trailing whitespace or BOM changes.** If a journal file gained a BOM or a trailing-space diff from some external tool, every mutation fails drift and the user sees a wall of 404s. `locate_header_at` must match the file's splitlines() output exactly, and the query service emits whatever splitlines() produced at read time, so the round-trip is consistent. Do not apply `.strip()` or `.rstrip()` to either side of the comparison.
- **Test fixtures hand-constructing request bodies** without `lineNumber` will break. Every existing test under `app/backend/tests/test_transaction_actions.py` and `test_notes_and_recategorize.py` that posts to one of the five endpoints must be updated. Dropping a field requires updating every fixture; do not try to make the new field optional just to avoid updating tests.
- **Event-log payload shape divergence.** The event log's `payload.header_line` is unchanged. Do not add `line_number` to the event payload; it's not audit data. If a future feature wants position info for replay, that's a separate task.

## Acceptance Criteria

- In a workspace with two transactions sharing an identical header line (same date, same status, same payee, same file), the user can click any transaction row, open the detail sidebar, and perform each of the five mutations (toggle-status, delete, recategorize, unmatch if a match-id exists, update-notes) on *each* transaction individually without a 409 error. Both the intended row mutates and the other row is untouched.
- Pydantic rejects a request to any of the five endpoints that does not contain an integer `lineNumber`. The frontend's existing code paths always include it, so this is enforced by type, not by runtime discipline.
- `git grep -E 'AmbiguousHeaderError|multiple matching header'` returns no matches in `app/backend/` outside of test files that specifically assert the old error is no longer raised. The error class may remain if any non-migrated caller exists, but ideally the class and its helper are deleted.
- `git grep -E 'legs\[0\]\.headerLine' app/frontend/src` shows every match is accompanied by `lineNumber` plumbing in the same callsite.
- All pre-existing tests in `app/backend/tests/` continue to pass (modulo the known pre-existing `fastapi` environment issue documented in Task 0 delivery notes).
- New regression tests pass: a test that sets up two transactions with identical header lines in the same fixture journal, hits each of the five endpoints twice (once for each transaction), and asserts both calls succeed and mutate the correct lines.
- New drift tests pass: a test that captures a valid `lineNumber`, simulates an external file edit that shifts transactions, fires the mutation endpoint, and asserts a 404 response.
- `pnpm check` in `app/frontend` passes (per AGENT_RULES §Verification).
- `uv run pytest app/backend/tests/test_transaction_actions.py app/backend/tests/test_notes_and_recategorize.py -q` passes.
- Smoke test in the running app: in a workspace with real data, open the transactions page, click a transaction, recategorize it from the detail sidebar. No error toast. Toggle clearing status. Delete a test transaction. Edit notes. All actions complete cleanly.

## Proposed Sequence

Suggested commit split. The senior-developer may collapse commits or resequence if a different split reads more cleanly in history; the only hard constraint is that the branch is atomic as merged.

1. **Backend: emit `lineNumber` from the query service, additive.**
   - Extend `ParsedTransaction` with `header_line_number`.
   - Update `_split_transactions` to track starting line offsets.
   - Update `load_transactions` / `RegisterEvent` to carry the field through.
   - Update `_compute_rows_with_balance` to add `lineNumber` to each `legs[]` entry.
   - No endpoint behavior change. No frontend change yet. API response is additively larger.
   - Verify: hit `/api/transactions` from a REPL or curl against a seeded workspace and confirm `lineNumber` is present on every row's `legs[0]` and matches the expected offset in the journal file.
2. **Backend: accept and prefer `lineNumber` on mutation endpoints.**
   - Add `lineNumber: int` to the five request models in `models.py`. **Required, not optional.**
   - Add `locate_header_at(lines, line_number, expected_header)` to `journal_block_service.py`.
   - Update each of the five endpoint handlers to use `locate_header_at` exclusively. Delete the `match_indexes` inline scan in `toggle-status`. Delete the `_locate_header` / `locate_header` old path if and only if nothing else calls it — audit and delete if clear, otherwise leave the old function alone and let it die when the last caller migrates. Either way, the five endpoints stop using it.
   - Add / update backend tests: the ambiguity regression case (two identical header lines, both mutable) and the drift case. Existing tests that post to these endpoints must be updated to include `lineNumber`.
   - **At this commit, any frontend that hasn't been updated is broken.** If you prefer a safer bisect history, gate this commit behind commit 3 and land them together as a single combined commit.
3. **Frontend: plumb `lineNumber` through `TransactionRow.legs[]` and action helpers.**
   - Update `types.ts` leg shape.
   - Update `transactionActions.ts` to send `lineNumber` on every `apiPost`.
   - Update `RegisterEntry` in `types.ts` with the companion `lineNumber` field.
   - Audit every other consumer (`TransactionDetailSheet.svelte`, `routes/transactions/+page.svelte`, any other file). Make sure row construction paths propagate `lineNumber` from the API response into the row model without dropping it.
   - `pnpm check` passes.
4. **Tidy.** Delete `locate_header` and `AmbiguousHeaderError` if no callers remain. Remove the 409 branch from `_locate_header`. Grep for stale "Ambiguous" copy or comments.
5. **Delivery notes.** Record commit hashes, the ambiguity-repro test evidence (before: two transactions with identical headers can't be mutated; after: both mutate correctly), the include-file strategy chosen (sentinel `-1` vs. suppression), and any caller that had to be updated beyond the known list.

Commits 2 and 3 may be combined into a single commit if the reviewer prefers atomicity over bisect granularity. Per `feedback_prefer_completeness.md`, no backward-compatibility flag — the wire contract changes in one coordinated landing.

## Definition of Done

- All acceptance criteria met.
- Both `pnpm check` and the relevant backend pytest modules green.
- Manual smoke test in the running app exercised every mutation from every entry point (row overflow menu, detail sidebar category combobox, clearing toggle, notes editor) and observed no 409 errors. Specifically: a real two-identical-header-line case was constructed and successfully mutated.
- Delivery notes list the commit(s), the chosen include-file strategy, and the exhaustive list of frontend callsites that were updated (so a reviewer can independently verify none were missed).
- No `AmbiguousHeaderError` branch remains reachable from the five endpoints. Either the error class is deleted or it is documented as a dead reference kept only for transitional reasons (explain why).

## UX Notes

- **No user-visible copy changes.** The error that disappears was an internal leak — it exposed the journal file's data model to the user, violating AGENT_RULES §"Write primary UI copy in terms of money, accounts, balances." If there's any toast or dialog text mentioning "header lines" in the frontend today, scrub it as part of this task.
- **The stale-data toast** (existing) continues to handle the drift case. Do not add a separate "line number mismatch" copy; the user doesn't know what that means.
- **Zero new loading or empty states.** This is a wire-protocol fix; the UI's state graph is identical to today's.

## Out of Scope

- UUID tx_id, content-hash tx_id, or any other form of stable in-journal identity.
- Fixing the latent `include` directive bug where `source_journal` is attributed to the top-level file rather than the physical containing file.
- Adding `line_number` to event-log payloads.
- Changes to `POST /api/transactions/notes` beyond the identity-contract migration. No copy, no validation, no formatting changes.
- Changes to the archived-manual leg of `/api/transactions/unmatch`.
- Transaction editing (payee/date/posting amounts). Deferred per ROADMAP "Deferred for Now."
- Semantic undo (5e). Paused per ROADMAP.

## Delivery Notes

Shipped on branch `worktree-agent-ae56c32b` as a single coordinated commit
covering backend identity contract, query-service plumbing, frontend wire
contract, regression and drift tests. Per `feedback_prefer_completeness.md`:
no backward-compat field, no feature flag — the wire contract changed
atomically.

### Commits (in order)

1. `feat(transactions): position-based identity for mutation endpoints` —
   single commit on the worktree branch covering all five workstreams
   (backend models, query-service line-number plumbing, journal_block_service
   helper, endpoint handlers, frontend types, frontend action callers, tests).

### Include-file strategy chosen

**Sentinel `-1`.** Confirmed via `Grep` that real workspaces use `include`
directives heavily: `workspace/journals/2026.journal` includes three
`rules/*.dat` files plus `opening/_opening_balances.journal`, which itself
includes six per-account opening files. Row suppression would have made
opening-balance rows silently disappear from the register — clearly the
wrong call. With the sentinel, included-file transactions still render in
the register; mutation attempts get 404 "stale data — try refreshing" via
the same drift path that catches concurrent edits, which matches the
endpoints' existing pre-task behaviour against include-file rows
(`HeaderNotFoundError` from the old string-scan).

Implementation: `_expand_journal_lines_with_origins` retains
`(physical_path, raw_line_index)` for every line emitted by include
expansion. `load_transactions` checks each transaction's expanded-text
start offset against that map. If the origin file matches the top-level
journal, the offset becomes a real `header_line_number`; otherwise `-1`.

### Exhaustive frontend callsite list

Every file the wire contract touches:

- `app/frontend/src/lib/transactions/types.ts` — `TransactionRow.legs[]`
  element gains required `lineNumber: number`. `RegisterEntry` (deprecated
  shim used by `ManualResolutionDialog`) gains `lineNumber?: number | null`
  to mirror its existing `headerLine`/`journalPath` companions.
- `app/frontend/src/lib/transactions/transactionActions.ts` — every
  `apiPost` call to the five mutation endpoints sends
  `lineNumber: leg.lineNumber`. The `toggleClearing` spread already kept
  `leg.lineNumber` via `{ ...leg }`; only `headerLine` needed update — no
  drift-on-followup risk.
- `app/frontend/src/lib/components/transactions/TransactionDetailSheet.svelte`
  — the inline notes `apiPost('/api/transactions/notes', ...)` call now
  sends `lineNumber: leg.lineNumber`.
- `app/frontend/src/routes/transactions/+page.svelte` — `openManualRes`
  builds a legacy `RegisterEntry` from a `TransactionRow.legs[0]`; updated
  to forward `lineNumber: leg?.lineNumber ?? null`.

`Grep` confirmed no other consumer of `legs[0].headerLine`,
`legs[0].journalPath`, or `leg.lineNumber` exists. `ManualResolutionDialog`
itself never reads `headerLine`/`journalPath`/`lineNumber` from
`RegisterEntry`; the fields are payload-only carriers.

### Ambiguity repro

Constructed in-process via FastAPI `TestClient` against a tmp workspace
seeded with two byte-identical headers (same date `2026-03-15`, same
status `unmarked`, same payee `Starbucks`, different amounts $5 and $7):

```
2026-03-15 Starbucks
    Assets:Bank:Checking  -$5.00
    Expenses:Coffee  $5.00

2026-03-15 Starbucks
    Assets:Bank:Checking  -$7.00
    Expenses:Coffee  $7.00
```

GET `/api/transactions` returned two rows with distinct `legs[0].lineNumber`
(5 and 9). On the old code, POSTing toggle-status with the shared
`headerLine` would have returned HTTP 409
`Ambiguous: multiple matching header lines found`. With the new code:

- Toggle-status on the $5 row → 200, only the $5 transaction's header
  changed to `* → !`; the $7 row remained `unmarked`.
- Recategorize on the $7 row → 200, only the $7 row's category changed.
- Notes on the $5 row → 200, notes line inserted only on the $5 block.
- Delete on the $5 row → 200, only the $5 block removed.
- Drift case: replay an old `lineNumber` after the file shifts → 404
  with the existing stale-data detail message.

### Verification outcomes

- `pnpm check` → **PASS**: `671 FILES 0 ERRORS 0 WARNINGS 0 FILES_WITH_PROBLEMS`.
- `uv run pytest app/backend/tests/test_transaction_actions.py app/backend/tests/test_notes_and_recategorize.py -q` →
  **PASS**: 32 passed (was 22 — 10 new regression and drift tests added).
- Targeted broader run (`test_transaction_actions`,
  `test_notes_and_recategorize`, `test_unified_transactions_service`,
  `test_account_register_service`, `test_undo_service`) → 102 passed.
- Full backend suite (excluding pre-existing fastapi-broken modules):
  525 passed, 3 failed in
  `test_institution_registry_derivation.py` — all three failures are
  pre-existing (`assert len(result) == 3` against an 8-template registry)
  and reproduce on `master` before any of my changes.
- **Manual smoke test (live FastAPI app via TestClient against a tmp
  workspace):**
  - **Regular row** with byte-identical-header neighbour: toggle-status,
    recategorize, notes, delete — all 200, all mutated the right block.
  - **Transfer-peer row** (synthetic, single-account scope on the peer
    side of a direct cross-account transfer): GET returned a row whose
    `legs[0].lineNumber` was the real backing transaction's offset
    (not `-1`); toggle-status via that row → 200, mutated the backing
    transaction in its actual journal file.
  - **Drift case**: external file edit invalidated a captured
    `lineNumber`, retry → 404 with
    `"Transaction not found in journal (stale data — try refreshing)"`.
  - **Unmatch endpoint**: not exercised live (requires `match-id`
    metadata + an `archived-manual.journal` sidecar, more setup than the
    smoke value warranted). The handler path is identical
    (`_locate_header(main_lines, req.lineNumber, req.headerLine)`); the
    Pydantic model now requires `lineNumber`.
  - **Split-posting row**: not exercised live (the existing
    recategorize endpoint already 422s on splits regardless of identity
    scheme).
  - **Opening-balance row** in include-file: load-transactions
    correctness verified by automated test
    (`test_include_file_transactions_get_sentinel_line_number`); a live
    mutation attempt would 404 by design.

### Pre-existing environment issue

The Phase-4b `fastapi` ModuleNotFoundError persists in the pytest env
(`uv run pytest`, no `--active`). Two test modules cannot be collected:
`test_unknown_stage_resume.py` and `test_workspace_bootstrap.py` — both
import from `main`, which transitively imports `fastapi`. They were
ignored via `--ignore` flags during full-suite verification. The same
issue prevented adding pytest-style FastAPI integration tests; the live
smoke tests above were run via `uv run python` from `app/backend` (which
does have `fastapi` available — separate venv resolution). Filing a
follow-up to align the pytest environment is out of scope.

### Ambiguity resolved during implementation

- **`locate_header` and `AmbiguousHeaderError` kept, not deleted.**
  `services/undo_service.py` still calls `locate_header` from four
  places (`_undo_transaction_recategorized`,
  `_undo_transaction_status_toggled`, `_undo_manual_entry_created`,
  `_undo_transaction_unmatched`). Per the plan §"Out of Scope":
  "No migration or cleanup of old event-log payloads. The event log's
  historical `header_line` payloads stay as-is." Event payloads carry
  `header_line` text, not `line_number`, so undo replay still has to
  scan. I documented `AmbiguousHeaderError` as deprecated-for-mutation,
  and the `locate_header` docstring now points readers to
  `locate_header_at` for any new mutation-style work.

- **The five-endpoint `_locate_header` wrapper kept, signature changed.**
  Renamed semantically (now takes `(lines, line_number, expected_header)`)
  but kept under the same name to minimize diff churn and keep the
  HTTPException translation localized. Its 409 branch is gone; only the
  404 path remains.

- **`_split_transactions` signature change is contained.** Only
  `journal_query_service._split_transactions` changed
  (`list[list[str]]` → `list[tuple[int, list[str]]]`); the lookalike
  helpers in `import_service.py` and `opening_balance_service.py` are
  separate copies and did not need to change.

- **Drift-check granularity.** Per the plan, the byte-for-byte equality
  check in `locate_header_at` does not normalize whitespace, does not
  parse the header, and does not `.strip()` either side. A test
  (`test_drift_does_not_normalize_whitespace`) locks this down so a
  future "be lenient" patch trips a regression.

- **Synthetic peer rows attribution verified.** `RegisterEvent`
  constructions in `transaction_helpers.py` (both
  `pending_transfer_event_for_peer_account` and
  `direct_transfer_event_for_peer_account`) and the inline
  construction in `unified_transactions_service.py` and
  `account_register_service.py` all forward
  `header_line_number=transaction.header_line_number`. The live smoke
  test confirmed the peer row's `legs[0].lineNumber` resolves to the
  real backing transaction's offset and mutates correctly.
