"""Tests for the tier-based match system in manual_entry_service.

Covers: tier assignment, clearing-status exclusion, auto-suggest rules,
amount tolerance boundaries, payee similarity, and the shared payee module.
"""

from datetime import date
from decimal import Decimal

from services.manual_entry_service import (
    TIER_SCORES,
    TIER_QUALITY,
    _is_exact_amount,
    _is_close_amount,
    _assign_tier,
    _auto_suggest,
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


def test_payee_no_plural_normalization() -> None:
    """'Groceries' vs 'Grocery' — plural stemming removed, no longer equivalent."""
    score = payee_similarity("Groceries", "Grocery")
    # SequenceMatcher ratio for "groceries" vs "grocery" is 0.75, below 0.92 threshold.
    # These are now treated as different tokens. In practice they'd appear alongside
    # a merchant name (e.g. "Winco Foods" vs "Winco Food") where the merchant carries.
    assert score == 0.0


def test_payee_empty_strings() -> None:
    assert payee_similarity("", "Anything") == 0.0
    assert payee_similarity("Anything", "") == 0.0
    assert payee_similarity("", "") == 0.0


def test_payee_bank_verbose_vs_short() -> None:
    """'COSTCO WHSE #0761 BOISE ID' vs 'Costco' — token subset match."""
    score = payee_similarity("COSTCO WHSE #0761 BOISE ID", "Costco")
    assert score >= 0.9  # 'costco' is full subset of short side


def test_payee_mala_house() -> None:
    """'UEP*MALA HOUSE BOISE ID' vs 'Mala House'."""
    score = payee_similarity("UEP*MALA HOUSE BOISE ID", "Mala House")
    assert score >= 0.9


def test_payee_no_overlap() -> None:
    """'DICE.FM' vs 'Treefort Music Festival' — zero token overlap."""
    score = payee_similarity("DICE.FM", "Treefort Music Festival")
    assert score == 0.0


# ---------------------------------------------------------------------------
# _is_exact_amount / _is_close_amount unit tests
# ---------------------------------------------------------------------------


def test_exact_amount_true() -> None:
    assert _is_exact_amount(Decimal("45.95"), Decimal("45.95")) is True


def test_exact_amount_sign_ignored() -> None:
    assert _is_exact_amount(Decimal("-45.95"), Decimal("45.95")) is True


def test_exact_amount_false() -> None:
    assert _is_exact_amount(Decimal("45.95"), Decimal("46.00")) is False


def test_exact_amount_none() -> None:
    assert _is_exact_amount(None, Decimal("50")) is False
    assert _is_exact_amount(Decimal("50"), None) is False


def test_close_amount_tip_25pct() -> None:
    """$45 manual, $56.93 bank → +26.5% → within +35%."""
    assert _is_close_amount(Decimal("56.93"), Decimal("45.00")) is True


def test_close_amount_tip_at_boundary() -> None:
    """$100 manual, $135 bank → exactly +35% → inside."""
    assert _is_close_amount(Decimal("135"), Decimal("100")) is True


def test_close_amount_tip_over_boundary() -> None:
    """$100 manual, $136 bank → +36% → outside."""
    assert _is_close_amount(Decimal("136"), Decimal("100")) is False


def test_close_amount_underpay_within() -> None:
    """$100 manual, $91 bank → -9% → within -10%."""
    assert _is_close_amount(Decimal("91"), Decimal("100")) is True


def test_close_amount_underpay_over() -> None:
    """$100 manual, $89 bank → -11% → outside -10%."""
    assert _is_close_amount(Decimal("89"), Decimal("100")) is False


def test_close_amount_excludes_exact() -> None:
    """Exact amounts return False for _is_close_amount (they're Tier 1, not Tier 2)."""
    assert _is_close_amount(Decimal("45.95"), Decimal("45.95")) is False


def test_close_amount_none() -> None:
    assert _is_close_amount(None, Decimal("50")) is False
    assert _is_close_amount(Decimal("50"), None) is False


def test_close_amount_zero_manual() -> None:
    assert _is_close_amount(Decimal("50"), Decimal("0")) is False


# ---------------------------------------------------------------------------
# _assign_tier unit tests
# ---------------------------------------------------------------------------


def test_tier1_payee_same_day_exact() -> None:
    assert _assign_tier(0.9, 0, True, False) == 1


def test_tier2_payee_same_day_close() -> None:
    assert _assign_tier(0.9, 0, False, True) == 2


def test_tier2_payee_close_date_exact() -> None:
    assert _assign_tier(0.9, 2, True, False) == 2


def test_tier3_payee_close_date_close_amount() -> None:
    assert _assign_tier(0.9, 2, False, True) == 3


def test_tier4_no_payee_same_day_exact() -> None:
    assert _assign_tier(0.0, 0, True, False) == 4


def test_tier4_no_payee_close_date_close_amount() -> None:
    assert _assign_tier(0.3, 1, False, True) == 4


def test_tier5_payee_only() -> None:
    """Payee matches but no amount signal → Tier 5."""
    assert _assign_tier(0.9, 2, False, False) == 5


def test_tier5_close_amount_no_payee_no_date_signal() -> None:
    """This can't happen (date > 3 returns None), but with payee only it's Tier 5."""
    assert _assign_tier(0.7, 0, False, False) == 5


def test_no_candidate_beyond_window() -> None:
    assert _assign_tier(0.9, 4, True, True) is None


def test_no_candidate_no_signals() -> None:
    """No payee, no amount signal, still in window → no candidate."""
    assert _assign_tier(0.3, 2, False, False) is None


# ---------------------------------------------------------------------------
# _auto_suggest unit tests
# ---------------------------------------------------------------------------


def _make_candidate(tier: int, txn_id: str = "manual:1") -> dict:
    return {"matchTier": tier, "manualTxnId": txn_id, "matchScore": TIER_SCORES[tier]}


def test_auto_suggest_tier1_single() -> None:
    assert _auto_suggest([_make_candidate(1)]) == "manual:1"


def test_auto_suggest_tier1_ambiguous() -> None:
    """Multiple Tier 1 candidates → no auto-suggest."""
    candidates = [_make_candidate(1, "manual:1"), _make_candidate(1, "manual:2")]
    assert _auto_suggest(candidates) is None


def test_auto_suggest_tier2_single() -> None:
    assert _auto_suggest([_make_candidate(2)]) == "manual:1"


def test_auto_suggest_tier2_with_tier5() -> None:
    """Tier 2 + Tier 5 → Tier 2 auto-suggests (only same-tier ambiguity blocks)."""
    candidates = [_make_candidate(2, "manual:1"), _make_candidate(5, "manual:2")]
    assert _auto_suggest(candidates) == "manual:1"


def test_auto_suggest_tier3_sole_candidate() -> None:
    assert _auto_suggest([_make_candidate(3)]) == "manual:1"


def test_auto_suggest_tier3_not_sole() -> None:
    """Tier 3 with other candidates → no auto-suggest."""
    candidates = [_make_candidate(3, "manual:1"), _make_candidate(5, "manual:2")]
    assert _auto_suggest(candidates) is None


def test_auto_suggest_tier4_sole_candidate() -> None:
    assert _auto_suggest([_make_candidate(4)]) == "manual:1"


def test_auto_suggest_tier4_not_sole() -> None:
    candidates = [_make_candidate(4, "manual:1"), _make_candidate(5, "manual:2")]
    assert _auto_suggest(candidates) is None


def test_auto_suggest_tier5_never() -> None:
    assert _auto_suggest([_make_candidate(5)]) is None


def test_auto_suggest_empty() -> None:
    assert _auto_suggest([]) is None


# ---------------------------------------------------------------------------
# find_match_candidates integration tests
# ---------------------------------------------------------------------------

_MANUAL_UBER = [
    "2026-03-28 Uber",
    "    ; :manual:",
    "    Expenses:Rides  $45.95",
    "    Assets:Bank:Checking",
]


def test_tier1_exact_match() -> None:
    """Same payee, same day, exact amount → Tier 1."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c["matchTier"] == 1
    assert c["matchScore"] == TIER_SCORES[1]
    assert c["matchQuality"] == "strong"


def test_tier2_same_day_close_amount() -> None:
    """Same payee, same day, close amount (+26%) → Tier 2."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("56.93"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchTier"] == 2
    assert candidates[0]["matchQuality"] == "strong"


