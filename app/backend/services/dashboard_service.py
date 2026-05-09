from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from .commodity_service import CommodityMismatchError, commodity_label
from .config_service import AppConfig, infer_account_kind
from .journal_query_service import (
    ParsedTransaction,
    Posting,
    amount_to_number,
    get_transactions_cached,
    is_generated_opening_balance_transaction,
    pretty_account_name,
)
from .opening_balance_service import opening_balance_index
from .reconciliation_service import reconciliation_status as compute_reconciliation_status


def _account_kind(account: str) -> str:
    return infer_account_kind(account)


def _month_key(posted_on: date) -> str:
    return posted_on.strftime("%Y-%m")


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + offset
    shifted_year, shifted_month_index = divmod(total, 12)
    return shifted_year, shifted_month_index + 1


def _month_window(today: date, count: int) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    start_offset = -(count - 1)
    for offset in range(start_offset, 1):
        months.append(_shift_month(today.year, today.month, offset))
    return months


def _month_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%b")


def _accumulate_total(
    totals: defaultdict,
    commodities: dict,
    key,
    amount: Decimal,
    commodity: str | None,
    *,
    label: str,
) -> None:
    if key in commodities and commodities[key] != commodity:
        raise CommodityMismatchError(
            f"{label} mixes commodities ({commodity_label(commodities[key])} and {commodity_label(commodity)})."
        )
    commodities[key] = commodity
    totals[key] += amount


def _primary_posting(transaction: ParsedTransaction, config: AppConfig) -> Posting | None:
    import_account_id = transaction.metadata.get("import_account_id")
    if import_account_id and import_account_id in config.import_accounts:
        linked_tracked_account_id = (
            str(config.import_accounts[import_account_id].get("tracked_account_id", "")).strip() or import_account_id
        )
        tracked_account = str(
            config.tracked_accounts.get(linked_tracked_account_id, {}).get(
                "ledger_account",
                config.import_accounts[import_account_id].get("ledger_account", ""),
            )
        ).strip()
        if tracked_account:
            for posting in transaction.postings:
                if posting.account == tracked_account:
                    return posting

    tracked_accounts = {
        str(account_cfg.get("ledger_account", "")).strip()
        for account_cfg in config.tracked_accounts.values()
    }
    for posting in transaction.postings:
        if posting.account in tracked_accounts:
            return posting

    for posting in transaction.postings:
        if _account_kind(posting.account) in {"asset", "liability"}:
            return posting
    return transaction.postings[0] if transaction.postings else None


def _primary_account_display(posting: Posting | None, config: AppConfig) -> tuple[str, str | None]:
    if posting is None:
        return ("Unassigned account", None)

    for account_id, account_cfg in config.tracked_accounts.items():
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        if ledger_account == posting.account:
            return (str(account_cfg.get("display_name", account_id)), account_id)

    return (pretty_account_name(posting.account), None)


def _transaction_category(transaction: ParsedTransaction) -> tuple[str, bool]:
    expense_postings = [posting for posting in transaction.postings if _account_kind(posting.account) == "expense"]
    if expense_postings:
        account = expense_postings[0].account
        return (pretty_account_name(account), account.lower().startswith("expenses:unknown"))

    income_postings = [posting for posting in transaction.postings if _account_kind(posting.account) == "income"]
    if income_postings:
        return (pretty_account_name(income_postings[0].account), False)

    return ("Transfer", False)


