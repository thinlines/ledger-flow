from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter, register_translator
from ..types import LedgerTransaction, Posting, Record

GENERIC_CHECKING = "generic.checking"


@register_translator
class GenericCheckingTranslator:
    """Cash-account translator. One posting per transaction (tracked-account
    side). The other leg is synthesized later by ledger convert + rules."""

    name = GENERIC_CHECKING

    def translate(self, record: Record, account: str) -> LedgerTransaction:
        return LedgerTransaction(
            date=record.date,
            payee=record.description,
            code=record.code,
            note=record.note,
            balance=record.balance,
            postings=[
                Posting(
                    account=account,
                    amount=record.amount,
                    commodity=record.currency,
                )
            ],
        )


@register_adapter
class WellsFargoAdapter:
    name = "wells_fargo"
    institution = "wells_fargo"
    formats = ("csv",)
    translator_name = GENERIC_CHECKING

    display_name = "Wells Fargo"
    csv_date_format = "%m/%d/%Y"
    suggested_ledger_prefix = "Assets:Bank:Wells Fargo"
    aliases = ("wfchk", "wfsav", "wfcc", "wells-fargo", "wellsfargo")
    head = 0
    tail = 0
    encoding = "utf-8"

    _REF_RE = re.compile(r"REF #([A-Z0-9]+)")
    _CHECK_RE = re.compile(r"CHECK # ?(\d+)")

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            # Headerless WF format: date, amount, cleared, note, description
            code = self._extract_code(row[3], row[4])
            yield Record(
                date=datetime.strptime(row[0], "%m/%d/%Y").date(),
                description=row[4],
                amount=Decimal(row[1]),
                currency="$",
                code=code,
                note=None,
                balance=None,  # WF CSV has no running-balance column
                raw={"cleared": row[2]},
            )

    def _extract_code(self, note: str, description: str) -> str | None:
        """Matches WellsFargoCSV.code() in Scripts/BankCSV.py.

        Precedence:
        1. note column (if non-empty)
        2. REF #<alphanumeric> in description
        3. CHECK # <digits> in description
        4. None (no code)
        """
        if note:
            return note
        ref_match = self._REF_RE.search(description)
        if ref_match:
            return ref_match.group(1)
        check_match = self._CHECK_RE.search(description)
        if check_match:
            return check_match.group(1)
        return None
