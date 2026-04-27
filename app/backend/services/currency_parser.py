"""Shared currency-amount parser used by manual entry, reconciliation, and any
other surface that accepts a free-form user-typed money string.

The single accepted shape: optional leading ``$``, optional minus sign, comma
group separators, optional surrounding whitespace.  Empty input rejects.

Other backend modules call :func:`parse_amount` directly; the frontend mirrors
the behavior under ``$lib/currency-parser`` and a shared JSON fixture asserts
parity.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_amount(raw: str) -> Decimal:
    """Parse a user-typed currency amount into a Decimal.

    Accepts ``"$2,500.00"``, ``"-100"``, ``"  1,234.56  "``.  Rejects empty
    strings and non-numeric input with :class:`ValueError`.
    """
    cleaned = (raw or "").strip().lstrip("$").replace(",", "")
    if not cleaned:
        raise ValueError(f"Invalid amount: {raw!r}")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {raw!r}") from exc
