from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .commodity_service import CommodityMismatchError, commodity_label
from .config_service import AppConfig, infer_account_kind
from .header_parser import TransactionStatus
from .journal_query_service import (
    amount_to_number,
    is_generated_opening_balance_transaction,
    load_transactions,
    pretty_account_name,
)
from .transaction_helpers import (
    RegisterEvent,
    account_amount,
    bilateral_matched_pending_transfer_orders,
    detail_lines,
    direct_transfer_event_for_peer_account,
    grouped_settled_pending_transfer_orders,
    manual_resolution_note,
    manual_resolution_token,
    opening_balance_detail_line,
    pending_transfer_event_for_peer_account,
    source_tracked_account_details,
    tracked_account_display,
    transaction_summary,
)
from .search_parser import SearchTerm, parse_search
from .transfer_service import (
    is_transfer_account,
    parse_transfer_metadata,
)
from .activity_service import (
    PeriodRange,
    _shift_month as shift_month,
    _last_day_of_month as last_day_of_month,
    _first_of_month as first_of_month,
    _resolve_current_range as resolve_current_range,
    _resolve_prior_range as resolve_prior_range,
    _build_summary as build_summary,
    _rows_in_range as rows_in_range,
    _rolling_window_months as rolling_window_months,
    _matches_category as matches_category,
)


@dataclass(frozen=True)
class UnifiedTransactionFilters:
    accounts: list[str]        # tracked account IDs, empty = all
    categories: list[str]      # category account prefixes
    period: str | None         # this-month, last-30, last-3-months, last-6-months, this-year
    from_date: date | None     # custom range start
    to_date: date | None       # custom range end
    month: str | None          # YYYY-MM shorthand
    status: list[str] | None   # cleared, pending, unmarked
    search: str | None         # payee text match


@dataclass(frozen=True)
class _UnifiedRow:
    """Internal composite holding a RegisterEvent plus unified-endpoint-specific fields."""
    event: RegisterEvent
    account_id: str
    account_label: str
    categories: list[dict]
    is_transfer: bool
    is_manual: bool


def _resolve_date_range(
    filters: UnifiedTransactionFilters,
    today: date,
) -> PeriodRange | None:
    """Resolve filters into a date range, or None if no date filter is active."""
    if filters.month:
        year_str, month_str = filters.month.split("-")
        start = first_of_month(int(year_str), int(month_str))
        end = last_day_of_month(start)
        return PeriodRange(start, end)

    if filters.from_date or filters.to_date:
        start = filters.from_date or date.min
        end = filters.to_date or today
        return PeriodRange(start, end)

    if filters.period:
        if filters.period == "last-6-months":
            start_year, start_month = shift_month(today.year, today.month, -5)
            start = first_of_month(start_year, start_month)
            return PeriodRange(start, today)
        if filters.period == "this-year":
            start = date(today.year, 1, 1)
            return PeriodRange(start, today)
        return resolve_current_range(None, filters.period, today)

    return None


def _resolve_prior_range_for_filters(
    filters: UnifiedTransactionFilters,
    today: date,
    current: PeriodRange,
) -> PeriodRange:
    """Resolve the prior comparison range for summary computation."""
    if filters.month:
        return resolve_prior_range(filters.month, "last-3-months", today, current)

    if filters.from_date or filters.to_date:
        # Custom range: prior range is same-length window ending the day before current starts.
        duration = (current.end - current.start).days
        prior_end = current.start - timedelta(days=1)
        prior_start = prior_end - timedelta(days=duration)
        return PeriodRange(prior_start, prior_end)

    if filters.period:
        if filters.period == "last-6-months":
            start_year, start_month = shift_month(current.start.year, current.start.month, -6)
            prior_start = first_of_month(start_year, start_month)
            end_year, end_month = shift_month(current.start.year, current.start.month, -1)
            prior_end = last_day_of_month(first_of_month(end_year, end_month))
            return PeriodRange(prior_start, prior_end)
        if filters.period == "this-year":
            prior_start = date(today.year - 1, 1, 1)
            _, last_day = calendar.monthrange(today.year - 1, today.month)
            prior_end = date(today.year - 1, today.month, min(today.day, last_day))
            return PeriodRange(prior_start, prior_end)
        return resolve_prior_range(None, filters.period, today, current)

    # No date filter — should not be called, but handle gracefully.
    return PeriodRange(current.start, current.end)


