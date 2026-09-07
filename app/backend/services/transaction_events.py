"""Transaction events: the register/unified build pipeline.

The public interface is `account_events`. Everything else in this module is
implementation detail — pending-transfer settlement matching, event
construction, and the presentation vocabulary the events carry.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from functools import cache

from .config_service import AppConfig, infer_account_kind
from .header_parser import TransactionStatus
from .journal_query_service import (
    account_amount,
    amount_to_number,
    is_generated_opening_balance_transaction,
    pretty_account_name,
)
from .projection_service import load_transactions_projected
from .transfer_service import (
    MAX_TRANSFER_MATCH_DAYS,
    TRANSFER_STATE_BILATERAL_MATCH,
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
    clearing_status: str = "unmarked"
    header_line: str = ""
    journal_path: str = ""
    match_id: str | None = None
    notes: str | None = None
    # Raw statement text preserved by the import merchant layer (issue #24).
    statement_payee: str | None = None
    affects_balance: bool = True
    counts_as_transaction: bool = True
    # Stable projected identity for the (lf_txn_id, raw_block_hash) mutation
    # contract; None when the row came from the legacy loader.
    txn_id: str | None = None
    block_hash: str | None = None
    # Which tracked account this event belongs to.
    account_id: str = ""
    account_label: str = ""
    categories: list[dict] = field(default_factory=list)
    is_transfer: bool = False
    is_manual: bool = False
    is_assertion: bool = False

@dataclass(frozen=True)
class PendingTransferCandidate:
    order: int
    posted_on: date
    source_tracked_account_id: str
    peer_account_id: str
    transfer_account: str
    amount: Decimal

def _grouped_settlement_subset_mask(candidates: list[PendingTransferCandidate], indexes: list[int]) -> int:
    if len(indexes) < 3:
        return 0
    if (candidates[indexes[-1]].posted_on - candidates[indexes[0]].posted_on).days > MAX_TRANSFER_MATCH_DAYS:
        return 0

    if sum((candidates[index].amount for index in indexes), Decimal(0)) != Decimal(0):
        return 0

    if len({candidates[index].source_tracked_account_id for index in indexes}) < 2:
        return 0

    for left_offset, left_index in enumerate(indexes):
        left_candidate = candidates[left_index]
        for right_index in indexes[left_offset + 1:]:
            right_candidate = candidates[right_index]
            if left_candidate.source_tracked_account_id == right_candidate.source_tracked_account_id:
                continue
            if left_candidate.amount + right_candidate.amount == Decimal(0):
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

    @cache
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

def _settled_orders(candidates: list[PendingTransferCandidate]) -> set[int]:
    """Orders belonging to a uniquely-resolvable balanced settlement group."""
    by_transfer_account: dict[str, list[PendingTransferCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_transfer_account[candidate.transfer_account].append(candidate)

    settled: set[int] = set()
    for group in by_transfer_account.values():
        if len(group) < 3:
            continue
        ordered = sorted(group, key=lambda candidate: (candidate.posted_on, candidate.order))
        masks = _candidate_group_masks(ordered)
        if not masks:
            continue

        for component_mask in _grouped_settlement_components(len(ordered), masks):
            component_masks = [mask for mask in masks if mask & component_mask == mask]
            covered_mask = _unique_grouped_component_mask(component_mask, component_masks)
            if not covered_mask:
                continue
            for index, candidate in enumerate(ordered):
                if covered_mask & (1 << index):
                    settled.add(candidate.order)

    return settled


def _bilateral_orders(candidates: list[PendingTransferCandidate]) -> set[int]:
    """Orders in an unambiguous two-sided pending pair.

    Callers pass candidates with settled-group rows already removed.
    """
    candidates_by_transfer_account: dict[str, list[PendingTransferCandidate]] = defaultdict(list)
    for candidate in candidates:
        candidates_by_transfer_account[candidate.transfer_account].append(candidate)

    bilateral_orders: set[int] = set()
    for candidates in candidates_by_transfer_account.values():
        if len(candidates) < 2:
            continue

        by_abs_amount: dict[Decimal, list[PendingTransferCandidate]] = defaultdict(list)
        for candidate in candidates:
            by_abs_amount[abs(candidate.amount)].append(candidate)

        for group in by_abs_amount.values():
            sides: dict[str, list[PendingTransferCandidate]] = defaultdict(list)
            for candidate in group:
                sides[candidate.source_tracked_account_id].append(candidate)

            if len(sides) != 2:
                continue

            side_a, side_b = list(sides.values())

            valid_pairs: list[tuple[PendingTransferCandidate, PendingTransferCandidate]] = []
            for a in side_a:
                for b in side_b:
                    if abs((a.posted_on - b.posted_on).days) <= MAX_TRANSFER_MATCH_DAYS:
                        valid_pairs.append((a, b))

            for a, b in valid_pairs:
                ambiguous = False
                for c in group:
                    if c.order == a.order or c.order == b.order:
                        continue
                    if (
                        abs((c.posted_on - a.posted_on).days) <= MAX_TRANSFER_MATCH_DAYS
                        or abs((c.posted_on - b.posted_on).days) <= MAX_TRANSFER_MATCH_DAYS
                    ):
                        ambiguous = True
                        break
                if not ambiguous:
                    bilateral_orders.add(a.order)
                    bilateral_orders.add(b.order)

    return bilateral_orders



def _source_tracked_account_details(
    config: AppConfig,
    transaction,
) -> tuple[str | None, str | None, str | None, str | None]:
    import_account_id = str(transaction.metadata.get("import_account_id") or "").strip() or None
    import_account = config.import_account(import_account_id)
    source_tracked_account_id = (
        import_account.tracked_account_id if import_account is not None else None
    )
    if source_tracked_account_id is None and config.account(import_account_id) is not None:
        source_tracked_account_id = import_account_id

    source = config.account(source_tracked_account_id) if source_tracked_account_id else None
    if source is not None and source.ledger_account:
        return (source_tracked_account_id, source.display_name, source.ledger_account, source.kind)

    for posting in transaction.postings:
        if is_transfer_account(posting.account):
            continue
        account = config.account_for_ledger(posting.account)
        if account is not None:
            return (account.id, account.display_name, account.ledger_account, account.kind)
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

    amount, _ = account_amount(transaction, source_ledger_account)
    transfer_acct, transfer_amt = _transfer_account_amount(transaction)
    if amount is None or transfer_acct is None or transfer_amt is None:
        return None

    expected_transfer_account = transfer_pair_account(source_tracked_account_id, transfer.peer_account_id)
    if transfer_acct != expected_transfer_account or amount + transfer_amt != Decimal(0):
        return None

    return PendingTransferCandidate(
        order=order,
        posted_on=transaction.posted_on,
        source_tracked_account_id=source_tracked_account_id,
        peer_account_id=transfer.peer_account_id,
        transfer_account=transfer_acct,
        amount=amount,
    )


def _other_tracked_posting_details(
    config: AppConfig,
    postings,
    current_account_id: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    for posting in postings:
        if is_transfer_account(posting.account):
            continue
        tracked = config.account_for_ledger(posting.account)
        if tracked is None or tracked.id == current_account_id:
            continue
        return (tracked.id, tracked.display_name, posting.account, tracked.kind)
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
        peer = config.account(transfer.peer_account_id)
        if peer is None:
            return (transfer.peer_account_id, None, None, None)
        return (
            transfer.peer_account_id,
            peer.display_name,
            peer.ledger_account or None,
            peer.kind,
        )

    source_account_id, source_name, source_ledger_account, source_kind = _source_tracked_account_details(config, transaction)
    if source_account_id is not None and source_account_id != current_account_id:
        return (source_account_id, source_name, source_ledger_account, source_kind)

    return _other_tracked_posting_details(config, transaction.postings, current_account_id)


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


def _transaction_summary(
    config: AppConfig,
    transaction,
    other_postings,
    current_account_id: str,
    *,
    grouped_settled: bool = False,
    bilateral_matched: bool = False,
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
        elif bilateral_matched and transfer.is_pending:
            transfer_state = TRANSFER_STATE_BILATERAL_MATCH
        elif transfer.is_pending:
            summary = f"{summary} (Pending)"
            transfer_state = None
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


def _opening_balance_detail_line(config: AppConfig, offset_account: str) -> dict[str, str]:
    tracked = config.account_for_ledger(offset_account)
    if tracked is not None and tracked.display_name:
        return {
            "label": tracked.display_name,
            "account": offset_account,
            "kind": tracked.kind or infer_account_kind(offset_account),
        }

    return {
        "label": pretty_account_name(offset_account),
        "account": offset_account,
        "kind": infer_account_kind(offset_account),
    }


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

    source_amount, source_commodity = account_amount(transaction, source_ledger_account)
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
        clearing_status=transaction.status.value,
        header_line=transaction.header_line,
        journal_path=transaction.source_journal,
        affects_balance=False,
        counts_as_transaction=False,
        txn_id=transaction.txn_id,
        block_hash=transaction.block_hash,
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

    source_amount, source_commodity = account_amount(transaction, source_ledger_account)
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
        clearing_status=transaction.status.value,
        header_line=transaction.header_line,
        journal_path=transaction.source_journal,
        affects_balance=True,
        counts_as_transaction=True,
        txn_id=transaction.txn_id,
        block_hash=transaction.block_hash,
    )


def _build_categories(transaction, tracked_ledger_account: str) -> list[dict]:
    """The N-1 categories list: every posting but the tracked and transfer legs."""
    categories = []
    for posting in transaction.postings:
        if posting.account == tracked_ledger_account:
            continue
        if is_transfer_account(posting.account):
            continue
        categories.append({
            "account": posting.account,
            "label": pretty_account_name(posting.account),
            "amount": amount_to_number(posting.amount) if posting.amount is not None else 0.0,
        })
    return categories


def _pending_transfer_candidates(config: AppConfig, transactions: list) -> list[PendingTransferCandidate]:
    candidates = []
    for order, transaction in enumerate(transactions):
        candidate = _pending_transfer_candidate(config, transaction, order)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _in_scope_event(
    config: AppConfig,
    transaction,
    order: int,
    scope: dict[str, tuple[str, str]],
    settled_orders: set[int],
    matched_orders: set[int],
) -> RegisterEvent | None:
    """The event for the first scoped account this transaction posts to."""
    for ledger_account, (account_id, account_label) in scope.items():
        amount, commodity = account_amount(transaction, ledger_account)
        if amount is None:
            continue

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
            lines = [_opening_balance_detail_line(config, offset_account)]
        else:
            summary, is_unknown, transfer_state, transfer_peer_account_id, transfer_peer_name = _transaction_summary(
                config,
                transaction,
                other_postings,
                account_id,
                grouped_settled=order in settled_orders,
                bilateral_matched=order in matched_orders,
            )
            if is_generated_opening:
                is_unknown = False
            lines = _detail_lines(config, transaction, other_postings, account_id)

        transfer = parse_transfer_metadata(transaction.metadata, config.tracked_accounts)
        has_import = bool(str(transaction.metadata.get("import_account_id") or "").strip())

        return RegisterEvent(
            posted_on=transaction.posted_on,
            order=order,
            amount=amount,
            commodity=commodity,
            payee=transaction.payee,
            summary=summary,
            is_unknown=is_unknown,
            is_opening_balance=is_primary_opening,
            detail_lines=lines,
            transfer_state=transfer_state,
            transfer_peer_account_id=transfer_peer_account_id,
            transfer_peer_account_name=transfer_peer_name,
            clearing_status=transaction.status.value,
            header_line=transaction.header_line,
            journal_path=transaction.source_journal,
            match_id=transaction.metadata.get("match-id") or None,
            notes=transaction.metadata.get("notes") or None,
            statement_payee=transaction.metadata.get("statement_payee") or None,
            counts_as_transaction=not is_generated_opening,
            txn_id=transaction.txn_id,
            block_hash=transaction.block_hash,
            account_id=account_id,
            account_label=account_label,
            categories=_build_categories(transaction, ledger_account),
            is_transfer=bool(transfer.peer_account_id),
            is_manual=(
                transaction.status == TransactionStatus.unmarked
                and not has_import
                and not is_generated_opening
            ),
            is_assertion=bool(str(transaction.metadata.get("lf_operation_id") or "").strip()),
        )

    return None


def account_events(config: AppConfig, account_ids: list[str]) -> list[RegisterEvent]:
    """Every register event for `account_ids`, ordered oldest first.

    Pending-transfer settlement is fully resolved before returning: callers
    never see candidates, masks, or the settled-before-matched ordering. A
    single-account scope also gets synthetic peer rows for transfers whose
    other side lives outside the journal's own postings.
    """
    scope: dict[str, tuple[str, str]] = {}
    for account_id in account_ids:
        tracked = config.account(account_id)
        if tracked is None:
            raise ValueError(f"Tracked account not found: {account_id}")
        if tracked.ledger_account:
            scope[tracked.ledger_account] = (account_id, tracked.display_name)

    transactions = load_transactions_projected(config)
    candidates = _pending_transfer_candidates(config, transactions)
    settled_orders = _settled_orders(candidates)
    matched_orders = _bilateral_orders(
        [candidate for candidate in candidates if candidate.order not in settled_orders]
    )
    pending_excluded_orders = settled_orders | matched_orders

    single_account_scope = len(account_ids) == 1
    events: list[RegisterEvent] = []

    for order, transaction in enumerate(transactions):
        event = _in_scope_event(config, transaction, order, scope, settled_orders, matched_orders)
        if event is not None:
            events.append(event)
            continue

        if not single_account_scope:
            continue

        account_id = account_ids[0]
        tracked = config.account(account_id)
        account_label = tracked.display_name if tracked is not None else account_id

        peer_event = _pending_transfer_event_for_peer_account(
            config, transaction, account_id, order, pending_excluded_orders,
        )
        if peer_event is None:
            peer_event = _direct_transfer_event_for_peer_account(config, transaction, account_id, order)
        if peer_event is not None:
            events.append(replace(
                peer_event,
                account_id=account_id,
                account_label=account_label,
                is_transfer=True,
            ))

    events.sort(key=lambda event: (event.posted_on, event.order))
    return events
