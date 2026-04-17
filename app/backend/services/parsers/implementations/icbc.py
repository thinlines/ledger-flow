from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter
from ..types import Record

# Column names matching IcbcCSV.__init__ at Scripts/BankCSV.py:172-188.
# The preamble (including the header row) is sliced off by csv_normalizer.py,
# so the adapter must supply explicit fieldnames to DictReader.
FIELDNAMES = [
    "交易日期",
    "摘要",
    "交易详情",
    "交易场所",
    "交易国家或地区简称",
    "钞/汇",
    "交易金额(收入)",
    "交易金额(支出)",
    "交易币种",
    "记账金额(收入)",
    "记账金额(支出)",
    "记账币种",
    "余额",
    "对方户名",
    "对方账户",
]


@register_adapter
class IcbcAdapter:
    name = "icbc"
    institution = "icbc"
    formats = ("csv",)
    translator_name = "generic.checking"

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.DictReader(io.StringIO(text), fieldnames=FIELDNAMES)
        for row in reader:
            currency = self._currency(row)
            amtout = row["记账金额(支出)"].strip()
            amtin = row["记账金额(收入)"].strip()

            if amtout:
                amount = -Decimal(amtout)
            elif amtin:
                amount = Decimal(amtin)
            else:
                amount = None

            balance_raw = row.get("余额", "").strip()
            # Source CSV may contain thousand-separator commas (e.g. "2,568.44");
            # strip them before converting to Decimal.
            balance = Decimal(balance_raw.replace(",", "")) if balance_raw else None

            counterparty = row["对方户名"].strip() or None

            yield Record(
                date=datetime.strptime(row["交易日期"].strip(), "%Y-%m-%d").date(),
                description=(
                    row["交易场所"].strip() + " " + row["对方户名"].strip()
                ).strip(),
                amount=amount,
                currency=currency,
                code=row["摘要"].strip() or None,
                counterparty=counterparty,
                balance=balance,
                note=None,
                raw={k: v for k, v in row.items() if v and v.strip()},
            )

    @staticmethod
    def _currency(row: dict) -> str:
        """Per-row currency detection.

        Mirrors Scripts/BankCSV.py:196-198: 美元 → USD, anything else → CNY.
        """
        return "USD" if row.get("记账币种", "").strip() == "美元" else "CNY"
