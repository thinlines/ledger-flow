from __future__ import annotations

from decimal import Decimal

from .commodity import next_running_commodity
from .config_service import AppConfig
from .journal_query_service import amount_to_number
from .transaction_events import account_events


def build_account_register(config: AppConfig, account_id: str) -> dict:
    tracked_account = config.account(account_id)
    if tracked_account is None:
        raise ValueError(f"Tracked account not found: {account_id}")

    ledger_account = tracked_account.ledger_account
    if not ledger_account:
        raise ValueError(f"Tracked account is missing a ledger account: {account_id}")

    events = account_events(config, [account_id])

    balance = Decimal(0)
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

    return {
        "baseCurrency": str(config.workspace.get("base_currency", "USD")),
        "accountId": account_id,
        "currentBalance": amount_to_number(balance),
        "entryCount": len(entries),
        "transactionCount": transaction_count,
        "latestTransactionDate": latest_transaction_date,
        "latestActivityDate": latest_activity_date,
        "hasOpeningBalance": any(event.is_opening_balance for event in events),
        "hasTransactionActivity": transaction_count > 0,
        "hasBalanceSource": any(event.affects_balance for event in events),
        "entries": entries,
    }
