from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from . import projection_service
from .commodity import CommodityMismatchError, commodity_label
from .config_service import AppConfig, infer_account_kind
from .header_parser import TransactionStatus
from .journal_query_service import (
    ParsedTransaction,
    Posting,
    amount_to_number,
    is_generated_opening_balance_transaction,
    pretty_account_name,
)
from .month_math import month_key, month_key_of, month_label, month_window, shift_month
from .opening_balance_service import opening_balance_index
from .projection_db import connect, database_path
from .projection_service import refresh_projection
from .reconciliation_service import (
    reconciliation_status as compute_reconciliation_status,
)
from .reference_data_service import account_subtypes


def _account_kind(account: str) -> str:
    return infer_account_kind(account)


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


def _decimal_from_nano(value: int | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value) / Decimal(1000000000)


def _load_dashboard_transactions_from_projection(
    config: AppConfig,
) -> list[ParsedTransaction]:
    """Load dashboard source rows from the journal projection, not journal text.

    The dashboard still uses the existing Python shaping code, but the read-heavy
    parse/hydrate step is served from SQLite projection tables.
    """
    refresh_projection(config)

    with connect(database_path(config.root_dir)) as conn:
        txn_rows = conn.execute(
            """
            SELECT transactions.id, transactions.date, transactions.payee,
                   transactions.status, transactions.raw_header,
                   journal_files.path, transactions.source_start_line
            FROM transactions
            JOIN journal_files ON journal_files.id = transactions.journal_file_id
            WHERE journal_files.role != 'archive'
              AND transactions.parse_status = 'ok'
            ORDER BY transactions.date, journal_files.path, transactions.txn_order
            """
        ).fetchall()

        posting_rows = conn.execute(
            """
            SELECT postings.transaction_id, postings.account, postings.amount_nano,
                   postings.commodity, postings.amount_inferred
            FROM postings
            JOIN transactions ON transactions.id = postings.transaction_id
            JOIN journal_files ON journal_files.id = transactions.journal_file_id
            WHERE journal_files.role != 'archive'
              AND transactions.parse_status = 'ok'
            ORDER BY postings.transaction_id, postings.posting_order
            """
        ).fetchall()

        metadata_rows = conn.execute(
            """
            SELECT metadata_entries.owner_id, metadata_entries.key,
                   metadata_entries.value_text
            FROM metadata_entries
            JOIN transactions ON transactions.id = metadata_entries.owner_id
            JOIN journal_files ON journal_files.id = transactions.journal_file_id
            WHERE metadata_entries.owner_type = 'transaction'
              AND journal_files.role != 'archive'
              AND transactions.parse_status = 'ok'
            ORDER BY metadata_entries.owner_id, metadata_entries.source_order
            """
        ).fetchall()

    postings_by_txn: dict[str, list[Posting]] = defaultdict(list)
    for txn_id, account, amount_nano, commodity, inferred in posting_rows:
        postings_by_txn[txn_id].append(
            Posting(
                account=account,
                amount=_decimal_from_nano(amount_nano),
                commodity=commodity,
                inferred=bool(inferred),
            )
        )

    metadata_by_txn: dict[str, dict[str, str]] = defaultdict(dict)
    for txn_id, key, value in metadata_rows:
        metadata_by_txn[txn_id][str(key).lower()] = str(value)

    root = config.root_dir.resolve()
    transactions: list[ParsedTransaction] = []
    for (
        txn_id,
        date_text,
        payee,
        status,
        raw_header,
        rel_path,
        source_start_line,
    ) in txn_rows:
        transactions.append(
            ParsedTransaction(
                posted_on=date.fromisoformat(date_text),
                payee=payee,
                postings=postings_by_txn.get(txn_id, []),
                metadata=metadata_by_txn.get(txn_id, {}),
                status=TransactionStatus(status),
                header_line=raw_header,
                source_journal=str(root / rel_path),
                header_line_number=int(source_start_line) - 1,
                txn_id=txn_id,
            )
        )

    return transactions


