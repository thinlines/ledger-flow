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
from services.source_identity import IdentityInputError

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
    assert source_identity._institution_amount(COSTCO_SMALL, CARD) == Decimal("-7.92")
    assert source_identity._institution_amount(COSTCO_LARGE, CARD) == Decimal("-127.53")


def test_explicit_institution_amount_is_used_as_written() -> None:
    postings = [
        {"account": "Expenses:Eating Out", "amount": "USD 7.92"},
        {"account": CARD, "amount": "USD -7.92"},
    ]
    assert source_identity._institution_amount(postings, CARD) == Decimal("-7.92")


def test_elided_amount_across_several_counter_postings_sums_them() -> None:
    postings = [
        {"account": "Expenses:Groceries", "amount": "USD 10.00"},
        {"account": "Expenses:Household", "amount": "USD 5.50"},
        {"account": CARD, "amount": ""},
    ]
    assert source_identity._institution_amount(postings, CARD) == Decimal("-15.50")


def test_indeterminable_amount_returns_none() -> None:
    """Two blank postings: ledger could not infer this either."""
    postings = [
        {"account": "Expenses:Groceries", "amount": ""},
        {"account": CARD, "amount": ""},
    ]
    assert source_identity._institution_amount(postings, CARD) is None


def test_missing_institution_posting_still_derives_the_negated_sum() -> None:
    """``ledger convert`` writes the institution posting bare, and some readers
    drop amount-less postings entirely — so this list can arrive without it.

    The institution amount is the negation of what remains either way. Returning
    the counter-posting's amount unchanged is a sign error, and it made the
    import path and the migration path disagree on 437 of 460 rows.
    """
    postings = [{"account": "Expenses:Groceries", "amount": "USD 10.00"}]
    assert source_identity._institution_amount(postings, CARD) == Decimal("-10.00")

    deposit = [{"account": "Income:Employer", "amount": "USD -975.70"}]
    assert source_identity._institution_amount(deposit, CARD) == Decimal("975.70")


def test_no_postings_at_all_returns_none() -> None:
    assert source_identity._institution_amount([], CARD) is None


# ---------------------------------------------------------------------------
# compute — the collision regression
# ---------------------------------------------------------------------------


def _identity(
    postings: list[dict],
    payee: str = "COSTCO WHSE #0761 BOISE ID",
    account_id: str = ACCOUNT_ID,
):
    return source_identity.of_statement_row(
        import_account_id=account_id,
        date="2026/04/27",
        statement_payee=payee,
        postings=postings,
        institution_account=CARD,
    )


def _card_posting(amount: str) -> list[dict]:
    """One explicit institution posting — the amount, with nothing to derive."""
    return [{"account": CARD, "amount": amount}]


def test_same_day_same_merchant_different_amounts_no_longer_collide() -> None:
    """The 2026-04-27 Costco regression."""
    assert _identity(COSTCO_SMALL) != _identity(COSTCO_LARGE)


def test_the_same_row_identifies_identically_across_runs() -> None:
    assert _identity(COSTCO_SMALL) == _identity(COSTCO_SMALL)


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
    assert _identity(purchase) != _identity(refund)


def test_payee_whitespace_and_case_do_not_change_identity() -> None:
    """The same row exported by two statement formats is one row."""
    spaced = _identity(COSTCO_SMALL, payee="COSTCO WHSE   #0761   BOISE ID")
    plain = _identity(COSTCO_SMALL, payee="costco whse #0761 boise id")
    assert spaced == plain


def test_amount_rendering_does_not_change_identity() -> None:
    """``USD -7.92`` and ``-7.92`` are the same amount, so the same row."""
    commodity_first = _identity(_card_posting("USD -7.92"), payee="COSTCO")
    bare = _identity(_card_posting("-7.920"), payee="COSTCO")
    assert commodity_first == bare


def test_identity_is_scoped_to_the_import_account() -> None:
    a = _identity(_card_posting("USD -7.92"), payee="COSTCO", account_id="acct_a")
    b = _identity(_card_posting("USD -7.92"), payee="COSTCO", account_id="acct_b")
    assert a != b


def test_missing_amount_is_refused_rather_than_hashed_blank() -> None:
    with pytest.raises(IdentityInputError, match="without an amount"):
        _identity([{"account": "Expenses:Groceries", "amount": ""}], payee="COSTCO")


# ---------------------------------------------------------------------------
# Key names
# ---------------------------------------------------------------------------


def test_key_names_are_the_documented_ones() -> None:
    assert source_identity.IDENTITY_KEY == "lf_source_identity"
    assert source_identity.PAYLOAD_HASH_KEY == "source_payload_hash"
    assert source_identity.suffix_of("lf_source_identity_2") == 2
    assert source_identity.suffix_of("xlf_source_identity") is None


