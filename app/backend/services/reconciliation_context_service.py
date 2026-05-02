"""Builds the read-only payload the reconciliation route needs in one round-trip.

The route asks for ``openingBalance`` (running balance at ``periodStart - 1
day``), the asserted-account currency, the most recent reconciliation date,
the earliest journal posting date for the account (used as the suggested
``periodStart`` when the account has never been reconciled), and the per-row
transactions in ``[periodStart, periodEnd]`` from the asserted account's
perspective. Transfer rows surface only the asserted-account posting amount —
the route never has to worry about which side it's looking at.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .config_service import AppConfig
from .journal_query_service import (
    is_generated_opening_balance_transaction,
    load_transactions,
    pretty_account_name,
)
from .reconciliation_service import latest_reconciliation_date
from .transaction_helpers import (
    account_amount,
    tracked_account_display,
)
from .transfer_service import is_transfer_account, parse_transfer_metadata


@dataclass(frozen=True)
class ReconciliationContextRow:
    id: str
    date: str
    payee: str
    category: str
    signed_amount: Decimal


@dataclass(frozen=True)
class ReconciliationContext:
    opening_balance: Decimal
    currency: str
    last_reconciliation_date: date | None
    earliest_posting_date: date | None
    transactions: list[ReconciliationContextRow]


def _category_label(config: AppConfig, transaction, ledger_account: str) -> str:
    """Pick a human-readable category line for one transaction row.

    Priorities:
    1. If this is a transfer (peer is a tracked account or another non-transfer
       posting on a tracked account), label it with the peer.
    2. Otherwise, the first non-asserted, non-transfer posting account.
    3. Fall back to a generic placeholder.
    """
    transfer = parse_transfer_metadata(transaction.metadata, config.tracked_accounts)
    if transfer.peer_account_id:
        peer_name, _, _ = tracked_account_display(config, transfer.peer_account_id)
        if peer_name:
            return f"Transfer · {peer_name}"

    for posting in transaction.postings:
        if posting.account == ledger_account:
            continue
        if is_transfer_account(posting.account):
            continue
        return posting.account

    # All-transfer transaction (rare for the asserted-account view) — label by
    # the transfer leg so the user has something to read.
    for posting in transaction.postings:
        if posting.account == ledger_account:
            continue
        return pretty_account_name(posting.account)

    return ""


def _is_assertion_only_transaction(transaction) -> bool:
    """True when the transaction is solely a balance-assertion entry written by
    the reconcile flow.  Identified by the ``reconciliation_event_id`` metadata
    key the writer always emits.
    """
    return bool(str(transaction.metadata.get("reconciliation_event_id") or "").strip())


def build_reconciliation_context(
    *,
    config: AppConfig,
    tracked_account_cfg: dict,
    period_start: date,
    period_end: date,
) -> ReconciliationContext:
    """Compute the modal payload for a single tracked account and date range.

    ``period_start`` and ``period_end`` are inclusive.  ``opening_balance`` is
    the running balance as of the close of business on ``period_start - 1 day``
    (i.e. the sum of every posting on the asserted ledger account dated strictly
    earlier than ``period_start``).

    Reconciliation-assertion transactions (zero-amount postings) are skipped
    from the visible row list — they would render as noise in the modal.  They
    contribute zero to the balance either way.
    """
    ledger_account = str(tracked_account_cfg.get("ledger_account", "")).strip()
    if not ledger_account:
        raise ValueError("Tracked account is missing a ledger account.")

    base_currency = str(config.workspace.get("base_currency", "USD")).strip().upper() or "USD"
    last_recon = latest_reconciliation_date(config, ledger_account)

    transactions = load_transactions(config)

    opening_balance = Decimal("0")
    earliest_posting: date | None = None
    rows: list[ReconciliationContextRow] = []

    for index, transaction in enumerate(transactions):
        amount, _ = account_amount(transaction, ledger_account)
        if amount is None:
            continue
        if _is_assertion_only_transaction(transaction):
            continue

        posted = transaction.posted_on
        if earliest_posting is None or posted < earliest_posting:
            earliest_posting = posted

        if posted < period_start:
            opening_balance += amount
            continue
        if posted > period_end:
            continue

        if is_generated_opening_balance_transaction(transaction):
            payee = "Opening balance"
        else:
            payee = transaction.payee

        rows.append(
            ReconciliationContextRow(
                id=f"{posted.isoformat()}-{index}",
                date=posted.isoformat(),
                payee=payee,
                category=_category_label(config, transaction, ledger_account),
                signed_amount=amount,
            )
        )

    rows.sort(key=lambda row: (row.date, row.id))

    return ReconciliationContext(
        opening_balance=opening_balance,
        currency=base_currency,
        last_reconciliation_date=last_recon,
        earliest_posting_date=earliest_posting,
        transactions=rows,
    )
