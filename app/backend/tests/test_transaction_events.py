from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import write_year_journal
from services.transaction_events import (
    PendingTransferCandidate,
    account_events,
    _bilateral_orders,
    _settled_orders,
)
from services.transfer_service import transfer_pair_account

PAIR = transfer_pair_account("checking", "savings")


def _candidate(
    order: int,
    day: int,
    source: str,
    amount: str,
    *,
    peer: str | None = None,
    transfer_account: str = PAIR,
) -> PendingTransferCandidate:
    return PendingTransferCandidate(
        order=order,
        posted_on=date(2026, 3, day),
        source_tracked_account_id=source,
        peer_account_id=peer or ("savings" if source == "checking" else "checking"),
        transfer_account=transfer_account,
        amount=Decimal(amount),
    )


def test_balanced_group_across_two_accounts_settles_every_row() -> None:
    candidates = [
        _candidate(0, 12, "checking", "-0.46"),
        _candidate(1, 12, "savings", "0.12"),
        _candidate(2, 12, "savings", "0.34"),
    ]

    assert _settled_orders(candidates) == {0, 1, 2}


def test_opposing_pair_within_window_is_bilaterally_matched() -> None:
    candidates = [
        _candidate(0, 12, "checking", "-25.00"),
        _candidate(1, 14, "savings", "25.00"),
    ]

    assert _bilateral_orders(candidates) == {0, 1}


def test_unbalanced_remainder_stays_pending_while_balanced_subset_settles() -> None:
    candidates = [
        _candidate(0, 12, "checking", "-0.46"),
        _candidate(1, 12, "savings", "0.12"),
        _candidate(2, 12, "savings", "0.34"),
        _candidate(3, 13, "savings", "0.10"),
    ]

    assert _settled_orders(candidates) == {0, 1, 2}


def test_group_resolvable_two_ways_fails_closed() -> None:
    # Two $0.12 rows and two $0.34 rows: the zero-sum set can be partitioned
    # more than one way, so grouped settlement must decline to pick.
    candidates = [
        _candidate(0, 12, "checking", "-0.12"),
        _candidate(1, 12, "checking", "-0.34"),
        _candidate(2, 12, "savings", "0.12"),
        _candidate(3, 12, "savings", "0.34"),
    ]

    assert _settled_orders(candidates) == set()


def test_group_confined_to_one_account_never_settles() -> None:
    candidates = [
        _candidate(0, 12, "checking", "-0.46"),
        _candidate(1, 12, "checking", "0.12"),
        _candidate(2, 12, "checking", "0.34"),
    ]

    assert _settled_orders(candidates) == set()


def test_group_smaller_than_three_rows_never_settles() -> None:
    candidates = [
        _candidate(0, 12, "checking", "-0.46"),
        _candidate(1, 12, "savings", "0.46"),
    ]

    assert _settled_orders(candidates) == set()


def test_group_wider_than_the_window_row_cap_never_settles() -> None:
    # The only zero-sum subset spans 9 rows, one more than
    # MAX_GROUPED_SETTLEMENT_WINDOW_ROWS, so no window can cover it.
    candidates = [_candidate(0, 12, "checking", "-100.00")]
    candidates += [_candidate(index, 12, "savings", "11.00") for index in range(1, 8)]
    candidates.append(_candidate(8, 12, "savings", "23.00"))

    assert _settled_orders(candidates) == set()


def test_two_equal_pairs_are_too_ambiguous_to_match_bilaterally() -> None:
    candidates = [
        _candidate(0, 1, "checking", "-500.00"),
        _candidate(1, 1, "checking", "-500.00"),
        _candidate(2, 3, "savings", "500.00"),
        _candidate(3, 3, "savings", "500.00"),
    ]

    assert _bilateral_orders(candidates) == set()


def test_pair_exactly_on_the_window_edge_still_matches() -> None:
    candidates = [
        _candidate(0, 1, "checking", "-100.00"),
        _candidate(1, 8, "savings", "100.00"),
    ]

    assert _bilateral_orders(candidates) == {0, 1}


def test_pair_one_day_past_the_window_does_not_match() -> None:
    candidates = [
        _candidate(0, 1, "checking", "-100.00"),
        _candidate(1, 9, "savings", "100.00"),
    ]

    assert _bilateral_orders(candidates) == set()


def test_distinct_amount_pairs_match_bilaterally_when_grouping_declines() -> None:
    candidates = [
        _candidate(0, 12, "checking", "-0.12"),
        _candidate(1, 12, "checking", "-0.34"),
        _candidate(2, 12, "savings", "0.12"),
        _candidate(3, 12, "savings", "0.34"),
    ]

    assert _settled_orders(candidates) == set()
    assert _bilateral_orders(candidates) == {0, 1, 2, 3}


def test_settlement_runs_before_matching_and_the_two_do_not_overlap() -> None:
    other_pair = transfer_pair_account("checking", "brokerage")
    candidates = [
        _candidate(0, 12, "checking", "-0.46"),
        _candidate(1, 12, "savings", "0.12"),
        _candidate(2, 12, "savings", "0.34"),
        _candidate(3, 12, "checking", "-90.00", peer="brokerage", transfer_account=other_pair),
        _candidate(4, 13, "brokerage", "90.00", peer="checking", transfer_account=other_pair),
    ]

    settled = _settled_orders(candidates)
    remaining = [candidate for candidate in candidates if candidate.order not in settled]

    assert settled == {0, 1, 2}
    assert _bilateral_orders(remaining) == {3, 4}


GROUPED_SETTLEMENT_JOURNAL = f"""
2026/03/12 ACH verification withdrawal
    ; import_account_id: checking
    ; transfer_id: transfer-checking
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: savings
    {PAIR}  $0.46
    Assets:Bank:Checking

2026/03/12 ACH verification deposit 1
    ; import_account_id: savings
    ; transfer_id: transfer-savings-1
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {PAIR}  $-0.12
    Assets:Bank:Savings

2026/03/12 ACH verification deposit 2
    ; import_account_id: savings
    ; transfer_id: transfer-savings-2
    ; transfer_type: import_match
    ; transfer_match_state: pending
    ; transfer_peer_account_id: checking
    {PAIR}  $-0.34
    Assets:Bank:Savings
""".strip() + "\n"


def test_account_events_resolves_settlement_without_caller_orchestration(books_config) -> None:
    write_year_journal(books_config, GROUPED_SETTLEMENT_JOURNAL)

    events = account_events(books_config, ["savings"])

    assert [event.amount for event in events] == [Decimal("0.12"), Decimal("0.34")]
    assert {event.transfer_state for event in events} == {"settled_grouped"}
    assert all(event.account_id == "savings" for event in events)
