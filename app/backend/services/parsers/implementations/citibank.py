from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter
from ..types import Record


@register_adapter
class CitibankAdapter:
    name = "citibank"
    institution = "citibank"
    aliases = ("citi", "citibank", "citi-bank")
    formats = ("csv",)
    translator_name = "generic.checking"

    display_name = "Citibank"
    csv_date_format = "%m/%d/%Y"
    suggested_ledger_prefix = "Liabilities:Credit Card:Citibank"
    encoding = "utf-8-sig"
    head = 0
    tail = 0

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.DictReader(io.StringIO(text))
        has_status = reader.fieldnames is not None and "Status" in reader.fieldnames

        for row in reader:
            if has_status and row.get("Status", "").strip() == "Pending":
                continue

            debit = row.get("Debit", "").strip()
            credit = row.get("Credit", "").strip()

            if not debit and not credit:
                continue

            if debit and credit:
                raise ValueError(
                    f"Citibank row has both Debit and Credit populated; "
                    f"adapter cannot determine sign. Row: {row!r}"
                )

            if debit:
                amount = -Decimal(debit)
            else:
                amount = Decimal(credit)

            yield Record(
                date=datetime.strptime(row["Date"].strip(), "%m/%d/%Y").date(),
                description=row["Description"].strip(),
                amount=amount,
                currency="$",
                code=None,
                balance=None,
                note=None,
                raw={
                    "status": row.get("Status", "").strip() or None,
                    "member_name": row.get("Member Name", "").strip() or None,
                    "debit": debit or None,
                    "credit": credit or None,
                },
            )
