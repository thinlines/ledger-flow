from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .config_service import AppConfig, infer_account_kind
from .journal_query_service import amount_to_number, load_transactions, pretty_account_name
from .opening_balance_service import opening_balance_index
from .transfer_service import is_transfer_account


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
    transfer_state: str | None = None
    transfer_peer_account_id: str | None = None
    transfer_peer_account_name: str | None = None


def _account_amount(transaction, ledger_account: str) -> Decimal | None:
    matched = [posting.amount for posting in transaction.postings if posting.account == ledger_account]
    if not matched:
        return None
    return sum((amount or Decimal("0")) for amount in matched)


def _tracked_account_display(config: AppConfig, tracked_account_id: str | None) -> tuple[str | None, str | None, str | None]:
    if not tracked_account_id:
        return (None, None, None)
    tracked_account = config.tracked_accounts.get(tracked_account_id)
    if tracked_account is None:
        return (None, None, None)
    ledger_account = str(tracked_account.get("ledger_account", "")).strip() or None
    return (
        str(tracked_account.get("display_name", tracked_account_id)),
        ledger_account,
        infer_account_kind(ledger_account or ""),
    )


def _detail_lines(config: AppConfig, transaction, postings) -> list[dict[str, str]]:
    transfer_peer_account_id = str(transaction.metadata.get("transfer_peer_account_id") or "").strip() or None
    transfer_peer_name, transfer_peer_ledger_account, transfer_peer_kind = _tracked_account_display(
        config,
        transfer_peer_account_id,
    )
    if transfer_peer_name:
        return [
            {
                "label": transfer_peer_name,
                "account": transfer_peer_ledger_account or transfer_peer_account_id or "",
                "kind": transfer_peer_kind or "other",
            }
        ]

    return [
        {
            "label": pretty_account_name(posting.account),
            "account": posting.account,
            "kind": infer_account_kind(posting.account),
        }
        for posting in postings
        if not is_transfer_account(posting.account)
    ]


def _transaction_summary(config: AppConfig, transaction, other_postings) -> tuple[str, bool, str | None, str | None]:
    transfer_peer_account_id = str(transaction.metadata.get("transfer_peer_account_id") or "").strip() or None
    transfer_state = str(transaction.metadata.get("transfer_state") or "").strip() or None
    transfer_peer_name, _, _ = _tracked_account_display(config, transfer_peer_account_id)
    if transfer_peer_name:
        summary = f"Transfer · {transfer_peer_name}"
        if transfer_state == "pending":
            summary = f"{summary} (Pending)"
        return (summary, False, transfer_state, transfer_peer_name)

    if not other_postings:
        return ("No category details", False, None, None)

    expense_postings = [posting for posting in other_postings if infer_account_kind(posting.account) == "expense"]
    income_postings = [posting for posting in other_postings if infer_account_kind(posting.account) == "income"]
    is_unknown = any(posting.account.lower().startswith("expenses:unknown") for posting in expense_postings)

    if len(other_postings) > 1:
        return (f"Split · {len(other_postings)} lines", is_unknown, None, None)

    primary = other_postings[0]
    label = pretty_account_name(primary.account)
    if infer_account_kind(primary.account) in {"asset", "liability"}:
        return (f"Transfer · {label}", is_unknown, None, None)
    if expense_postings or income_postings:
        return (label, is_unknown, None, None)
    return (f"Matched with {label}", is_unknown, None, None)


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
        summary, is_unknown, transfer_state, transfer_peer_name = _transaction_summary(config, transaction, other_postings)
        events.append(
            RegisterEvent(
                posted_on=transaction.posted_on,
                order=order,
                amount=amount,
                payee=transaction.payee,
                summary=summary,
                is_unknown=is_unknown,
                is_opening_balance=False,
                detail_lines=_detail_lines(config, transaction, other_postings),
                transfer_state=transfer_state,
                transfer_peer_account_id=str(transaction.metadata.get("transfer_peer_account_id") or "").strip() or None,
                transfer_peer_account_name=transfer_peer_name,
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
                "transferState": event.transfer_state,
                "transferPeerAccountId": event.transfer_peer_account_id,
                "transferPeerAccountName": event.transfer_peer_account_name,
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
