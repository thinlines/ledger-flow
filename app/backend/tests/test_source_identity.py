"""Source identity (issue #007, seam 2).

The regression these pin down is real: on 2026-04-27 two Costco purchases of
$7.92 and $127.53 posted to the same card on the same day were written with
one identical ``lf_source_identity``, because the institution posting's amount
is elided and the old extractor returned ``""`` for it.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from services import source_identity
from services.source_identity import IdentityInputError, SourceIdentity

CARD = "Liabilities:Wells:Fargo:Credit:Card"
ACCOUNT_ID = "wells_fargo_credit_card_9867"

# The two colliding blocks exactly as the journal holds them.
COSTCO_SMALL = [
    {"account": "Expenses:Eating Out", "amount": "USD 7.92"},
    {"account": CARD, "amount": ""},
]
COSTCO_LARGE = [
    {"account": "Expenses:Shopping:Groceries", "amount": "USD 127.53"},
    {"account": CARD, "amount": ""},
]


# ---------------------------------------------------------------------------
# institution_amount — the elided-posting fix
# ---------------------------------------------------------------------------


def test_elided_institution_amount_is_derived_from_the_counter_posting() -> None:
    assert source_identity.institution_amount(COSTCO_SMALL, CARD) == Decimal("-7.92")
    assert source_identity.institution_amount(COSTCO_LARGE, CARD) == Decimal("-127.53")


def test_explicit_institution_amount_is_used_as_written() -> None:
    postings = [
        {"account": "Expenses:Eating Out", "amount": "USD 7.92"},
        {"account": CARD, "amount": "USD -7.92"},
    ]
    assert source_identity.institution_amount(postings, CARD) == Decimal("-7.92")


def test_elided_amount_across_several_counter_postings_sums_them() -> None:
    postings = [
        {"account": "Expenses:Groceries", "amount": "USD 10.00"},
        {"account": "Expenses:Household", "amount": "USD 5.50"},
        {"account": CARD, "amount": ""},
    ]
    assert source_identity.institution_amount(postings, CARD) == Decimal("-15.50")


def test_indeterminable_amount_returns_none() -> None:
    """Two blank postings: ledger could not infer this either."""
    postings = [
        {"account": "Expenses:Groceries", "amount": ""},
        {"account": CARD, "amount": ""},
    ]
    assert source_identity.institution_amount(postings, CARD) is None


def test_missing_institution_posting_still_derives_the_negated_sum() -> None:
    """``ledger convert`` writes the institution posting bare, and some readers
    drop amount-less postings entirely — so this list can arrive without it.

    The institution amount is the negation of what remains either way. Returning
    the counter-posting's amount unchanged is a sign error, and it made the
    import path and the migration path disagree on 437 of 460 rows.
    """
    postings = [{"account": "Expenses:Groceries", "amount": "USD 10.00"}]
    assert source_identity.institution_amount(postings, CARD) == Decimal("-10.00")

    deposit = [{"account": "Income:Employer", "amount": "USD -975.70"}]
    assert source_identity.institution_amount(deposit, CARD) == Decimal("975.70")


def test_no_postings_at_all_returns_none() -> None:
    assert source_identity.institution_amount([], CARD) is None


# ---------------------------------------------------------------------------
# compute — the collision regression
# ---------------------------------------------------------------------------


def _identity(postings: list[dict], payee: str = "COSTCO WHSE #0761 BOISE ID"):
    return source_identity.compute(
        import_account_id=ACCOUNT_ID,
        date="2026/04/27",
        statement_payee=payee,
        amount=source_identity.institution_amount(postings, CARD),
    )


def test_same_day_same_merchant_different_amounts_no_longer_collide() -> None:
    """The 2026-04-27 Costco regression."""
    assert _identity(COSTCO_SMALL).value != _identity(COSTCO_LARGE).value


def test_the_same_row_identifies_identically_across_runs() -> None:
    assert _identity(COSTCO_SMALL).value == _identity(COSTCO_SMALL).value


def test_a_purchase_and_its_refund_do_not_collide() -> None:
    """2026-03-03 Costco: 235.69 and a -60.41 return."""
    purchase = [
        {"account": "Expenses:Shopping:Groceries", "amount": "USD 235.69"},
        {"account": CARD, "amount": ""},
    ]
    refund = [
        {"account": "Expenses:Shopping:Groceries", "amount": "USD -60.41"},
        {"account": CARD, "amount": ""},
    ]
    assert _identity(purchase).value != _identity(refund).value


def test_payee_whitespace_and_case_do_not_change_identity() -> None:
    """The same row exported by two statement formats is one row."""
    spaced = _identity(COSTCO_SMALL, payee="COSTCO WHSE   #0761   BOISE ID")
    plain = _identity(COSTCO_SMALL, payee="costco whse #0761 boise id")
    assert spaced.value == plain.value


def test_amount_rendering_does_not_change_identity() -> None:
    """``USD -7.92`` and ``-7.92`` are the same amount, so the same row."""
    commodity_first = source_identity.compute(
        import_account_id=ACCOUNT_ID, date="2026/04/27",
        statement_payee="COSTCO", amount=Decimal("-7.92"),
    )
    bare = source_identity.compute(
        import_account_id=ACCOUNT_ID, date="2026/04/27",
        statement_payee="COSTCO", amount=Decimal("-7.920"),
    )
    assert commodity_first.value == bare.value


def test_identity_is_scoped_to_the_import_account() -> None:
    a = source_identity.compute(
        import_account_id="acct_a", date="2026/04/27",
        statement_payee="COSTCO", amount=Decimal("-7.92"),
    )
    b = source_identity.compute(
        import_account_id="acct_b", date="2026/04/27",
        statement_payee="COSTCO", amount=Decimal("-7.92"),
    )
    assert a.value != b.value


def test_missing_amount_is_refused_rather_than_hashed_blank() -> None:
    with pytest.raises(IdentityInputError, match="without an amount"):
        source_identity.compute(
            import_account_id=ACCOUNT_ID, date="2026/04/27",
            statement_payee="COSTCO", amount=None,
        )


# ---------------------------------------------------------------------------
# Generation 1 compatibility
# ---------------------------------------------------------------------------


def test_legacy_value_reproduces_the_hash_this_workspace_actually_stored() -> None:
    """The real ``lf_source_identity`` on both 2026-04-27 Costco blocks.

    Generation 1 hashed an empty amount, which is why one value covers two
    different purchases. Reproducing it exactly is what lets a re-import
    recognise pre-fix rows without rewriting journal data.
    """
    stored = "6e54f8c786b3717650153c7b80c6775ab0232b021c1cff0292a3de976571d568"

    small = _identity(COSTCO_SMALL)
    large = _identity(COSTCO_LARGE)

    assert small.legacy_value == stored
    assert large.legacy_value == stored


def test_matches_accepts_either_generation() -> None:
    identity = _identity(COSTCO_SMALL)

    assert identity.matches(identity.value)
    assert identity.matches(identity.legacy_value)
    assert not identity.matches("something-else")
    assert not identity.matches(None)
    assert not identity.matches("")


def test_legacy_only_match_is_distinguishable_from_a_current_match() -> None:
    """A caller must be able to tell 'certainly this row' from 'a hash that
    could not tell rows apart'."""
    identity = _identity(COSTCO_SMALL)

    assert identity.is_legacy_only_match(identity.legacy_value)
    assert not identity.is_legacy_only_match(identity.value)
    assert not identity.is_legacy_only_match("something-else")


# ---------------------------------------------------------------------------
# Key names and the carried-duplicate suffix family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("lf_source_identity", "1"),
        ("lf_source_identity_2", "2"),
        ("lf_source_identity_13", "13"),
        ("source_payload_hash", "1"),
        ("source_payload_hash_2", "2"),
        ("source_identity", None),
        ("lf_source_identity_x", None),
        ("lf_txn_id", None),
        ("", None),
    ],
)
def test_suffix_of_covers_both_families(key: str, expected: str | None) -> None:
    assert source_identity.suffix_of(key) == expected


def test_key_regexes_are_anchored_to_the_documented_names() -> None:
    assert source_identity.IDENTITY_KEY == "lf_source_identity"
    assert source_identity.PAYLOAD_HASH_KEY == "source_payload_hash"
    assert source_identity.IDENTITY_KEY_RE.match("lf_source_identity_2")
    assert not source_identity.IDENTITY_KEY_RE.match("xlf_source_identity")


def test_source_identity_is_hashable_and_comparable() -> None:
    a = SourceIdentity(value="v", legacy_value="l")
    b = SourceIdentity(value="v", legacy_value="l")
    assert a == b
    assert len({a, b}) == 1