def test_tier2_close_date_exact_amount() -> None:
    """Same payee, 2 days off, exact amount → Tier 2."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 30), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchTier"] == 2


def test_tier3_close_date_close_amount() -> None:
    """Same payee, 1 day off, close amount → Tier 3."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 29), Decimal("56.93"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchTier"] == 3
    assert candidates[0]["matchQuality"] == "likely"


def test_tier4_no_payee_exact_amount_same_day() -> None:
    """No payee overlap, same day, exact amount → Tier 4 (payment processor case)."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("45.95"), "DICE.FM", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchTier"] == 4
    assert candidates[0]["matchQuality"] == "possible"


def test_tier5_payee_only_no_amount_signal() -> None:
    """Same payee, close date, but amount way off (>35%) → Tier 5."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 29), Decimal("500.00"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchTier"] == 5
    assert candidates[0]["matchQuality"] == "possible"


def test_no_candidate_beyond_window() -> None:
    """Unrelated payee + far date → no candidates."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 4, 15), Decimal("999.99"), "Totally Different", "Assets:Bank:Checking",
    )
    assert len(candidates) == 0


def test_no_candidate_no_signals() -> None:
    """Unrelated payee, no amount match, but in window → still no candidate (no signal)."""
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 29), Decimal("999.99"), "Totally Different", "Assets:Bank:Checking",
    )
    assert len(candidates) == 0


def test_cleared_manual_excluded() -> None:
    """Cleared (*) manual entry should NOT appear as a candidate."""
    journal = [
        "2026-03-28 * Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal, date(2026, 3, 28), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 0


def test_uncleared_pending_manual_included() -> None:
    """Pending (!) manual entry is still a valid candidate."""
    journal = [
        "2026-03-28 ! Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal, date(2026, 3, 28), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchTier"] == 1


def test_candidate_has_reason_string() -> None:
    candidates = find_match_candidates(
        _MANUAL_UBER, date(2026, 3, 28), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 1
    reason = candidates[0]["matchReason"]
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_candidates_sorted_by_tier_then_date() -> None:
    """Two manual entries: one Tier 1 (same day), one Tier 2 (1 day off). Tier 1 first."""
    journal_lines = [
        "2026-03-28 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
        "",
        "2026-03-27 Uber Ride",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal_lines, date(2026, 3, 28), Decimal("45.95"), "Uber", "Assets:Bank:Checking",
    )
    assert len(candidates) == 2
    assert candidates[0]["matchTier"] <= candidates[1]["matchTier"]


def test_mala_house_tip_scenario() -> None:
    """Acceptance criteria 1: Mala House $45 manual vs UEP*MALA HOUSE $56.93 import."""
    journal = [
        "2026-05-02 Mala House",
        "    ; :manual:",
        "    Expenses:Eating Out  45.00 $",
        "    Liabilities:Wells:Fargo:Credit:Card",
    ]
    candidates = find_match_candidates(
        journal, date(2026, 5, 2), Decimal("56.93"),
        "UEP*MALA HOUSE BOISE ID", "Liabilities:Wells:Fargo:Credit:Card",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchTier"] == 2  # payee match, same day, close amount


def test_costco_close_amount_scenario() -> None:
    """Acceptance criteria 2: Costco $296.97 manual vs COSTCO WHSE $296.79 import."""
    journal = [
        "2026-02-21 Costco",
        "    ; :manual:",
        "    Expenses:Shopping:Groceries  $ 296.97",
        "    Liabilities:Wells:Fargo:Credit:Card",
    ]
    candidates = find_match_candidates(
        journal, date(2026, 2, 21), Decimal("296.79"),
        "COSTCO WHSE #0761 BOISE ID", "Liabilities:Wells:Fargo:Credit:Card",
    )
    assert len(candidates) == 1
    # -0.06% — within -10%, close amount
    assert candidates[0]["matchTier"] == 2


def test_treefort_dice_fm_scenario() -> None:
    """Acceptance criteria 3: Treefort $212 vs DICE.FM $212 — no payee overlap."""
    journal = [
        "2026-03-15 Treefort Music Festival",
        "    ; :manual:",
        "    Expenses:Entertainment  $ 212.00",
        "    Liabilities:Wells:Fargo:Credit:Card",
    ]
    candidates = find_match_candidates(
        journal, date(2026, 3, 15), Decimal("212.00"),
        "DICE.FM 8005551234", "Liabilities:Wells:Fargo:Credit:Card",
    )
    assert len(candidates) == 1
    assert candidates[0]["matchTier"] == 4  # no payee, exact amount, same day


def test_two_costcos_different_amounts() -> None:
    """Acceptance criteria 4: two Costco manual entries, different amounts."""
    journal = [
        "2026-01-01 Costco",
        "    ; :manual:",
        "    Expenses:Shopping:Groceries  $ 127.00",
        "    Assets:Bank:Checking",
        "",
        "2026-01-01 Costco",
        "    ; :manual:",
        "    Expenses:Shopping:Groceries  $ 350.00",
        "    Assets:Bank:Checking",
    ]
    # Import for the $127 one (bank says $129)
    candidates = find_match_candidates(
        journal, date(2026, 1, 1), Decimal("129.00"),
        "COSTCO WHSE #0761", "Assets:Bank:Checking",
    )
    assert len(candidates) == 2
    # The $127 manual should be Tier 2 (close amount), the $350 should be Tier 5 (amount way off)
    assert candidates[0]["matchTier"] == 2
    assert candidates[0]["amount"] == "127.00"
    assert candidates[1]["matchTier"] == 5


def test_two_costcos_same_amount_ambiguous() -> None:
    """Acceptance criteria 5: same store, same day, same exact amount → ambiguous."""
    journal = [
        "2026-01-01 Costco",
        "    ; :manual:",
        "    Expenses:Shopping:Groceries  $ 127.00",
        "    Assets:Bank:Checking",
        "",
        "2026-01-01 Costco",
        "    ; :manual:",
        "    Expenses:Shopping:Groceries  $ 127.00",
        "    Assets:Bank:Checking",
    ]
    candidates = find_match_candidates(
        journal, date(2026, 1, 1), Decimal("127.00"),
        "COSTCO WHSE #0761", "Assets:Bank:Checking",
    )
    assert len(candidates) == 2
    assert candidates[0]["matchTier"] == 1
    assert candidates[1]["matchTier"] == 1
    # Auto-suggest should NOT fire
    assert _auto_suggest(candidates) is None


# ---------------------------------------------------------------------------
# populate_match_candidates (auto-suggestion integration)
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


def test_auto_suggest_tier4_sole_candidate() -> None:
    """DICE.FM $212 vs Treefort $212 — Tier 4, sole candidate → auto-suggests."""
    journal_lines = [
        "2026-03-15 Treefort Music Festival",
        "    ; :manual:",
        "    Expenses:Entertainment  $ 212.00",
        "    Liabilities:Credit:Card",
    ]
    groups = [{
        "sourceTrackedAccountId": "cc",
        "txns": [{
            "date": "2026-03-15",
            "amount": "$212.00",
        }],
        "payeeDisplay": "DICE.FM 8005551234",
    }]
    tracked = {
        "cc": {
            "ledger_account": "Liabilities:Credit:Card",
            "import_account_id": "cc_import",
        },
    }
    from pathlib import Path
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".journal", delete=False) as f:
        f.write("\n".join(journal_lines))
        f.flush()
        populate_match_candidates(groups, Path(f.name), {}, tracked)
    txn = groups[0]["txns"][0]
    assert txn.get("suggestedMatchId") is not None


def test_auto_suggest_not_fired_for_multiple_tier1() -> None:
    """Two identical manual entries → multiple Tier 1 → no auto-suggestion."""
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


def test_auto_suggest_tier5_never() -> None:
    """Tier 5 candidate (payee match, way off amount) → never auto-suggests."""
    journal_lines = [
        "2026-03-28 Uber",
        "    ; :manual:",
        "    Expenses:Rides  $45.95",
        "    Assets:Bank:Checking",
    ]
    groups = [{
        "sourceTrackedAccountId": "checking",
        "txns": [{
            "date": "2026-03-29",
            "amount": "$500.00",
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
    assert "matchCandidates" in txn  # candidate appears
    assert txn.get("suggestedMatchId") is None  # but not auto-suggested


def test_cleared_entry_excluded_from_populate() -> None:
    """Cleared manual entry is not surfaced even via populate_match_candidates."""
    journal_lines = [
        "2026-03-28 * Uber",
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
    assert txn.get("matchCandidates") is None
