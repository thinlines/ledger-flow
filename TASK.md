# Dashboard History Payload + Transaction Cache (10a)

## Objective

Expose full spending-category and cash-flow history from the dashboard endpoint so the frontend can render multi-month charts, sparklines, and cross-filter interactions without additional API calls. Add a lazy-fetch endpoint for drill-down to individual transactions scoped by period and category. Introduce an mtime-based transaction cache to eliminate redundant journal parsing on repeated dashboard loads.

## Scope

### Included

1. **Add `categoryHistory` to the dashboard overview response.** Expose every `(month, category)` entry from the already-computed `category_spending` dict as a flat array. Each row includes the ledger account path, a pretty label (via `pretty_account_name`), and the absolute spending amount. This is the data source for category sparklines, spending-drivers donut, and selected-category time series on the frontend.

2. **Add `cashFlowHistory` to the dashboard overview response.** Expose all months present in `monthly_income` and `monthly_spending` as a flat array — not just the 6-month window. Each row includes month key, label, income, spending, and net. This is the data source for the ECharts grouped bar chart.

3. **Add `GET /api/dashboard/transactions` endpoint.** Lazy fetch for drill-down transaction detail, scoped by `period` (required, month key like `"2026-04"`) and optionally `category` (ledger account path). Returns a paginated list of matching transactions with `date`, `payee`, `amount`, `category`, `categoryLabel`, and `accountLabel`. Supports `limit` (default 50) and `offset` (default 0) query params. Response includes `total` count for pagination.

4. **Add mtime-based transaction cache in `journal_query_service.py`.** `load_transactions()` today re-parses all journal files on every call. Wrap it with a cache keyed on the maximum mtime across all journal files in `config.journal_dir`. Cache hit = one `stat()` per journal file. Cache miss = full re-parse. Thread-safe via `threading.Lock`. Module-level (process lifetime). The cache returns a copy or is treated as read-only by all callers.

### Explicitly Excluded

- Any frontend changes. This is a backend-only task.
- Removing or modifying `categoryTrends` or `cashFlow.series` from the existing response. These remain for backward compatibility; the frontend still reads them. Removal happens in 10c.
- Weekly or daily granularity in the transactions endpoint. Only month-level period filtering is supported in 10a.
- Changes to any other endpoint (`/api/transactions`, `/api/transactions/activity`, `/api/dashboard/direction`).
- User-facing UI changes.

## System Behavior

### Inputs

- Frontend calls `GET /api/dashboard/overview` (existing endpoint, augmented response).
- Frontend calls `GET /api/dashboard/transactions?period=2026-04&category=Expenses:Food:Groceries&limit=20&offset=0` (new endpoint).

### Logic

**`categoryHistory` construction** (in `build_dashboard_overview`):

After the existing single-pass accumulation loop, iterate all entries in `category_spending` and emit one row per `(month, account)` pair:
```python
category_history = [
    {
        "month": month,
        "category": account,
        "categoryLabel": pretty_account_name(account),
        "amount": amount_to_number(total),
    }
    for (month, account), total in sorted(category_spending.items())
]
```
Sort by `(month, category)` for stable ordering.

**`cashFlowHistory` construction** (in `build_dashboard_overview`):

Collect all month keys present in either `monthly_income` or `monthly_spending`. For each month, emit income, spending, net, and a short label. Sort chronologically.
```python
all_months = sorted(set(monthly_income.keys()) | set(monthly_spending.keys()))
cash_flow_history = [
    {
        "month": month_key,
        "label": date(int(month_key[:4]), int(month_key[5:7]), 1).strftime("%b"),
        "income": amount_to_number(monthly_income.get(month_key, Decimal("0"))),
        "spending": amount_to_number(monthly_spending.get(month_key, Decimal("0"))),
        "net": amount_to_number(
            monthly_income.get(month_key, Decimal("0"))
            - monthly_spending.get(month_key, Decimal("0"))
        ),
    }
    for month_key in all_months
]
```

**`GET /api/dashboard/transactions` logic:**

