#!/usr/bin/python

"""
Takes the CSV of payee aliases and spits out the .dat for ledger
"""

import sys
import os
import csv
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("input", help="The CSV of aliases (format: payee,alias)")
parser.add_argument("-o", "--output", metavar="PATH", help="Output file to write to")
args = parser.parse_args()


def collate_payees(dest=sys.stdout):
    for payee in sorted([str(key) for key in aliases.keys()]):
        print("payee", payee, file=dest)
        for alias in sorted(aliases[payee]):
            print("\talias", alias, file=dest)


try:
    with open(args.input) as f:
        aliases = dict()
        reader = csv.DictReader(f)
        for txn in reader:
            try:
                aliases[txn["payee"]].append(txn["alias"])
            except KeyError:
                aliases[txn["payee"]] = [txn["alias"]]
except FileNotFoundError:
    print(
          f"Warning: payee alias {args.input} file not found. Creating a new one",
          file=sys.stderr
    )
    print("payee,alias", file=open(args.input, "w"))
    exit(2)

if args.output:
    with open(args.output, "w") as dest:
        collate_payees(dest)
else:
    collate_payees()
