from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .config_service import AppConfig
from .header_parser import TransactionStatus
from .journal_query_service import (
    amount_to_number,
    is_generated_opening_balance_transaction,
    pretty_account_name,
)
from .projection_service import load_transactions_projected
from .search_parser import SearchTerm, parse_search
from .transaction_helpers import (
    RegisterEvent,
    account_amount,
    bilateral_matched_pending_transfer_orders,
    detail_lines,
    direct_transfer_event_for_peer_account,
    grouped_settled_pending_transfer_orders,
    opening_balance_detail_line,
    pending_transfer_event_for_peer_account,
    transaction_summary,
)
from .transfer_service import (
    is_transfer_account,
    parse_transfer_metadata,
)


@dataclass(frozen=True)
class PeriodRange:
    start: date
    end: date  # inclusive


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + offset
    shifted_year, shifted_month_index = divmod(total, 12)
    return shifted_year, shifted_month_index + 1


def _first_of_month(year: int, month: int) -> date:
    return date(year, month, 1)


def _last_day_of_month(value: date) -> date:
    _, last = calendar.monthrange(value.year, value.month)
    return date(value.year, value.month, last)


def _month_range(year: int, month: int) -> PeriodRange:
    """The full calendar month containing `year`-`month`."""
    start = _first_of_month(year, month)
    return PeriodRange(start, _last_day_of_month(start))


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
    is_assertion: bool = False


def _resolve_date_range(
    filters: UnifiedTransactionFilters,
    today: date,
) -> PeriodRange | None:
    """Resolve filters into a date range, or None if no date filter is active."""
    if filters.month:
        year_str, month_str = filters.month.split("-")
        return _month_range(int(year_str), int(month_str))

    if filters.from_date or filters.to_date:
        return PeriodRange(filters.from_date or date.min, filters.to_date or today)

    if filters.period:
        return _resolve_period(filters.period, today)

    return None


def _resolve_period(period: str, today: date) -> PeriodRange:
    """Resolve a named relative period into a range ending today.

    An unrecognized name falls back to last-3-months.
    """
    if period == "this-month":
        return PeriodRange(today.replace(day=1), today)
    if period == "last-30":
        return PeriodRange(today - timedelta(days=29), today)
    if period == "this-year":
        return PeriodRange(date(today.year, 1, 1), today)
    months_back = 5 if period == "last-6-months" else 2
    start_year, start_month = _shift_month(today.year, today.month, -months_back)
    return PeriodRange(_first_of_month(start_year, start_month), today)


def build_unified_transactions(
    config: AppConfig,
    filters: UnifiedTransactionFilters,
    *,
    today: date | None = None,
) -> dict:
    current_day = today or date.today()

    # 1. Load all transactions (served from the journal projection).
    transactions = load_transactions_projected(config)

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
        tracked = config.account(account_id)
        ledger_acct = tracked.ledger_account
        display_name = tracked.display_name
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

            if is_primary_opening:
                offset_account = other_postings[0].account if other_postings else ""
                summary = "Starting point for this account"
                is_unknown = False
                transfer_state = None
                transfer_peer_account_id = None
                transfer_peer_name = None
                dl = [opening_balance_detail_line(config, offset_account)]
            else:
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

            is_assertion = bool(
                str(transaction.metadata.get("lf_operation_id") or "").strip()
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
                clearing_status=transaction.status.value,
                header_line=transaction.header_line,
                journal_path=transaction.source_journal,
                match_id=transaction.metadata.get("match-id") or None,
                notes=transaction.metadata.get("notes") or None,
                statement_payee=transaction.metadata.get("statement_payee") or None,
                counts_as_transaction=not is_generated_opening,
                txn_id=transaction.txn_id,
                block_hash=transaction.block_hash,
            )
            unified_rows.append(_UnifiedRow(
                event=event,
                account_id=acct_id,
                account_label=acct_display_name,
                categories=categories,
                is_transfer=is_transfer,
                is_manual=is_manual,
                is_assertion=is_assertion,
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
        summary = _build_unified_summary(rows)

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
        return _month_range(today.year, today.month)
    if val == "last-month":
        return _month_range(*_shift_month(today.year, today.month, -1))
    if val == "this-year":
        return PeriodRange(date(today.year, 1, 1), date(today.year, 12, 31))
    # YYYY-MM
    if len(val) == 7 and val[4:5] == "-":
        try:
            return _month_range(int(val[:4]), int(val[5:7]))
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

    balance = Decimal(0)
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
            "isAssertion": urow.is_assertion,
            "legs": [{
                "journalPath": ev.journal_path,
                "txnId": ev.txn_id,
                "blockHash": ev.block_hash,
            }],
            "matchId": ev.match_id,
            "transferState": ev.transfer_state,
            "detailLines": ev.detail_lines,
            "notes": ev.notes,
            "statementPayee": ev.statement_payee,
        })

    return (rows, multi_currency)


def _build_unified_summary(rows: list[dict]) -> dict | None:
    """Totals across the rows left after filtering, or None when there are none."""
    if not rows:
        return None

    period_total = sum(row["amount"] for row in rows)
    period_count = len(rows)

    top_row = max(rows, key=lambda row: abs(row["amount"]))
    top_transaction = None
    if abs(top_row["amount"]) > 0:
        top_transaction = {
            "date": top_row["date"],
            "payee": top_row["payee"],
            "amount": top_row["amount"],
            "accountLabel": top_row["account"]["label"],
        }

    return {
        "periodTotal": round(period_total, 2),
        "periodCount": period_count,
        "averageAmount": round(period_total / period_count, 2),
        "topTransaction": top_transaction,
    }


def _build_account_meta(
    unified_rows: list[_UnifiedRow],
    account_id: str,
    multi_currency: bool,
) -> dict:
    """Build account metadata when exactly one account is scoped."""
    balance = Decimal(0)
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
