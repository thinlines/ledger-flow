"""One month vocabulary for the services that bucket transactions by month.

A month key is always ``YYYY-MM`` with a zero-padded year, and a month window is
always a list of ``(year, month)`` pairs ending with the current month. Callers
that want keys map ``month_key_of`` over the window.
"""

from __future__ import annotations

from datetime import date


def month_key(value: date) -> str:
    """Return the ``YYYY-MM`` bucket a date falls in."""
    return month_key_of(value.year, value.month)


def month_key_of(year: int, month: int) -> str:
    """Return the ``YYYY-MM`` key for an explicit year and month."""
    return f"{year:04d}-{month:02d}"


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    """Move a year/month pair by `offset` months, carrying across year boundaries."""
    total = (year * 12 + (month - 1)) + offset
    shifted_year, shifted_month_index = divmod(total, 12)
    return shifted_year, shifted_month_index + 1


def month_window(today: date, count: int) -> list[tuple[int, int]]:
    """Return the `count` months ending with the month `today` falls in."""
    return [
        shift_month(today.year, today.month, offset)
        for offset in range(-(count - 1), 1)
    ]


def month_label(year: int, month: int) -> str:
    """Return the abbreviated month name, e.g. ``Apr``."""
    return date(year, month, 1).strftime("%b")