def _primary_posting(transaction: ParsedTransaction, config: AppConfig) -> Posting | None:
    import_account = config.import_account(transaction.metadata.get("import_account_id"))
    if import_account is not None:
        linked = config.account(import_account.tracked_account_id or import_account.id)
        tracked_account = (
            linked.ledger_account if linked is not None else import_account.ledger_account
        )
        if tracked_account:
            for posting in transaction.postings:
                if posting.account == tracked_account:
                    return posting

    tracked_accounts = {account.ledger_account for account in config.accounts}
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

    account = config.account_for_ledger(posting.account)
    if account is not None:
        return (account.display_name, account.id)

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
    transactions = _load_dashboard_transactions_from_projection(config)
    _, opening_by_ledger_account = opening_balance_index(config)
    opening_balance_accounts = set(opening_by_ledger_account)
    account_balances: defaultdict[str, Decimal] = defaultdict(lambda: Decimal(0))
    account_balance_commodities: dict[str, str | None] = {}
    accounts_with_balance_source: set[str] = set()
    accounts_with_activity: set[str] = set()
    account_last_transaction: dict[str, date] = {}
    monthly_income: defaultdict[str, Decimal] = defaultdict(lambda: Decimal(0))
    monthly_income_commodities: dict[str, str | None] = {}
    monthly_spending: defaultdict[str, Decimal] = defaultdict(lambda: Decimal(0))
    monthly_spending_commodities: dict[str, str | None] = {}
    category_spending: defaultdict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal(0))
    category_spending_commodities: dict[tuple[str, str], str | None] = {}
    unknown_transaction_count = 0
    recent_rows: list[dict] = []
    activity_transactions: list[ParsedTransaction] = []

    for transaction in transactions:
        is_opening_balance = is_generated_opening_balance_transaction(transaction)
        month = month_key(transaction.posted_on)

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
        primary_amount = primary.amount if primary and primary.amount is not None else Decimal(0)
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

    current_month = month_key(current_day)
    previous_month_key = month_key_of(*shift_month(current_day.year, current_day.month, -1))

    reconciliation_status_map = compute_reconciliation_status(config)
    balances = []
    tracked_total = Decimal(0)
    tracked_total_commodity: str | None = None
    tracked_total_initialized = False
    for account_id, account_cfg in sorted(
        config.tracked_accounts.items(),
        key=lambda item: str(item[1].get("display_name", item[0])),
    ):
        ledger_account = config.ledger_account_for(account_id)
        balance = account_balances.get(ledger_account, Decimal(0))
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

    net_worth = Decimal(0)
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
    for year_value, month_value in month_window(current_day, 6):
        key = month_key_of(year_value, month_value)
        income = monthly_income.get(key, Decimal(0))
        spending = monthly_spending.get(key, Decimal(0))
        series.append(
            {
                "month": key,
                "label": month_label(year_value, month_value),
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
            current_categories.get(account, Decimal(0)),
            previous_categories.get(account, Decimal(0)),
            account,
        ),
        reverse=True,
    )[:6]:
        current_total = current_categories.get(category, Decimal(0))
        previous_total = previous_categories.get(category, Decimal(0))
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
            "income": amount_to_number(monthly_income.get(month_key, Decimal(0))),
            "spending": amount_to_number(monthly_spending.get(month_key, Decimal(0))),
            "net": amount_to_number(
                monthly_income.get(month_key, Decimal(0))
                - monthly_spending.get(month_key, Decimal(0))
            ),
        }
        for month_key in all_cash_flow_months
    ]

    last_updated = activity_transactions[-1].posted_on.isoformat() if activity_transactions else None
    income_this_month = monthly_income.get(current_month, Decimal(0))
    spending_this_month = monthly_spending.get(current_month, Decimal(0))

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

    transactions = _load_dashboard_transactions_from_projection(config)

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
        primary_amount = primary.amount if primary and primary.amount is not None else Decimal(0)
        account_label, account_id = _primary_account_display(primary, config)

        matching.append({
            "date": transaction.posted_on.isoformat(),
            "payee": transaction.payee,
            "amount": amount_to_number(primary_amount),
            "category": category_account,
            "categoryLabel": category_label,
            "accountLabel": account_label,
            "accountId": account_id,
            "isTransfer": category_label == "Transfer",
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


def _matches_base_currency(posting: Posting, base_currency: str) -> bool:
    """Return True if the posting's commodity matches the base currency or is unmarked."""
    from .commodity import BASE_CURRENCY_SYMBOLS

    if posting.commodity is None:
        return True
    symbol = BASE_CURRENCY_SYMBOLS.get(base_currency)
    return posting.commodity == base_currency or posting.commodity == symbol


def build_dashboard_direction(config: AppConfig, *, today: date | None = None) -> dict:
    current_day = today or date.today()
    transactions = projection_service.load_transactions_projected(config)
    _, opening_by_ledger_account = opening_balance_index(config)
    base_currency = str(config.workspace.get("base_currency", "USD"))

    # -----------------------------------------------------------------------
    # Accumulate per-account balances, monthly spending/income, category data
    # Filter postings to the base currency to avoid cross-commodity math.
    # -----------------------------------------------------------------------
    account_balances: defaultdict[str, Decimal] = defaultdict(Decimal)
    account_last_transaction: dict[str, date] = {}
    accounts_with_activity: set[str] = set()

    monthly_spending: defaultdict[str, Decimal] = defaultdict(Decimal)
    monthly_income: defaultdict[str, Decimal] = defaultdict(Decimal)

    # category -> month -> spending total
    category_month_spending: defaultdict[str, defaultdict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    unknown_transaction_count = 0
    activity_transactions: list[ParsedTransaction] = []

    for transaction in transactions:
        is_opening_balance = is_generated_opening_balance_transaction(transaction)
        month = month_key(transaction.posted_on)

        for posting in transaction.postings:
            if posting.amount is None:
                continue
            if not _matches_base_currency(posting, base_currency):
                continue

            kind = infer_account_kind(posting.account)
            if kind in {"asset", "liability"}:
                account_balances[posting.account] += posting.amount
                if not is_opening_balance:
                    accounts_with_activity.add(posting.account)
                    prev = account_last_transaction.get(posting.account)
                    if prev is None or transaction.posted_on > prev:
                        account_last_transaction[posting.account] = transaction.posted_on
            elif is_opening_balance:
                continue
            elif kind == "expense":
                monthly_spending[month] += posting.amount
                category_month_spending[posting.account][month] += posting.amount
            elif kind == "income":
                monthly_income[month] += -posting.amount

        if is_opening_balance:
            continue

        activity_transactions.append(transaction)
        # Check for unknown transactions
        for posting in transaction.postings:
            if posting.account.lower().startswith("expenses:unknown"):
                unknown_transaction_count += 1
                break

    current_month = month_key(current_day)
    trailing_6 = [month_key_of(y, m) for y, m in month_window(current_day, 6)]

    # -----------------------------------------------------------------------
    # Health Signal: Runway gauge
    # -----------------------------------------------------------------------
    tracked_ledger_accounts = {
        account.ledger_account
        for account in config.accounts
    }

    LIQUID_SUBTYPES = {"checking", "savings", "cash"}
    FIXED_ASSET_SUBTYPES = {"vehicle", "real_estate"}

    # Subtype is declaration-canonical (issue #19): read the projected
    # lf_subtype metadata, not config.toml.
    projected_subtypes = account_subtypes(config)

    spendable_cash = Decimal(0)
    for account in config.accounts:
        if not account.ledger_account or account.kind != "asset":
            continue
        subtype = projected_subtypes.get(account.ledger_account)
        if subtype is None or subtype in LIQUID_SUBTYPES:
            spendable_cash += account_balances.get(account.ledger_account, Decimal(0))

    total_spending_6m = sum(
        monthly_spending.get(m, Decimal(0)) for m in trailing_6
    )
    avg_monthly_spending_6m = total_spending_6m / 6 if trailing_6 else Decimal(0)

    # Sum minimum payments across all tracked liabilities with the field set
    monthly_obligations = Decimal(0)
    for account in config.accounts:
        if not account.ledger_account or account.kind != "liability":
            continue
        ob_entry = opening_by_ledger_account.get(account.ledger_account)
        if ob_entry and ob_entry.minimum_payment:
            monthly_obligations += abs(ob_entry.minimum_payment)

    runway = None
    total_monthly_burn = avg_monthly_spending_6m + monthly_obligations
    if total_monthly_burn > 0:
        months_of_runway = float(spendable_cash / total_monthly_burn)
        runway = {
            "months": round(months_of_runway, 1),
            "spendableCash": amount_to_number(spendable_cash),
            "avgMonthlySpending": amount_to_number(avg_monthly_spending_6m),
            "monthlyObligations": amount_to_number(monthly_obligations),
        }

    # -----------------------------------------------------------------------
    # Health Signal: Net worth trend (6-month sparkline)
    # -----------------------------------------------------------------------
    # Build cumulative net worth at month boundaries from asset+liability postings
    # sorted by date.
    month_end_net_worth: dict[str, float] = {}

    # Gather all (month, amount) pairs from asset/liability postings
    monthly_nw_delta: defaultdict[str, Decimal] = defaultdict(Decimal)
    for txn in transactions:
        m = month_key(txn.posted_on)
        for posting in txn.postings:
            if posting.amount is None:
                continue
            if not _matches_base_currency(posting, base_currency):
                continue
            if infer_account_kind(posting.account) in {"asset", "liability"}:
                monthly_nw_delta[m] += posting.amount

    # Walk all months in order up to current, accumulating net worth
    all_months = sorted(monthly_nw_delta.keys())
    if all_months:
        earliest_month = all_months[0]
        # Generate every month from earliest through current
        ey, em = int(earliest_month[:4]), int(earliest_month[5:7])
        cy, cm = current_day.year, current_day.month
        walk_months: list[str] = []
        wy, wm = ey, em
        while (wy, wm) <= (cy, cm):
            walk_months.append(month_key_of(wy, wm))
            wy, wm = shift_month(wy, wm, 1)

        cumulative = Decimal(0)
        for m in walk_months:
            cumulative += monthly_nw_delta.get(m, Decimal(0))
            month_end_net_worth[m] = amount_to_number(cumulative)

    # Extract the 6-month window
    net_worth_trend = None
    sparkline_data = []
    for m in trailing_6:
        if m in month_end_net_worth:
            sparkline_data.append({"month": m, "value": month_end_net_worth[m]})

    if len(sparkline_data) >= 2:
        net_worth_trend = sparkline_data

    # -----------------------------------------------------------------------
    # Health Signal: Recurring vs discretionary split
    # -----------------------------------------------------------------------
    # A category is recurring if it has postings in >= 4 of the last 6 months
    category_occurrences: defaultdict[str, int] = defaultdict(int)
    for category, month_totals in category_month_spending.items():
        for m in trailing_6:
            if month_totals.get(m, Decimal(0)) > 0:
                category_occurrences[category] += 1

    recurring_categories: list[str] = []
    recurring_total = Decimal(0)
    discretionary_total = Decimal(0)

    for category, month_totals in category_month_spending.items():
        current_spending = month_totals.get(current_month, Decimal(0))
        if current_spending <= 0:
            continue
        if category_occurrences[category] >= 4:
            recurring_total += current_spending
            recurring_categories.append(pretty_account_name(category))
        else:
            discretionary_total += current_spending

    recurring_vs_discretionary = {
        "recurring": amount_to_number(recurring_total),
        "discretionary": amount_to_number(discretionary_total),
        "recurringCategories": sorted(recurring_categories),
        "total": amount_to_number(recurring_total + discretionary_total),
    }

    # -----------------------------------------------------------------------
    # Notable Signal: Largest transaction this week
    # -----------------------------------------------------------------------
    week_ago = current_day - timedelta(days=7)
    largest_this_week = None
    largest_abs = Decimal(0)

    for txn in activity_transactions:
        if txn.posted_on < week_ago:
            continue
        if txn.posted_on > current_day:
            continue
        for posting in txn.postings:
            if posting.amount is not None and abs(posting.amount) > largest_abs:
                # Only consider tracked-account postings as the "primary" amount
                if posting.account in tracked_ledger_accounts or infer_account_kind(posting.account) in {"asset", "liability"}:
                    largest_abs = abs(posting.amount)
                    largest_this_week = {
                        "payee": txn.payee,
                        "amount": amount_to_number(posting.amount),
                        "date": txn.posted_on.isoformat(),
                        "accountLabel": _primary_account_display(_primary_posting(txn, config), config)[0],
                    }

    # -----------------------------------------------------------------------
    # Notable Signal: Category spike
    # -----------------------------------------------------------------------
    category_spike = None
    largest_overshoot = Decimal(0)

    for category, month_totals in category_month_spending.items():
        current_spending = month_totals.get(current_month, Decimal(0))
        if current_spending <= 0:
            continue

        # 6-month rolling average (all 6 months, including zeros)
        total_6m = sum(month_totals.get(m, Decimal(0)) for m in trailing_6)
        avg_6m = total_6m / 6

        if avg_6m > 0 and current_spending > 2 * avg_6m:
            ratio = float(current_spending / avg_6m)
            overshoot = current_spending - avg_6m
            if overshoot > largest_overshoot:
                largest_overshoot = overshoot
                category_spike = {
                    "category": pretty_account_name(category),
                    "current": amount_to_number(current_spending),
                    "average": amount_to_number(avg_6m),
                    "ratio": round(ratio, 1),
                }

    # -----------------------------------------------------------------------
    # Notable Signal: Spending streak
    # -----------------------------------------------------------------------
    spending_streak = None
    streak_count = 0

    # Walk backwards from current month
    for offset in range(0, -12, -1):
        mk = month_key_of(*shift_month(current_day.year, current_day.month, offset))
        spending = monthly_spending.get(mk, Decimal(0))
        income = monthly_income.get(mk, Decimal(0))
        if spending > income and (spending > 0 or income > 0):
            streak_count += 1
        else:
            break

    if streak_count >= 2:
        spending_streak = {"months": streak_count}

    # -----------------------------------------------------------------------
    # Loose Ends
    # -----------------------------------------------------------------------
    # Review queue count
    review_queue_count = unknown_transaction_count

    # Statement inbox count
    statement_inbox_count = 0
    try:
        statement_inbox_count = len(list(config.csv_dir.glob("*.csv")))
    except Exception:
        pass

    # Stale accounts (> 30 days since last transaction)
    # Skip fixed assets (vehicles, real estate) — inactivity is expected, not a loose end.
    stale_threshold = current_day - timedelta(days=30)
    stale_accounts: list[dict] = []
    for account in config.accounts:
        if not account.ledger_account:
            continue
        if projected_subtypes.get(account.ledger_account) in FIXED_ASSET_SUBTYPES:
            continue
        last_date = account_last_transaction.get(account.ledger_account)
        if last_date is not None and last_date < stale_threshold:
            days_since = (current_day - last_date).days
            stale_accounts.append({
                "id": account.id,
                "displayName": account.display_name,
                "daysSinceActivity": days_since,
            })

    # Missing opening balances
    opening_balance_ledger_accounts = set(opening_by_ledger_account.keys())
    missing_opening_balances: list[dict] = []
    for account in config.accounts:
        if not account.ledger_account:
            continue
        has_activity = account.ledger_account in accounts_with_activity
        has_opening = account.ledger_account in opening_balance_ledger_accounts
        if has_activity and not has_opening:
            missing_opening_balances.append({
                "id": account.id,
                "displayName": account.display_name,
            })

    # Broken reconciliations
    broken_reconciliations: list[dict] = []
    try:
        recon_status = compute_reconciliation_status(config)
        for account_id, status in recon_status.items():
            if not status.get("ok", True):
                display_name = str(
                    config.tracked_accounts.get(account_id, {}).get("display_name", account_id)
                )
                broken_reconciliations.append({
                    "id": account_id,
                    "displayName": display_name,
                })
    except Exception:
        pass  # Fail open: omit broken-reconciliation items if detection errors

    # -----------------------------------------------------------------------
    # Assemble response
    # -----------------------------------------------------------------------
    return {
        "runway": runway,
        "netWorthTrend": net_worth_trend,
        "recurringVsDiscretionary": recurring_vs_discretionary,
        "notableSignals": {
            "largestThisWeek": largest_this_week,
            "categorySpike": category_spike,
            "spendingStreak": spending_streak,
        },
        "looseEnds": {
            "reviewQueueCount": review_queue_count,
            "statementInboxCount": statement_inbox_count,
            "staleAccounts": stale_accounts,
            "missingOpeningBalances": missing_opening_balances,
            "brokenReconciliations": broken_reconciliations,
        },
        "baseCurrency": base_currency,
    }