def build_unified_transactions(
    config: AppConfig,
    filters: UnifiedTransactionFilters,
    *,
    today: date | None = None,
) -> dict:
    current_day = today or date.today()

    # 1. Load all transactions.
    transactions = load_transactions(config)

    # 2. Determine scope accounts.
    if filters.accounts:
        scope_account_ids = []
        for account_id in filters.accounts:
            if account_id not in config.tracked_accounts:
                raise ValueError(f"Tracked account not found: {account_id}")
            scope_account_ids.append(account_id)
    else:
        scope_account_ids = list(config.tracked_accounts.keys())

    scope_ledger_accounts: dict[str, tuple[str, str]] = {}
    for account_id in scope_account_ids:
        tracked = config.tracked_accounts[account_id]
        ledger_acct = str(tracked.get("ledger_account", "")).strip()
        display_name = str(tracked.get("display_name", account_id))
        if ledger_acct:
            scope_ledger_accounts[ledger_acct] = (account_id, display_name)

    single_account_scope = len(scope_account_ids) == 1

    # 3. Compute grouped-settlement and bilateral-match orders.
    grouped_settled_orders = grouped_settled_pending_transfer_orders(config, transactions)
    bilateral_matched_orders = bilateral_matched_pending_transfer_orders(config, transactions, grouped_settled_orders)
    pending_excluded_orders = grouped_settled_orders | bilateral_matched_orders

    # 4. Build rows.
    unified_rows: list[_UnifiedRow] = []

    for order, transaction in enumerate(transactions):
        found_in_scope = False
        for ledger_account, (acct_id, acct_display_name) in scope_ledger_accounts.items():
            amount, commodity = account_amount(transaction, ledger_account)
            if amount is None:
                continue

            found_in_scope = True
            other_postings = [posting for posting in transaction.postings if posting.account != ledger_account]
            is_generated_opening = is_generated_opening_balance_transaction(transaction)
            opening_account_id = str(transaction.metadata.get("tracked_account_id", "")).strip() or None
            is_primary_opening = is_generated_opening and opening_account_id == acct_id
            token = None

            if is_primary_opening:
                offset_account = other_postings[0].account if other_postings else ""
                summary = "Starting point for this account"
                is_unknown = False
                transfer_state = None
                transfer_peer_account_id = None
                transfer_peer_name = None
                dl = [opening_balance_detail_line(config, offset_account)]
            else:
                token = manual_resolution_token(
                    config,
                    transaction,
                    grouped_settled=order in pending_excluded_orders,
                )
                summary, is_unknown, transfer_state, transfer_peer_account_id, transfer_peer_name = transaction_summary(
                    config,
                    transaction,
                    other_postings,
                    acct_id,
                    grouped_settled=order in grouped_settled_orders,
                    bilateral_matched=order in bilateral_matched_orders,
                )
                if is_generated_opening:
                    is_unknown = False
                dl = detail_lines(config, transaction, other_postings, acct_id)

            categories = _build_categories(transaction, ledger_account)
            transfer = parse_transfer_metadata(transaction.metadata, config.tracked_accounts)
            is_transfer = bool(transfer.peer_account_id)
            has_import = bool(str(transaction.metadata.get("import_account_id") or "").strip())
            is_manual = (
                transaction.status == TransactionStatus.unmarked
                and not has_import
                and not is_generated_opening
            )

            event = RegisterEvent(
                posted_on=transaction.posted_on,
                order=order,
                amount=amount,
                commodity=commodity,
                payee=transaction.payee,
                summary=summary,
                is_unknown=is_unknown,
                is_opening_balance=is_primary_opening,
                detail_lines=dl,
                transfer_state=transfer_state,
                transfer_peer_account_id=transfer_peer_account_id,
                transfer_peer_account_name=transfer_peer_name,
                manual_resolution_token=token,
                manual_resolution_note=manual_resolution_note(transaction),
                clearing_status=transaction.status.value,
                header_line=transaction.header_line,
                journal_path=transaction.source_journal,
                header_line_number=transaction.header_line_number,
                match_id=transaction.metadata.get("match-id") or None,
                notes=transaction.metadata.get("notes") or None,
                counts_as_transaction=not is_generated_opening,
            )
            unified_rows.append(_UnifiedRow(
                event=event,
                account_id=acct_id,
                account_label=acct_display_name,
                categories=categories,
                is_transfer=is_transfer,
                is_manual=is_manual,
            ))
            break  # Only count once per transaction

        if found_in_scope:
            continue

        # Synthetic peer rows — only in single-account scope.
        if single_account_scope:
            acct_id = scope_account_ids[0]
            acct_cfg = config.tracked_accounts.get(acct_id, {})
            acct_label = str(acct_cfg.get("display_name", acct_id))

            pending_peer_event = pending_transfer_event_for_peer_account(
                config, transaction, acct_id, order, pending_excluded_orders,
            )
            if pending_peer_event is not None:
                unified_rows.append(_UnifiedRow(
                    event=pending_peer_event,
                    account_id=acct_id,
                    account_label=acct_label,
                    categories=[],
                    is_transfer=True,
                    is_manual=False,
                ))
                continue

            direct_peer_event = direct_transfer_event_for_peer_account(config, transaction, acct_id, order)
            if direct_peer_event is not None:
                unified_rows.append(_UnifiedRow(
                    event=direct_peer_event,
                    account_id=acct_id,
                    account_label=acct_label,
                    categories=[],
                    is_transfer=True,
                    is_manual=False,
                ))

    # 5. Apply filters.
    search_terms = parse_search(filters.search or "")

    # date: and status: formula terms override their chip counterparts.
    date_search_terms = [t for t in search_terms if t.field == "date"]
    status_search_terms = [t for t in search_terms if t.field == "status"]

    if date_search_terms:
        # Search formula date term overrides chip date filters.
        date_range = _resolve_search_date_range(date_search_terms[0], current_day)
    else:
        date_range = _resolve_date_range(filters, current_day)

    if date_range is not None:
        unified_rows = [r for r in unified_rows if date_range.start <= r.event.posted_on <= date_range.end]

    if filters.categories:
        unified_rows = _filter_by_categories(unified_rows, filters.categories)

    if status_search_terms:
        # Search formula status term overrides chip status filter.
        status_set = {t.value for t in status_search_terms}
        unified_rows = [r for r in unified_rows if r.event.clearing_status in status_set]
    elif filters.status:
        status_set = set(filters.status)
        unified_rows = [r for r in unified_rows if r.event.clearing_status in status_set]

    # Apply remaining (non-date, non-status) search terms.
    non_override_terms = [t for t in search_terms if t.field not in ("date", "status")]
    if non_override_terms:
        unified_rows = _apply_search_terms(unified_rows, non_override_terms)

    # 6. Sort.
    unified_rows.sort(key=lambda r: (r.event.posted_on, r.event.order))

    # 7. Compute running balance.
    rows, multi_currency = _compute_rows_with_balance(unified_rows)

    # 8. Summary.
    summary = None
    if date_range is not None:
        summary = _build_unified_summary(rows, filters, current_day, date_range)

    # 9. Account metadata.
    account_meta = None
    if single_account_scope:
        account_meta = _build_account_meta(unified_rows, scope_account_ids[0], multi_currency)

    # 10. Serialize — rows reversed (newest first).
    serialized_rows = list(reversed(rows))

    return {
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "filters": {
            "accounts": filters.accounts,
            "categories": filters.categories,
            "period": filters.period,
            "month": filters.month,
            "status": filters.status,
            "search": filters.search,
        },
        "rows": serialized_rows,
        "totalCount": len(serialized_rows),
        "summary": summary,
        "accountMeta": account_meta,
    }


