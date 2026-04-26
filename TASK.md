# Reconciliation Backend (8a) — Reconcile Endpoint, Assertion Writer, Import Fence, Failure Detection

## Objective

A user can hit `POST /api/accounts/{id}/reconcile` with a period and closing balance, and the system writes one zero-amount balance-assertion transaction to the journal, verifies the assertion holds, and emits an `account.reconciled.v1` event. After a date is reconciled, any new import on or before that date is classified as a `conflict`, never silently inserted. The account API and dashboard payloads gain a `reconciliationStatus` field that surfaces broken assertions with the failure date, expected balance, and actual balance.

This task delivers the substrate for 8b (the modal) and 8c (the rendering). It does not deliver any UI; the only user-visible effect is that broken reconciliations and reconciled-date conflicts now exist in API responses, and a cURL request can write a reconciliation.

## Scope

### Included

1. `POST /api/accounts/{accountId}/reconcile` — the reconcile endpoint.
2. Assertion writer — locates the journal file holding `periodEnd`, appends a zero-amount transaction with a balance assertion as the last transaction on its date in that file, then verifies the assertion holds. Rolls back on failure.
3. `account.reconciled.v1` event in the event log, with the standard `journal_refs` hash-before / hash-after pair so existing semantic undo handles deletion of the assertion transaction via the existing transaction actions menu (no new undo handler).
4. Reconciled-date import fence — when classifying an import row, if its date is on or before the most recent reconciliation assertion for the affected tracked account, classify as `conflict` with reason `reconciled_date_fence`. Existing `new` / `duplicate` / `conflict` model is preserved.
5. Read-side failure detection — a service that runs `ledger`/`hledger` against the journal, parses balance-assertion errors, and exposes per-account `reconciliationStatus`. Wire into `_tracked_account_ui` in `main.py:169` so all account-shaped responses (account list, dashboard balance sheet) carry it.
6. Tests for: writer happy path, writer rollback on failure, assertion ordering invariant (last-on-date), event emission, import fence triggers, failure-detection translation, `reconciliationStatus` on the account UI shape.

### Explicitly Excluded

- Reconciliation modal on `/accounts` (8b).
- Assertion rendering in the transactions list and account card (8c).
- Loose-ends entry for broken reconciliations (8c).
- PDF upload / storage (8d).
- Reconciliation history view on the account page (8e).
- Subset-sum solver (8f).
- Adjustment-transaction button (8g).
- Confirmation modal for edits/deletes of pre-reconciliation transactions (8h).
- Multi-currency reconciliation. Single posting, single currency per the plan.
- Reconciliation of income / expense / equity accounts. Balance-sheet accounts only — the endpoint returns `400` if the account's ledger account is not under `Assets:` or `Liabilities:`.
- Smart-date offsets (Beancount Reds-style `min(statement_end - 2, last_posting_date)`). Use the user-entered `periodEnd` as the assertion date verbatim. Document the trade-off in `DECISIONS.md §16`.
- New undo handler for reconciliation. Deletion via the existing transaction actions menu reverses it; the existing `transaction.deleted.v1` handler suffices.

## System Behavior

### 1. `POST /api/accounts/{accountId}/reconcile`

**Request body:**

```json
{
  "periodStart": "2026-03-18",
  "periodEnd": "2026-04-17",
  "closingBalance": "2500.00",
  "currency": "USD"
}
```