1. Load transactions via the cached `load_transactions` path.
2. Parse `period` as a month key (`"YYYY-MM"`). Validate format; return 422 if invalid.
3. Filter transactions to those where `posted_on` falls within the month.
4. If `category` is provided, further filter to transactions that have at least one posting whose `account` starts with the `category` value. This supports both exact matches (`Expenses:Food:Groceries`) and prefix matches (`Expenses:Food`).
5. For each matching transaction, determine the display fields using the same helpers as `build_dashboard_overview`: `_primary_posting`, `_primary_account_display`, `_transaction_category`.
6. Sort by date descending (most recent first within the month).
7. Return `total` (pre-pagination count), then slice by `offset` and `limit`.
8. Each transaction row:
   - `date`: ISO date string
   - `payee`: transaction payee
   - `amount`: primary posting amount (signed, via `amount_to_number`)
   - `category`: ledger account path of the expense/income posting
   - `categoryLabel`: pretty name via `pretty_account_name`
   - `accountLabel`: display name of the primary account

**mtime cache:**

```python
import os
import threading

_tx_cache: list[ParsedTransaction] | None = None
_tx_cache_mtime: float | None = None
_tx_cache_lock = threading.Lock()

def get_transactions_cached(config: AppConfig) -> list[ParsedTransaction]:
    max_mtime = max(
        (os.path.getmtime(p) for p in config.journal_dir.glob("*.journal") if p.exists()),
        default=0.0,
    )
    with _tx_cache_lock:
        global _tx_cache, _tx_cache_mtime
        if _tx_cache is None or max_mtime != _tx_cache_mtime:
            _tx_cache = load_transactions(config)
            _tx_cache_mtime = max_mtime
        return _tx_cache
```

The cache checks the maximum mtime across all `.journal` files (not just one), since `load_transactions` reads all of them. Opening-balance journals live in a separate directory and are loaded via `include` directives, so their mtime is captured by the top-level journal file's mtime changing when the include is added.

### Outputs

- `GET /api/dashboard/overview` response gains two new top-level fields: `categoryHistory` (array) and `cashFlowHistory` (array). All existing fields unchanged.
- `GET /api/dashboard/transactions` returns `{ transactions, total, period, category }`.

## System Invariants

