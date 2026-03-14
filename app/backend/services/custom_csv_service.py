from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dateutil import parser as date_parser


INTERMEDIATE_FIELDNAMES = ["date", "code", "description", "amount", "total", "note", "symbol", "price"]
DEFAULT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1", "gb18030")
SUPPORTED_DELIMITERS = [",", ";", "\t", "|"]
CURRENCY_SYMBOLS = {"$", "€", "£", "¥"}


def normalize_custom_profile(raw: dict, *, default_currency: str, default_display_name: str) -> dict:
    display_name = str(raw.get("display_name") or default_display_name).strip() or default_display_name
    delimiter = str(raw.get("delimiter") or ",")
    if delimiter == "\\t":
        delimiter = "\t"
    if delimiter not in SUPPORTED_DELIMITERS:
        raise ValueError("Delimiter must be one of comma, semicolon, tab, or pipe")

    amount_mode = str(raw.get("amount_mode") or "signed").strip() or "signed"
    if amount_mode not in {"signed", "debit_credit"}:
        raise ValueError("Amount mode must be 'signed' or 'debit_credit'")

    profile = {
        "kind": "custom_csv",
        "display_name": display_name,
        "encoding": str(raw.get("encoding") or "utf-8").strip() or "utf-8",
        "delimiter": delimiter,
        "skip_rows": max(0, int(raw.get("skip_rows") or 0)),
        "skip_footer_rows": max(0, int(raw.get("skip_footer_rows") or 0)),
        "reverse_order": bool(raw.get("reverse_order", True)),
        "date_column": str(raw.get("date_column") or "").strip(),
        "date_format": str(raw.get("date_format") or "").strip() or None,
        "description_column": str(raw.get("description_column") or "").strip(),
        "secondary_description_column": str(raw.get("secondary_description_column") or "").strip() or None,
        "amount_mode": amount_mode,
        "amount_column": str(raw.get("amount_column") or "").strip() or None,
        "debit_column": str(raw.get("debit_column") or "").strip() or None,
        "credit_column": str(raw.get("credit_column") or "").strip() or None,
        "balance_column": str(raw.get("balance_column") or "").strip() or None,
        "code_column": str(raw.get("code_column") or "").strip() or None,
        "note_column": str(raw.get("note_column") or "").strip() or None,
        "currency": str(raw.get("currency") or default_currency).strip() or default_currency,
    }

    if not profile["date_column"]:
        raise ValueError("Custom CSV profile requires a date column")
    if not profile["description_column"]:
        raise ValueError("Custom CSV profile requires a description column")
    if amount_mode == "signed" and not profile["amount_column"]:
        raise ValueError("Signed amount mode requires an amount column")
    if amount_mode == "debit_credit" and not (profile["debit_column"] or profile["credit_column"]):
        raise ValueError("Debit/credit mode requires a debit or credit column")

    return profile


def inspect_csv_bytes(
    content: bytes,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    skip_rows: int = 0,
    skip_footer_rows: int = 0,
) -> dict:
    text, resolved_encoding = _decode_bytes(content, encoding)
    lines = _trim_lines(text.splitlines(), skip_rows, skip_footer_rows)
    if not lines:
        raise ValueError("No CSV rows remain after applying skip settings")

    resolved_delimiter = delimiter or _sniff_delimiter(lines)
    if resolved_delimiter == "\\t":
        resolved_delimiter = "\t"
    if resolved_delimiter not in SUPPORTED_DELIMITERS:
        resolved_delimiter = ","

    reader = csv.DictReader(lines, delimiter=resolved_delimiter)
    headers = [str(header).strip() for header in (reader.fieldnames or []) if header is not None]
    sample_rows: list[dict[str, str]] = []
    for row in reader:
        if row is None:
            continue
        cleaned = {str(key): (value or "").strip() for key, value in row.items() if key is not None}
        if any(value for value in cleaned.values()):
            sample_rows.append(cleaned)
        if len(sample_rows) >= 6:
            break

    return {
        "encoding": resolved_encoding,
        "delimiter": resolved_delimiter,
        "headers": headers,
        "sampleRows": sample_rows,
    }


def normalize_custom_csv_to_intermediate(csv_path: Path, profile: dict) -> str:
    content = csv_path.read_bytes()
    text, _ = _decode_bytes(content, str(profile.get("encoding") or "utf-8"))
    lines = _trim_lines(
        text.splitlines(),
        int(profile.get("skip_rows") or 0),
        int(profile.get("skip_footer_rows") or 0),
    )
    if not lines:
        raise ValueError("No CSV rows remain after applying skip settings")

    delimiter = str(profile.get("delimiter") or ",")
    if delimiter == "\\t":
        delimiter = "\t"
    reader = csv.DictReader(lines, delimiter=delimiter)
    rows: list[dict[str, str | None]] = []
    fieldnames = reader.fieldnames or []
    missing = [
        column
        for column in _required_columns(profile)
        if column and column not in fieldnames
    ]
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}")

    for line_no, row in enumerate(reader, start=2):
        cleaned = {str(key): (value or "").strip() for key, value in row.items() if key is not None}
        if not any(cleaned.values()):
            continue
        if _should_skip_row(cleaned, profile):
            continue

        date_value = _parse_date(cleaned.get(str(profile["date_column"]), ""), str(profile.get("date_format") or ""))
        description_parts = [
            cleaned.get(str(profile["description_column"]), ""),
        ]
        secondary_column = str(profile.get("secondary_description_column") or "").strip()
        if secondary_column:
            description_parts.append(cleaned.get(secondary_column, ""))
        description = " ".join(part.strip() for part in description_parts if part and part.strip()).strip()
        if not description:
            raise ValueError(f"Row {line_no} is missing a description")

        amount = _build_amount(cleaned, profile, line_no=line_no)
        total = None
        balance_column = str(profile.get("balance_column") or "").strip()
        if balance_column:
            balance_value = cleaned.get(balance_column, "").strip()
            if balance_value:
                total = _normalize_money(balance_value, str(profile["currency"]), positive_only=False)
        code = cleaned.get(str(profile.get("code_column") or ""), "").strip() or None
        note = cleaned.get(str(profile.get("note_column") or ""), "").strip() or None

        rows.append(
            {
                "date": date_value,
                "code": code,
                "description": description,
                "amount": amount,
                "total": total,
                "note": note,
                "symbol": None,
                "price": None,
            }
        )

    output_rows = list(reversed(rows)) if bool(profile.get("reverse_order", True)) else rows
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=INTERMEDIATE_FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(output_rows)
    return out.getvalue()


