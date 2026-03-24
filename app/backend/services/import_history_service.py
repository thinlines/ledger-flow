from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .backup_service import backup_file
from .config_service import AppConfig
from .import_index import ImportIndex
from .transfer_service import (
    TRANSFER_MATCH_STATE_PENDING,
    build_import_match_transfer_metadata_updates,
    parse_transfer_metadata,
    upsert_transaction_metadata,
)


APPLIED_STATUS = "applied"
UNDONE_STATUS = "undone"
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")


@dataclass(frozen=True)
class JournalTransaction:
    start: int
    end: int
    source_identity: str | None
    source_payload_hash: str | None
    metadata: dict[str, str]


def history_file_path(config: AppConfig) -> Path:
    return config.imports_dir / "import-log.ndjson"


def ensure_history_file(config: AppConfig) -> Path:
    path = history_file_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    return path


def _read_entries(config: AppConfig) -> list[dict]:
    path = ensure_history_file(config)
    entries: list[dict] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


def _write_entries(config: AppConfig, entries: list[dict]) -> None:
    path = ensure_history_file(config)
    text = "\n".join(json.dumps(entry, sort_keys=True) for entry in entries)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _sort_key(entry: dict) -> str:
    return str(entry.get("appliedAt") or entry.get("createdAt") or "")


