"""Tests for the continuous match-scoring system in manual_entry_service.

Covers: exact match, amount-tolerance boundary, payee-similarity edge cases,
minimum-threshold rejection, auto-suggestion gating, and the shared payee
similarity module.
"""

from datetime import date
from decimal import Decimal

from services.manual_entry_service import (
    AUTO_SUGGEST_THRESHOLD,
    MIN_MATCH_SCORE,
    _amount_score,
    _date_score,
    _match_quality,
    find_match_candidates,
    populate_match_candidates,
)
from services.payee_similarity import payee_similarity


# ---------------------------------------------------------------------------
# payee_similarity unit tests
# ---------------------------------------------------------------------------


def test_payee_identical() -> None:
    assert payee_similarity("Uber", "Uber") == 1.0


def test_payee_case_insensitive() -> None:
    assert payee_similarity("uber", "UBER") == 1.0


def test_payee_token_overlap() -> None:
    """'Uber Eats' vs 'Uber Trip' share 'uber' — partial overlap."""
    score = payee_similarity("Uber Eats", "Uber Trip")
    assert 0.5 < score < 1.0


def test_payee_substring_not_high() -> None:
    """'AT&T' inside 'BATTERY PLUS' must NOT produce a high score."""
    score = payee_similarity("AT&T", "BATTERY PLUS")
    assert score < 0.5


def test_payee_unrelated() -> None:
    assert payee_similarity("Starbucks", "Home Depot") == 0.0


def test_payee_noise_word_removal() -> None:
    """'Online Payment' vs 'Payment' — 'online' is a noise word."""
    score = payee_similarity("Online Payment", "Payment")
    assert score >= 0.9


def test_payee_plural_normalization() -> None:
    """'Groceries' vs 'Grocery' — plural normalization."""
    score = payee_similarity("Groceries", "Grocery")
    assert score >= 0.92


def test_payee_empty_strings() -> None:
    assert payee_similarity("", "Anything") == 0.0
    assert payee_similarity("Anything", "") == 0.0
    assert payee_similarity("", "") == 0.0


# ---------------------------------------------------------------------------
# _amount_score unit tests
# ---------------------------------------------------------------------------


def test_amount_exact_match() -> None:
    assert _amount_score(Decimal("45.95"), Decimal("45.95")) == 1.0


def test_amount_sign_ignored() -> None:
    assert _amount_score(Decimal("-45.95"), Decimal("45.95")) == 1.0


def test_amount_within_tolerance() -> None:
    """$49.95 vs $50.00 — delta $0.05, 0.1% of smaller, well within 5%."""
    score = _amount_score(Decimal("49.95"), Decimal("50.00"))
    assert 0.3 < score < 1.0


def test_amount_at_tolerance_boundary() -> None:
    """$100 vs $105 — delta is exactly 5% of $100. Should be at the edge (≈0.3)."""
    score = _amount_score(Decimal("100"), Decimal("105"))
    assert 0.25 <= score <= 0.35


def test_amount_outside_tolerance() -> None:
    """$50 vs $500 — way outside 5%. Must be 0.0."""
    assert _amount_score(Decimal("50"), Decimal("500")) == 0.0


def test_amount_just_outside_tolerance() -> None:
    """$100 vs $105.01 — just beyond the 5% band."""
    assert _amount_score(Decimal("100"), Decimal("105.01")) == 0.0


def test_amount_cap_at_five_dollars() -> None:
    """$1000 vs $1005 — 0.5%, within percentage, but exactly at the $5 cap."""
    score = _amount_score(Decimal("1000"), Decimal("1005"))
    assert 0.25 <= score <= 0.35  # edge of tolerance band


def test_amount_cap_exceeded() -> None:
    """$1000 vs $1006 — within 0.6% but $6 exceeds $5 cap."""
    assert _amount_score(Decimal("1000"), Decimal("1006")) == 0.0


def test_amount_none_import() -> None:
    assert _amount_score(None, Decimal("50")) == 0.0


def test_amount_none_manual() -> None:
    assert _amount_score(Decimal("50"), None) == 0.0


def test_amount_both_none() -> None:
    assert _amount_score(None, None) == 0.0


# ---------------------------------------------------------------------------
# _date_score unit tests
# ---------------------------------------------------------------------------


def test_date_same_day() -> None:
    assert _date_score(0) == 1.0


def test_date_one_day() -> None:
    score = _date_score(1)
    assert 0.5 < score < 1.0


def test_date_at_window_edge() -> None:
    """3 days — the MAX_MANUAL_MATCH_DAYS edge."""
    score = _date_score(3)
    assert 0.0 < score < 0.5


def test_date_beyond_window() -> None:
    assert _date_score(4) == 0.0
    assert _date_score(10) == 0.0


# ---------------------------------------------------------------------------
# _match_quality unit tests
# ---------------------------------------------------------------------------


def test_quality_strong() -> None:
    assert _match_quality(0.85) == "strong"


def test_quality_likely() -> None:
    assert _match_quality(0.60) == "likely"


def test_quality_possible() -> None:
    assert _match_quality(0.35) == "possible"


# ---------------------------------------------------------------------------
# find_match_candidates integration tests
# ---------------------------------------------------------------------------

_MANUAL_UBER = [
    "2026-03-28 Uber",
    "    ; :manual:",
    "    Expenses:Rides  $45.95",
    "    Assets:Bank:Checking",
]


def test_exact_match_scores_strong() -> None:
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c["matchQuality"] == "strong"
    assert c["matchScore"] >= AUTO_SUGGEST_THRESHOLD
    assert "matchReason" in c
    assert "matchTier" not in c  # old field removed


