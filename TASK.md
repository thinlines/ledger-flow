# Current Task

## Title

Transactions screen rethink — Phase 4a: Unified backend endpoint

## Objective

Build a single `GET /api/transactions` endpoint that replaces both `/api/transactions/register` (single-account) and `/api/transactions/activity` (cross-account). The endpoint returns a unified `TransactionRow[]` shape implementing the N-1 posting rule, computes running balance server-side, and supports filter params for account scope, date range, category, status, and search. Transfer-pair collapse is deferred to Phase 4b.

This is the backend foundation that Phase 4b (frontend unification) and Phase 4c (polish) build on. The two legacy endpoints remain untouched — they are retired in Phase 4b when the frontend switches to the new endpoint.

See [`plans/transactions-rethink.md`](plans/transactions-rethink.md) for the full design.

## Scope

### Included

- **New service file** `app/backend/services/unified_transactions_service.py` containing `build_unified_transactions(config, filters, *, today=None) -> dict`.
- **New shared helpers module** `app/backend/services/transaction_helpers.py` — extract the helpers needed by both the register service and the unified service (currently private in `account_register_service.py`). Promote to public functions. Update `account_register_service.py` imports so the existing register endpoint continues to work unchanged.
- **New route** `GET /api/transactions` in `main.py` with query param parsing.
- **N-1 posting rule** implemented server-side: a ledger transaction with N postings displays as 1 row, suppressing the tracked-account leg. The remaining N-1 postings populate `categories[]`.
- **Running balance** computed across the visible filtered row set in date order. Single-account scope = that account's balance. Multi-account same-currency scope = sum of tracked-account balances (net-worth proxy). Multi-currency scope = running balance omitted (`null`).
- **Summary block** reusing `_build_summary()` from the activity service when a date filter is active.
- **Account metadata** (`accountMeta`) returned when exactly one account is scoped — same data as the current register response top-level fields (currentBalance, hasOpeningBalance, etc.).
- **Filter params**: `accounts`, `categories`, `period`, `from_date`, `to_date`, `month`, `status`, `search`.
- **Synthetic peer rows** for pending and direct transfers in single-account scope (same behavior as current register service).
- **Tests** in `app/backend/tests/test_unified_transactions_service.py` following the existing `_make_config` + `tmp_path` fixture pattern.

### Explicitly Excluded

- **Transfer-pair collapse** — deferred to Phase 4b. Two tracked-to-tracked transfer transactions appear as separate rows for now. The collapse logic has unresolved edge cases (clearing-status conflicts, manual-resolution tokens, mismatched dates) that need specification before implementation.
- **Frontend changes** — no component or page modifications. The frontend continues using the legacy endpoints.
- **Deleting legacy endpoints** — `/api/transactions/register` and `/api/transactions/activity` remain unchanged.
- **Search formula syntax** (`>50`, `<-20`) — deferred to Phase 4c (polish).
- **Any new UI copy or user-visible changes** — this is a backend-only task.

## System Behavior

### Inputs

- `GET /api/transactions` with optional query params:
  - `accounts` — comma-separated tracked-account IDs (empty = all tracked accounts)
  - `categories` — comma-separated category account prefixes (prefix match: `Expenses:Food` matches `Expenses:Food:Groceries`)
  - `period` — `this-month` | `last-30` | `last-3-months` | `last-6-months` | `this-year`
  - `from_date`, `to_date` — ISO date strings for custom range
  - `month` — `YYYY-MM` shorthand (overrides `period`)
  - `status` — comma-separated: `cleared`, `pending`, `unmarked`
  - `search` — case-insensitive payee substring match

### Logic

**Pipeline** (in order):
1. Load all parsed transactions via `load_transactions(config)`.
2. Determine scope accounts: if `accounts` param is set, restrict to those IDs; otherwise use all tracked accounts from config.
3. Compute grouped-settlement and bilateral-match orders (reuse existing helpers).
4. Build `UnifiedRow` list — for each transaction:
   - Identify owning tracked account via `_source_tracked_account_details()`.
   - If the tracked-account ledger posting exists and the account is in scope:
     - Extract amount and commodity from the tracked-account posting.
     - Build `categories[]` from remaining postings (N-1 rule): all postings except the tracked-account posting and transfer-account postings. Each entry: `{ account, label, amount }`.
     - Detect `isTransfer` via transfer metadata, `isUnknown` from `Expenses:Unknown` prefix, `isManual` from `:manual:` tag, `isOpeningBalance` via `is_generated_opening_balance_transaction()`.
     - Build detail_lines, transfer state, manual resolution token/note, notes.
   - If the transaction doesn't touch the scoped account directly, check for synthetic peer rows (pending/direct transfers) — only in single-account scope.
