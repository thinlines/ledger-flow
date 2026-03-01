#!/bin/python

import argparse
import csv
from BankCSV import create_bank_csv
import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


parser = argparse.ArgumentParser()

parser.add_argument("input", help="The CSV file to process")
parser.add_argument("institution", help="The name of the institution")
parser.add_argument("-c", "--config", metavar="PATH", help="Path to TOML config")
args = parser.parse_args()


def main():
    # Set up configuration
    with open(args.config if args.config else "config.toml", "rb") as f:
        config = tomllib.load(f)
        institutions_cfg = config.get("institutions", {})
        csv_config = institutions_cfg.get(args.institution)
        if csv_config is None:
            raise ValueError(
                f"Institution config for {args.institution!r} not found. Check your config file"
            )

        head = csv_config.get("head", 0)
        tail = csv_config.get("tail", False)
        encoding = csv_config.get("encoding", "utf-8")
        parser_key = csv_config.get("parser", args.institution)

    with open(args.input, encoding=encoding) as file:
        lns = file.readlines()
        tail = -tail if tail else len(lns)
        lines = lns[head:tail]
        bank_csv = create_bank_csv(parser_key, lines, config)
        reader = bank_csv.reader()

        output = []
        for row in reader:
            output_row = {
                "date": bank_csv.date(row),
                "code": bank_csv.code(row),
                "description": bank_csv.description(row),
                "amount": bank_csv.amount(row),
                "total": bank_csv.total(row),
                "note": bank_csv.note(row),
                "symbol": bank_csv.symbol(row),
                "price": bank_csv.price(row),
            }
            output.append(output_row)

        writer = csv.DictWriter(
            sys.stdout, fieldnames=bank_csv.fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(reversed(output))


if __name__ == "__main__":
    main()
