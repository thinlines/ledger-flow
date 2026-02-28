#!/bin/python

"""BankCSV.py

This module provides classes to process CSVs from each of the
financial institutions I import data from. BankCSV provides a
template class upon which the others are based.
"""

import csv
import sys
import re
from dateutil import parser
from datetime import datetime


def create_bank_csv(institution, input_lines, config):
    institutions = {
        inst: globals()[inst.capitalize() + "CSV"] for inst in config["institutions"]
    }
    try:
        return institutions[institution](input_lines)
    except KeyError:
        available_institutions = ", ".join(institutions.keys())
        raise ValueError(
            f"Unsupported institution: {institution}. Available institutions: {available_institutions}"
        )


class BankCSV:
    """A CSV of transactions."""

    fieldnames = ["date", "code", "description", "amount", "total", "note"]

    def __init__(self, input_csv):
        self.input_csv = input_csv

    def reader(self):
        return csv.DictReader(self.input_csv, self.header)

    def note(self, row):
        return None

    def date(self, row, col_name="date", date_fmt="%Y/%m/%d", input_date_fmt=None):
        col_names = [col_name, "交易日期", "时间"]
        for col_name in col_names:
            if col_name in row:
                if input_date_fmt:
                    date = datetime.strptime(row[col_name], input_date_fmt)
                else:
                    date = parser.parse(row[col_name])
                return date.strftime(date_fmt)

    def code(self, row, col_name="code"):
        return row[col_name].strip()

    def description(self, row):
        pass

    def amount(self, row, col_name="amount", debit_name=None, credit_name=None):
        try:
            return self.currency + row[col_name].strip()
        except KeyError:
            raise ValueError(f"Amount column {col_name} not found")

    def total(self, row, col_name="total"):
        col_names = [col_name, "balance", "余额"]
        for col_name in col_names:
            for key in row:
                if col_name in key:
                    if type(self.currency == "str"):
                        return row[col_name] + self.currency
                    else:
                        return row[col_name] + self.currency(row)

    def symbol(self, row):
        pass

    def price(self, row):
        pass

    def currency(self, row):
        return "$"


class AlipayCSV(BankCSV):
    """A CSV of transactions from Alipay"""

    def __init__(self, input_csv):
        super().__init__(input_csv)
        self.currency = "¥"
        self.header = [
            "流水号",
            "时间",
            "名称",
            "备注",
            "收入",
            "支出",
            "账户余额（元）",
            "资金渠道",
        ]

    def code(self, row):
        return row["流水号"].strip()

    def description(self, row):
        return row["名称"].strip()

    def amount(self, row):
        return self.currency + row["收入"].strip() + row["支出"].strip()

    def total(self, row):
        return self.currency + row["账户余额（元）"].strip()


class BjbCSV(BankCSV):
    """A CSV of transactions from Beijing Bank"""

    def __init__(self, input_csv):
        super().__init__(input_csv)
        self.currency = "CNY"
        self.header = [
            "交易日期",
            "币种",
            "钞汇",
            "业务摘要",
            "发生额",
            "余额",
            "对方户名",
            "对方账号",
            "流水单号"
        ]

    def code(self, row):
        return row["业务摘要"]

    def description(self, row):
        return f'{row["对方户名"]}'

    def amount(self, row):
        amt_type = row["发生额"][0]
        if amt_type == "+":
            amount = f'{row["发生额"][1:]} {self.currency}'
        elif amt_type == "-":
            amount = f'-{row["发生额"][1:]} {self.currency}'
        else:
            raise ValueError(f"Unknown amount type: {amt_type}")
        return amount

    def total(self, row):
        return f'{row["余额"]} {self.currency}'


class IcbcCSV(BankCSV):
    """A CSV of transactions from ICBC"""

    def __init__(self, input_csv):
        super().__init__(input_csv)
        self.header = [
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

    def code(self, row):
        return row["摘要"].strip()

    def description(self, row):
        return row["交易场所"].strip() + " " + row["对方户名"].strip()

    def currency(self, row):
        currency = row["记账币种"].strip()
        return "USD" if currency == "美元" else "CNY"

    def amount(self, row):
        currency = self.currency(row)
        amtout = row["记账金额(支出)"].strip()
        amtin = row["记账金额(收入)"].strip()
        if amtout:
            return "-" + amtout + currency
        elif amtin:
            return amtin + currency

    def total(self, row):
        currency = self.currency(row)
        return row["余额"].strip() + currency


class SchwabCSV(BankCSV):
    """A CSV of transactions from Schwab"""

    def __init__(self, input_csv):
        super().__init__(input_csv)
        self.dateFmt = r"[0-9]{2}/[0-9]{2}/[0-9]{4}"
        self.currency = ""
        self.header = [
            "Date",
            "Action",
            "Symbol",
            "Description",
            "Quantity",
            "Price",
            "Fees & Comm",
            "Amount",
        ]
        self.header.extend(["symbol", "price"])

    def date(self, row):
        if "as of" in row["Date"]:
            searchstring = f"({self.dateFmt}) as of ({self.dateFmt})"
            match = re.search(searchstring, row["Date"])
            date = match.group(2)
        else:
            date = row["Date"]
        return date

    def code(self, row):
        pass

    def description(self, row):
        q = row["Quantity"]
        a = row["Action"]
        symb = row["Symbol"]
        amt = row["Amount"]
        d = row["Description"]
        if symb and q:
            desc = f"Schwab - {a} {q} {symb} @@ {amt[1:]}"
        elif symb:
            desc = f"Schwab - {a}"
        else:
            desc = f"Schwab - {a} - {d}"
        return desc

    def amount(self, row):
        qnty = row["Quantity"]
        symb = row["Symbol"]
        amt = row["Amount"]
        action = row["Action"]
        if symb and qnty:
            amt = amt[1:]
            amount = f"-{qnty} {symb} @@ {amt}"
        else:
            amount = amt
        return amount

    def total(self, row):
        return None

    def note(self, row):
        if "as of" in row["Date"]:
            searchstring = f"({self.dateFmt}) as of {self.dateFmt}"
            match = re.search(searchstring, row["Date"])
            note = f"[={match.group(1)}], date: {match.group(1)}"
            return note

    def symbol(self, row):
        return row["Symbol"] or None

    def price(self, row):
        return row["Price"] or None


class WellsFargoCSV(BankCSV):
    """A CSV of transactions from Wells Fargo"""

    def __init__(self, input_csv):
        super().__init__(input_csv)
        self.header = ["date", "amount", "cleared", "note", "description"]
        self.currency = "$"

    def code(self, row):
        desc = row["description"]
        note = row["note"]
        if note:
            code = note
        elif "REF #" in desc:
            code = re.search("REF #([A-Z0-9]+)", desc).group(1)
        elif "CHECK #" in desc:
            code = re.search("CHECK # ?([0-9]+)", desc).group(1)
        else:
            code = ""
        return code

    def description(self, row):
        return row["description"]


WfsavCSV = WellsFargoCSV
WfchkCSV = WellsFargoCSV
WfccCSV = WellsFargoCSV
