from __future__ import annotations
import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter
from ..types import Record


@register_adapter
class ChaseAdapter:
    name = "chase"
    institution = "chase"
    formats = ("csv",)
    translator_name = "generic.checking"

    display_name = "Chase Bank"
    csv_date_format = "%m/%d/%Y"
    suggested_ledger_prefix = "Assets:Bank:Chase"
    aliases = ("jpmorgan_chase", "jpm_chase", "chase_bank")
    head = 0
    tail = 0
    encoding = "utf-8"

    _EXPECTED_COLUMNS = (
        "Details",
        "Posting Date",
        "Description",
        "Amount",
        "Type",
        "Balance",
        "Check or Slip #",
    )

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("Chase CSV is empty or missing header row")
        missing = [c for c in self._EXPECTED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ValueError(
                f"Chase CSV header missing expected columns: {missing!r}; "
                f"got {reader.fieldnames!r}"
            )

        for row in reader:
            amount_raw = (row.get("Amount") or "").strip()
            balance_raw = (row.get("Balance") or "").strip()
            code_raw = (row.get("Check or Slip #") or "").strip()

            yield Record(
                date=datetime.strptime(
                    row["Posting Date"].strip(), self.csv_date_format
                ).date(),
                description=row["Description"].strip(),
                amount=Decimal(amount_raw) if amount_raw else None,
                currency="$",
                code=code_raw or None,
                balance=Decimal(balance_raw) if balance_raw else None,
                note=None,
                raw={
                    "Details": (row.get("Details") or "").strip(),
                    "Type": (row.get("Type") or "").strip(),
                },
            )
