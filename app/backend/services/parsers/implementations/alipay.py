from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter
from ..types import Record

# Column names matching AlipayCSV.__init__ in Scripts/BankCSV.py:105-114.
# The CSV header row is sliced off by csv_normalizer (head=13), so
# DictReader needs explicit fieldnames — same list the legacy parser uses.
_FIELDNAMES = [
    "流水号",
    "时间",
    "名称",
    "备注",
    "收入",
    "支出",
    "账户余额（元）",
    "资金渠道",
]


@register_adapter
class AlipayAdapter:
    name = "alipay"
    institution = "alipay"
    formats = ("csv",)
    translator_name = "generic.checking"

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.DictReader(io.StringIO(text), fieldnames=_FIELDNAMES)
        for row in reader:
            income = row.get("收入", "").strip()
            expense = row.get("支出", "").strip()
            # Alipay source has signs embedded: income positive, expense negative.
            # Matches Scripts/BankCSV.py:122 amount() behavior.
            raw_amount = income + expense
            yield Record(
                date=datetime.strptime(
                    row["时间"].strip(), "%Y-%m-%d %H:%M:%S"
                ).date(),
                description=row["名称"].strip(),
                amount=Decimal(raw_amount) if raw_amount else None,
                currency="¥",
                code=row["流水号"].strip() or None,
                balance=(
                    Decimal(row["账户余额（元）"].strip())
                    if row.get("账户余额（元）", "").strip()
                    else None
                ),
                note=None,  # AlipayCSV does not override BankCSV.note(); always None.
                raw={k: v for k, v in row.items() if v},
            )
