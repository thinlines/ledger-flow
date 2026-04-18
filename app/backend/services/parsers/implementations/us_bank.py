from __future__ import annotations
import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter
from ..types import Record


@register_adapter
class USBankAdapter:
    name = "us_bank"
    institution = "us_bank"
    formats = ("csv",)
    translator_name = "generic.checking"

    display_name = "U.S. Bank"
    csv_date_format = "%m/%d/%Y"
    suggested_ledger_prefix = "Assets:Bank:US Bank"
    aliases = ("us_bank", "usbank", "us-bank")
    head = 0
    tail = 0
    encoding = "utf-8"

    _COL_DATE = 0
    _COL_TXN = 1
    _COL_NAME = 2
    _COL_MEMO = 3
    _COL_AMOUNT = 4

    _DEBIT = "DEBIT"
    _CREDIT = "CREDIT"

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if header is None:
            return
        if header and header[0].lstrip("\ufeff").strip().strip('"').lower() != "date":
            raise ValueError(
                f"Unexpected U.S. Bank header row: {header!r}; "
                f"expected first column 'Date'"
            )

        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) < 5:
                raise ValueError(
                    f"U.S. Bank row has {len(row)} columns, expected at "
                    f"least 5: {row!r}"
                )

            txn = row[self._COL_TXN].strip().upper()
            raw_amount = row[self._COL_AMOUNT].strip().replace(",", "")
            if not raw_amount:
                raise ValueError(f"U.S. Bank row has empty Amount: {row!r}")
            magnitude = Decimal(raw_amount)

            if txn == self._DEBIT:
                signed = -magnitude
            elif txn == self._CREDIT:
                signed = magnitude
            else:
                raise ValueError(
                    f"U.S. Bank row has unexpected Transaction "
                    f"value {txn!r}; expected 'DEBIT' or 'CREDIT'"
                )

            name = row[self._COL_NAME].strip()
            memo = row[self._COL_MEMO].strip()
            description = name if not memo else f"{name} {memo}".strip()

            yield Record(
                date=datetime.strptime(
                    row[self._COL_DATE].strip(), self.csv_date_format
                ).date(),
                description=description,
                amount=signed,
                currency="$",
                code=None,
                balance=None,
                note=None,
                raw={
                    "Date": row[self._COL_DATE],
                    "Transaction": row[self._COL_TXN],
                    "Name": row[self._COL_NAME],
                    "Memo": row[self._COL_MEMO],
                    "Amount": row[self._COL_AMOUNT],
                },
            )
