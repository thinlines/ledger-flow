from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from .config_service import AppConfig


TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
HEADER_RE = re.compile(
    r"^(?P<date>\d{4}[-/]\d{2}[-/]\d{2})"
    r"(?:\s+[*!])?"
    r"(?:\s+\([^)]+\))?"
    r"\s*(?P<payee>.*)$"
)
POSTING_RE = re.compile(r"^\s+([^\s].*?)(?:(?:\s{2,}|\t+)(.+))?$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")


@dataclass(frozen=True)
class Posting:
    account: str
    amount: Decimal | None
    inferred: bool = False


@dataclass(frozen=True)
class ParsedTransaction:
    posted_on: date
    payee: str
    postings: list[Posting]
    metadata: dict[str, str]


def _amount_to_number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _parse_amount(raw: str) -> Decimal | None:
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return None

    digits = "".join(ch for ch in compact if ch.isdigit() or ch in {".", ","})
    if not digits:
        return None

    sign = -1 if "-" in compact else 1
    try:
        return Decimal(digits.replace(",", "")) * sign
    except InvalidOperation:
        return None


def _split_transactions(journal_text: str) -> list[list[str]]:
    transactions: list[list[str]] = []
    current: list[str] = []
    for raw in journal_text.splitlines():
        if TXN_START_RE.match(raw):
            if current:
                transactions.append(current)
            current = [raw]
        elif current:
            current.append(raw)
    if current:
        transactions.append(current)
    return transactions


def _parse_transaction(lines: list[str]) -> ParsedTransaction | None:
    header_match = HEADER_RE.match(lines[0])
    if not header_match:
        return None

    try:
        posted_on = date.fromisoformat(header_match.group("date").replace("/", "-"))
    except ValueError:
        return None

    metadata: dict[str, str] = {}
    postings: list[Posting] = []

    for line in lines[1:]:
        meta_match = META_RE.match(line)
        if meta_match:
            metadata[meta_match.group(1).strip().lower()] = meta_match.group(2).strip()
            continue

        posting_match = POSTING_RE.match(line)
        if not posting_match:
            continue

        account = posting_match.group(1).strip()
        amount = _parse_amount(posting_match.group(2) or "")
        postings.append(Posting(account=account, amount=amount))

    if not postings:
        return None

    known_total = sum((posting.amount or Decimal("0")) for posting in postings if posting.amount is not None)
    blank_indexes = [index for index, posting in enumerate(postings) if posting.amount is None]
    if len(blank_indexes) == 1:
        idx = blank_indexes[0]
        postings[idx] = Posting(account=postings[idx].account, amount=-known_total, inferred=True)

    return ParsedTransaction(
        posted_on=posted_on,
        payee=header_match.group("payee").strip() or "Untitled transaction",
        postings=postings,
        metadata=metadata,
    )


def _account_kind(account: str) -> str:
    prefix = account.split(":", 1)[0].strip().lower()
    if prefix == "assets":
        return "asset"
    if prefix in {"liabilities", "liability"}:
        return "liability"
    if prefix in {"expenses", "expense"}:
        return "expense"
    if prefix in {"income", "revenue"}:
        return "income"
    if prefix in {"equity", "capital"}:
        return "equity"
    return "other"


def _pretty_account_name(account: str) -> str:
    parts = [segment.replace("_", " ").strip() for segment in account.split(":") if segment.strip()]
    if not parts:
        return "Unlabeled"
    if len(parts) == 1:
        return parts[0].title()
    return " / ".join(part.title() for part in parts[1:])


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


def _load_transactions(config: AppConfig) -> list[ParsedTransaction]:
    transactions: list[ParsedTransaction] = []
    for journal_path in sorted(config.journal_dir.glob("*.journal")):
        if not journal_path.exists():
            continue
        text = journal_path.read_text(encoding="utf-8")
        for lines in _split_transactions(text):
            transaction = _parse_transaction(lines)
            if transaction is not None:
                transactions.append(transaction)
    return sorted(transactions, key=lambda txn: txn.posted_on)


