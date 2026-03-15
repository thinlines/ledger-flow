from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from .config_service import AppConfig


TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
HEADER_RE = re.compile(
    r"^(?P<date>\d{4}[-/]\d{2}[-/]\d{2})"
    r"(?:\s+[*!])?"
    r"(?:\s+\([^)]+\))?"
    r"\s*(?P<payee>.*)$"
)
POSTING_RE = re.compile(r"^\s+([^\s].*?)(?:(?:\s{2,}|\t+)(.+))?$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")


@dataclass(frozen=True)
class Posting:
    account: str
    amount: Decimal | None
    inferred: bool = False


@dataclass(frozen=True)
class ParsedTransaction:
    posted_on: date
    payee: str
    postings: list[Posting]
    metadata: dict[str, str]


def amount_to_number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def pretty_account_name(account: str) -> str:
    parts = [segment.replace("_", " ").strip() for segment in account.split(":") if segment.strip()]
    if not parts:
        return "Unlabeled"
    if len(parts) == 1:
        return parts[0].title()
    return " / ".join(part.title() for part in parts[1:])


def _parse_amount(raw: str) -> Decimal | None:
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return None

    digits = "".join(ch for ch in compact if ch.isdigit() or ch in {".", ","})
    if not digits:
        return None

    sign = -1 if "-" in compact else 1
    try:
        return Decimal(digits.replace(",", "")) * sign
    except InvalidOperation:
        return None


def _split_transactions(journal_text: str) -> list[list[str]]:
    transactions: list[list[str]] = []
    current: list[str] = []
    for raw in journal_text.splitlines():
        if TXN_START_RE.match(raw):
            if current:
                transactions.append(current)
            current = [raw]
        elif current:
            current.append(raw)
    if current:
        transactions.append(current)
    return transactions


def _parse_transaction(lines: list[str]) -> ParsedTransaction | None:
    header_match = HEADER_RE.match(lines[0])
    if not header_match:
        return None

    try:
        posted_on = date.fromisoformat(header_match.group("date").replace("/", "-"))
    except ValueError:
        return None

    metadata: dict[str, str] = {}
    postings: list[Posting] = []

    for line in lines[1:]:
        meta_match = META_RE.match(line)
        if meta_match:
            metadata[meta_match.group(1).strip().lower()] = meta_match.group(2).strip()
            continue

        posting_match = POSTING_RE.match(line)
        if not posting_match:
            continue

        account = posting_match.group(1).strip()
        amount = _parse_amount(posting_match.group(2) or "")
        postings.append(Posting(account=account, amount=amount))

    if not postings:
        return None

    known_total = sum((posting.amount or Decimal("0")) for posting in postings if posting.amount is not None)
    blank_indexes = [index for index, posting in enumerate(postings) if posting.amount is None]
    if len(blank_indexes) == 1:
        idx = blank_indexes[0]
        postings[idx] = Posting(account=postings[idx].account, amount=-known_total, inferred=True)

    return ParsedTransaction(
        posted_on=posted_on,
        payee=header_match.group("payee").strip() or "Untitled transaction",
        postings=postings,
        metadata=metadata,
    )


def load_transactions(config: AppConfig) -> list[ParsedTransaction]:
    transactions: list[ParsedTransaction] = []
    for journal_path in sorted(config.journal_dir.glob("*.journal")):
        if not journal_path.exists():
            continue
        text = journal_path.read_text(encoding="utf-8")
        for lines in _split_transactions(text):
            transaction = _parse_transaction(lines)
            if transaction is not None:
                transactions.append(transaction)
    return sorted(transactions, key=lambda txn: txn.posted_on)
