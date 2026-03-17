from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re


TRANSFER_ROOT_ACCOUNT = "Assets:Transfers"
PAIR_SEPARATOR = "__"
ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")


def is_transfer_account(account: str) -> bool:
    cleaned = account.strip()
    return cleaned == TRANSFER_ROOT_ACCOUNT or cleaned.startswith(f"{TRANSFER_ROOT_ACCOUNT}:")


def transfer_pair_account(source_tracked_account_id: str, target_tracked_account_id: str) -> str:
    left, right = sorted([source_tracked_account_id.strip(), target_tracked_account_id.strip()])
    return f"{TRANSFER_ROOT_ACCOUNT}:{left}{PAIR_SEPARATOR}{right}"


def parse_amount(raw: str) -> Decimal | None:
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


def infer_blank_posting_amounts(postings: list[dict]) -> list[dict]:
    normalized = [dict(posting) for posting in postings]
    blank_indexes = [index for index, posting in enumerate(normalized) if posting.get("amountNumber") is None]
    if len(blank_indexes) != 1:
        return normalized

    known_total = sum(
        (posting.get("amountNumber") or Decimal("0"))
        for posting in normalized
        if posting.get("amountNumber") is not None
    )
    idx = blank_indexes[0]
    normalized[idx]["amountNumber"] = -known_total
    return normalized


def parse_metadata_lines(lines: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in lines:
        match = META_RE.match(line)
        if match:
            metadata[match.group(1).strip().lower()] = match.group(2).strip()
    return metadata


def upsert_transaction_metadata(txn_lines: list[str], updates: dict[str, str | None]) -> list[str]:
    if not txn_lines:
        return []

    updated = list(txn_lines)
    existing_indexes: dict[str, int] = {}
    for index, line in enumerate(updated[1:], start=1):
        match = META_RE.match(line)
        if not match:
            continue
        existing_indexes[match.group(1).strip().lower()] = index

    # Remove keys first so inserts land in the right place.
    removals = sorted(
        (existing_indexes[key] for key, value in updates.items() if value is None and key in existing_indexes),
        reverse=True,
    )
    for index in removals:
        updated.pop(index)

    existing_indexes = {}
    insert_at = 1
    for index, line in enumerate(updated[1:], start=1):
        match = META_RE.match(line)
        if match:
            existing_indexes[match.group(1).strip().lower()] = index
            insert_at = index + 1
            continue
        break

    inserts: list[str] = []
    for key, value in updates.items():
        if value is None:
            continue
        line = f"    ; {key}: {value}"
        if key in existing_indexes:
            updated[existing_indexes[key]] = line
        else:
            inserts.append(line)

    if inserts:
        updated[insert_at:insert_at] = inserts

    return updated


def rewrite_posting_account(line: str, target_account: str) -> tuple[str, bool]:
    match = ACCOUNT_LINE_RE.match(line)
    if match:
        return (f"{match.group(1)}{target_account}{match.group(3)}{match.group(4)}", True)

    match = ACCOUNT_ONLY_RE.match(line)
    if match:
        return (f"{match.group(1)}{target_account}", True)

    return line, False


def ensure_transfer_account(accounts_dat: Path, source_tracked_account_id: str, target_tracked_account_id: str) -> str:
    transfer_account = transfer_pair_account(source_tracked_account_id, target_tracked_account_id)
    lines = accounts_dat.read_text(encoding="utf-8").splitlines() if accounts_dat.exists() else []
    known_accounts = {
        line[len("account "):].strip()
        for line in lines
        if line.startswith("account ")
    }
    if transfer_account in known_accounts:
        return transfer_account

    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"account {transfer_account}")
    lines.append("    ; type: Asset")
    lines.append("    ; description: Internal transfer clearing account")
    accounts_dat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return transfer_account