def _primary_posting(transaction: ParsedTransaction, config: AppConfig) -> Posting | None:
    import_account_id = transaction.metadata.get("import_account_id")
    if import_account_id and import_account_id in config.import_accounts:
        tracked_account = str(config.import_accounts[import_account_id].get("ledger_account", "")).strip()
        if tracked_account:
            for posting in transaction.postings:
                if posting.account == tracked_account:
                    return posting

    tracked_accounts = {
        str(account_cfg.get("ledger_account", "")).strip()
        for account_cfg in config.import_accounts.values()
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

    for account_id, account_cfg in config.import_accounts.items():
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        if ledger_account == posting.account:
            return (str(account_cfg.get("display_name", account_id)), account_id)

    return (_pretty_account_name(posting.account), None)


def _transaction_category(transaction: ParsedTransaction) -> tuple[str, bool]:
    expense_postings = [posting for posting in transaction.postings if _account_kind(posting.account) == "expense"]
    if expense_postings:
        account = expense_postings[0].account
        return (_pretty_account_name(account), account.lower().startswith("expenses:unknown"))

    income_postings = [posting for posting in transaction.postings if _account_kind(posting.account) == "income"]
    if income_postings:
        return (_pretty_account_name(income_postings[0].account), False)

    return ("Transfer", False)


def build_dashboard_overview(config: AppConfig, *, today: date | None = None) -> dict:
    current_day = today or date.today()
    transactions = _load_transactions(config)
    account_balances: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    monthly_income: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    monthly_spending: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    category_spending: defaultdict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    unknown_transaction_count = 0
    recent_rows: list[dict] = []

    for transaction in transactions:
        month = _month_key(transaction.posted_on)

        for posting in transaction.postings:
            if posting.amount is None:
                continue

            kind = _account_kind(posting.account)
            if kind in {"asset", "liability"}:
                account_balances[posting.account] += posting.amount
            elif kind == "expense":
                monthly_spending[month] += posting.amount
                category_spending[(month, posting.account)] += posting.amount
            elif kind == "income":
                monthly_income[month] += -posting.amount

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
                "amount": _amount_to_number(primary_amount),
                "isIncome": primary_amount > 0,
                "isUnknown": is_unknown,
            }
        )

    current_month = f"{current_day.year:04d}-{current_day.month:02d}"
    previous_year, previous_month = _shift_month(current_day.year, current_day.month, -1)
    previous_month_key = f"{previous_year:04d}-{previous_month:02d}"

    balances = []
    tracked_total = Decimal("0")
    for account_id, account_cfg in sorted(config.import_accounts.items(), key=lambda item: str(item[1].get("display_name", item[0]))):
        ledger_account = str(account_cfg.get("ledger_account", "")).strip()
        balance = account_balances.get(ledger_account, Decimal("0"))
        tracked_total += balance
        balances.append(
            {
                "id": account_id,
                "displayName": str(account_cfg.get("display_name", account_id)),
                "institutionId": str(account_cfg.get("institution", "")).strip() or None,
                "ledgerAccount": ledger_account,
                "last4": account_cfg.get("last4"),
                "kind": _account_kind(ledger_account),
                "balance": _amount_to_number(balance),
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
                "income": _amount_to_number(income),
                "spending": _amount_to_number(spending),
                "net": _amount_to_number(income - spending),
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
                "category": _pretty_account_name(category),
                "account": category,
                "current": _amount_to_number(current_total),
                "previous": _amount_to_number(previous_total),
                "delta": _amount_to_number(delta),
                "direction": direction,
            }
        )

    last_updated = transactions[-1].posted_on.isoformat() if transactions else None
    income_this_month = monthly_income.get(current_month, Decimal("0"))
    spending_this_month = monthly_spending.get(current_month, Decimal("0"))

    return {
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "hasData": bool(transactions),
        "lastUpdated": last_updated,
        "summary": {
            "netWorth": _amount_to_number(net_worth),
            "trackedBalanceTotal": _amount_to_number(tracked_total),
            "incomeThisMonth": _amount_to_number(income_this_month),
            "spendingThisMonth": _amount_to_number(spending_this_month),
            "savingsThisMonth": _amount_to_number(income_this_month - spending_this_month),
            "transactionCount": len(transactions),
            "unknownTransactionCount": unknown_transaction_count,
        },
        "balances": balances,
        "cashFlow": {
            "currentMonth": current_month,
            "previousMonth": previous_month_key,
            "income": _amount_to_number(income_this_month),
            "spending": _amount_to_number(spending_this_month),
            "net": _amount_to_number(income_this_month - spending_this_month),
            "series": series,
        },
        "categoryTrends": category_trends,
        "recentTransactions": list(reversed(recent_rows))[:8],
    }
