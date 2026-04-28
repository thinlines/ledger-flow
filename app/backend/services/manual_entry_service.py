from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from .currency_parser import parse_amount
from .import_service import (
    _merge_transaction_blocks,
    _render_journal_text,
    _split_journal_preamble_and_transactions,
)

MAX_MANUAL_MATCH_DAYS = 3

from .header_parser import HEADER_RE

META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")

SYSTEM_METADATA_KEYS = frozenset({
    "import_account_id", "institution_template", "source_identity",
    "source_payload_hash", "source_file_sha256", "importer_version",
    "transfer_id", "transfer_peer_account_id", "transfer_type",
    "transfer_match_state", "transfer_state",
    "match-id",
})

TIER_LABELS = {1: "date_exact_amount", 2: "date_close_amount", 3: "date_payee", 4: "payee_only"}


def _load_known_accounts(accounts_dat: Path) -> set[str]:
    known = set()
    if not accounts_dat.exists():
        return known
    for line in accounts_dat.read_text(encoding="utf-8").splitlines():
        if line.startswith("account "):
            known.add(line[len("account "):].strip())
    return known


def _parse_amount_str(raw: str) -> Decimal:
    return parse_amount(raw)


def _format_currency_amount(amount: Decimal, currency: str) -> str:
    sign = "-" if amount < 0 else ""
    abs_amount = abs(amount)
    if currency == "USD":
        return f"{sign}${abs_amount:,.2f}"
    return f"{sign}{abs_amount:,.2f} {currency}"


def has_manual_tag(lines: list[str]) -> bool:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(";") and ":manual:" in stripped:
            return True
    return False


def _parse_posted_on(value: str) -> date | None:
    cleaned = value.replace("/", "-").strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Create manual transaction
# ---------------------------------------------------------------------------

def build_manual_transaction_block(
    *,
    txn_date: str,
    payee: str,
    amount: Decimal,
    destination_account: str,
    tracked_ledger_account: str,
    currency: str = "USD",
) -> list[str]:
    date_formatted = txn_date.replace("/", "-")
    amount_str = _format_currency_amount(amount, currency)
    return [
        f"{date_formatted} {payee}",
        "    ; :manual:",
        f"    {destination_account}  {amount_str}",
        f"    {tracked_ledger_account}",
    ]


def create_manual_transaction(
    *,
    journal_path: Path,
    accounts_dat: Path,
    tracked_account_cfg: dict,
    txn_date: str,
    payee: str,
    amount_str: str,
    destination_account: str,
    currency: str = "USD",
) -> dict:
    amount = _parse_amount_str(amount_str)
    tracked_ledger_account = str(tracked_account_cfg.get("ledger_account", "")).strip()
    if not tracked_ledger_account:
        raise ValueError("Tracked account is missing a ledger account.")

    known_accounts = _load_known_accounts(accounts_dat) if accounts_dat.exists() else set()
    destination_warning = None
    if destination_account not in known_accounts:
        destination_warning = f"Account '{destination_account}' is not in accounts.dat. The transaction will still be created."

    block = build_manual_transaction_block(
        txn_date=txn_date,
        payee=payee,
        amount=amount,
        destination_account=destination_account,
        tracked_ledger_account=tracked_ledger_account,
        currency=currency,
    )

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    if not journal_path.exists():
        journal_path.write_text("", encoding="utf-8")

    existing_text = journal_path.read_text(encoding="utf-8")
    preamble, existing_blocks = _split_journal_preamble_and_transactions(existing_text)
    merged = _merge_transaction_blocks(existing_blocks, [block])
    journal_path.write_text(_render_journal_text(preamble, merged), encoding="utf-8")

    return {
        "created": True,
        "date": txn_date,
        "payee": payee,
        "amount": str(amount),
        "destinationAccount": destination_account,
        "trackedLedgerAccount": tracked_ledger_account,
        "warning": destination_warning,
    }


# ---------------------------------------------------------------------------
# Parse manual entries from journal
# ---------------------------------------------------------------------------

def _parse_manual_entry_destination(lines: list[str], tracked_ledger_account: str) -> str | None:
    for line in lines[1:]:
        if line.strip().startswith(";"):
            continue
        m = ACCOUNT_LINE_RE.match(line) or ACCOUNT_ONLY_RE.match(line)
        if not m:
            continue
        account = m.group(2).strip()
        if account != tracked_ledger_account and "Unknown" not in account:
            return account
    return None


def _parse_manual_entry_amount(lines: list[str], tracked_ledger_account: str) -> Decimal | None:
    from .transfer_service import parse_amount as _parse_amount

    for line in lines[1:]:
        if line.strip().startswith(";"):
            continue
        m = ACCOUNT_LINE_RE.match(line)
        if not m:
            continue
        account = m.group(2).strip()
        if account != tracked_ledger_account:
            return _parse_amount(m.group(4).strip())
    return None


def _extract_user_metadata_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped.startswith(";"):
            continue
        if ":manual:" in stripped:
            continue
        m = META_RE.match(line)
        if m and m.group(1).strip().lower() in SYSTEM_METADATA_KEYS:
            continue
        result.append(line)
    return result


# ---------------------------------------------------------------------------
# Match candidate detection
# ---------------------------------------------------------------------------