def test_stored_identities_are_all_on_the_current_generation() -> None:
    """The real ``lf_source_identity`` on the 2026-04-27 Costco blocks after
    ``migrate_source_identities`` ran.

    Before the migration one value covered both purchases, because the pre-fix
    hash took an empty amount. They are distinct now, and each is what
    ``of_statement_row`` produces — so classification needs no compat path.
    """
    small = _identity(COSTCO_SMALL)
    large = _identity(COSTCO_LARGE)

    assert small != large


# ---------------------------------------------------------------------------
# The carried-duplicate family
#
# A block claims one source row normally, several when duplicates were merged:
# the survivor keeps its own identity at suffix 1 and carries each absorbed
# row's at 2, 3, … so a re-import of any of their source files still
# recognises the merged block. Five modules used to reimplement reading that.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("lf_source_identity", 1),
        ("lf_source_identity_2", 2),
        ("lf_source_identity_13", 13),
        ("source_payload_hash", 1),
        ("source_file_sha256_3", 3),
        ("importer_version", 1),
        ("source_identity", None),
        ("lf_source_identity_x", None),
        ("lf_txn_id", None),
        ("", None),
    ],
)
def test_suffix_of_spans_every_carried_family(key: str, expected: int | None) -> None:
    """The unsuffixed key is suffix 1 — the ``or "1"`` step each reader used to
    write for itself, and the one they wrote differently."""
    assert source_identity.suffix_of(key) == expected


def test_carry_onto_writes_the_whole_slot_in_order() -> None:
    """The four families move as one: whichever fields the absorbed row carried
    are emitted together at the slot they share."""
    (variant,) = source_identity.variants_of({
        "lf_source_identity": "absorbed",
        "source_payload_hash": "absorbed-payload",
        "importer_version": "mvp2",
    })
    added = source_identity.carry_onto({"lf_source_identity": "own"}, [variant])

    assert added == (
        ("lf_source_identity_2", "absorbed"),
        ("source_payload_hash_2", "absorbed-payload"),
        # source_file_sha256 absent — the absorbed row never carried one.
        ("importer_version_2", "mvp2"),
    )


def test_carry_onto_skips_a_row_the_block_already_claims() -> None:
    """Merging the same row twice adds nothing."""
    (variant,) = source_identity.variants_of({"lf_source_identity": "dup"})
    existing = {"lf_source_identity": "own", "lf_source_identity_2": "dup"}
    assert source_identity.carry_onto(existing, [variant]) == ()


def test_carry_onto_gives_each_new_row_its_own_slot() -> None:
    variants = source_identity.variants_of({
        "lf_source_identity": "a", "lf_source_identity_2": "b",
    })
    added = source_identity.carry_onto({"lf_source_identity": "own"}, variants)
    assert [key for key, _ in added] == ["lf_source_identity_2", "lf_source_identity_3"]


def test_carry_onto_never_claims_slot_one() -> None:
    """Slot 1 is the block's own row, even when the block has no identity yet."""
    (variant,) = source_identity.variants_of({"lf_source_identity": "absorbed"})
    added = source_identity.carry_onto({}, [variant])
    assert added == (("lf_source_identity_2", "absorbed"),)


def test_variants_of_pairs_each_identity_with_its_own_slot() -> None:
    metadata = {
        "lf_source_identity": "own",
        "source_payload_hash": "own-payload",
        "lf_source_identity_2": "carried",
        "source_payload_hash_2": "carried-payload",
        "importer_version_2": "mvp2",
        "lf_txn_id": "not-a-variant",
    }
    own, carried = source_identity.variants_of(metadata)

    assert (own.suffix, own.identity, own.payload_hash) == (1, "own", "own-payload")
    assert (carried.suffix, carried.identity) == (2, "carried")
    assert carried.payload_hash == "carried-payload"
    assert carried.importer_version == "mvp2"
    assert carried.source_file_sha256 is None


def test_variants_are_ordered_by_suffix_not_by_metadata_order() -> None:
    """Callers take ``variants[0]`` as the block's own row, so order is part of
    the contract — and dicts preserve insertion order, not suffix order."""
    metadata = {
        "lf_source_identity_10": "tenth",
        "lf_source_identity_2": "second",
        "lf_source_identity": "own",
    }
    assert [v.suffix for v in source_identity.variants_of(metadata)] == [1, 2, 10]


def test_a_slot_without_an_identity_is_not_a_variant() -> None:
    """An identity is what makes a variant; the other three are description."""
    metadata = {"source_payload_hash_2": "orphan", "importer_version_2": "mvp2"}
    assert source_identity.variants_of(metadata) == ()


def test_blank_values_do_not_become_variants() -> None:
    assert source_identity.variants_of({"lf_source_identity": "   "}) == ()


def test_variant_reports_the_whole_slot_it_occupies() -> None:
    """The un-merge removes a variant by this set. Leaving a stray
    ``source_payload_hash_2`` behind an erased identity is how a block starts
    disagreeing with itself."""
    (variant,) = source_identity.variants_of({"lf_source_identity_2": "carried"})
    assert variant.keys == {
        "lf_source_identity_2",
        "source_payload_hash_2",
        "source_file_sha256_2",
        "importer_version_2",
    }