def _iter_transaction_ranges(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, line in enumerate(lines) if TXN_START_RE.match(line)]
    ranges: list[tuple[int, int]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        ranges.append((start, end))
    return ranges


def _scan_journal_transactions(lines: list[str]) -> list[JournalTransaction]:
    transactions: list[JournalTransaction] = []
    for start, end in _iter_transaction_ranges(lines):
        source_identity = None
        source_payload_hash = None
        metadata: dict[str, str] = {}
        for line in lines[start + 1:end]:
            match = META_RE.match(line)
            if not match:
                continue
            key = match.group(1).strip().lower()
            value = match.group(2).strip() or None
            if value is not None:
                metadata[key] = value
            if key == "source_identity":
                source_identity = value
            elif key == "source_payload_hash":
                source_payload_hash = value
        transactions.append(
            JournalTransaction(
                start=start,
                end=end,
                source_identity=source_identity,
                source_payload_hash=source_payload_hash,
                metadata=metadata,
            )
        )
    return transactions


def _load_journal_transactions(journal_path: Path) -> tuple[list[str], list[JournalTransaction]]:
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    return lines, _scan_journal_transactions(lines)


def _upsert_transaction_metadata(
    lines: list[str],
    transaction: JournalTransaction,
    updates: dict[str, str | None],
) -> list[str]:
    txn_lines = list(lines[transaction.start:transaction.end])
    txn_lines = upsert_transaction_metadata(txn_lines, updates)
    updated_lines = list(lines)
    updated_lines[transaction.start:transaction.end] = txn_lines
    return updated_lines


def _downgrade_remaining_transfer_peers(lines: list[str], removed_transactions: list[JournalTransaction]) -> list[str]:
    removed_transfer_ids = {
        str(transaction.metadata.get("transfer_id") or "").strip()
        for transaction in removed_transactions
        if str(transaction.metadata.get("transfer_id") or "").strip()
    }
    if not removed_transfer_ids:
        return lines

    updated_lines = list(lines)
    journal_transactions = _scan_journal_transactions(updated_lines)
    for transfer_id in sorted(removed_transfer_ids):
        remaining = [
            transaction
            for transaction in journal_transactions
            if str(transaction.metadata.get("transfer_id") or "").strip() == transfer_id
        ]
        if len(remaining) > 1:
            raise ValueError("Transfer-linked transactions are no longer in a valid state for undo.")
        if len(remaining) != 1:
            continue
        remaining_transfer = parse_transfer_metadata(remaining[0].metadata)
        if remaining_transfer.transfer_id is None or remaining_transfer.peer_account_id is None:
            raise ValueError("Transfer-linked transactions are no longer in a valid state for undo.")
        if not (
            remaining_transfer.is_import_match
            or remaining_transfer.raw_transfer_state in {"pending", "matched"}
        ):
            raise ValueError("Only counterpart-aware transfers can be downgraded during undo.")
        updated_lines = _upsert_transaction_metadata(
            updated_lines,
            remaining[0],
            build_import_match_transfer_metadata_updates(
                transfer_id=remaining_transfer.transfer_id,
                peer_account_id=remaining_transfer.peer_account_id,
                transfer_match_state=TRANSFER_MATCH_STATE_PENDING,
            ),
        )
        journal_transactions = _scan_journal_transactions(updated_lines)

    return updated_lines


def _required_imported_transactions(entry: dict) -> list[tuple[str, str | None]]:
    required: list[tuple[str, str | None]] = []
    for txn in entry.get("importedTransactions", []):
        source_identity = str(txn.get("sourceIdentity") or "").strip()
        if not source_identity:
            continue
        payload_hash_raw = txn.get("sourcePayloadHash")
        payload_hash = str(payload_hash_raw).strip() if payload_hash_raw is not None else None
        required.append((source_identity, payload_hash or None))
    return required


def _match_transactions_for_undo(
    entry: dict,
    journal_transactions: list[JournalTransaction],
) -> tuple[list[JournalTransaction] | None, str | None]:
    required = _required_imported_transactions(entry)
    if not required:
        return [], None

    by_identity: dict[str, list[JournalTransaction]] = {}
    by_identity_and_payload: dict[tuple[str, str | None], list[JournalTransaction]] = {}
    for transaction in journal_transactions:
        if not transaction.source_identity:
            continue
        by_identity.setdefault(transaction.source_identity, []).append(transaction)
        key = (transaction.source_identity, transaction.source_payload_hash)
        by_identity_and_payload.setdefault(key, []).append(transaction)

    used_starts: set[int] = set()
    matches: list[JournalTransaction] = []
    for source_identity, source_payload_hash in required:
        candidates = (
            by_identity_and_payload.get((source_identity, source_payload_hash), [])
            if source_payload_hash is not None
            else by_identity.get(source_identity, [])
        )
        match = next((candidate for candidate in candidates if candidate.start not in used_starts), None)
        if match is None:
            return None, "Some transactions from this import can no longer be identified in the journal."
        used_starts.add(match.start)
        matches.append(match)
    return matches, None


def _undo_state_by_id(config: AppConfig, entries: list[dict]) -> dict[str, tuple[bool, str | None]]:
    journal_cache: dict[str, tuple[list[str], list[JournalTransaction]]] = {}

    states: dict[str, tuple[bool, str | None]] = {}
    for entry in entries:
        entry_id = str(entry["id"])
        if entry.get("status") == UNDONE_STATUS:
            states[entry_id] = (False, "This import was already undone.")
            continue

        journal_path_raw = str(entry.get("targetJournalPath") or "").strip()
        if not journal_path_raw:
            states[entry_id] = (False, "The journal for this import is not available.")
            continue

        journal_path = Path(journal_path_raw)
        if not journal_path.exists():
            states[entry_id] = (False, "The journal for this import is no longer available.")
            continue

        cache_key = str(journal_path.resolve(strict=False))
        if cache_key not in journal_cache:
            journal_cache[cache_key] = _load_journal_transactions(journal_path)

        _, journal_transactions = journal_cache[cache_key]
        _, reason = _match_transactions_for_undo(entry, journal_transactions)
        states[entry_id] = (False, reason) if reason else (True, None)
    return states


def _decorate_entries(config: AppConfig, entries: list[dict]) -> list[dict]:
    undo_state = _undo_state_by_id(config, entries)
    decorated: list[dict] = []
    for entry in sorted(entries, key=_sort_key, reverse=True):
        item = dict(entry)
        can_undo, reason = undo_state.get(str(entry["id"]), (False, "This import cannot be undone."))
        item["canUndo"] = can_undo
        item["undoBlockedReason"] = reason
        decorated.append(item)
    return decorated


def list_import_history(config: AppConfig) -> list[dict]:
    return _decorate_entries(config, _read_entries(config))


def record_applied_import(config: AppConfig, stage: dict) -> dict:
    applied_at = datetime.now(UTC).isoformat()
    imported_transactions = [
        {
            "sourceIdentity": txn.get("sourceIdentity"),
            "sourcePayloadHash": txn.get("sourcePayloadHash"),
            "date": txn.get("date"),
            "payee": txn.get("payee"),
        }
        for txn in stage.get("preparedTransactions", [])
        if txn.get("matchStatus") == "new"
    ]

    result = dict(stage.get("result") or {})
    entry = {
        "id": uuid4().hex,
        "kind": "import",
        "status": APPLIED_STATUS,
        "createdAt": applied_at,
        "appliedAt": applied_at,
        "stageId": stage.get("stageId"),
        "year": stage.get("year"),
        "importAccountId": stage.get("importAccountId"),
        "importAccountDisplayName": stage.get("importAccountDisplayName"),
        "destinationAccount": stage.get("destinationAccount"),
        "importSourceDisplayName": stage.get("importSourceDisplayName"),
        "csvFileName": Path(str(stage.get("csvPath") or "statement.csv")).name,
        "originalCsvPath": stage.get("csvPath"),
        "archivedCsvPath": result.get("archivedCsvPath"),
        "targetJournalPath": stage.get("targetJournalPath"),
        "backupPath": result.get("backupPath"),
        "sourceFileSha256": stage.get("sourceFileSha256"),
        "summary": dict(stage.get("summary") or {}),
        "result": result,
        "importedTransactions": imported_transactions,
    }

    entries = _read_entries(config)
    entries.append(entry)
    _write_entries(config, entries)
    decorated = _decorate_entries(config, entries)
    return next(item for item in decorated if str(item["id"]) == entry["id"])


def _restore_archived_csv_to_inbox(config: AppConfig, entry: dict) -> tuple[str | None, str | None]:
    original_csv = str(entry.get("originalCsvPath") or "").strip()
    archived_csv = str(entry.get("archivedCsvPath") or "").strip()
    if not original_csv:
        return None, None

    original_path = Path(original_csv)
    inbox_root = config.csv_dir.resolve(strict=False)
    if not original_path.resolve(strict=False).is_relative_to(inbox_root):
        return None, None
    if original_path.exists():
        return str(original_path.resolve(strict=False)), None
    if not archived_csv:
        return None, None

    archived_path = Path(archived_csv)
    if not archived_path.exists():
        return None, "Archived source CSV is missing, so it could not be restored to the inbox."

    original_path.parent.mkdir(parents=True, exist_ok=True)
    archived_path.replace(original_path)
    return str(original_path.resolve(strict=False)), None


def undo_import(config: AppConfig, history_id: str) -> dict:
    entries = _read_entries(config)
    entry = next((item for item in entries if str(item.get("id")) == history_id), None)
    if entry is None:
        raise KeyError(history_id)

    undo_state = _undo_state_by_id(config, entries)
    can_undo, reason = undo_state.get(history_id, (False, "This import cannot be undone."))
    if not can_undo:
        raise ValueError(reason or "This import cannot be undone.")

    journal_path = Path(str(entry["targetJournalPath"]))
    lines, journal_transactions = _load_journal_transactions(journal_path)
    matched_transactions, reason = _match_transactions_for_undo(entry, journal_transactions)
    if matched_transactions is None:
        raise ValueError(reason or "This import cannot be undone.")

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    undo_backup = backup_file(journal_path, "undo") if journal_path.exists() else None
    ranges = sorted((transaction.start, transaction.end) for transaction in matched_transactions)
    kept_lines: list[str] = []
    cursor = 0
    for start, end in ranges:
        kept_lines.extend(lines[cursor:start])
        cursor = end
    kept_lines.extend(lines[cursor:])
    kept_lines = _downgrade_remaining_transfer_peers(kept_lines, matched_transactions)
    if kept_lines:
        journal_path.write_text("\n".join(kept_lines).rstrip() + "\n", encoding="utf-8")
    else:
        journal_path.write_text("", encoding="utf-8")

    source_identities = [
        str(txn["sourceIdentity"])
        for txn in entry.get("importedTransactions", [])
        if txn.get("sourceIdentity")
    ]
    ImportIndex(config.root_dir / ".workflow" / "state.db").delete_transactions(
        str(entry["importAccountId"]),
        source_identities,
    )

    restored_csv_path, source_csv_warning = _restore_archived_csv_to_inbox(config, entry)
    entry["status"] = UNDONE_STATUS
    entry["undo"] = {
        "undoneAt": datetime.now(UTC).isoformat(),
        "undoBackupPath": str(undo_backup.resolve(strict=False)) if undo_backup is not None else None,
        "restoredInboxCsvPath": restored_csv_path,
        "removedTxnCount": len(matched_transactions),
        "sourceCsvWarning": source_csv_warning,
    }

    _write_entries(config, entries)
    decorated = _decorate_entries(config, entries)
    return next(item for item in decorated if str(item["id"]) == history_id)
