from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .config_service import AppConfig, infer_account_kind
from .journal_query_service import (
    amount_to_number,
    is_generated_opening_balance_transaction,
    load_transactions,
    pretty_account_name,
)
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
    affects_balance: bool = True
    counts_as_transaction: bool = True


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


def _tracked_account_by_ledger_account(
    config: AppConfig,
    ledger_account: str,
) -> tuple[str | None, str | None, str | None]:
    target = ledger_account.strip()
    for tracked_account_id, tracked_account in config.tracked_accounts.items():
        tracked_ledger_account = str(tracked_account.get("ledger_account", "")).strip()
        if tracked_ledger_account != target:
            continue
        return (
            tracked_account_id,
            str(tracked_account.get("display_name", tracked_account_id)),
            infer_account_kind(tracked_ledger_account),
        )
    return (None, None, None)


def _source_tracked_account_details(
    config: AppConfig,
    transaction,
) -> tuple[str | None, str | None, str | None, str | None]:
    import_account_id = str(transaction.metadata.get("import_account_id") or "").strip() or None
    import_account = config.import_accounts.get(import_account_id or "") if import_account_id else None
    source_tracked_account_id = (
        str(import_account.get("tracked_account_id", "")).strip()
        if import_account is not None
        else ""
    ) or None
    if source_tracked_account_id is None and import_account_id and import_account_id in config.tracked_accounts:
        source_tracked_account_id = import_account_id

    if source_tracked_account_id:
        source_name, source_ledger_account, source_kind = _tracked_account_display(config, source_tracked_account_id)
        if source_ledger_account:
            return (source_tracked_account_id, source_name, source_ledger_account, source_kind)

    for posting in transaction.postings:
        if is_transfer_account(posting.account):
            continue
        for tracked_account_id, tracked_account in config.tracked_accounts.items():
            ledger_account = str(tracked_account.get("ledger_account", "")).strip()
            if ledger_account == posting.account:
                return (
                    tracked_account_id,
                    str(tracked_account.get("display_name", tracked_account_id)),
                    ledger_account,
                    infer_account_kind(ledger_account),
                )
        return (None, pretty_account_name(posting.account), posting.account, infer_account_kind(posting.account))

    return (None, None, None, None)


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


def _pending_transfer_event_for_peer_account(
    config: AppConfig,
    transaction,
    account_id: str,
    order: int,
) -> RegisterEvent | None:
    transfer_state = str(transaction.metadata.get("transfer_state") or "").strip() or None
    if transfer_state != "pending":
        return None

    target_account_id = str(transaction.metadata.get("transfer_peer_account_id") or "").strip() or None
    if target_account_id != account_id:
        return None

    source_account_id, source_name, source_ledger_account, source_kind = _source_tracked_account_details(config, transaction)
    if not source_ledger_account:
        return None

    source_amount = _account_amount(transaction, source_ledger_account)
    if source_amount is None:
        return None

    label = source_name or pretty_account_name(source_ledger_account)
    return RegisterEvent(
        posted_on=transaction.posted_on,
        order=order,
        amount=-source_amount,
        payee=transaction.payee,
        summary=f"Transfer · {label} (Pending)",
        is_unknown=False,
        is_opening_balance=False,
        detail_lines=[
            {
                "label": label,
                "account": source_ledger_account,
                "kind": source_kind or infer_account_kind(source_ledger_account),
            }
        ],
        transfer_state=transfer_state,
        transfer_peer_account_id=source_account_id,
        transfer_peer_account_name=source_name or label,
        affects_balance=False,
        counts_as_transaction=False,
    )


def _opening_balance_detail_line(config: AppConfig, offset_account: str) -> dict[str, str]:
    tracked_account_id, tracked_name, tracked_kind = _tracked_account_by_ledger_account(config, offset_account)
    if tracked_name:
        return {
            "label": tracked_name,
            "account": offset_account,
            "kind": tracked_kind or infer_account_kind(offset_account),
        }

    return {
        "label": pretty_account_name(offset_account),
        "account": offset_account,
        "kind": infer_account_kind(offset_account),
    }


def build_account_register(config: AppConfig, account_id: str) -> dict:
    tracked_account = config.tracked_accounts.get(account_id)
    if tracked_account is None:
        raise ValueError(f"Tracked account not found: {account_id}")

    ledger_account = str(tracked_account.get("ledger_account", "")).strip()
    if not ledger_account:
        raise ValueError(f"Tracked account is missing a ledger account: {account_id}")

    events: list[RegisterEvent] = []
    for order, transaction in enumerate(load_transactions(config)):
        amount = _account_amount(transaction, ledger_account)
        if amount is not None:
            other_postings = [posting for posting in transaction.postings if posting.account != ledger_account]
            is_generated_opening = is_generated_opening_balance_transaction(transaction)
            opening_account_id = str(transaction.metadata.get("tracked_account_id", "")).strip() or None
            is_primary_opening = is_generated_opening and opening_account_id == account_id
            if is_primary_opening:
                offset_account = other_postings[0].account if other_postings else ""
                summary = "Starting point for this account"
                is_unknown = False
                transfer_state = None
                transfer_peer_name = None
                detail_lines = [_opening_balance_detail_line(config, offset_account)]
            else:
                summary, is_unknown, transfer_state, transfer_peer_name = _transaction_summary(
                    config,
                    transaction,
                    other_postings,
                )
                if is_generated_opening:
                    is_unknown = False
                detail_lines = _detail_lines(config, transaction, other_postings)
            events.append(
                RegisterEvent(
                    posted_on=transaction.posted_on,
                    order=order,
                    amount=amount,
                    payee=transaction.payee,
                    summary=summary,
                    is_unknown=is_unknown,
                    is_opening_balance=is_primary_opening,
                    detail_lines=detail_lines,
                    transfer_state=transfer_state,
                    transfer_peer_account_id=str(transaction.metadata.get("transfer_peer_account_id") or "").strip() or None,
                    transfer_peer_account_name=transfer_peer_name,
                    counts_as_transaction=not is_generated_opening,
                )
            )
            continue

        pending_peer_event = _pending_transfer_event_for_peer_account(config, transaction, account_id, order)
        if pending_peer_event is not None:
            events.append(pending_peer_event)

    events.sort(key=lambda event: (event.posted_on, event.order))

    balance = Decimal("0")
    rows: list[dict] = []
    transaction_count = 0
    latest_transaction_date: str | None = None
    for index, event in enumerate(events):
        if event.affects_balance:
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
        if event.counts_as_transaction and not event.is_opening_balance:
            transaction_count += 1
            latest_transaction_date = event.posted_on.isoformat()

    entries = list(reversed(rows))
    latest_activity_date = entries[0]["date"] if entries else None
    has_opening_balance = any(event.is_opening_balance for event in events)
    has_balance_source = any(event.affects_balance for event in events)

    return {
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "accountId": account_id,
        "currentBalance": amount_to_number(balance),
        "entryCount": len(entries),
        "transactionCount": transaction_count,
        "latestTransactionDate": latest_transaction_date,
        "latestActivityDate": latest_activity_date,
        "hasOpeningBalance": has_opening_balance,
        "hasTransactionActivity": transaction_count > 0,
        "hasBalanceSource": has_balance_source,
        "entries": entries,
    }
