from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from .config_service import AppConfig, infer_account_kind
from .journal_query_service import (
    ParsedTransaction,
    Posting,
    amount_to_number,
    is_generated_opening_balance_transaction,
    load_transactions,
    pretty_account_name,
)
from .opening_balance_service import opening_balance_index


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
    transactions = load_transactions(config)
    _, opening_by_ledger_account = opening_balance_index(config)
    opening_balance_accounts = set(opening_by_ledger_account)
    account_balances: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    accounts_with_balance_source: set[str] = set()
    accounts_with_activity: set[str] = set()
    monthly_income: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    monthly_spending: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    category_spending: defaultdict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
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
                account_balances[posting.account] += posting.amount
                accounts_with_balance_source.add(posting.account)
                if not is_opening_balance:
                    accounts_with_activity.add(posting.account)
            elif is_opening_balance:
                continue
            elif kind == "expense":
                monthly_spending[month] += posting.amount
                category_spending[(month, posting.account)] += posting.amount
            elif kind == "income":
                monthly_income[month] += -posting.amount

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

    balances = []
    tracked_total = Decimal("0")
    for account_id, account_cfg in sorted(
        config.tracked_accounts.items(),
        key=lambda item: str(item[1].get("display_name", item[0])),
    ):
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        balance = account_balances.get(ledger_account, Decimal("0"))
        has_opening_balance = ledger_account in opening_balance_accounts
        has_transaction_activity = ledger_account in accounts_with_activity
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
            }
        )

    net_worth = sum(
        (
            balance
            for account, balance in account_balances.items()
            if _account_kind(account) in {"asset", "liability"}
        ),
        start=Decimal("0"),
    )

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
    }
