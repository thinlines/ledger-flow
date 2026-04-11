from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .config_service import AppConfig
from .dashboard_service import (
    _primary_posting,
    _primary_account_display,
    _transaction_category,
    _account_kind,
)
from .journal_query_service import (
    amount_to_number,
    is_generated_opening_balance_transaction,
    load_transactions,
    ParsedTransaction,
)


@dataclass(frozen=True)
class PeriodRange:
    start: date
    end: date  # inclusive


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + offset
    shifted_year, shifted_month_index = divmod(total, 12)
    return shifted_year, shifted_month_index + 1


def _last_day_of_month(value: date) -> date:
    _, last = calendar.monthrange(value.year, value.month)
    return date(value.year, value.month, last)


def _first_of_month(year: int, month: int) -> date:
    return date(year, month, 1)


def _resolve_current_range(
    month: str | None, period: str, today: date
) -> PeriodRange:
    if month:
        year_str, month_str = month.split("-")
        start = _first_of_month(int(year_str), int(month_str))
        end = _last_day_of_month(start)
        return PeriodRange(start, end)
    if period == "this-month":
        start = today.replace(day=1)
        return PeriodRange(start, today)
    if period == "last-30":
        start = today - timedelta(days=29)
        return PeriodRange(start, today)
    # default: last-3-months
    start_year, start_month = _shift_month(today.year, today.month, -2)
    start = _first_of_month(start_year, start_month)
    return PeriodRange(start, today)


def _resolve_prior_range(
    month: str | None,
    period: str,
    today: date,
    current: PeriodRange,
) -> PeriodRange:
    if month:
        prior_year, prior_month = _shift_month(current.start.year, current.start.month, -1)
        prior_start = _first_of_month(prior_year, prior_month)
        prior_end = _last_day_of_month(prior_start)
        return PeriodRange(prior_start, prior_end)
    if period == "this-month":
        prior_year, prior_month = _shift_month(current.start.year, current.start.month, -1)
        prior_start = _first_of_month(prior_year, prior_month)
        # Match day-of-month in prior month, or clamp to last day if shorter.
        _, last_day = calendar.monthrange(prior_year, prior_month)
        prior_end = date(prior_year, prior_month, min(current.end.day, last_day))
        return PeriodRange(prior_start, prior_end)
    if period == "last-30":
        prior_start = today - timedelta(days=59)
        prior_end = today - timedelta(days=30)
        return PeriodRange(prior_start, prior_end)
    # default: last-3-months — prior covers the 3 full calendar months before current.start
    prior_start_year, prior_start_month = _shift_month(
        current.start.year, current.start.month, -3
    )
    prior_start = _first_of_month(prior_start_year, prior_start_month)
    prior_end_year, prior_end_month = _shift_month(
        current.start.year, current.start.month, -1
    )
    prior_end = _last_day_of_month(_first_of_month(prior_end_year, prior_end_month))
    return PeriodRange(prior_start, prior_end)


def _rolling_window_months(current_start: date, count: int = 6) -> list[str]:
    """Return YYYY-MM keys for the `count` calendar months immediately before `current_start`'s month."""
    months: list[str] = []
    for offset in range(-count, 0):
        year, month = _shift_month(current_start.year, current_start.month, offset)
        months.append(f"{year:04d}-{month:02d}")
    return months


def _matches_category(transaction: ParsedTransaction, category: str) -> bool:
    return any(
        posting.account == category or posting.account.startswith(category + ":")
        for posting in transaction.postings
    )


def _build_row(transaction: ParsedTransaction, config: AppConfig) -> dict:
    primary = _primary_posting(transaction, config)
    primary_amount = (
        primary.amount if primary and primary.amount is not None else Decimal("0")
    )
    account_label, import_account_id = _primary_account_display(primary, config)
    category_label, is_unknown = _transaction_category(transaction)

    category_account = ""
    expense_postings = [
        p for p in transaction.postings if _account_kind(p.account) == "expense"
    ]
    if expense_postings:
        category_account = expense_postings[0].account
    else:
        income_postings = [
            p for p in transaction.postings if _account_kind(p.account) == "income"
        ]
        if income_postings:
            category_account = income_postings[0].account

    return {
        "date": transaction.posted_on.isoformat(),
        "payee": transaction.payee,
        "accountLabel": account_label,
        "importAccountId": import_account_id,
        "category": category_label,
        "categoryAccount": category_account,
        "amount": amount_to_number(primary_amount),
        "isIncome": primary_amount > 0,
        "isUnknown": is_unknown,
    }


