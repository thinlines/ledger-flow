from __future__ import annotations

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
    pretty_account_name,
)


def _resolve_period_range(
    period: str, today: date
) -> tuple[date, date]:
    if period == "this-month":
        start = today.replace(day=1)
        return start, today
    if period == "last-30":
        return today - timedelta(days=29), today
    # default: last-3-months
    month = today.month
    year = today.year
    total = year * 12 + (month - 1) - 2
    start_year, start_month_idx = divmod(total, 12)
    start = date(start_year, start_month_idx + 1, 1)
    return start, today


def build_activity_view(
    config: AppConfig,
    *,
    category: str | None = None,
    month: str | None = None,
    period: str | None = None,
    today: date | None = None,
) -> dict:
    current_day = today or date.today()
    transactions = load_transactions(config)

    effective_period = period or "last-3-months"

    rows: list[dict] = []

    for transaction in transactions:
        if is_generated_opening_balance_transaction(transaction):
            continue

        # Time filter
        if month:
            txn_month = transaction.posted_on.strftime("%Y-%m")
            if txn_month != month:
                continue
        else:
            start, end = _resolve_period_range(effective_period, current_day)
            if transaction.posted_on < start or transaction.posted_on > end:
                continue

        # Category filter
        if category:
            has_match = any(
                posting.account == category
                or posting.account.startswith(category + ":")
                for posting in transaction.postings
            )
            if not has_match:
                continue

        primary = _primary_posting(transaction, config)
        primary_amount = (
            primary.amount if primary and primary.amount is not None else Decimal("0")
        )
        account_label, import_account_id = _primary_account_display(primary, config)
        category_label, is_unknown = _transaction_category(transaction)

        # Build categoryAccount from the transaction
        category_account = ""
        expense_postings = [p for p in transaction.postings if _account_kind(p.account) == "expense"]
        if expense_postings:
            category_account = expense_postings[0].account
        else:
            income_postings = [p for p in transaction.postings if _account_kind(p.account) == "income"]
            if income_postings:
                category_account = income_postings[0].account

        rows.append(
            {
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
        )

    # Sort most-recent-first
    rows.sort(key=lambda r: r["date"], reverse=True)

    return {
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "period": effective_period if not month else None,
        "category": category,
        "month": month,
        "transactions": rows,
        "totalCount": len(rows),
    }