def _required_columns(profile: dict) -> list[str]:
    columns = [
        str(profile.get("date_column") or "").strip(),
        str(profile.get("description_column") or "").strip(),
        str(profile.get("secondary_description_column") or "").strip(),
        str(profile.get("amount_column") or "").strip(),
        str(profile.get("debit_column") or "").strip(),
        str(profile.get("credit_column") or "").strip(),
        str(profile.get("balance_column") or "").strip(),
        str(profile.get("code_column") or "").strip(),
        str(profile.get("note_column") or "").strip(),
    ]
    return [column for column in columns if column]


def _should_skip_row(row: dict[str, str], profile: dict) -> bool:
    date_value = row.get(str(profile.get("date_column") or ""), "").strip()
    description_value = row.get(str(profile.get("description_column") or ""), "").strip()
    amount_value = row.get(str(profile.get("amount_column") or ""), "").strip()
    debit_value = row.get(str(profile.get("debit_column") or ""), "").strip()
    credit_value = row.get(str(profile.get("credit_column") or ""), "").strip()
    return not any([date_value, description_value, amount_value, debit_value, credit_value])


def _decode_bytes(content: bytes, encoding: str | None) -> tuple[str, str]:
    if encoding:
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError as e:
            raise ValueError(f"Could not decode CSV using {encoding}") from e

    for candidate in DEFAULT_ENCODINGS:
        try:
            return content.decode(candidate), candidate
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode CSV using supported encodings")


def _trim_lines(lines: list[str], skip_rows: int, skip_footer_rows: int) -> list[str]:
    start = max(0, int(skip_rows))
    end = len(lines) - max(0, int(skip_footer_rows))
    if end < start:
        return []
    return lines[start:end]


def _sniff_delimiter(lines: list[str]) -> str:
    sample = "\n".join(lines[:10])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(SUPPORTED_DELIMITERS))
        return dialect.delimiter
    except csv.Error:
        return ","


def _parse_date(raw_value: str, date_format: str) -> str:
    value = raw_value.strip()
    if not value:
        raise ValueError("Custom CSV row is missing a date")
    if date_format:
        parsed = datetime.strptime(value, date_format)
    else:
        parsed = date_parser.parse(value)
    return parsed.strftime("%Y/%m/%d")


def _build_amount(row: dict[str, str], profile: dict, *, line_no: int) -> str:
    currency = str(profile["currency"])
    amount_mode = str(profile["amount_mode"])
    if amount_mode == "signed":
        column = str(profile.get("amount_column") or "")
        return _normalize_money(row.get(column, ""), currency, positive_only=False)

    debit_column = str(profile.get("debit_column") or "")
    credit_column = str(profile.get("credit_column") or "")
    debit_value = row.get(debit_column, "").strip() if debit_column else ""
    credit_value = row.get(credit_column, "").strip() if credit_column else ""
    if debit_value and credit_value:
        raise ValueError(f"Row {line_no} has both debit and credit values")
    if debit_value:
        return _normalize_money(debit_value, currency, positive_only=True, negative=True)
    if credit_value:
        return _normalize_money(credit_value, currency, positive_only=True, negative=False)
    raise ValueError(f"Row {line_no} is missing both debit and credit values")


def _normalize_money(raw_value: str, currency: str, *, positive_only: bool, negative: bool = False) -> str:
    value = raw_value.strip()
    if not value:
        raise ValueError("Custom CSV row is missing an amount")

    is_negative = negative
    if value.startswith("(") and value.endswith(")"):
        is_negative = True
        value = value[1:-1]

    value = value.replace(",", "").strip()
    if value.upper().endswith("CR"):
        value = value[:-2].strip()
    if value.upper().endswith("DR"):
        value = value[:-2].strip()
        is_negative = True

    if value.startswith("+"):
        value = value[1:].strip()
    elif value.startswith("-"):
        value = value[1:].strip()
        is_negative = True

    for token in ["$", "USD", "EUR", "GBP", "CAD"]:
        if value.startswith(token):
            value = value[len(token):].strip()
        if value.endswith(token):
            value = value[:-len(token)].strip()

    try:
        amount = Decimal(value)
    except InvalidOperation as e:
        raise ValueError(f"Invalid amount value: {raw_value}") from e

    if amount < 0:
        amount = abs(amount)
        is_negative = True
    if not positive_only and raw_value.strip().startswith("-"):
        is_negative = True

    rendered = format(amount, "f")
    sign = "-" if is_negative else ""
    if currency in CURRENCY_SYMBOLS:
        return f"{currency}{sign}{rendered}"
    return f"{sign}{rendered} {currency}"
