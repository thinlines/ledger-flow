from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache

from .commodity_service import CommodityMismatchError, commodity_label
from .config_service import AppConfig, infer_account_kind
from .journal_query_service import (
    amount_to_number,
    is_generated_opening_balance_transaction,
    load_transactions,
    pretty_account_name,
)
from .transfer_service import (
    MAX_TRANSFER_MATCH_DAYS,
    TRANSFER_STATE_SETTLED_GROUPED,
    is_transfer_account,
    parse_transfer_metadata,
    transfer_pair_account,
)


MAX_GROUPED_SETTLEMENT_WINDOW_ROWS = 8


@dataclass(frozen=True)
class RegisterEvent:
    posted_on: date
    order: int
    amount: Decimal
    commodity: str | None
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


@dataclass(frozen=True)
class PendingTransferCandidate:
    order: int
    posted_on: date
    source_tracked_account_id: str
    peer_account_id: str
    transfer_account: str
    amount: Decimal


def _account_amount(transaction, ledger_account: str) -> tuple[Decimal | None, str | None]:
    matched = [posting for posting in transaction.postings if posting.account == ledger_account and posting.amount is not None]
    if not matched:
        return (None, None)

    commodities = {posting.commodity for posting in matched}
    if len(commodities) > 1:
        raise CommodityMismatchError(
            f"Account {ledger_account} mixes commodities within one transaction "
            f"({', '.join(sorted(commodity_label(commodity) for commodity in commodities))})."
        )

    return (
        sum((posting.amount or Decimal("0")) for posting in matched),
        next(iter(commodities), None),
    )


def _next_running_commodity(
    ledger_account: str,
    current: str | None,
    incoming: str | None,
    *,
    initialized: bool,
) -> str | None:
    if not initialized:
        return incoming
    if current != incoming:
        raise CommodityMismatchError(
            f"Account {ledger_account} mixes commodities in its running balance "
            f"({commodity_label(current)} and {commodity_label(incoming)})."
        )
    return current


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


def _transfer_account_amount(transaction) -> tuple[str | None, Decimal | None]:
    transfer_postings = [
        posting
        for posting in transaction.postings
        if is_transfer_account(posting.account) and posting.amount is not None
    ]
    if len(transfer_postings) != 1:
        return (None, None)
    return (transfer_postings[0].account, transfer_postings[0].amount)


def _pending_transfer_candidate(
    config: AppConfig,
    transaction,
    order: int,
) -> PendingTransferCandidate | None:
    transfer = parse_transfer_metadata(transaction.metadata, config.tracked_accounts)
    if not transfer.is_pending or not transfer.peer_account_id:
        return None

    source_tracked_account_id, _, source_ledger_account, _ = _source_tracked_account_details(config, transaction)
    if not source_tracked_account_id or not source_ledger_account or source_tracked_account_id == transfer.peer_account_id:
        return None

    amount, _ = _account_amount(transaction, source_ledger_account)
    transfer_account, transfer_amount = _transfer_account_amount(transaction)
    if amount is None or transfer_account is None or transfer_amount is None:
        return None

    expected_transfer_account = transfer_pair_account(source_tracked_account_id, transfer.peer_account_id)
    if transfer_account != expected_transfer_account or amount + transfer_amount != Decimal("0"):
        return None

    return PendingTransferCandidate(
        order=order,
        posted_on=transaction.posted_on,
        source_tracked_account_id=source_tracked_account_id,
        peer_account_id=transfer.peer_account_id,
        transfer_account=transfer_account,
        amount=amount,
    )


def _grouped_settlement_subset_mask(candidates: list[PendingTransferCandidate], indexes: list[int]) -> int:
    if len(indexes) < 3:
        return 0
    if (candidates[indexes[-1]].posted_on - candidates[indexes[0]].posted_on).days > MAX_TRANSFER_MATCH_DAYS:
        return 0

    if sum((candidates[index].amount for index in indexes), Decimal("0")) != Decimal("0"):
        return 0

    if len({candidates[index].source_tracked_account_id for index in indexes}) < 2:
        return 0

    for left_offset, left_index in enumerate(indexes):
        left_candidate = candidates[left_index]
        for right_index in indexes[left_offset + 1 :]:
            right_candidate = candidates[right_index]
            if left_candidate.source_tracked_account_id == right_candidate.source_tracked_account_id:
                continue
            if left_candidate.amount + right_candidate.amount == Decimal("0"):
                return 0

    mask = 0
    for index in indexes:
        mask |= 1 << index
    return mask


