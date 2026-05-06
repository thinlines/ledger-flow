from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .config_service import AppConfig, infer_account_kind
from .dashboard_service import _primary_posting, _primary_account_display
from .journal_query_service import (
    ParsedTransaction,
    Posting,
    amount_to_number,
    is_generated_opening_balance_transaction,
    load_transactions,
    pretty_account_name,
)
from .opening_balance_service import opening_balance_index
from .reconciliation_service import reconciliation_status as compute_reconciliation_status


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + offset
    y, m = divmod(total, 12)
    return y, m + 1


def _month_window(today: date, count: int) -> list[str]:
    """Return `count` month keys ending with the current month."""
    keys: list[str] = []
    for offset in range(-(count - 1), 1):
        y, m = _shift_month(today.year, today.month, offset)
        keys.append(f"{y:04d}-{m:02d}")
    return keys


def _matches_base_currency(posting: Posting, base_currency: str) -> bool:
    """Return True if the posting's commodity matches the base currency or is unmarked."""
    from .commodity_service import BASE_CURRENCY_SYMBOLS

    if posting.commodity is None:
        return True
    symbol = BASE_CURRENCY_SYMBOLS.get(base_currency)
    return posting.commodity == base_currency or posting.commodity == symbol


def build_dashboard_direction(config: AppConfig, *, today: date | None = None) -> dict:
    current_day = today or date.today()
    transactions = load_transactions(config)
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
        month = _month_key(transaction.posted_on)

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

    current_month = _month_key(current_day)
    trailing_6 = _month_window(current_day, 6)

    # -----------------------------------------------------------------------
    # Health Signal: Runway gauge
    # -----------------------------------------------------------------------
    tracked_ledger_accounts = {
        str(cfg.get("ledger_account", "")).strip()
        for cfg in config.tracked_accounts.values()
    }

    LIQUID_SUBTYPES = {"checking", "savings", "cash"}
    FIXED_ASSET_SUBTYPES = {"vehicle", "real_estate"}

    spendable_cash = Decimal("0")
    for account_id, account_cfg in config.tracked_accounts.items():
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        if not ledger_account or infer_account_kind(ledger_account) != "asset":
            continue
        subtype = account_cfg.get("subtype")
        if subtype is None or subtype in LIQUID_SUBTYPES:
            spendable_cash += account_balances.get(ledger_account, Decimal("0"))

    total_spending_6m = sum(
        monthly_spending.get(m, Decimal("0")) for m in trailing_6
    )
    avg_monthly_spending_6m = total_spending_6m / 6 if trailing_6 else Decimal("0")

    # Sum minimum payments across all tracked liabilities with the field set
    monthly_obligations = Decimal("0")
    for account_id, account_cfg in config.tracked_accounts.items():
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        if not ledger_account or infer_account_kind(ledger_account) != "liability":
            continue
        ob_entry = opening_by_ledger_account.get(ledger_account)
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
        m = _month_key(txn.posted_on)
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
            walk_months.append(f"{wy:04d}-{wm:02d}")
            wy, wm = _shift_month(wy, wm, 1)

        cumulative = Decimal("0")
        for m in walk_months:
            cumulative += monthly_nw_delta.get(m, Decimal("0"))
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
            if month_totals.get(m, Decimal("0")) > 0:
                category_occurrences[category] += 1

    recurring_categories: list[str] = []
    recurring_total = Decimal("0")
    discretionary_total = Decimal("0")

    for category, month_totals in category_month_spending.items():
        current_spending = month_totals.get(current_month, Decimal("0"))
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
    largest_abs = Decimal("0")

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
    largest_overshoot = Decimal("0")

    for category, month_totals in category_month_spending.items():
        current_spending = month_totals.get(current_month, Decimal("0"))
        if current_spending <= 0:
            continue

        # 6-month rolling average (all 6 months, including zeros)
        total_6m = sum(month_totals.get(m, Decimal("0")) for m in trailing_6)
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
        y, m = _shift_month(current_day.year, current_day.month, offset)
        mk = f"{y:04d}-{m:02d}"
        spending = monthly_spending.get(mk, Decimal("0"))
        income = monthly_income.get(mk, Decimal("0"))
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
    for account_id, account_cfg in config.tracked_accounts.items():
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        if not ledger_account:
            continue
        if account_cfg.get("subtype") in FIXED_ASSET_SUBTYPES:
            continue
        last_date = account_last_transaction.get(ledger_account)
        if last_date is not None and last_date < stale_threshold:
            days_since = (current_day - last_date).days
            stale_accounts.append({
                "id": account_id,
                "displayName": str(account_cfg.get("display_name", account_id)),
                "daysSinceActivity": days_since,
            })

    # Missing opening balances
    opening_balance_ledger_accounts = set(opening_by_ledger_account.keys())
    missing_opening_balances: list[dict] = []
    for account_id, account_cfg in config.tracked_accounts.items():
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        if not ledger_account:
            continue
        has_activity = ledger_account in accounts_with_activity
        has_opening = ledger_account in opening_balance_ledger_accounts
        if has_activity and not has_opening:
            missing_opening_balances.append({
                "id": account_id,
                "displayName": str(account_cfg.get("display_name", account_id)),
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