5. Apply filters in order: date/period → category → status → search.
6. Sort by `(date, order)`.
7. Compute running balance as cumulative sum of each row's amount. For multi-commodity scope, set `runningBalance = null` on all rows instead of raising an error.
8. Build summary via `_build_summary()` when a date filter is active.
9. Build `accountMeta` when exactly one account is scoped.
10. Serialize: rows reversed (newest first), fields as specified in response shape.

**N-1 rule detail:**
- 2-posting transaction (normal): 1 tracked-account posting (suppressed → `account` + `amount`), 1 other posting (→ `categories[0]`).
- 3-posting transaction (split): 1 tracked-account posting (suppressed), 2 others (→ `categories[0..1]`).
- Transaction with transfer-account posting: transfer-account postings excluded from `categories[]`. Transfer peer derived from transfer metadata.

**Running balance rules:**
- Single-account scope: each row's `amount` accumulates into the running balance. Opening balance rows anchor the starting point. Synthetic pending-transfer peer rows have `affects_balance = false`.
- Multi-account same-currency scope: same accumulation, but across all tracked accounts. Running balance represents net-worth proxy.
- Multi-currency: if any two rows in the filtered set have different commodities, set `runningBalance = null` on all rows. Do not raise `CommodityMismatchError` — fail soft with null so the frontend can hide the column.

### Outputs

**Response shape:**

```json
{
  "baseCurrency": "USD",
  "filters": {
    "accounts": ["checking"],
    "categories": [],
    "period": "last-3-months",
    "month": null,
    "status": null,
    "search": null
  },
  "rows": [
    {
      "id": "checking-2026-03-24-0",
      "date": "2026-03-24",
      "payee": "Trader Joe's",
      "amount": -42.10,
      "runningBalance": 1210.50,
      "account": { "id": "checking", "label": "Wells Fargo Checking" },
      "transferPeer": null,
      "categories": [
        { "account": "Expenses:Food:Groceries", "label": "Food / Groceries", "amount": 42.10 }
      ],
      "status": "cleared",
      "isTransfer": false,
      "isUnknown": false,
      "isManual": false,
      "isOpeningBalance": false,
      "legs": [{ "journalPath": "workspace/journals/2026.journal", "headerLine": "2026-03-24 * Trader Joe's" }],
      "matchId": null,
      "transferState": null,
      "manualResolutionToken": null,
      "manualResolutionNote": null,
      "detailLines": [{ "label": "Food / Groceries", "account": "Expenses:Food:Groceries", "kind": "expense" }],
      "notes": null
    }
  ],
  "summary": { "..." : "same shape as existing ActivitySummary" },
  "totalCount": 1,
  "accountMeta": {
    "accountId": "checking",
    "currentBalance": 1210.50,
    "entryCount": 42,
    "transactionCount": 40,
    "hasOpeningBalance": true,
    "hasTransactionActivity": true,
    "hasBalanceSource": true,
    "latestTransactionDate": "2026-03-24",
    "latestActivityDate": "2026-03-24"
  }
}
```

When `accounts` is empty or contains multiple accounts, `accountMeta` is `null`.

## System Invariants

- The N-1 rule must produce exactly one row per ledger transaction. Rows must never double-count the tracked-account leg.
- `runningBalance` on each row, when non-null, must equal the cumulative sum of all prior rows' `amount` fields (in date/order sequence). A user summing the `amount` column down the page must arrive at the final `runningBalance`.
- The `amount` field always represents the tracked-account leg's signed value. Negative = money left the tracked account. Positive = money entered.
- Opening-balance rows anchor the running balance. They are included in the cumulative sum.
- Synthetic peer rows for pending transfers must have `affects_balance = false` — they do not change the running balance.
- `categories[]` must never contain the tracked-account posting or a transfer-clearing-account posting.
- The existing `/api/transactions/register` and `/api/transactions/activity` endpoints must continue working unchanged after this task.
- `summary` is `null` when no date filter is active (matches current activity service behavior — summary requires a time-bounded comparison).

## States

- **Success**: response with `rows[]`, `summary`, optional `accountMeta`.
- **Empty result**: response with `rows: []`, `totalCount: 0`, `summary: null`. Filters echoed back.
- **Error — invalid account**: 404 if an explicit `accounts` param references a non-existent tracked account ID.
- **Error — commodity mismatch within single account**: 400 with `CommodityMismatchError` detail (existing behavior preserved from register service). Only raised when a single account has mixed commodities within its own postings, not cross-account.

## Edge Cases