# -- Internal helpers --


def _resolve_search_date_range(term: SearchTerm, today: date) -> PeriodRange | None:
    """Resolve a date: search term into a PeriodRange."""
    val = term.value
    if val == "this-month":
        start = first_of_month(today.year, today.month)
        end = last_day_of_month(start)
        return PeriodRange(start, end)
    if val == "last-month":
        y, m = shift_month(today.year, today.month, -1)
        start = first_of_month(y, m)
        end = last_day_of_month(start)
        return PeriodRange(start, end)
    if val == "this-year":
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
        return PeriodRange(start, end)
    # YYYY-MM
    if len(val) == 7 and val[4:5] == "-":
        try:
            y, m = int(val[:4]), int(val[5:7])
            start = first_of_month(y, m)
            end = last_day_of_month(start)
            return PeriodRange(start, end)
        except (ValueError, OverflowError):
            return None
    # YYYY-MM-DD
    if len(val) == 10 and val[4:5] == "-" and val[7:8] == "-":
        try:
            d = date.fromisoformat(val)
            return PeriodRange(d, d)
        except ValueError:
            return None
    return None


def _apply_search_terms(
    rows: list[_UnifiedRow],
    terms: list[SearchTerm],
) -> list[_UnifiedRow]:
    """Filter rows by AND-combining all search terms."""
    for term in terms:
        rows = [r for r in rows if _row_matches_term(r, term)]
    return rows