def _candidate_group_masks(candidates: list[PendingTransferCandidate]) -> list[int]:
    masks: set[int] = set()
    candidate_count = len(candidates)
    for start in range(candidate_count - 2):
        window_indexes = [start]
        for end in range(start + 1, candidate_count):
            if (candidates[end].posted_on - candidates[start].posted_on).days > MAX_TRANSFER_MATCH_DAYS:
                break
            window_indexes.append(end)

        if len(window_indexes) < 3 or len(window_indexes) > MAX_GROUPED_SETTLEMENT_WINDOW_ROWS:
            continue

        trailing_indexes = window_indexes[1:]
        for selected in range(1 << len(trailing_indexes)):
            if selected.bit_count() < 2:
                continue
            indexes = [start]
            indexes.extend(
                trailing_indexes[offset]
                for offset in range(len(trailing_indexes))
                if selected & (1 << offset)
            )
            mask = _grouped_settlement_subset_mask(candidates, indexes)
            if mask:
                masks.add(mask)
    return sorted(masks)


def _mask_packings_union(packings: tuple[tuple[int, ...], ...], additions: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    merged: list[tuple[int, ...]] = list(packings)
    for packing in additions:
        if packing in merged:
            continue
        merged.append(packing)
        if len(merged) == 2:
            break
    return tuple(merged)


def _unique_grouped_component_mask(component_mask: int, masks: list[int]) -> int:
    row_masks: dict[int, list[int]] = defaultdict(list)
    for mask in masks:
        row_bits = mask
        while row_bits:
            row_bit = row_bits & -row_bits
            row_masks[row_bit.bit_length() - 1].append(mask)
            row_bits ^= row_bit

    @lru_cache(maxsize=None)
    def _solve(available_mask: int) -> tuple[int, tuple[tuple[int, ...], ...]]:
        if available_mask == 0:
            return (0, ((),))

        first_bit = available_mask & -available_mask
        first_index = first_bit.bit_length() - 1

        best_count, best_packings = _solve(available_mask ^ first_bit)
        for mask in row_masks.get(first_index, []):
            if mask & available_mask != mask:
                continue
            covered_count, packings = _solve(available_mask ^ mask)
            covered_count += mask.bit_count()
            normalized = tuple(tuple(sorted((mask, *packing))) for packing in packings)
            if covered_count > best_count:
                best_count = covered_count
                best_packings = normalized[:2]
            elif covered_count == best_count:
                best_packings = _mask_packings_union(best_packings, normalized)

        return (best_count, best_packings)

    covered_count, packings = _solve(component_mask)
    if covered_count == 0 or len(packings) != 1:
        return 0

    covered_mask = 0
    for mask in packings[0]:
        covered_mask |= mask
    return covered_mask


def _grouped_settlement_components(candidate_count: int, masks: list[int]) -> list[int]:
    adjacency = [0] * candidate_count
    active_rows = 0
    for mask in masks:
        row_bits = mask
        active_rows |= mask
        while row_bits:
            row_bit = row_bits & -row_bits
            adjacency[row_bit.bit_length() - 1] |= mask
            row_bits ^= row_bit

    components: list[int] = []
    seen = 0
    for index in range(candidate_count):
        row_bit = 1 << index
        if not (active_rows & row_bit) or (seen & row_bit):
            continue

        component_mask = 0
        frontier = row_bit
        while frontier:
            current_bit = frontier & -frontier
            frontier ^= current_bit
            if component_mask & current_bit:
                continue
            component_mask |= current_bit
            frontier |= adjacency[current_bit.bit_length() - 1] & ~component_mask

        seen |= component_mask
        components.append(component_mask)

    return components


def _grouped_settled_pending_transfer_orders(config: AppConfig, transactions: list) -> set[int]:
    candidates_by_transfer_account: dict[str, list[PendingTransferCandidate]] = defaultdict(list)
    for order, transaction in enumerate(transactions):
        candidate = _pending_transfer_candidate(config, transaction, order)
        if candidate is not None:
            candidates_by_transfer_account[candidate.transfer_account].append(candidate)

    grouped_orders: set[int] = set()
    for candidates in candidates_by_transfer_account.values():
        if len(candidates) < 3:
            continue
        ordered_candidates = sorted(candidates, key=lambda candidate: (candidate.posted_on, candidate.order))
        masks = _candidate_group_masks(ordered_candidates)
        if not masks:
            continue

        for component_mask in _grouped_settlement_components(len(ordered_candidates), masks):
            component_masks = [mask for mask in masks if mask & component_mask == mask]
            covered_mask = _unique_grouped_component_mask(component_mask, component_masks)
            if not covered_mask:
                continue
            for index, candidate in enumerate(ordered_candidates):
                if covered_mask & (1 << index):
                    grouped_orders.add(candidate.order)

    return grouped_orders


def _detail_lines(
    config: AppConfig,
    transaction,
    postings,
    current_account_id: str | None,
) -> list[dict[str, str]]:
    transfer_peer_account_id, transfer_peer_name, transfer_peer_ledger_account, transfer_peer_kind = _transfer_peer_details(
        config,
        transaction,
        current_account_id,
    )
    if transfer_peer_account_id:
        label = transfer_peer_name or transfer_peer_account_id
        return [
            {
                "label": label,
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


def _other_tracked_posting_details(
    config: AppConfig,
    postings,
    current_account_id: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    for posting in postings:
        if is_transfer_account(posting.account):
            continue
        tracked_account_id, tracked_name, tracked_kind = _tracked_account_by_ledger_account(config, posting.account)
        if tracked_account_id is None or tracked_account_id == current_account_id:
            continue
        return (tracked_account_id, tracked_name, posting.account, tracked_kind)
    return (None, None, None, None)


def _transfer_peer_details(
    config: AppConfig,
    transaction,
    current_account_id: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    transfer = parse_transfer_metadata(transaction.metadata, config.tracked_accounts)
    if not transfer.peer_account_id:
        return (None, None, None, None)

    if current_account_id is None or transfer.peer_account_id != current_account_id:
        transfer_peer_name, transfer_peer_ledger_account, transfer_peer_kind = _tracked_account_display(
            config,
            transfer.peer_account_id,
        )
        return (
            transfer.peer_account_id,
            transfer_peer_name,
            transfer_peer_ledger_account,
            transfer_peer_kind,
        )

    source_account_id, source_name, source_ledger_account, source_kind = _source_tracked_account_details(config, transaction)
    if source_account_id is not None and source_account_id != current_account_id:
        return (source_account_id, source_name, source_ledger_account, source_kind)

    return _other_tracked_posting_details(config, transaction.postings, current_account_id)


def _transaction_summary(
    config: AppConfig,
    transaction,
    other_postings,
    current_account_id: str,
    *,
    grouped_settled: bool = False,
) -> tuple[str, bool, str | None, str | None, str | None]:
    transfer = parse_transfer_metadata(transaction.metadata, config.tracked_accounts)
    transfer_peer_account_id, transfer_peer_name, _, _ = _transfer_peer_details(
        config,
        transaction,
        current_account_id,
    )
    if transfer_peer_account_id:
        label = transfer_peer_name or transfer_peer_account_id
        summary = f"Transfer · {label}"
        transfer_state = transfer.transfer_state_for_ui
        if grouped_settled and transfer.is_pending:
            transfer_state = TRANSFER_STATE_SETTLED_GROUPED
        elif transfer.is_pending:
            summary = f"{summary} (Pending)"
        return (summary, False, transfer_state, transfer_peer_account_id, label)

    if not other_postings:
        return ("No category details", False, None, None, None)

    expense_postings = [posting for posting in other_postings if infer_account_kind(posting.account) == "expense"]
    income_postings = [posting for posting in other_postings if infer_account_kind(posting.account) == "income"]
    is_unknown = any(posting.account.lower().startswith("expenses:unknown") for posting in expense_postings)

    if len(other_postings) > 1:
        return (f"Split · {len(other_postings)} lines", is_unknown, None, None, None)

    primary = other_postings[0]
    label = pretty_account_name(primary.account)
    if infer_account_kind(primary.account) in {"asset", "liability"}:
        return (f"Transfer · {label}", is_unknown, None, None, None)
    if expense_postings or income_postings:
        return (label, is_unknown, None, None, None)
    return (f"Matched with {label}", is_unknown, None, None, None)


def _pending_transfer_event_for_peer_account(
    config: AppConfig,
    transaction,
    account_id: str,
    order: int,
    grouped_settled_orders: set[int],
) -> RegisterEvent | None:
    transfer = parse_transfer_metadata(transaction.metadata, config.tracked_accounts)
    if not transfer.is_pending or order in grouped_settled_orders:
        return None

    target_account_id = transfer.peer_account_id
    if target_account_id != account_id:
        return None

    source_account_id, source_name, source_ledger_account, source_kind = _source_tracked_account_details(config, transaction)
    if not source_ledger_account:
        return None

    source_amount, source_commodity = _account_amount(transaction, source_ledger_account)
    if source_amount is None:
        return None

    label = source_name or pretty_account_name(source_ledger_account)
    return RegisterEvent(
        posted_on=transaction.posted_on,
        order=order,
        amount=-source_amount,
        commodity=source_commodity,
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
        transfer_state=transfer.transfer_state_for_ui,
        transfer_peer_account_id=source_account_id,
        transfer_peer_account_name=source_name or label,
        affects_balance=False,
        counts_as_transaction=False,
    )


def _direct_transfer_event_for_peer_account(
    config: AppConfig,
    transaction,
    account_id: str,
    order: int,
) -> RegisterEvent | None:
    transfer = parse_transfer_metadata(transaction.metadata, config.tracked_accounts)
    if transfer.is_import_match or transfer.peer_account_id != account_id:
        return None

    source_account_id, source_name, source_ledger_account, source_kind = _source_tracked_account_details(config, transaction)
    if not source_ledger_account:
        return None

    source_amount, source_commodity = _account_amount(transaction, source_ledger_account)
    if source_amount is None:
        return None

    label = source_name or pretty_account_name(source_ledger_account)
    return RegisterEvent(
        posted_on=transaction.posted_on,
        order=order,
        amount=-source_amount,
        commodity=source_commodity,
        payee=transaction.payee,
        summary=f"Transfer · {label}",
        is_unknown=False,
        is_opening_balance=False,
        detail_lines=[
            {
                "label": label,
                "account": source_ledger_account,
                "kind": source_kind or infer_account_kind(source_ledger_account),
            }
        ],
        transfer_state=None,
        transfer_peer_account_id=source_account_id,
        transfer_peer_account_name=source_name or label,
        affects_balance=True,
        counts_as_transaction=True,
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

    transactions = load_transactions(config)
    grouped_settled_orders = _grouped_settled_pending_transfer_orders(config, transactions)

    events: list[RegisterEvent] = []
    for order, transaction in enumerate(transactions):
        amount, commodity = _account_amount(transaction, ledger_account)
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
                transfer_peer_account_id = None
                transfer_peer_name = None
                detail_lines = [_opening_balance_detail_line(config, offset_account)]
            else:
                summary, is_unknown, transfer_state, transfer_peer_account_id, transfer_peer_name = _transaction_summary(
                    config,
                    transaction,
                    other_postings,
                    account_id,
                    grouped_settled=order in grouped_settled_orders,
                )
                if is_generated_opening:
                    is_unknown = False
                detail_lines = _detail_lines(config, transaction, other_postings, account_id)
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
                    detail_lines=detail_lines,
                    transfer_state=transfer_state,
                    transfer_peer_account_id=transfer_peer_account_id,
                    transfer_peer_account_name=transfer_peer_name,
                    counts_as_transaction=not is_generated_opening,
                )
            )
            continue

        pending_peer_event = _pending_transfer_event_for_peer_account(
            config,
            transaction,
            account_id,
            order,
            grouped_settled_orders,
        )
        if pending_peer_event is not None:
            events.append(pending_peer_event)
            continue

        direct_peer_event = _direct_transfer_event_for_peer_account(config, transaction, account_id, order)
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
            balance_commodity = _next_running_commodity(
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
