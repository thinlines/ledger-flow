from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter
from ..types import Record


@register_adapter
class BankOfAmericaAdapter:
    name = "bank_of_america"
    institution = "bank_of_america"
    formats = ("csv",)
    translator_name = "generic.checking"

    display_name = "Bank of America"
    csv_date_format = "%m/%d/%Y"
    suggested_ledger_prefix = "Assets:Bank:Bank of America"
    aliases = ("bofa", "bank-of-america", "bankofamerica", "boa")
    encoding = "utf-8"
    head = 6
    tail = 0

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if header is None:
            return
        expected = ["Date", "Description", "Amount", "Running Bal."]
        if [h.strip() for h in header[:4]] != expected:
            raise ValueError(
                f"Unexpected Bank of America CSV header: {header!r}; "
                f"expected {expected!r}. Check head/tail slicing in "
                f"institution_registry or the source file's preamble shape."
            )
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            yield Record(
                date=datetime.strptime(row[0].strip(), self.csv_date_format).date(),
                description=row[1].strip(),
                amount=self._parse_decimal(row[2]),
                currency="$",
                code=None,
                balance=self._parse_decimal(row[3]) if len(row) > 3 else None,
                note=None,
                raw={"running_balance_raw": row[3] if len(row) > 3 else ""},
            )

    @staticmethod
    def _parse_decimal(cell: str) -> Decimal | None:
        cleaned = cell.replace(",", "").strip()
        if not cleaned:
            return None
        return Decimal(cleaned)