- **Transaction touching no tracked account**: skipped — does not appear in any response.
- **Transaction touching multiple tracked accounts without transfer metadata**: attributed to the "source" account (via `_source_tracked_account_details`). Other tracked-account postings appear in `categories[]`.
- **Multi-currency cross-account scope**: `runningBalance` set to `null` on all rows. No error raised.
- **Opening balance in cross-account mode**: each tracked account's opening balance appears as a separate row. They collectively anchor the running balance.
- **Split transaction (3+ postings)**: N-1 rule produces 2+ entries in `categories[]`. The row is normal, not a transfer.
- **Search on empty string**: treated as no search filter.
- **`period` and `month` both set**: `month` takes precedence (existing activity service behavior).
- **Filters producing zero results**: `summary` is `null`, `rows` is `[]`.

## Failure Behavior

- If `load_transactions()` fails (journal parse error), propagate as 500. Do not return partial results.
- If a tracked account referenced in `accounts` param doesn't exist, return 404 with a clear message. Do not silently ignore.
- Multi-currency in cross-account mode fails soft: `runningBalance = null` on all rows. The frontend hides the column.
- Single-account multi-commodity (within one account's postings): raise `CommodityMismatchError` as 400, matching existing register behavior.

## Regression Risks

- **Register endpoint behavior change**: the shared helpers extraction (Step 1) must not alter `build_account_register()` output. Run existing `test_account_register_service.py` before and after.
- **Activity endpoint behavior change**: no code changes to `activity_service.py`, but verify `test_activity_service.py` still passes (if tests exist).
- **Import identity metadata**: the unified service reads `import_account_id`, `match-id`, `notes`, and transfer metadata from transaction comments. These are read-only — no writes.
- **Transfer detection**: reusing grouped-settlement and bilateral-match detection from the register service. These must produce identical results to the current register.

## Acceptance Criteria

- `GET /api/transactions` with no params returns all tracked-account transactions from last 3 months, newest first, with `runningBalance` and `summary`.
- `GET /api/transactions?accounts=checking` returns single-account results with `accountMeta`, running balance, clearing status, transfer state, manual resolution tokens, and notes — matching the data from the current register endpoint for the same account.
- `GET /api/transactions?accounts=checking&period=this-month` returns filtered results with `summary` block.
- `GET /api/transactions?categories=Expenses:Food` returns only transactions with a posting to `Expenses:Food` or any sub-account.
- `GET /api/transactions?status=cleared` returns only cleared transactions.
- `GET /api/transactions?search=trader` returns only transactions with "trader" in the payee (case-insensitive).
- N-1 rule: a 2-posting expense produces 1 category. A 3-posting split produces 2 categories. No row duplicates the tracked-account leg.
- Running balance is cumulative and coherent when summing amounts down the page.
- Multi-currency cross-account: `runningBalance` is `null` on all rows (no error).
- Existing tests in `test_account_register_service.py` pass unchanged.
- `uv run pytest -q` passes.

## Proposed Sequence

1. **Extract shared helpers** into `app/backend/services/transaction_helpers.py`. Move `_account_amount`, `_source_tracked_account_details`, `_tracked_account_display`, `_tracked_account_by_ledger_account`, `_transfer_peer_details`, `_detail_lines`, `_manual_resolution_token`, `_manual_resolution_note`, `_opening_balance_detail_line`, `_grouped_settled_pending_transfer_orders`, `_bilateral_matched_pending_transfer_orders`, `_pending_transfer_event_for_peer_account`, `_direct_transfer_event_for_peer_account`, `_transaction_summary`, `RegisterEvent`, `PendingTransferCandidate`, and the grouped-settlement helpers. Update imports in `account_register_service.py`. Run existing tests.
2. **Build `unified_transactions_service.py`** with `UnifiedTransactionFilters` dataclass, the pipeline functions, and `build_unified_transactions()`.
3. **Add the route** in `main.py` with query param parsing and error handling.
4. **Write tests** covering: single-account parity with register, cross-account parity with activity, N-1 rule (2-leg and 3-leg), running balance coherence, all filter types, summary block, accountMeta, edge cases (no tracked account, multi-currency, empty results).

## Definition of Done

- The unified endpoint returns correct data for both single-account and cross-account queries.
- N-1 posting rule is verified by tests.
- Running balance is mathematically coherent (cumulative sum check in tests).
- All existing tests pass — no regressions in register or activity behavior.
- `uv run pytest -q` passes.

## Out of Scope

See "Explicitly Excluded" above. Everything from Phase 4b (frontend), Phase 4c (polish), and transfer-pair collapse is out of scope.