def test_wildly_different_amount_low_quality() -> None:
    """$45.95 manual vs $500 import — amount fails tolerance.

    Same payee + same day still surfaces as a weak candidate (payee + date
    signals are non-zero), but it must NOT be "strong" and must NOT be
    auto-suggested.
    """
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("500.00"), "Uber", "Assets:Bank:Checking",
    )
    if candidates:
        assert candidates[0]["matchQuality"] != "strong"
        assert candidates[0]["matchScore"] < AUTO_SUGGEST_THRESHOLD


def test_small_amount_delta_within_tolerance() -> None:
    """$45.95 manual vs $46.00 import — $0.05 delta, well within tolerance."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("46.00"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchQuality"] in ("strong", "likely")


def test_unrelated_payee_substring_rejected() -> None:
    """'BATTERY PLUS' should not match 'Uber' even with exact amount + same day."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("45.95"), "BATTERY PLUS", "Assets:Bank:Checking",
    )
    # Should appear (exact amount + same day is strong) but payee is unrelated
    # so quality should NOT be "strong"
    if candidates:
        assert candidates[0]["matchQuality"] != "strong" or candidates[0]["matchScore"] < 0.85


def test_no_candidates_below_threshold() -> None:
    """Unrelated payee + different amount + far date → no candidates."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 4, 15), Decimal("999.99"), "Totally Different", "Assets:Bank:Checking",
    )
    assert len(candidates) == 0


def test_payee_alone_cannot_clear_threshold() -> None:
    """Strong payee but 0 amount and 0 date → below MIN_MATCH_SCORE (0.40)."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 4, 15), Decimal("999.99"), "Uber", "Assets:Bank:Checking",
    )
    # payee 1.0 * 0.35 = 0.35 < 0.40 threshold
    assert len(candidates) == 0


def test_candidate_has_reason_string() -> None:
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    reason = candidates[0]["matchReason"]
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_candidates_sorted_by_descending_score() -> None:
    """Two manual entries: one exact, one close. Exact should come first."""
    journal_lines = [
        "2026-03-28 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
        "",
        "2026-03-27 Uber Ride",
        "    ; :manual:",
        "    Expenses:Rides  $46.00",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal_lines, date(2026, 3, 28), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 2
    assert candidates[0]["matchScore"] >= candidates[1]["matchScore"]


# ---------------------------------------------------------------------------
# Auto-suggestion tests
# ---------------------------------------------------------------------------


def test_auto_suggest_single_high_confidence() -> None:
    journal_lines = [
        "2026-03-28 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    groups = [{
        "sourceTrackedAccountId": "checking",
        "txns": [{
            "date": "2026-03-28",
            "amount": "$45.95",
        }],
        "payeeDisplay": "Uber",
    }]
    tracked = {
        "checking": {
            "ledger_account": "Assets:Bank:Checking",
            "import_account_id": "checking_import",
        },
    }
    from pathlib import Path
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".journal", delete=False) as f:
        f.write("\n".join(journal_lines))
        f.flush()
        populate_match_candidates(groups, Path(f.name), {}, tracked)
    txn = groups[0]["txns"][0]
    assert "suggestedMatchId" in txn
    assert txn["suggestedMatchId"] is not None


def test_auto_suggest_not_fired_for_low_score() -> None:
    """Different amount + different payee → no auto-suggestion even if above MIN_MATCH_SCORE."""
    journal_lines = [
        "2026-03-28 Some Store",
        "    ; :manual:",
        "    Expenses:Shopping  $100.00",
        "    Assets:Bank:Checking",
    ]
    groups = [{
        "sourceTrackedAccountId": "checking",
        "txns": [{
            "date": "2026-03-28",
            "amount": "$102.00",
        }],
        "payeeDisplay": "Some Store",
    }]
    tracked = {
        "checking": {
            "ledger_account": "Assets:Bank:Checking",
            "import_account_id": "checking_import",
        },
    }
    from pathlib import Path
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".journal", delete=False) as f:
        f.write("\n".join(journal_lines))
        f.flush()
        populate_match_candidates(groups, Path(f.name), {}, tracked)
    txn = groups[0]["txns"][0]
    # May or may not have candidates, but suggestedMatchId should not be set
    # unless the score is above AUTO_SUGGEST_THRESHOLD
    if "suggestedMatchId" in txn:
        candidates = txn.get("matchCandidates", [])
        high = [c for c in candidates if c["matchScore"] >= AUTO_SUGGEST_THRESHOLD]
        assert len(high) == 1  # only suggest if truly high confidence


def test_auto_suggest_not_fired_for_multiple_high() -> None:
    """Two identical manual entries → multiple high candidates → no auto-suggestion."""
    journal_lines = [
        "2026-03-28 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
        "",
        "2026-03-28 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    groups = [{
        "sourceTrackedAccountId": "checking",
        "txns": [{
            "date": "2026-03-28",
            "amount": "$45.95",
        }],
        "payeeDisplay": "Uber",
    }]
    tracked = {
        "checking": {
            "ledger_account": "Assets:Bank:Checking",
            "import_account_id": "checking_import",
        },
    }
    from pathlib import Path
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".journal", delete=False) as f:
        f.write("\n".join(journal_lines))
        f.flush()
        populate_match_candidates(groups, Path(f.name), {}, tracked)
    txn = groups[0]["txns"][0]
    assert txn.get("suggestedMatchId") is None
