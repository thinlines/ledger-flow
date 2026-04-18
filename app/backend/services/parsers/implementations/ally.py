from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter
from ..types import Record


_CHECK_RE = re.compile(r"Check\s*#\s*(\d+)", re.IGNORECASE)
_AMOUNT_STRIP_RE = re.compile(r"[,\s]")


def _parse_amount(raw: str) -> Decimal:
    s = raw.strip()
    if not s:
        raise ValueError("Ally Amount column is empty")
    negative = False
    if s.startswith("-"):
        negative = True
        s = s[1:].lstrip()
    if s.startswith("$"):
        s = s[1:].lstrip()
    if s.startswith("-"):
        negative = True
        s = s[1:].lstrip()
    s = _AMOUNT_STRIP_RE.sub("", s)
    value = Decimal(s)
    return -value if negative else value


@register_adapter
class AllyAdapter:
    name = "ally"
    institution = "ally"
    formats = ("csv",)
    translator_name = "generic.checking"

    display_name = "Ally Bank"
    csv_date_format = "%m/%d/%Y"
    suggested_ledger_prefix = "Assets:Bank:Ally"
    aliases = ("ally_bank", "allybank")
    head = 1
    tail = 0
    encoding = "utf-8-sig"

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) < 5:
                raise ValueError(
                    f"Ally row has {len(row)} columns; expected 5 "
                    f"(Date,Time,Amount,Type,Description): {row!r}"
                )
            date_s, time_s, amount_s, type_s, description_s = (
                row[0].strip(),
                row[1].strip(),
                row[2].strip(),
                row[3].strip(),
                row[4].strip(),
            )
            yield Record(
                date=datetime.strptime(date_s, self.csv_date_format).date(),
                description=description_s,
                amount=_parse_amount(amount_s),
                currency="$",
                code=self._extract_check_number(description_s, type_s),
                balance=None,
                note=None,
                raw={
                    "time": time_s,
                    "type": type_s,
                },
            )

    @staticmethod
    def _extract_check_number(description: str, type_: str) -> str | None:
        if type_.lower() != "check" and "check" not in description.lower():
            return None
        match = _CHECK_RE.search(description)
        return match.group(1) if match else None
