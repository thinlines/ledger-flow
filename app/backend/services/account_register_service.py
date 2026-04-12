from __future__ import annotations

from decimal import Decimal

from .commodity_service import CommodityMismatchError
from .config_service import AppConfig
from .journal_query_service import (
    amount_to_number,
    is_generated_opening_balance_transaction,
    load_transactions,
)
from .transaction_helpers import (
    RegisterEvent,
    account_amount,
    bilateral_matched_pending_transfer_orders,
    detail_lines,
    direct_transfer_event_for_peer_account,
    grouped_settled_pending_transfer_orders,
    manual_resolution_note,
    manual_resolution_token,
    next_running_commodity,
    opening_balance_detail_line,
    pending_transfer_event_for_peer_account,
    transaction_summary,
)


def build_account_register(config: AppConfig, account_id: str) -> dict:
    tracked_account = config.tracked_accounts.get(account_id)
    if tracked_account is None:
        raise ValueError(f"Tracked account not found: {account_id}")

    ledger_account = str(tracked_account.get("ledger_account", "")).strip()
    if not ledger_account:
        raise ValueError(f"Tracked account is missing a ledger account: {account_id}")

    transactions = load_transactions(config)
    grouped_settled_orders = grouped_settled_pending_transfer_orders(config, transactions)
    bilateral_matched_orders = bilateral_matched_pending_transfer_orders(config, transactions, grouped_settled_orders)
    pending_excluded_orders = grouped_settled_orders | bilateral_matched_orders

    events: list[RegisterEvent] = []
    for order, transaction in enumerate(transactions):
        amount, commodity = account_amount(transaction, ledger_account)
        if amount is not None:
            other_postings = [posting for posting in transaction.postings if posting.account != ledger_account]
            is_generated_opening = is_generated_opening_balance_transaction(transaction)
            opening_account_id = str(transaction.metadata.get("tracked_account_id", "")).strip() or None
            is_primary_opening = is_generated_opening and opening_account_id == account_id
            token = None
            if is_primary_opening:
                offset_account = other_postings[0].account if other_postings else ""
                summary = "Starting point for this account"
                is_unknown = False
                transfer_state = None
                transfer_peer_account_id = None
                transfer_peer_name = None
                dl = [opening_balance_detail_line(config, offset_account)]
            else:
                token = manual_resolution_token(
                    config,
                    transaction,
                    grouped_settled=order in pending_excluded_orders,
                )
                summary, is_unknown, transfer_state, transfer_peer_account_id, transfer_peer_name = transaction_summary(
                    config,
                    transaction,
                    other_postings,
                    account_id,
                    grouped_settled=order in grouped_settled_orders,
                    bilateral_matched=order in bilateral_matched_orders,
                )
                if is_generated_opening:
                    is_unknown = False
                dl = detail_lines(config, transaction, other_postings, account_id)
            events.append(
                RegisterEvent(
                    posted_on=transaction.posted_on,
                    order=order,
                    amount=amount,
                    commodity=commodity,
                    payee=transaction.payee,
                    summary=summary,
                    is_unknown=is_unknown,
                    is_opening_balance=is_primary_opening,
                    detail_lines=dl,
                    transfer_state=transfer_state,
                    transfer_peer_account_id=transfer_peer_account_id,
                    transfer_peer_account_name=transfer_peer_name,
                    manual_resolution_token=token,
                    manual_resolution_note=manual_resolution_note(transaction),
                    clearing_status=transaction.status.value,
                    header_line=transaction.header_line,
                    journal_path=transaction.source_journal,
                    match_id=transaction.metadata.get("match-id") or None,
                    notes=transaction.metadata.get("notes") or None,
                    counts_as_transaction=not is_generated_opening,
                )
            )
            continue

        pending_peer_event = pending_transfer_event_for_peer_account(
            config,
            transaction,
            account_id,
            order,
            pending_excluded_orders,
        )
        if pending_peer_event is not None:
            events.append(pending_peer_event)
            continue

        direct_peer_event = direct_transfer_event_for_peer_account(config, transaction, account_id, order)
        if direct_peer_event is not None:
            events.append(direct_peer_event)

    events.sort(key=lambda event: (event.posted_on, event.order))

    balance = Decimal("0")
    balance_commodity: str | None = None
    balance_initialized = False
    rows: list[dict] = []
    transaction_count = 0
    latest_transaction_date: str | None = None
    for index, event in enumerate(events):
        if event.affects_balance:
            balance_commodity = next_running_commodity(
                ledger_account,
                balance_commodity,
                event.commodity,
                initialized=balance_initialized,
            )
            balance_initialized = True
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
                "manualResolutionToken": event.manual_resolution_token,
                "manualResolutionNote": event.manual_resolution_note,
                "clearingStatus": event.clearing_status,
                "headerLine": event.header_line,
                "journalPath": event.journal_path,
                "matchId": event.match_id,
                "notes": event.notes,
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
