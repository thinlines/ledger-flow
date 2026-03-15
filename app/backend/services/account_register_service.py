from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .config_service import AppConfig, infer_account_kind
from .journal_query_service import amount_to_number, load_transactions, pretty_account_name
from .opening_balance_service import opening_balance_index


@dataclass(frozen=True)
class RegisterEvent:
    posted_on: date
    order: int
    amount: Decimal
    payee: str
    summary: str
    is_unknown: bool
    is_opening_balance: bool
    detail_lines: list[dict[str, str]]


def _account_amount(transaction, ledger_account: str) -> Decimal | None:
    matched = [posting.amount for posting in transaction.postings if posting.account == ledger_account]
    if not matched:
        return None
    return sum((amount or Decimal("0")) for amount in matched)


def _detail_lines(postings) -> list[dict[str, str]]:
    return [
        {
            "label": pretty_account_name(posting.account),
            "account": posting.account,
            "kind": infer_account_kind(posting.account),
        }
        for posting in postings
    ]


def _transaction_summary(other_postings) -> tuple[str, bool]:
    if not other_postings:
        return ("No category details", False)

    expense_postings = [posting for posting in other_postings if infer_account_kind(posting.account) == "expense"]
    income_postings = [posting for posting in other_postings if infer_account_kind(posting.account) == "income"]
    is_unknown = any(posting.account.lower().startswith("expenses:unknown") for posting in expense_postings)

    if len(other_postings) > 1:
        return (f"Split · {len(other_postings)} lines", is_unknown)

    primary = other_postings[0]
    label = pretty_account_name(primary.account)
    if infer_account_kind(primary.account) in {"asset", "liability"}:
        return (f"Transfer · {label}", is_unknown)
    if expense_postings or income_postings:
        return (label, is_unknown)
    return (f"Matched with {label}", is_unknown)


def build_account_register(config: AppConfig, account_id: str) -> dict:
    tracked_account = config.tracked_accounts.get(account_id)
    if tracked_account is None:
        raise ValueError(f"Tracked account not found: {account_id}")

    ledger_account = str(tracked_account.get("ledger_account", "")).strip()
    if not ledger_account:
        raise ValueError(f"Tracked account is missing a ledger account: {account_id}")

    opening_by_id, opening_by_ledger = opening_balance_index(config)
    opening_entry = opening_by_id.get(account_id)
    if opening_entry is None:
        opening_entry = opening_by_ledger.get(ledger_account)

    events: list[RegisterEvent] = []
    if opening_entry is not None:
        events.append(
            RegisterEvent(
                posted_on=date.fromisoformat(opening_entry.date),
                order=-1,
                amount=opening_entry.amount,
                payee="Opening balance",
                summary="Starting point for this account",
                is_unknown=False,
                is_opening_balance=True,
                detail_lines=[
                    {
                        "label": "Opening balances",
                        "account": "Equity:Opening-Balances",
                        "kind": "equity",
                    }
                ],
            )
        )

    for order, transaction in enumerate(load_transactions(config)):
        amount = _account_amount(transaction, ledger_account)
        if amount is None:
            continue

        other_postings = [posting for posting in transaction.postings if posting.account != ledger_account]
        summary, is_unknown = _transaction_summary(other_postings)
        events.append(
            RegisterEvent(
                posted_on=transaction.posted_on,
                order=order,
                amount=amount,
                payee=transaction.payee,
                summary=summary,
                is_unknown=is_unknown,
                is_opening_balance=False,
                detail_lines=_detail_lines(other_postings),
            )
        )

    events.sort(key=lambda event: (event.posted_on, event.order))

    balance = Decimal("0")
    rows: list[dict] = []
    transaction_count = 0
    for index, event in enumerate(events):
        balance += event.amount
        rows.append(
            {
                "id": f"{account_id}-{event.posted_on.isoformat()}-{index}",
                "date": event.posted_on.isoformat(),
                "payee": event.payee,
                "summary": event.summary,
                "amount": amount_to_number(event.amount),
                "runningBalance": amount_to_number(balance),
                "isUnknown": event.is_unknown,
                "isOpeningBalance": event.is_opening_balance,
                "detailLines": event.detail_lines,
            }
        )
        if not event.is_opening_balance:
            transaction_count += 1

    entries = list(reversed(rows))
    latest_activity_date = entries[0]["date"] if entries else None

    return {
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "accountId": account_id,
        "currentBalance": amount_to_number(balance),
        "entryCount": len(entries),
        "transactionCount": transaction_count,
        "latestActivityDate": latest_activity_date,
        "entries": entries,
    }
