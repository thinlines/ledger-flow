from __future__ import annotations

from datetime import date

from services.month_math import (
    month_key,
    month_key_of,
    month_label,
    month_window,
    shift_month,
)


def test_month_key_is_zero_padded_year_month() -> None:
    assert month_key(date(2026, 4, 18)) == "2026-04"
    assert month_key(date(999, 12, 1)) == "0999-12"


def test_month_key_of_matches_month_key() -> None:
    assert month_key_of(2026, 4) == month_key(date(2026, 4, 18))


def test_shift_month_crosses_year_boundaries() -> None:
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert shift_month(2025, 12, 1) == (2026, 1)
    assert shift_month(2026, 4, 0) == (2026, 4)
    assert shift_month(2026, 4, -15) == (2025, 1)


def test_month_window_ends_with_the_current_month() -> None:
    assert month_window(date(2026, 4, 18), 3) == [(2026, 2), (2026, 3), (2026, 4)]


def test_month_window_of_one_is_just_the_current_month() -> None:
    assert month_window(date(2026, 4, 18), 1) == [(2026, 4)]


def test_month_label_is_the_abbreviated_month_name() -> None:
    assert month_label(2026, 4) == "Apr"