def _rows_in_range(rows: list[dict], window: PeriodRange) -> list[dict]:
    return [
        row
        for row in rows
        if window.start <= date.fromisoformat(row["date"]) <= window.end
    ]


def _build_summary(
    all_rows: list[dict],
    current_rows: list[dict],
    current_range: PeriodRange,
    prior_range: PeriodRange,
) -> dict | None:
    if not current_rows:
        return None

    period_total = sum(row["amount"] for row in current_rows)
    period_count = len(current_rows)
    average_amount = period_total / period_count if period_count else 0.0

    prior_rows = _rows_in_range(all_rows, prior_range)
    if prior_rows:
        prior_total: float | None = sum(row["amount"] for row in prior_rows)
        prior_count: int | None = len(prior_rows)
    else:
        has_earlier_data = any(
            date.fromisoformat(row["date"]) < current_range.start for row in all_rows
        )
        if has_earlier_data:
            prior_total = 0.0
            prior_count = 0
        else:
            prior_total = None
            prior_count = None

    if prior_total is None:
        delta_amount: float | None = None
        delta_percent: float | None = None
    else:
        delta_amount = period_total - prior_total
        if prior_total != 0:
            delta_percent = ((period_total - prior_total) / abs(prior_total)) * 100.0
        else:
            delta_percent = None

    rolling_keys = _rolling_window_months(current_range.start)
    monthly_totals: dict[str, float] = {key: 0.0 for key in rolling_keys}
    monthly_counts: dict[str, int] = {key: 0 for key in rolling_keys}
    for row in all_rows:
        month_key = row["date"][:7]
        if month_key in monthly_totals:
            monthly_totals[month_key] += row["amount"]
            monthly_counts[month_key] += 1
    months_with_data = [key for key in rolling_keys if monthly_counts[key] > 0]
    if len(months_with_data) >= 2:
        rolling_total = sum(monthly_totals[key] for key in months_with_data)
        rolling_monthly_average: float | None = rolling_total / len(months_with_data)
    else:
        rolling_monthly_average = None
    rolling_months = len(months_with_data)

    top_transaction: dict | None = None
    top_row = max(current_rows, key=lambda row: abs(row["amount"]))
    if abs(top_row["amount"]) > 0:
        top_transaction = {
            "date": top_row["date"],
            "payee": top_row["payee"],
            "amount": top_row["amount"],
            "accountLabel": top_row["accountLabel"],
        }

    return {
        "periodTotal": round(period_total, 2),
        "periodCount": period_count,
        "averageAmount": round(average_amount, 2),
        "priorPeriodTotal": (
            round(prior_total, 2) if prior_total is not None else None
        ),
        "priorPeriodCount": prior_count,
        "deltaAmount": (
            round(delta_amount, 2) if delta_amount is not None else None
        ),
        "deltaPercent": (
            round(delta_percent, 2) if delta_percent is not None else None
        ),
        "rollingMonthlyAverage": (
            round(rolling_monthly_average, 2)
            if rolling_monthly_average is not None
            else None
        ),
        "rollingMonths": rolling_months,
        "topTransaction": top_transaction,
    }


def build_activity_view(
    config: AppConfig,
    *,
    category: str | None = None,
    month: str | None = None,
    period: str | None = None,
    today: date | None = None,
) -> dict:
    current_day = today or date.today()
    effective_period = period or "last-3-months"
    transactions = load_transactions(config)

    current_range = _resolve_current_range(month, effective_period, current_day)
    prior_range = _resolve_prior_range(month, effective_period, current_day, current_range)

    # Single pass: build row dicts for every transaction that passes the category filter.
    all_rows: list[dict] = []
    for transaction in transactions:
        if is_generated_opening_balance_transaction(transaction):
            continue
        if category and not _matches_category(transaction, category):
            continue
        all_rows.append(_build_row(transaction, config))

    current_rows = _rows_in_range(all_rows, current_range)
    current_rows.sort(key=lambda row: row["date"], reverse=True)

    summary = _build_summary(all_rows, current_rows, current_range, prior_range)

    return {
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "period": effective_period if not month else None,
        "category": category,
        "month": month,
        "transactions": current_rows,
        "totalCount": len(current_rows),
        "summary": summary,
    }