def find_match_candidates(
    journal_lines: list[str],
    import_txn_date: date,
    import_amount: Decimal | None,
    import_payee: str,
    tracked_ledger_account: str,
) -> list[dict]:
    candidates: list[dict] = []
    starts = [i for i, line in enumerate(journal_lines) if TXN_START_RE.match(line)]

    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(journal_lines)
        txn_lines = journal_lines[start:end]

        if not has_manual_tag(txn_lines):
            continue

        header_match = HEADER_RE.match(txn_lines[0])
        if not header_match:
            continue

        txn_date_str = header_match.group("date").replace("/", "-")
        txn_date = _parse_posted_on(txn_date_str)
        if txn_date is None:
            continue

        txn_payee = header_match.group("payee").strip()

        destination = _parse_manual_entry_destination(txn_lines, tracked_ledger_account)
        if not destination or "Unknown" in destination:
            continue

        manual_amount = _parse_manual_entry_amount(txn_lines, tracked_ledger_account)
        date_diff = abs((import_txn_date - txn_date).days)
        date_in_window = date_diff <= MAX_MANUAL_MATCH_DAYS

        payee_match = False
        if import_payee and txn_payee:
            payee_match = (
                import_payee.lower() in txn_payee.lower()
                or txn_payee.lower() in import_payee.lower()
            )

        exact_amount = (
            import_amount is not None
            and manual_amount is not None
            and abs(import_amount) == abs(manual_amount)
        )
        close_amount = (
            import_amount is not None
            and manual_amount is not None
            and not exact_amount
        )

        if date_in_window and exact_amount:
            tier = 1
        elif date_in_window and close_amount:
            tier = 2
        elif date_in_window and payee_match:
            tier = 3
        elif payee_match:
            tier = 4
        else:
            continue

        candidates.append({
            "manualTxnId": f"manual:{start + 1}",
            "date": txn_date_str,
            "payee": txn_payee,
            "amount": str(manual_amount) if manual_amount is not None else None,
            "destinationAccount": destination,
            "lineStart": start + 1,
            "lineEnd": end,
            "matchTier": tier,
            "matchQuality": TIER_LABELS[tier],
            "dateDiff": date_diff,
        })

    candidates.sort(key=lambda c: (c["matchTier"], c["dateDiff"]))
    return candidates


def populate_match_candidates(
    groups: list[dict],
    journal_path: Path,
    import_accounts: dict[str, dict],
    tracked_accounts: dict[str, dict],
) -> None:
    from .transfer_service import parse_amount as _parse_amount

    import_enabled_tracked_ids = set()
    tracked_ledger_by_id: dict[str, str] = {}
    for tracked_id, tracked_cfg in tracked_accounts.items():
        import_account_id = str(tracked_cfg.get("import_account_id") or "").strip()
        ledger_account = str(tracked_cfg.get("ledger_account") or "").strip()
        if import_account_id:
            import_enabled_tracked_ids.add(tracked_id)
        if ledger_account:
            tracked_ledger_by_id[tracked_id] = ledger_account

    if not import_enabled_tracked_ids or not journal_path.exists():
        return

    journal_lines = journal_path.read_text(encoding="utf-8").splitlines()

    for group in groups:
        source_tracked_id = str(group.get("sourceTrackedAccountId") or "").strip()
        if not source_tracked_id or source_tracked_id not in import_enabled_tracked_ids:
            continue

        tracked_ledger = tracked_ledger_by_id.get(source_tracked_id, "")
        if not tracked_ledger:
            continue

        for txn in group.get("txns", []):
            txn_date_str = str(txn.get("date", "")).strip().replace("/", "-")
            imported_date = _parse_posted_on(txn_date_str)
            if imported_date is None:
                continue

            amount_raw = str(txn.get("amount", "")).strip()
            imported_amount = _parse_amount(amount_raw) if amount_raw else None
            imported_payee = str(group.get("payeeDisplay", "")).strip()

            candidates = find_match_candidates(
                journal_lines, imported_date, imported_amount, imported_payee, tracked_ledger,
            )

            if candidates:
                txn["matchCandidates"] = candidates
                tier_1 = [c for c in candidates if c["matchTier"] == 1]
                if len(tier_1) == 1:
                    txn["suggestedMatchId"] = tier_1[0]["manualTxnId"]


# ---------------------------------------------------------------------------
# Apply match: remove manual entry + carry metadata
# ---------------------------------------------------------------------------

def remove_manual_entry_lines(journal_path: Path, line_start: int, line_end: int) -> bool:
    if not journal_path.exists():
        return False

    lines = journal_path.read_text(encoding="utf-8").splitlines()
    start_idx = line_start - 1
    if start_idx < 0 or line_end > len(lines):
        return False

    txn_lines = lines[start_idx:line_end]
    if not txn_lines or not has_manual_tag(txn_lines):
        return False

    updated = lines[:start_idx] + lines[line_end:]
    while len(updated) >= 2 and not updated[-1].strip() and not updated[-2].strip():
        updated.pop()

    journal_path.write_text("\n".join(updated) + "\n" if updated else "", encoding="utf-8")
    return True


def extract_manual_entry_metadata(
    journal_path: Path, line_start: int, line_end: int, tracked_ledger_account: str,
) -> tuple[str | None, list[str]]:
    if not journal_path.exists():
        return None, []

    lines = journal_path.read_text(encoding="utf-8").splitlines()
    start_idx = line_start - 1
    if start_idx < 0 or line_end > len(lines):
        return None, []

    txn_lines = lines[start_idx:line_end]
    if not txn_lines or not has_manual_tag(txn_lines):
        return None, []

    destination = _parse_manual_entry_destination(txn_lines, tracked_ledger_account)
    user_metadata = _extract_user_metadata_lines(txn_lines)
    return destination, user_metadata