- `accountId` — tracked-account id (the same id used by the `/api/accounts` and `/api/tracked-accounts` endpoints).
- `periodStart`, `periodEnd` — ISO dates (`YYYY-MM-DD`). `periodStart <= periodEnd` required.
- `closingBalance` — string-encoded decimal, parsed by the existing currency parser (`app/backend/services/manual_entry_service.py` has the canonical regex; reuse, don't reinvent).
- `currency` — must match the workspace base currency. Reject other values with `400` and the message `Multi-currency accounts are out of scope (#TODO multi-currency support).`

**Validation:**

- Tracked account exists. Otherwise `404 Tracked account not found: <id>`.
- Account is balance-sheet (ledger account starts with `Assets:` or `Liabilities:`). Otherwise `400 Reconciliation is only supported for asset and liability accounts.`
- `periodStart <= periodEnd`, both parseable. Otherwise `400 Invalid period: <reason>`.
- `closingBalance` parses to a decimal. Otherwise `400 Invalid closing balance: <value>`.
- `periodEnd` is on or after the most recent existing reconciliation date for this account. Otherwise `409 A more recent reconciliation already exists for this account on <date>. Delete it first if you want to reconcile an earlier period.`
- `currency` matches the workspace base currency. Otherwise `400` per above.

**Side effects:**

- Backup the target journal via the existing `backup_file` helper (`backup_service.py`) with reason `reconcile`.
- Append the assertion transaction (see "Assertion writer" below).
- Verify the assertion via `ledger -f <main journal> bal --strict <ledger_account>`. Parse the exit code and stderr.
- If verification succeeds, emit `account.reconciled.v1` to the event log with `journal_refs` carrying `hash_before` and `hash_after` of the journal file.
- If verification fails, roll back the journal file from the backup, do NOT emit an event, and return `422` with the parsed error.

**Response (success):**

```json
{
  "ok": true,
  "assertionTransaction": {
    "journalPath": "journals/2026.journal",
    "headerLine": "2026-04-17 * Statement reconciliation · Wells Fargo Checking · ending 2026-04-17",
    "lineNumber": 1487
  },
  "eventId": "01HGE..."
}
```

**Response (assertion failed):**

```json
{
  "outcome": "assertion_failed",
  "message": "Reconciliation rejected — expected $2,500.00, found $2,487.43.",
  "expected": "2500.00",
  "actual": "2487.43",
  "rawError": "<unparsed ledger stderr>"
}
```

HTTP `422` for the assertion-failed outcome.

### 2. Assertion Writer

A new service module: `app/backend/services/reconciliation_service.py`.

**Locating the target journal:**

- Year-derived: `journal_dir / f"{periodEnd[:4]}.journal"`. Same convention used by `transactions_create` in `main.py:496`.
- If the file does not exist, create it (consistent with the import path).

**Composing the transaction block:**

```
2026-04-17 * Statement reconciliation · <accountDisplayName> · ending 2026-04-17
    ; reconciliation_event_id: <uuidv7>
    ; statement_period: 2026-03-18..2026-04-17
    <ledger_account>  $0 = $2,500.00
```

- `<accountDisplayName>` — `tracked_account_cfg["display_name"]`, falling back to `accountId`.
- `<ledger_account>` — `tracked_account_cfg["ledger_account"]`. Required; if empty, return `400 Tracked account is missing a ledger account.`
- `<uuidv7>` — generated by the writer **before** `emit_event` is called, then passed to `emit_event` as the explicit event id (extend `emit_event` if it doesn't already accept a caller-supplied id; if not feasible without invasive changes, generate the id inside `reconciliation_service`, write the journal with it, then ask `emit_event` to use it). Both the journal metadata and the event log row must reference the same id.
- Currency formatting: use the existing `format_currency_for_ledger` helper if present in `manual_entry_service.py` or `transaction_helpers.py`; if not, format as `$<value>` for USD and `<value> <CCY>` for other currencies. Reuse, don't reinvent.

**Insertion ordering (critical invariant):**

- Read the file. Find the last line whose date prefix (`line[:10]`) equals `periodEnd` and that matches `TXN_START_RE` (from `journal_query_service.py`). The assertion transaction inserts immediately after that block ends (i.e., after that block's last line and any trailing blank line that belongs to it).
- If no transaction with date `periodEnd` exists in the file, find the last transaction with date `< periodEnd` and insert after its block. If no such transaction exists, append to the end of file.
- Always insert with one blank line before the new block (unless inserting at file start, no preceding blank).
- After insertion, the assertion transaction must be the last transaction with date `periodEnd` in file order. Add a unit test that asserts this on a journal where another `periodEnd`-dated transaction exists later in the file (this case can arise if the journal was hand-edited or merged).

**Verification:**

- Run `ledger -f <root>/<main_journal> bal --strict <ledger_account>` via `run_cmd` (`ledger_runner.py`). The main journal is determined by the existing `_main_journal_path` helper (find it in `main.py` or `workspace_service.py`; reuse).
- If `run_cmd` raises `CommandError`, parse stderr for `Balance assertion off by` (ledger) and `assertion failed` / `expected ... but found ...` (hledger) patterns. Extract `expected` and `actual` if present; otherwise pass the raw error in `rawError`.
- If parsing succeeds, return the structured failure to the endpoint. The endpoint rolls back from the pre-write backup.
- If `run_cmd` returns successfully (exit 0), the assertion holds.

**Rollback:**

- The backup_file helper copies the file before mutation. On verification failure, copy the backup back over the live file. Do NOT emit any event in this branch — the reconciliation never happened, from the event log's perspective.

### 3. `account.reconciled.v1` event

Emitted via the existing `emit_event` from `event_log_service.py`. Shape:

```json
{
  "id": "01HGE...",
  "type": "account.reconciled.v1",
  "timestamp": "2026-04-26T15:42:11Z",
  "actor": "user",
  "summary": "Reconciled Wells Fargo Checking · ending 2026-04-17 · $2,500.00",
  "payload": {
    "tracked_account_id": "wells-checking",
    "ledger_account": "Assets:Checking:Wells Fargo",
    "period_start": "2026-03-18",
    "period_end": "2026-04-17",
    "closing_balance": "2500.00",
    "currency": "USD",
    "journal_path": "journals/2026.journal",
    "header_line": "2026-04-17 * Statement reconciliation · Wells Fargo Checking · ending 2026-04-17",
    "line_number": 1487
  },
  "journal_refs": [
    { "path": "journals/2026.journal", "hash_before": "...", "hash_after": "..." }
  ]
}
```

No new undo handler. Deletion is covered by the existing transaction actions menu (`transaction.deleted.v1` + the existing handler in `undo_service.py`). Document this in the test for the writer: round-trip "reconcile then delete the assertion transaction" should leave the journal byte-equivalent to before the reconcile (modulo trailing whitespace).

### 4. Reconciled-date import fence

**Where:** the import classification path, not the import application path. Currently at `main.py:396` (`return "new" / "duplicate" / "conflict"` ladder — confirm the exact location). Reuse the existing classification function; do not duplicate it.

**Logic:**

- Resolve the tracked account for the import row. If the row maps to no tracked account (orphan import), do not apply the fence — fall through to the existing classification.
- Look up the most recent reconciliation date for that tracked account. The lookup function lives in `reconciliation_service.py` (a small `latest_reconciliation_date(config, ledger_account) -> date | None` helper that scans the journal for assertion transactions with `; reconciliation_event_id:` metadata on the asserted account's posting). Cache once per import classification pass — do not re-parse per row.
- If the row's date is on or before that date, the row's `matchStatus` becomes `conflict` and a new field `conflictReason: "reconciled_date_fence"` is added (existing rows without this reason get `conflictReason: null` to keep the response shape stable).
- The conflict reason carries the reconciliation date in a separate field: `reconciledThrough: "2026-04-17"`. The frontend can render copy from this without re-deriving.

**Response shape:** existing `{ matchStatus, ... }` rows gain two optional fields:

```json
{ "matchStatus": "conflict", "conflictReason": "reconciled_date_fence", "reconciledThrough": "2026-04-17" }
```

Existing conflict rows (e.g., `source_identity` collisions) get `conflictReason: "identity_collision"` and `reconciledThrough: null`. Pick a stable enum: `"identity_collision" | "reconciled_date_fence"`.

**Apply path:** the apply endpoint must refuse to apply any row with `matchStatus === "conflict"` regardless of reason. Confirm this is already the case (it should be — conflicts are gated today) and add a test that proves it for the new reason.

### 5. Failure detection

A new function in `reconciliation_service.py`:

```python
def reconciliation_status(config) -> dict[str, ReconciliationStatus]:
    """Returns {tracked_account_id: ReconciliationStatus}.

    ReconciliationStatus is either {"ok": True} or
    {"ok": False, "broken": {"date": "YYYY-MM-DD", "expected": "...", "actual": "...", "rawError": "..."}}.
    """
```

**Implementation:**

- Run `ledger -f <main_journal> bal --strict` once. Parse stderr.
- Ledger emits one error line per failed assertion, with the form `Error: Balance assertion off by ... in <file>:<line>`. Extract: file, line, expected, actual.
- Map each failed assertion line back to a tracked account by reading the journal at that line and finding the asserted ledger account. The ledger account → tracked account mapping already exists (`_tracked_account_id_for_ledger_account` in `main.py:222`).
- Cache the result for the duration of a single request. Do NOT cache across requests — the journal can change.
- If `ledger` is unavailable (CommandError other than assertion failure), return `{ok: True}` for every account and log a warning. Do NOT pretend a reconciliation is broken just because the CLI is missing.

**Wiring:**

- `_tracked_account_ui` in `main.py:169` adds `reconciliationStatus` to its return dict. Default `{"ok": true}` when no entry is present in the map.
- This propagates automatically into:
  - `GET /api/accounts` (account list)
  - `GET /api/dashboard/overview` balance sheet (which calls `_tracked_account_ui`)
  - Any other endpoint reusing `_tracked_account_ui`

**Performance:** the failure-detection ledger call is one shell-out per page load that hits these endpoints. Acceptable for MVP — the same path already runs `ledger` for other queries. If profiling shows it's hot, gate it behind a `?withReconciliationStatus=1` query param.

### System Invariants

- The assertion transaction is always the last transaction on its date in the journal file that holds it. The writer enforces this on insert; future imports must respect it (covered by the import fence).
- Once a reconciled date exists for an account, the journal is never silently mutated on or before that date by the import path. Only an explicit user action (delete the assertion transaction) clears the fence.
- The `ledger account → tracked account` mapping is the single source of truth for routing failures. If a journal contains an assertion on a ledger account no tracked account currently maps to (e.g., because the user deleted the tracked account but kept the journal), the failure shows up in logs but does NOT crash the endpoint — return `{ok: True}` for known tracked accounts and ignore the orphaned failure.
- The event log is append-only. A failed reconciliation never writes an event.
- Hand-written or imported balance-assertion transactions (no `reconciliation_event_id` metadata) trigger failure detection but are NOT part of the "most recent reconciliation date" computation for the import fence. Only assertions with the `reconciliation_event_id` metadata count toward the fence and the future history view.

### States

- **Default:** No reconciliations exist for any account. All `reconciliationStatus` fields default `{ok: true}`. Import classification proceeds unchanged.
- **At least one reconciliation, all valid:** `{ok: true}` per account. Import fence active for dates ≤ most-recent reconciliation per account.
- **Broken reconciliation:** `{ok: false, broken: {date, expected, actual, rawError}}` for the affected account. Failure surfaces in account/dashboard responses.
- **Endpoint loading:** standard FastAPI request lifecycle — no special UI state, this is API-only work.
- **Reconcile request — success:** `200` with the assertion transaction descriptor and event id.
- **Reconcile request — assertion failed:** `422` with structured error.
- **Reconcile request — validation error:** `400` / `404` / `409` with a human-readable message.

### Edge Cases

- **Period end on an unused date.** If no transactions exist on `periodEnd`, the assertion still inserts at the position just after the last transaction with date `< periodEnd`. Test this.
- **`periodEnd` precedes any existing transaction in the file.** Insert at the top, no preceding blank line. Test this.
- **`periodEnd` year file does not exist.** Create it, insert as the only transaction in the file. Test this.
- **Two reconciliations on the same date for the same account.** Refuse with `409 A reconciliation already exists for this account on <date>.` (Same-day re-reconciliation makes no sense — delete the prior one and redo if needed.)
- **`periodStart > periodEnd`.** Reject with `400`. Tested in validation.
- **Import row date equals reconciliation date.** Treated as `≤ reconciled_date` → `conflict`. Verified by test: a reconciliation written on 2026-04-17 fences out an import row also dated 2026-04-17.
- **Import row date is the day after a reconciliation.** Allowed through. Test this.
- **Tracked account whose ledger account contains a colon-prefixed parent that's also tracked** (e.g., parent `Assets:Checking` and child `Assets:Checking:Wells`). The lookup must match the *exact* ledger account from the assertion posting, not a parent. Test with overlapping account hierarchies.
- **Hand-edited assertion line that the user wrote before this feature shipped.** Failure detection picks it up. Import fence does NOT pick it up (no `reconciliation_event_id`). Documented in the test: "hand-written assertion is honored for failure detection only".
- **Assertion fails immediately after write.** Rollback restores the byte-equivalent file. Test with a fixture journal where the closing balance is wrong on purpose, assert that after the failed reconcile the file is byte-identical to the pre-write backup and no event is emitted.
- **Concurrent reconcile + import.** No locking in MVP. If the user reconciles in tab A while an import classification is in flight in tab B, tab B may complete its classification before tab A's writer runs — its classifications will not see the new fence. Acceptable; documented as a known race.

### Failure Behavior

- Validation failures: `400` / `404` / `409` with concrete messages. Do not leak Python tracebacks.
- Assertion failure on write: `422`, journal rolled back via the pre-write backup, no event emitted. Existing journal byte-equivalence preserved.
- Ledger CLI missing or crashes during verification: rollback (treat as failure), `500 Could not verify the assertion: ledger CLI is unavailable.` Log the underlying error.
- Failure detection unavailable (ledger CLI missing): every account reports `{ok: true}` with a single warning log line per request. Account/dashboard endpoints continue to serve. The user does not see a misleading "all good" banner — this layer's job is data, not copy; 8c handles the surface and can defensively render `Last verified: <timestamp>` once we wire that.
- Import classification with the fence: a row that flips from `new` to `conflict` because of the fence is gated by the existing apply-time conflict check. Re-running classification reproducibly returns the same answer.

### Regression Risks

- **`_tracked_account_ui` shape change.** Adding `reconciliationStatus` to every account-shaped response could break any frontend reader that asserts a fixed key set. Audit consumers — the dashboard balance sheet, the accounts list page, the account chip helpers in transactions. Add the field as optional in the TS types so old code paths don't error.
- **Import classification refactor.** Threading the fence in without breaking the existing `new` / `duplicate` / `conflict` semantics is the highest-risk piece. Wrap the fence in a small `apply_reconciliation_fence(rows, latest_dates)` helper, run it after the existing classifier, and test the unaltered path explicitly (no reconciliations → identical outputs to today).
- **Journal-write ordering.** A bug in the "last on its date" insertion would silently break future reconciliations of the same account (the assertion would check an intermediate balance and could pass for the wrong reason). Cover with a dedicated test that inserts an assertion when later transactions exist on the same date.
- **Failure-detection ledger error parsing.** `ledger` and `hledger` produce slightly different error formats. MVP targets `ledger` only — capture the regex, snapshot a real error string in a fixture, and add a test. If hledger support comes later, extend the parser, not the call site.
- **Event-log linkage.** The `reconciliation_event_id` in the journal metadata must equal the event id in `events.jsonl`. If they diverge, the future history view (8e) loses the ability to associate assertions with events. Cover with an integration test: write a reconciliation, read both the assertion transaction's metadata and the most recent event, assert the ids match.

## Acceptance Criteria

- `POST /api/accounts/{id}/reconcile` with a valid body writes one transaction to the journal file matching `periodEnd[:4]`, of the form `<periodEnd> * Statement reconciliation · <displayName> · ending <periodEnd>`, with `; reconciliation_event_id:` and `; statement_period:` metadata lines, and one posting `<ledger_account>  $0 = $<closingBalance>`.
- The written transaction is the last transaction with date `periodEnd` in its file, even when other transactions on `periodEnd` already exist below the insertion point.
- `account.reconciled.v1` is appended to `events.jsonl` with the documented payload and `journal_refs`. The event id matches the `reconciliation_event_id` in the journal metadata.
- A reconcile request whose closing balance does not match the journal-derived balance returns `422`, leaves the journal byte-identical to the pre-write state, and emits NO event.
- A reconcile request for the same account on the same date as an existing reconciliation returns `409`.
- A reconcile request for an income / expense / equity account returns `400`.
- A reconcile request with a non-base currency returns `400`.
- After a reconciliation exists for tracked account `X` with `periodEnd = D`, an import preview of a row dated `D` mapped to `X` reports `matchStatus: "conflict"` with `conflictReason: "reconciled_date_fence"` and `reconciledThrough: D`. A row dated `D + 1 day` reports unchanged classification.
- After an external edit breaks an existing assertion, `GET /api/accounts` returns the affected account with `reconciliationStatus: {ok: false, broken: {date, expected, actual, rawError}}`. Other accounts continue to report `{ok: true}`.
- Deleting the assertion transaction via the existing transaction actions menu (`/api/transactions/delete`) leaves the journal in a state byte-equivalent to before the reconciliation (modulo any transactions added in between), and removes the import fence for that account.
- `pnpm check` passes (no frontend changes are required, but type changes in `app/frontend/src/lib/api/types.ts` for the new optional fields must compile).
- `uv run pytest -q` passes, including the new tests enumerated under Regression Risks.

## Proposed Sequence

Each step independently verifiable.

1. **Skeleton service module + writer.** Create `reconciliation_service.py` with `write_assertion_transaction(...)` and `latest_reconciliation_date(...)`. No endpoint yet. Tests: ordering invariant on a synthetic journal (insertion when nothing on date, when other txns on date, at file start, into nonexistent file).
2. **Verification + rollback.** Add the post-write `ledger bal --strict` call inside the writer. Test: bad closing balance triggers rollback and journal byte-equivalence; good closing balance proceeds.
3. **Endpoint + event emission.** Wire `POST /api/accounts/{id}/reconcile` in `main.py`. Add the validation ladder. Emit `account.reconciled.v1`. Tests: round-trip success returns the documented response; validation failures hit the right HTTP codes.
4. **Failure detection.** Add `reconciliation_status(config)` and wire into `_tracked_account_ui`. Tests: synthetic broken assertion in a fixture journal surfaces in `/api/accounts`; healthy journal returns `{ok: true}` per account; missing ledger CLI degrades gracefully.
5. **Import fence.** Add `apply_reconciliation_fence(rows, latest_dates)` post-classifier in the import preview path. Tests: row on/before reconciliation → conflict; row after → unchanged; existing conflict reasons still attach as `identity_collision`.
6. **Round-trip integration test.** Write a reconciliation, then delete the assertion transaction via `/api/transactions/delete`, then assert the journal is byte-equivalent to pre-reconciliation, the event log has `account.reconciled.v1` followed by `transaction.deleted.v1` linked via the standard delete handler, and `latest_reconciliation_date` for that account returns `None`.

## Definition of Done

- All 11 acceptance criteria pass.
- `uv run pytest -q` passes — new tests listed above, plus all existing tests.
- `pnpm check` passes.
- `DECISIONS.md` gains §14, §15, §16, §17, §19 per `plans/statement-reconciliation.md`. (§18 about PDFs lands with 8d.)
- `ROADMAP.md` updated: 8a marked shipped, 8b promoted to active.
- A short follow-up note added at the bottom of [`plans/statement-reconciliation.md`](plans/statement-reconciliation.md) describing any deviations from spec encountered during implementation.

## UX Notes

This task is API-only — no UI surfaces here. UX follows in 8b and 8c. One note carries forward: the `rawError` field on broken-status payloads is the source of truth for the "details" disclosure 8c will render. Make sure the parser preserves the original ledger error text verbatim, not a cleaned-up version. The translated copy (`expected`, `actual`, `date`) is on top of `rawError`, not instead of it.

## Out of Scope

- Reconciliation modal (8b).
- Assertion rendering (8c).
- PDF upload (8d).
- History view (8e).
- Subset-sum solver (8f).
- Adjustment button (8g).
- Pre-reconciliation edit confirmation (8h).
- Multi-currency support.
- Smart-date offsets.
- Reconciliation of non-balance-sheet accounts.
- A new undo handler for `account.reconciled.v1` — deletion via the transaction actions menu suffices.

## Dependencies

- 5b (event log) — shipped.
- 5d (transaction actions menu, including delete) — shipped. The delete action's existing undo path is what reverses a reconciliation.
- 5e core (undo dispatcher) — shipped. No new handler added in this task; the existing `transaction.deleted.v1` handler covers reconciliation reversal.
- The `ledger` CLI is required at runtime for both writer verification and read-side failure detection. The codebase already depends on it (see `import_service.py:486`); no new dependency.

## Open Questions

None. Decisions inline:

- **Single-currency MVP.** Multi-currency rejected at validation. Revisit when a real user reports it.
- **Statement-end date is the assertion date.** No smart-date offset. Revisit if a real user reports lagging-postings issues.
- **No new undo handler.** Reuse the existing delete handler via the transaction actions menu.
- **Failure detection runs on every account/dashboard request.** Acceptable cost for MVP. Gate behind a query param if profiling shows it's hot.
- **Ledger error parsing targets `ledger` only.** hledger support is a follow-up; MVP runs on the same CLI the import path already uses.
- **Same-day re-reconciliation is rejected (`409`).** User must delete the prior reconciliation first.