def build_dashboard_overview(config: AppConfig, *, today: date | None = None) -> dict:
    current_day = today or date.today()
    transactions = get_transactions_cached(config)
    _, opening_by_ledger_account = opening_balance_index(config)
    opening_balance_accounts = set(opening_by_ledger_account)
    account_balances: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    account_balance_commodities: dict[str, str | None] = {}
    accounts_with_balance_source: set[str] = set()
    accounts_with_activity: set[str] = set()
    account_last_transaction: dict[str, date] = {}
    monthly_income: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    monthly_income_commodities: dict[str, str | None] = {}
    monthly_spending: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    monthly_spending_commodities: dict[str, str | None] = {}
    category_spending: defaultdict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    category_spending_commodities: dict[tuple[str, str], str | None] = {}
    unknown_transaction_count = 0
    recent_rows: list[dict] = []
    activity_transactions: list[ParsedTransaction] = []

    for transaction in transactions:
        is_opening_balance = is_generated_opening_balance_transaction(transaction)
        month = _month_key(transaction.posted_on)

        for posting in transaction.postings:
            if posting.amount is None:
                continue

            kind = _account_kind(posting.account)
            if kind in {"asset", "liability"}:
                _accumulate_total(
                    account_balances,
                    account_balance_commodities,
                    posting.account,
                    posting.amount,
                    posting.commodity,
                    label=f"Account {posting.account}",
                )
                accounts_with_balance_source.add(posting.account)
                if not is_opening_balance:
                    accounts_with_activity.add(posting.account)
                    if posting.account not in account_last_transaction or transaction.posted_on > account_last_transaction[posting.account]:
                        account_last_transaction[posting.account] = transaction.posted_on
            elif is_opening_balance:
                continue
            elif kind == "expense":
                _accumulate_total(
                    monthly_spending,
                    monthly_spending_commodities,
                    month,
                    posting.amount,
                    posting.commodity,
                    label=f"Monthly spending for {month}",
                )
                _accumulate_total(
                    category_spending,
                    category_spending_commodities,
                    (month, posting.account),
                    posting.amount,
                    posting.commodity,
                    label=f"Category spending for {posting.account} in {month}",
                )
            elif kind == "income":
                _accumulate_total(
                    monthly_income,
                    monthly_income_commodities,
                    month,
                    -posting.amount,
                    posting.commodity,
                    label=f"Monthly income for {month}",
                )

        if is_opening_balance:
            continue

        activity_transactions.append(transaction)
        category_label, is_unknown = _transaction_category(transaction)
        if is_unknown:
            unknown_transaction_count += 1

        primary = _primary_posting(transaction, config)
        primary_amount = primary.amount if primary and primary.amount is not None else Decimal("0")
        account_label, import_account_id = _primary_account_display(primary, config)
        recent_rows.append(
            {
                "date": transaction.posted_on.isoformat(),
                "payee": transaction.payee,
                "accountLabel": account_label,
                "importAccountId": import_account_id,
                "category": category_label,
                "amount": amount_to_number(primary_amount),
                "isIncome": primary_amount > 0,
                "isUnknown": is_unknown,
            }
        )

    current_month = f"{current_day.year:04d}-{current_day.month:02d}"
    previous_year, previous_month = _shift_month(current_day.year, current_day.month, -1)
    previous_month_key = f"{previous_year:04d}-{previous_month:02d}"

    reconciliation_status_map = compute_reconciliation_status(config)
    balances = []
    tracked_total = Decimal("0")
    tracked_total_commodity: str | None = None
    tracked_total_initialized = False
    for account_id, account_cfg in sorted(
        config.tracked_accounts.items(),
        key=lambda item: str(item[1].get("display_name", item[0])),
    ):
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        balance = account_balances.get(ledger_account, Decimal("0"))
        balance_commodity = account_balance_commodities.get(ledger_account)
        has_opening_balance = ledger_account in opening_balance_accounts
        has_transaction_activity = ledger_account in accounts_with_activity
        if ledger_account in account_balance_commodities:
            if tracked_total_initialized and tracked_total_commodity != balance_commodity:
                raise CommodityMismatchError(
                    "Tracked balances mix commodities "
                    f"({commodity_label(tracked_total_commodity)} and {commodity_label(balance_commodity)})."
                )
            tracked_total_initialized = True
            tracked_total_commodity = balance_commodity
        tracked_total += balance
        balances.append(
            {
                "id": account_id,
                "displayName": str(account_cfg.get("display_name", account_id)),
                "institutionId": str(account_cfg.get("institution", "")).strip() or None,
                "ledgerAccount": ledger_account,
                "last4": account_cfg.get("last4"),
                "kind": _account_kind(ledger_account),
                "balance": amount_to_number(balance),
                "importConfigured": bool(account_cfg.get("import_account_id")),
                "hasOpeningBalance": has_opening_balance,
                "hasTransactionActivity": has_transaction_activity,
                "hasBalanceSource": ledger_account in accounts_with_balance_source,
                "lastTransactionDate": account_last_transaction[ledger_account].isoformat() if ledger_account in account_last_transaction else None,
                "reconciliationStatus": reconciliation_status_map.get(account_id, {"ok": True}),
            }
        )

    net_worth = Decimal("0")
    net_worth_commodity: str | None = None
    net_worth_initialized = False
    for account, balance in account_balances.items():
        if _account_kind(account) not in {"asset", "liability"}:
            continue
        balance_commodity = account_balance_commodities.get(account)
        if net_worth_initialized and net_worth_commodity != balance_commodity:
            raise CommodityMismatchError(
                "Net worth mixes commodities "
                f"({commodity_label(net_worth_commodity)} and {commodity_label(balance_commodity)})."
            )
        net_worth_initialized = True
        net_worth_commodity = balance_commodity
        net_worth += balance

    series = []
    for year_value, month_value in _month_window(current_day, 6):
        key = f"{year_value:04d}-{month_value:02d}"
        income = monthly_income.get(key, Decimal("0"))
        spending = monthly_spending.get(key, Decimal("0"))
        series.append(
            {
                "month": key,
                "label": _month_label(year_value, month_value),
                "income": amount_to_number(income),
                "spending": amount_to_number(spending),
                "net": amount_to_number(income - spending),
            }
        )

    current_categories = {
        category: total
        for (month, category), total in category_spending.items()
        if month == current_month
    }
    previous_categories = {
        category: total
        for (month, category), total in category_spending.items()
        if month == previous_month_key
    }
    category_names = set(current_categories) | set(previous_categories)
    category_trends = []
    for category in sorted(
        category_names,
        key=lambda account: (
            current_categories.get(account, Decimal("0")),
            previous_categories.get(account, Decimal("0")),
            account,
        ),
        reverse=True,
    )[:6]:
        current_total = current_categories.get(category, Decimal("0"))
        previous_total = previous_categories.get(category, Decimal("0"))
        delta = current_total - previous_total
        direction = "flat"
        if delta > 0:
            direction = "up"
        elif delta < 0:
            direction = "down"
        category_trends.append(
            {
                "category": pretty_account_name(category),
                "account": category,
                "current": amount_to_number(current_total),
                "previous": amount_to_number(previous_total),
                "delta": amount_to_number(delta),
                "direction": direction,
            }
        )

    category_history = [
        {
            "month": month,
            "category": account,
            "categoryLabel": pretty_account_name(account),
            "amount": amount_to_number(total),
        }
        for (month, account), total in sorted(category_spending.items())
    ]

    all_cash_flow_months = sorted(set(monthly_income.keys()) | set(monthly_spending.keys()))
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
        for month_key in all_cash_flow_months
    ]

    last_updated = activity_transactions[-1].posted_on.isoformat() if activity_transactions else None
    income_this_month = monthly_income.get(current_month, Decimal("0"))
    spending_this_month = monthly_spending.get(current_month, Decimal("0"))

    return {
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "hasData": bool(activity_transactions),
        "lastUpdated": last_updated,
        "summary": {
            "netWorth": amount_to_number(net_worth),
            "trackedBalanceTotal": amount_to_number(tracked_total),
            "incomeThisMonth": amount_to_number(income_this_month),
            "spendingThisMonth": amount_to_number(spending_this_month),
            "savingsThisMonth": amount_to_number(income_this_month - spending_this_month),
            "transactionCount": len(activity_transactions),
            "unknownTransactionCount": unknown_transaction_count,
        },
        "balances": balances,
        "cashFlow": {
            "currentMonth": current_month,
            "previousMonth": previous_month_key,
            "income": amount_to_number(income_this_month),
            "spending": amount_to_number(spending_this_month),
            "net": amount_to_number(income_this_month - spending_this_month),
            "series": series,
        },
        "categoryTrends": category_trends,
        "recentTransactions": list(reversed(recent_rows))[:8],
        "categoryHistory": category_history,
        "cashFlowHistory": cash_flow_history,
    }