def _row_matches_term(row: _UnifiedRow, term: SearchTerm) -> bool:
    """Test whether a single unified row matches a single search term."""
    if term.field == "payee":
        return term.value.lower() in row.event.payee.lower()

    if term.field == "amount":
        abs_amount = abs(row.event.amount)
        if term.operator == "gt":
            return abs_amount > term.value_num
        if term.operator == "lt":
            return abs_amount < term.value_num
        if term.operator == "gte":
            return abs_amount >= term.value_num
        if term.operator == "lte":
            return abs_amount <= term.value_num
        if term.operator == "eq":
            return abs_amount == term.value_num
        if term.operator == "range":
            return term.value_num <= abs_amount <= term.value_num_end
        return False

    if term.field == "category":
        val_lower = term.value.lower()
        for cat in row.categories:
            label = cat.get("label", "")
            if val_lower in label.lower():
                return True
        return False

    if term.field == "account":
        return term.value.lower() in row.account_label.lower()

    # date and status are handled before this function is called.
    return True


def _build_categories(transaction, tracked_ledger_account: str) -> list[dict]:
    """Build the N-1 categories list: all postings except the tracked-account posting
    and transfer-account postings."""
    categories = []
    for posting in transaction.postings:
        if posting.account == tracked_ledger_account:
            continue
        if is_transfer_account(posting.account):
            continue
        categories.append({
            "account": posting.account,
            "label": pretty_account_name(posting.account),
            "amount": amount_to_number(posting.amount) if posting.amount is not None else 0.0,
        })
    return categories


def _filter_by_categories(unified_rows: list[_UnifiedRow], categories: list[str]) -> list[_UnifiedRow]:
    """Keep rows where any category entry matches any of the category prefixes."""
    filtered = []
    for row in unified_rows:
        if _any_category_matches(row.categories, categories):
            filtered.append(row)
    return filtered


def _any_category_matches(categories: list[dict], prefixes: list[str]) -> bool:
    """Check if any category account matches any of the given prefixes."""
    for cat in categories:
        account = cat.get("account", "")
        for prefix in prefixes:
            if account == prefix or account.startswith(prefix + ":"):
                return True
    return False


