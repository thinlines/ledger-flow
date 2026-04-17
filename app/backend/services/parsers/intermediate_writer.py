"""Serialize LedgerTransaction streams into the project's intermediate CSV format.

Amount / total formatting (historical quirk preserved for byte-exact compatibility):

- **Amount cell** — no thousand separators: ``:.2f``
- **Total cell** — thousand separators: ``:,.2f``

Commodity placement:
- 1-char symbols (``$``, ``¥``): prefix  → ``$-1000.00``, ``¥-332.50``
- Multi-char codes (``CNY``, ``USD``): suffix → ``-9.90CNY``, ``500.00USD``

The split between ``:f`` and ``:,f`` is inherited from the legacy
``BankCSV.amount()`` vs ``BankCSV.total()`` helpers. Normalizing this is
out of scope until post-Task 07.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from decimal import Decimal
from io import StringIO

from .types import LedgerTransaction

INTERMEDIATE_FIELDNAMES: tuple[str, ...] = (
    "date",
    "code",
    "description",
    "amount",
    "total",
    "note",
)


def _format_amount(amount: Decimal, commodity: str) -> str:
    """Format a monetary amount *without* thousand separators.

    Commodity placement: prefix for 1-char symbols, suffix for multi-char codes.
    Matches the legacy ``BankCSV.amount()`` output across WF, Alipay, and ICBC
    fixtures.
    """
    formatted = f"{amount:.2f}"
    if len(commodity) == 1:
        return f"{commodity}{formatted}"
    return f"{formatted}{commodity}"


def _format_total(balance: Decimal, commodity: str) -> str:
    """Format a running-balance total *with* thousand separators.

    Same commodity-placement rules as ``_format_amount``.  Matches the legacy
    ``BankCSV.total()`` output (e.g. ``"2,568.44CNY"`` in the ICBC fixture).
    """
    formatted = f"{balance:,.2f}"
    if len(commodity) == 1:
        return f"{commodity}{formatted}"
    return f"{formatted}{commodity}"


def _validate_primary_posting(txn: LedgerTransaction) -> None:
    """Raise early on malformed transactions rather than emitting ambiguous CSV."""
    if not txn.postings:
        raise ValueError("LedgerTransaction must have at least one posting")

    primary = txn.postings[0]

    if primary.amount is None:
        raise ValueError("Primary posting amount is required")
    if not isinstance(primary.amount, Decimal):
        raise TypeError(
            f"Primary posting amount must be Decimal, got {type(primary.amount).__name__}"
        )
    if not primary.commodity:
        raise ValueError("LedgerTransaction posting commodity is required")


def write_intermediate(
    transactions: Iterable[LedgerTransaction],
    *,
    fieldnames: Sequence[str] = INTERMEDIATE_FIELDNAMES,
) -> str:
    """Serialize LedgerTransactions to the project's intermediate CSV format.

    Contract:
    - Ordering: writes transactions in the order received. Callers that need
      newest-first ordering (the legacy convention) reverse before passing.
    - Line endings: CRLF (Python csv.DictWriter default in text mode).
    - Encoding: returns str; caller encodes to UTF-8 if bytes are needed.
    - Columns: writes exactly ``fieldnames`` as the header row; LedgerTransaction
      fields outside this list are dropped.
    - Primary posting: ``postings[0]`` is the tracked-account posting by
      translator convention. The writer renders its amount and commodity.
    - Amount formatting: no thousand separators (``:.2f``).
    - Total formatting: thousand separators (``:,.2f``). Empty when
      ``LedgerTransaction.balance`` is ``None``.
    """
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for txn in transactions:
        _validate_primary_posting(txn)

        primary = txn.postings[0]
        commodity = primary.commodity  # type: ignore[assignment]  # validated above

        # Amount cell — no thousand separators
        amount_cell = _format_amount(primary.amount, commodity)  # type: ignore[arg-type]

        # Total cell — thousand separators, or empty when balance is None
        total_cell = (
            _format_total(txn.balance, commodity) if txn.balance is not None else ""
        )

        row = {
            "date": txn.date.strftime("%Y/%m/%d"),
            "code": txn.code or "",
            "description": txn.payee,
            "amount": amount_cell,
            "total": total_cell,
            "note": txn.note or "",
        }
        writer.writerow(row)

    return out.getvalue()