- Existing `categoryTrends`, `cashFlow.series`, `recentTransactions`, `balances`, and `summary` fields must remain byte-identical to their current values for the same input data and `today` parameter. The new fields are pure additions.
- `categoryHistory` amounts must be positive (absolute spending). This matches the sign convention of `category_spending` which accumulates expense posting amounts (already positive in the journal).
- `cashFlowHistory` income values must be positive (negated from the journal's negative income postings), matching the existing `cashFlow.series` sign convention.
- The cache must never serve stale data — if any journal file has been modified since the last parse, the cache must miss and re-parse.
- The transactions endpoint must not return opening-balance transactions (consistent with `build_dashboard_overview` which skips them via `is_generated_opening_balance_transaction`).
- `period` filtering is inclusive of the full month: day 1 through the last day of the month.

## States

- **Default (overview):** `categoryHistory` and `cashFlowHistory` are present in every response. Empty arrays when `hasData` is false.
- **Transactions endpoint — success:** returns matching transactions with count.
- **Transactions endpoint — no matches:** returns `{ transactions: [], total: 0, period: "...", category: "..." }`.
- **Transactions endpoint — invalid period format:** 422 with descriptive error message.
- **Error (commodity mismatch):** existing 400 behavior unchanged. New fields are not computed if the error is raised during the accumulation loop (which runs before the new code).

## Edge Cases

- **No journal data:** `categoryHistory` and `cashFlowHistory` are empty arrays. Transactions endpoint returns empty for any period. Cache stores the empty list with mtime 0.0.
- **Single month of data:** `cashFlowHistory` has one entry. `categoryHistory` has entries only for that month's categories.
- **Opening-balance transactions:** excluded from `categoryHistory` (they are already excluded from `category_spending` by the `is_opening_balance` check at line 192), excluded from the transactions endpoint response, but their account balance contributions are unchanged.
- **Transfer transactions (no expense/income posting):** not present in `categoryHistory` (only expense postings feed `category_spending`). In the transactions endpoint, `_transaction_category` returns `("Transfer", False)` — they appear in period queries but are filtered out by a `category` param since they have no expense/income account path.
- **Cache with no journal files:** `max()` returns default `0.0`. Cache holds empty list. No crash.
- **Concurrent requests during cache miss:** Lock serializes. Second request waits for first parse to complete, then gets the cached result.
- **Journal file deleted between cache check and parse:** `load_transactions` handles missing files gracefully (line 221: `if not journal_path.exists(): continue`). Cache stores whatever `load_transactions` returns.

## Failure Behavior

- If `period` query param is missing or malformed (not `YYYY-MM`), return HTTP 422 with `"Invalid period format. Expected YYYY-MM."`.
- If `limit` or `offset` are negative, clamp to 0.
- If `category` does not match any postings, return empty results (not an error).
- `CommodityMismatchError` in `build_dashboard_overview` continues to raise HTTP 400 as today. The new fields do not introduce new commodity-mismatch paths since they reuse `category_spending` and `monthly_income`/`monthly_spending` which already validate.

## Regression Risks

- **Payload size increase.** `categoryHistory` adds ~480 rows for a 24-month × 20-category journal. This is small (~20KB), but verify the response time does not degrade noticeably for the existing test fixture.
- **Existing field mutation.** The new code must not change the computation of `categoryTrends`, `cashFlow`, `balances`, `summary`, or `recentTransactions`. Existing tests serve as the regression gate.
- **Cache correctness.** A bug in mtime comparison (e.g., checking only one file instead of `max`) could serve stale data after an import. The cache must check all journal files.
- **Thread safety.** The lock must protect both the read and write of `_tx_cache` and `_tx_cache_mtime`. A race condition here could serve a partially-constructed list.

## Acceptance Criteria

- `GET /api/dashboard/overview` response includes `categoryHistory` array with entries for every `(month, category)` pair in the journal's expense history.
- Each `categoryHistory` entry has `month` (string), `category` (string, ledger account path), `categoryLabel` (string, pretty name), `amount` (number, positive).
- `GET /api/dashboard/overview` response includes `cashFlowHistory` array with entries for every month that has income or spending activity.
- Each `cashFlowHistory` entry has `month`, `label`, `income`, `spending`, `net` — matching the shape of existing `cashFlow.series` entries.
- `GET /api/dashboard/transactions?period=2026-03` returns transactions for March 2026 with correct `total` count.
- `GET /api/dashboard/transactions?period=2026-03&category=Expenses:Food:Groceries` returns only grocery transactions in March.
- `GET /api/dashboard/transactions?period=2026-03&limit=2&offset=0` returns at most 2 transactions.
- `GET /api/dashboard/transactions` without `period` returns HTTP 422.
- `GET /api/dashboard/transactions?period=invalid` returns HTTP 422.
- All existing `test_dashboard_service.py` tests pass without modification (regression gate).
- At least 6 new tests covering: `categoryHistory` content, `cashFlowHistory` content, empty journal, transactions endpoint with and without category filter, transactions endpoint with invalid period.
- `uv run pytest -q` passes.

## Proposed Sequence

1. **Add mtime cache.** Add `get_transactions_cached()` to `journal_query_service.py`. Update `build_dashboard_overview` to call it instead of `load_transactions` directly. Run existing tests — they must pass unchanged (cache is transparent).

2. **Add `categoryHistory` to the overview response.** After the existing accumulation loop in `build_dashboard_overview`, construct the `categoryHistory` array from `category_spending`. Add it to the return dict. Write tests asserting correct content for the existing test fixture.

3. **Add `cashFlowHistory` to the overview response.** Construct from `monthly_income` and `monthly_spending` — all months, not windowed. Add to return dict. Write tests.

4. **Add `GET /api/dashboard/transactions` endpoint.** Register in `main.py`. Implement the filtering, pagination, and response construction. The handler calls `get_transactions_cached()`, filters, and returns. Write tests for period filtering, category filtering, pagination, empty results, and invalid period.

5. **Run full test suite.** Verify all existing dashboard tests pass unchanged. Verify no regressions in other test files.

## Definition of Done

- All acceptance criteria pass.
- Existing dashboard tests pass without modification — confirms the new fields are pure additions with no side effects on existing response shape.
- The transactions endpoint handles all documented error cases (missing period, invalid format).
- The mtime cache is thread-safe and does not serve stale data.
- `uv run pytest -q` passes.

## Out of Scope

- Frontend consumption of `categoryHistory`, `cashFlowHistory`, or the transactions endpoint.
- Removal of deprecated fields (`categoryTrends`, `cashFlow.series`).
- Weekly/daily period granularity in the transactions endpoint.
- Any changes to the direction endpoint, transactions endpoint (`/api/transactions`), or activity endpoint.
- ECharts installation or any frontend dependency changes.
