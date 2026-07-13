from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import glob
from pathlib import Path
import re

from .commodity_service import CommodityMismatchError, commodity_label, parse_amount
from .header_parser import TransactionStatus, parse_header
from .journal_syntax import (
    ACCOUNT_LINE_RE,
    ACCOUNT_ONLY_RE,
    LF_TXN_ID_META_RE,
    META_RE,
    POSTING_RE,
    TXN_START_RE,
)

__all__ = [
    "ACCOUNT_LINE_RE",
    "ACCOUNT_ONLY_RE",
    "LF_TXN_ID_META_RE",
    "META_RE",
    "POSTING_RE",
    "TXN_START_RE",
]


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
    # Zero-indexed offset of the header line within the *physical* file at
    # ``source_journal`` (matches ``Path(source_journal).read_text().splitlines()``
    # indexing). For transactions that physically live in an included file, the
    # header line will not be found in the top-level file; in that case this is
    # set to ``-1`` (sentinel), and mutation endpoints will reject the request
    # via the same drift path that catches stale data.
    header_line_number: int = -1
    # Stable projected identity (spec: Mutation-Time Projection). Populated
    # by the projection loader.
    txn_id: str | None = None
    block_hash: str | None = None


def amount_to_number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def pretty_account_name(account: str) -> str:
    parts = [segment.replace("_", " ").strip() for segment in account.split(":") if segment.strip()]
    if not parts:
        return "Unlabeled"
    if len(parts) == 1:
        return parts[0].title()
    return " / ".join(part.title() for part in parts[1:])


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
