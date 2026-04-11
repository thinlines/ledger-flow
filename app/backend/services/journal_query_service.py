from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
import glob
from pathlib import Path
import re

from .archive_service import ARCHIVED_MANUAL_JOURNAL_NAME
from .commodity_service import CommodityMismatchError, commodity_label, parse_amount
from .config_service import AppConfig
from .header_parser import HEADER_RE, TransactionStatus, parse_header


TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
POSTING_RE = re.compile(r"^\s+([^\s].*?)(?:(?:\s{2,}|\t+)(.+))?$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
INCLUDE_RE = re.compile(r"^\s*include\s+(.+?)\s*$")


@dataclass(frozen=True)
class Posting:
    account: str
    amount: Decimal | None
    commodity: str | None = None
    inferred: bool = False


@dataclass(frozen=True)
class ParsedTransaction:
    posted_on: date
    payee: str
    postings: list[Posting]
    metadata: dict[str, str]
    status: TransactionStatus = TransactionStatus.unmarked
    header_line: str = ""
    source_journal: str = ""


def amount_to_number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def pretty_account_name(account: str) -> str:
    parts = [segment.replace("_", " ").strip() for segment in account.split(":") if segment.strip()]
    if not parts:
        return "Unlabeled"
    if len(parts) == 1:
        return parts[0].title()
    return " / ".join(part.title() for part in parts[1:])


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


def _normalize_include_target(raw: str) -> str:
    target = raw.split(";", 1)[0].strip()
    if len(target) >= 2 and target[0] == target[-1] and target[0] in {'"', "'"}:
        return target[1:-1].strip()
    return target


def _resolve_include_paths(base_dir: Path, target: str) -> list[Path]:
    if not target:
        return []
    pattern = base_dir / target
    matches = [Path(match) for match in sorted(glob.glob(str(pattern), recursive=True))]
    if matches:
        return matches
    if pattern.exists():
        return [pattern]
    return []


def _expand_journal_lines(path: Path, stack: tuple[Path, ...] = ()) -> list[str]:
    resolved_path = path.resolve()
    if resolved_path in stack or not path.exists():
        return []

    lines: list[str] = []
    next_stack = (*stack, resolved_path)
    for raw in path.read_text(encoding="utf-8").splitlines():
        include_match = INCLUDE_RE.match(raw)
        if not include_match:
            lines.append(raw)
            continue

        include_target = _normalize_include_target(include_match.group(1))
        include_paths = _resolve_include_paths(path.parent, include_target)
        if not include_paths:
            continue
        for include_path in include_paths:
            lines.extend(_expand_journal_lines(include_path, next_stack))
    return lines


def _parse_transaction(lines: list[str]) -> ParsedTransaction | None:
    parsed_header = parse_header(lines[0])
    if not parsed_header:
        return None

    try:
        posted_on = date.fromisoformat(parsed_header.date.replace("/", "-"))
    except ValueError:
        return None

    txn_status = parsed_header.status
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
        parsed_amount = parse_amount(posting_match.group(2) or "")
        postings.append(
            Posting(
                account=account,
                amount=parsed_amount.value if parsed_amount is not None else None,
                commodity=parsed_amount.commodity if parsed_amount is not None else None,
            )
        )

    if not postings:
        return None

    known_total = sum((posting.amount or Decimal("0")) for posting in postings if posting.amount is not None)
    blank_indexes = [index for index, posting in enumerate(postings) if posting.amount is None]
    if len(blank_indexes) == 1:
        idx = blank_indexes[0]
        known_commodities = {posting.commodity for posting in postings if posting.amount is not None}
        if len(known_commodities) > 1:
            raise CommodityMismatchError(
                "Transaction mixes multiple commodities and cannot infer the blank posting amount "
                f"({', '.join(sorted(commodity_label(commodity) for commodity in known_commodities))})."
            )
        postings[idx] = Posting(
            account=postings[idx].account,
            amount=-known_total,
            commodity=next(iter(known_commodities), None),
            inferred=True,
        )

    return ParsedTransaction(
        posted_on=posted_on,
        payee=parsed_header.payee or "Untitled transaction",
        postings=postings,
        metadata=metadata,
        status=txn_status,
        header_line=lines[0],
    )


def is_generated_opening_balance_transaction(transaction: ParsedTransaction) -> bool:
    return bool(str(transaction.metadata.get("tracked_account_id", "")).strip())


def load_transactions(config: AppConfig) -> list[ParsedTransaction]:
    transactions: list[ParsedTransaction] = []
    for journal_path in sorted(config.journal_dir.glob("*.journal")):
        if not journal_path.exists():
            continue
        # archived-manual.journal is a sidecar that holds matched manual entries
        # for undo. Loading it duplicates each matched transaction next to its
        # imported counterpart in the register.
        if journal_path.name == ARCHIVED_MANUAL_JOURNAL_NAME:
            continue
        text = "\n".join(_expand_journal_lines(journal_path))
        for lines in _split_transactions(text):
            transaction = _parse_transaction(lines)
            if transaction is not None:
                transactions.append(replace(transaction, source_journal=str(journal_path)))
    return sorted(transactions, key=lambda txn: txn.posted_on)