def query_dashboard_transactions(
    config: AppConfig,
    *,
    period: str,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return paginated transactions for a given month, optionally filtered by category."""
    import calendar
    import re as _re

    if not _re.fullmatch(r"\d{4}-\d{2}", period):
        raise ValueError("Invalid period format. Expected YYYY-MM.")

    year = int(period[:4])
    month_num = int(period[5:7])
    if month_num < 1 or month_num > 12:
        raise ValueError("Invalid period format. Expected YYYY-MM.")

    period_start = date(year, month_num, 1)
    last_day = calendar.monthrange(year, month_num)[1]
    period_end = date(year, month_num, last_day)

    transactions = get_transactions_cached(config)

    matching: list[dict] = []
    for transaction in transactions:
        if is_generated_opening_balance_transaction(transaction):
            continue
        if transaction.posted_on < period_start or transaction.posted_on > period_end:
            continue

        if category is not None:
            has_category = any(
                posting.account.startswith(category)
                for posting in transaction.postings
            )
            if not has_category:
                continue

        category_label, _ = _transaction_category(transaction)
        category_account = ""
        for posting in transaction.postings:
            kind = _account_kind(posting.account)
            if kind in {"expense", "income"}:
                category_account = posting.account
                break

        primary = _primary_posting(transaction, config)
        primary_amount = primary.amount if primary and primary.amount is not None else Decimal("0")
        account_label, _ = _primary_account_display(primary, config)

        matching.append({
            "date": transaction.posted_on.isoformat(),
            "payee": transaction.payee,
            "amount": amount_to_number(primary_amount),
            "category": category_account,
            "categoryLabel": category_label,
            "accountLabel": account_label,
        })

    matching.sort(key=lambda r: r["date"], reverse=True)

    total = len(matching)
    limit = max(limit, 0)
    offset = max(offset, 0)
    page = matching[offset : offset + limit] if limit > 0 else []

    return {
        "transactions": page,
        "total": total,
        "period": period,
        "category": category,
    }
