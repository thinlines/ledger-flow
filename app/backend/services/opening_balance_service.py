from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from .config_service import AppConfig, infer_account_kind


TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
HEADER_RE = re.compile(
    r"^(?P<date>\d{4}[-/]\d{2}[-/]\d{2})"
    r"(?:\s+[*!])?"
    r"(?:\s+\([^)]+\))?"
    r"\s*(?P<payee>.*)$"
)
POSTING_RE = re.compile(r"^\s+([^\s].*?)(?:(?:\s{2,}|\t+)(.+))?$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
OPENING_BALANCES_EQUITY = "Equity:Opening-Balances"


@dataclass(frozen=True)
class OpeningBalanceEntry:
    tracked_account_id: str | None
    ledger_account: str
    offset_account: str
    amount: Decimal
    date: str


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


def _entry_from_transaction(lines: list[str]) -> OpeningBalanceEntry | None:
    header_match = HEADER_RE.match(lines[0])
    if not header_match:
        return None

    tracked_account_id: str | None = None
    postings: list[tuple[str, Decimal | None]] = []

    for line in lines[1:]:
        meta_match = META_RE.match(line)
        if meta_match:
            key = meta_match.group(1).strip().lower()
            if key == "tracked_account_id":
                tracked_account_id = meta_match.group(2).strip() or None
            continue

        posting_match = POSTING_RE.match(line)
        if not posting_match:
            continue

        account = posting_match.group(1).strip()
        postings.append((account, _parse_amount(posting_match.group(2) or "")))

    primary_index = next(
        (
            idx
            for idx, (account, amount) in enumerate(postings)
            if amount is not None and infer_account_kind(account) in {"asset", "liability"}
        ),
        None,
    )
    if primary_index is None:
        return None

    primary_account, primary_amount = postings[primary_index]
    offset_account = next(
        (
            account
            for idx, (account, _) in enumerate(postings)
            if idx != primary_index
        ),
        OPENING_BALANCES_EQUITY,
    )

    return OpeningBalanceEntry(
        tracked_account_id=tracked_account_id,
        ledger_account=primary_account,
        offset_account=offset_account,
        amount=primary_amount,
        date=header_match.group("date").replace("/", "-"),
    )


def load_opening_balance_entries(config: AppConfig) -> list[OpeningBalanceEntry]:
    entries: list[OpeningBalanceEntry] = []
    for journal_path in sorted(config.opening_bal_dir.glob("*.journal")):
        if not journal_path.exists():
            continue
        text = journal_path.read_text(encoding="utf-8")
        for lines in _split_transactions(text):
            entry = _entry_from_transaction(lines)
            if entry is not None:
                entries.append(entry)
    return entries


def opening_balance_index(config: AppConfig) -> tuple[dict[str, OpeningBalanceEntry], dict[str, OpeningBalanceEntry]]:
    by_account_id: dict[str, OpeningBalanceEntry] = {}
    by_ledger_account: dict[str, OpeningBalanceEntry] = {}
    for entry in load_opening_balance_entries(config):
        if entry.tracked_account_id:
            by_account_id[entry.tracked_account_id] = entry
        by_ledger_account[entry.ledger_account] = entry
    return by_account_id, by_ledger_account


def _format_amount(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'))}"


def _default_opening_date(config: AppConfig) -> str:
    return f"{config.start_year:04d}-01-01"


def write_opening_balance(
    config: AppConfig,
    tracked_account_id: str,
    ledger_account: str,
    amount_text: str,
    opening_date: str | None = None,
    offset_account: str = OPENING_BALANCES_EQUITY,
) -> None:
    cleaned_amount = amount_text.strip()
    target_path = config.opening_bal_dir / f"{tracked_account_id}.journal"

    if not cleaned_amount:
        if target_path.exists():
            target_path.unlink()
        return

    amount = _parse_amount(cleaned_amount)
    if amount is None or amount == 0:
        if target_path.exists():
            target_path.unlink()
        return

    date = (opening_date or "").strip() or _default_opening_date(config)
    offset_ledger_account = offset_account.strip() or OPENING_BALANCES_EQUITY
    currency = str(config.workspace.get("base_currency", "USD")).strip() or "USD"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        "\n".join(
            [
                f"{date} Opening balance",
                f"    ; tracked_account_id: {tracked_account_id}",
                f"    {ledger_account}  {currency} {_format_amount(amount)}",
                f"    {offset_ledger_account}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def delete_opening_balance(config: AppConfig, tracked_account_id: str) -> None:
    target_path = config.opening_bal_dir / f"{tracked_account_id}.journal"
    if target_path.exists():
        target_path.unlink()