def _compute_rows_with_balance(
    unified_rows: list[_UnifiedRow],
) -> tuple[list[dict], bool]:
    """Compute running balance and serialize unified rows to response row dicts.

    Returns (rows, multi_currency) where multi_currency indicates whether
    multiple commodities were detected across rows.
    """
    # Detect multi-commodity across all events.
    seen_commodity: str | None = None
    multi_currency = False
    for urow in unified_rows:
        ev = urow.event
        if ev.affects_balance and ev.commodity is not None:
            if seen_commodity is None:
                seen_commodity = ev.commodity
            elif seen_commodity != ev.commodity:
                multi_currency = True
                break

    balance = Decimal("0")
    rows: list[dict] = []
    for index, urow in enumerate(unified_rows):
        ev = urow.event
        if ev.affects_balance and not multi_currency:
            balance += ev.amount

        running_balance = None if multi_currency else amount_to_number(balance)

        transfer_peer = None
        if ev.transfer_peer_account_id:
            transfer_peer = {
                "id": ev.transfer_peer_account_id,
                "label": ev.transfer_peer_account_name or ev.transfer_peer_account_id,
            }

        rows.append({
            "id": f"{urow.account_id}-{ev.posted_on.isoformat()}-{index}",
            "date": ev.posted_on.isoformat(),
            "payee": ev.payee,
            "amount": amount_to_number(ev.amount),
            "runningBalance": running_balance,
            "account": {"id": urow.account_id, "label": urow.account_label},
            "transferPeer": transfer_peer,
            "categories": urow.categories,
            "status": ev.clearing_status,
            "isTransfer": urow.is_transfer,
            "isUnknown": ev.is_unknown,
            "isManual": urow.is_manual,
            "isOpeningBalance": ev.is_opening_balance,
            "legs": [{
                "journalPath": ev.journal_path,
                "headerLine": ev.header_line,
                "lineNumber": ev.header_line_number,
            }],
            "matchId": ev.match_id,
            "transferState": ev.transfer_state,
            "manualResolutionToken": ev.manual_resolution_token,
            "manualResolutionNote": ev.manual_resolution_note,
            "detailLines": ev.detail_lines,
            "notes": ev.notes,
        })

    return (rows, multi_currency)


def _build_unified_summary(
    rows: list[dict],
    filters: UnifiedTransactionFilters,
    today: date,
    current_range: PeriodRange,
) -> dict | None:
    """Build the summary block reusing activity service's _build_summary."""
    if not rows:
        return None

    prior_range = _resolve_prior_range_for_filters(filters, today, current_range)

    # Build summary-compatible rows: need "date", "payee", "accountLabel", "amount".
    summary_current_rows = [
        {
            "date": row["date"],
            "payee": row["payee"],
            "accountLabel": row["account"]["label"],
            "amount": row["amount"],
        }
        for row in rows
    ]

    # Pass current_rows as all_rows. The summary builder will compute prior_rows
    # from all_rows, which will be empty since all rows are in the current range.
    # This means prior comparison may show no data, which is acceptable.
    return build_summary(summary_current_rows, summary_current_rows, current_range, prior_range)


def _build_account_meta(
    unified_rows: list[_UnifiedRow],
    account_id: str,
    multi_currency: bool,
) -> dict:
    """Build account metadata when exactly one account is scoped."""
    balance = Decimal("0")
    entry_count = 0
    transaction_count = 0
    has_opening_balance = False
    has_balance_source = False
    latest_transaction_date: str | None = None
    latest_activity_date: str | None = None

    for urow in unified_rows:
        ev = urow.event
        entry_count += 1
        if ev.affects_balance and not multi_currency:
            balance += ev.amount
            has_balance_source = True
        elif ev.affects_balance:
            has_balance_source = True

        if ev.is_opening_balance:
            has_opening_balance = True

        if ev.counts_as_transaction and not ev.is_opening_balance:
            transaction_count += 1
            latest_transaction_date = ev.posted_on.isoformat()

    if unified_rows:
        latest_activity_date = max(r.event.posted_on for r in unified_rows).isoformat()

    current_balance = None if multi_currency else amount_to_number(balance)

    return {
        "accountId": account_id,
        "currentBalance": current_balance,
        "entryCount": entry_count,
        "transactionCount": transaction_count,
        "hasOpeningBalance": has_opening_balance,
        "hasTransactionActivity": transaction_count > 0,
        "hasBalanceSource": has_balance_source,
        "latestTransactionDate": latest_transaction_date,
        "latestActivityDate": latest_activity_date,
    }
