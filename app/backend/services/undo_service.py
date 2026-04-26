"""Semantic undo for journal mutations via compensating events.

Dispatches on the forward event type, verifies journal hashes have not drifted,
applies the inverse mutation, and writes a compensating event linked back to
the original.

Journals remain the canonical source of truth — undo writes journals and records
the change in the event log.  The event log is never rewritten.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from services.archive_service import archive_manual_entry
from services.backup_service import backup_file
from services.event_log_service import emit_event, hash_file, read_events, rel_path
from services.header_parser import TransactionStatus, parse_header, set_header_status
from services.journal_block_service import (
    AmbiguousHeaderError,
    HeaderNotFoundError,
    find_transaction_block,
    locate_header,
)
from services.journal_query_service import TXN_START_RE
from services.transfer_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE, rewrite_posting_account

logger = logging.getLogger(__name__)

# Mirrors the regex in main.py; duplicated to keep services free of FastAPI deps.
_NOTES_RE = re.compile(r"^(\s*;\s*)notes:\s*(.*)$")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class UndoOutcome(str, Enum):
    SUCCESS = "success"
    DRIFT = "drift"
    NOT_FOUND = "not_found"
    ALREADY_COMPENSATED = "already_compensated"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass(frozen=True)
class UndoResult:
    outcome: UndoOutcome
    message: str
    compensating_event_id: str | None
    forward_event_id: str


class UndoFailedError(Exception):
    """Raised by a handler when the inverse mutation cannot be applied cleanly."""


# Type alias for handler callables.
HandlerFn = Callable[[Path, dict], dict[str, str]]


# ---------------------------------------------------------------------------
# Event log helpers
# ---------------------------------------------------------------------------


def _find_event(events: list[dict], event_id: str) -> dict | None:
    for event in events:
        if event.get("id") == event_id:
            return event
    return None


def _is_compensated(events: list[dict], event_id: str) -> str | None:
    """Return the compensating event id if *event_id* has already been undone."""
    for event in events:
        if event.get("compensates") == event_id:
            return event.get("id")
    return None


# ---------------------------------------------------------------------------
# Undo dispatcher
# ---------------------------------------------------------------------------


def undo_event(workspace_path: Path, event_id: str) -> UndoResult:
    """Attempt to undo the event identified by *event_id*.

    Returns an :class:`UndoResult` describing the outcome.
    """
    events = read_events(workspace_path)

    # 1. Locate the forward event.
    forward = _find_event(events, event_id)
    if forward is None:
        return UndoResult(UndoOutcome.NOT_FOUND, "Event not found", None, event_id)

    # 2. Idempotency check.
    existing = _is_compensated(events, event_id)
    if existing is not None:
        return UndoResult(
            UndoOutcome.ALREADY_COMPENSATED,
            "Already undone",
            existing,
            event_id,
        )

    # 3. Dispatch table lookup.
    event_type = forward.get("type", "")
    handler = _HANDLERS.get(event_type)
    if handler is None:
        return UndoResult(
            UndoOutcome.UNSUPPORTED,
            f"Undo not supported for event type: {event_type}",
            None,
            event_id,
        )

    # 4. Drift verification.
    for ref in forward.get("journal_refs", []):
        ref_path = ref.get("path", "")
        expected_hash = ref.get("hash_after")
        if not ref_path or not expected_hash:
            continue
        full_path = workspace_path / ref_path
        current_hash = hash_file(full_path)
        if current_hash != expected_hash:
            return UndoResult(
                UndoOutcome.DRIFT,
                f"File changed since the action: {ref_path}",
                None,
                event_id,
            )

    # 5. Apply the compensating action.
    try:
        new_hashes = handler(workspace_path, forward)
    except UndoFailedError as exc:
        return UndoResult(UndoOutcome.FAILED, str(exc), None, event_id)

    # 6. Emit the compensating event.
    journal_refs = []
    for ref in forward.get("journal_refs", []):
        ref_path = ref.get("path", "")
        if ref_path and ref_path in new_hashes:
            journal_refs.append({
                "path": ref_path,
                "hash_before": ref.get("hash_after"),  # Our "before" is the forward's "after".
                "hash_after": new_hashes[ref_path],
            })

    forward_summary = forward.get("summary", "")
    compensating_id = emit_event(
        workspace_path,
        event_type=f"{event_type}.compensated.v1",
        summary=f"Undid: {forward_summary}",
        payload={**forward.get("payload", {}), "compensated_event_id": event_id},
        journal_refs=journal_refs,
        compensates=event_id,
    )

    return UndoResult(
        UndoOutcome.SUCCESS,
        f"Undid: {forward_summary}",
        compensating_id,
        event_id,
    )


# ---------------------------------------------------------------------------
# Compensating-action handlers
# ---------------------------------------------------------------------------


def _undo_transaction_deleted(workspace_path: Path, event: dict) -> dict[str, str]:
    """Restore a deleted transaction block at the correct date-ordered position."""
    payload = event.get("payload", {})
    journal_rel = payload.get("journal_path", "")
    header_line = payload.get("header_line", "")
    deleted_block = payload.get("deleted_block", "")

    if not journal_rel or not deleted_block:
        raise UndoFailedError("Incomplete event payload — missing journal_path or deleted_block")

    journal_path = workspace_path / journal_rel

    # Safety: refuse if a transaction with the same header already exists.
    text = journal_path.read_text(encoding="utf-8") if journal_path.is_file() else ""
    lines = text.splitlines()
    if header_line and any(line == header_line for line in lines):
        raise UndoFailedError("Transaction was re-created — refusing to duplicate")

    backup_file(journal_path, "undo")

    # Parse the date from the header line for insertion ordering.
    restored_date = header_line[:10] if header_line else ""
    restored_lines = deleted_block.splitlines()

    # Find insertion point: after the last transaction with date <= restored_date.
    insert_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if TXN_START_RE.match(lines[i]) and lines[i][:10] <= restored_date:
            # Find end of this block to insert after it.
            end_i = i + 1
            while end_i < len(lines):
                if TXN_START_RE.match(lines[end_i]):
                    break
                end_i += 1
            insert_idx = end_i
            break

    # Insert with a blank line separator.
    insert_block = [""] + restored_lines if insert_idx > 0 else restored_lines
    lines[insert_idx:insert_idx] = insert_block

    journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") or not text else "\n"), encoding="utf-8")

    return {journal_rel: hash_file(journal_path)}


def _undo_transaction_recategorized(workspace_path: Path, event: dict) -> dict[str, str]:
    """Restore the previous category account on a recategorized transaction."""
    payload = event.get("payload", {})
    journal_rel = payload.get("journal_path", "")
    header_line = payload.get("header_line", "")
    previous_account = payload.get("previous_account", "")
    new_account = payload.get("new_account", "Expenses:Unknown")

    if not journal_rel or not header_line or not previous_account:
        raise UndoFailedError("Incomplete event payload")

    journal_path = workspace_path / journal_rel
    text = journal_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    try:
        header_idx = locate_header(lines, header_line)
    except (HeaderNotFoundError, AmbiguousHeaderError) as exc:
        raise UndoFailedError(str(exc)) from exc

    block_start, block_end = find_transaction_block(lines, header_idx)

    backup_file(journal_path, "undo")

    # Find the posting with new_account and rewrite it back.
    found = False
    for i in range(block_start + 1, block_end):
        stripped = lines[i].strip()
        if stripped.startswith(";") or stripped == "":
            continue
        m = ACCOUNT_LINE_RE.match(lines[i]) or ACCOUNT_ONLY_RE.match(lines[i])
        if m and m.group(2).strip() == new_account:
            new_line, changed = rewrite_posting_account(lines[i], previous_account)
            if changed:
                lines[i] = new_line
                found = True
                break

    if not found:
        raise UndoFailedError(f"Destination account {new_account} not found on transaction")

    journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    return {journal_rel: hash_file(journal_path)}


def _undo_transaction_status_toggled(workspace_path: Path, event: dict) -> dict[str, str]:
    """Restore the previous clearing status on a toggled transaction."""
    payload = event.get("payload", {})
    journal_rel = payload.get("journal_path", "")
    header_line = payload.get("header_line", "")
    previous_status_str = payload.get("previous_status", "")

    if not journal_rel or not header_line or not previous_status_str:
        raise UndoFailedError("Incomplete event payload")

    journal_path = workspace_path / journal_rel
    text = journal_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # The header line in the file is now the *new* header (post-toggle).
    # We need to find it. The event's header_line is the *original* (pre-toggle).
    # Reconstruct the current header by applying the forward toggle.
    new_status_str = payload.get("new_status", "")
    try:
        new_status = TransactionStatus(new_status_str)
    except ValueError as exc:
        raise UndoFailedError(f"Invalid new_status in event: {new_status_str}") from exc

    current_header = set_header_status(header_line, new_status)

    try:
        header_idx = locate_header(lines, current_header)
    except (HeaderNotFoundError, AmbiguousHeaderError) as exc:
        raise UndoFailedError(str(exc)) from exc

    backup_file(journal_path, "undo")

    try:
        previous_status = TransactionStatus(previous_status_str)
    except ValueError as exc:
        raise UndoFailedError(f"Invalid previous_status in event: {previous_status_str}") from exc

    restored_line = set_header_status(current_header, previous_status)
    lines[header_idx] = restored_line
    journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    return {journal_rel: hash_file(journal_path)}


def _undo_manual_entry_created(workspace_path: Path, event: dict) -> dict[str, str]:
    """Delete the manual entry that was created."""
    payload = event.get("payload", {})
    date = payload.get("date", "")
    payee = payload.get("payee", "")

    if not date or not payee:
        raise UndoFailedError("Incomplete event payload — missing date or payee")

    # Manual entries use "/" date separators in the header (see manual_entry_service).
    date_formatted = date.replace("-", "/")
    expected_header = f"{date_formatted} {payee}"

    # Determine journal path from journal_refs.
    refs = event.get("journal_refs", [])
    if not refs:
        raise UndoFailedError("No journal_refs in event")
    journal_rel = refs[0].get("path", "")
    if not journal_rel:
        raise UndoFailedError("Empty journal path in refs")

    journal_path = workspace_path / journal_rel
    text = journal_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    try:
        header_idx = locate_header(lines, expected_header)
    except (HeaderNotFoundError, AmbiguousHeaderError) as exc:
        raise UndoFailedError(f"Could not locate the manual entry to undo: {exc}") from exc

    block_start, block_end = find_transaction_block(lines, header_idx)

    backup_file(journal_path, "undo")

    # Consume a preceding blank line to avoid double-blank-line gaps.
    remove_start = block_start
    if remove_start > 0 and lines[remove_start - 1].strip() == "":
        remove_start -= 1
    new_lines = lines[:remove_start] + lines[block_end:]

    journal_path.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    return {journal_rel: hash_file(journal_path)}


def _undo_transaction_unmatched(workspace_path: Path, event: dict) -> dict[str, str]:
    """Re-create the match that was undone: re-stamp the imported transaction,
    remove the restored manual entry from the main journal, and re-archive it.
    """
    payload = event.get("payload", {})
    journal_rel = payload.get("journal_path", "")
    archive_rel = payload.get("archive_path", "")
    header_line = payload.get("header_line", "")
    match_id = payload.get("match_id", "")
    restored_manual_block = payload.get("restored_manual_block", "")

    if not journal_rel or not header_line or not match_id or not restored_manual_block:
        raise UndoFailedError("Incomplete event payload")

    journal_path = workspace_path / journal_rel
    archive_path = workspace_path / archive_rel if archive_rel else workspace_path / "journals" / "archived-manual.journal"

    # Parse the restored manual block to recover the category account.
    manual_lines = restored_manual_block.splitlines()
    manual_category: str | None = None
    for ml in manual_lines:
        stripped = ml.strip()
        if stripped.startswith(";") or stripped == "" or TXN_START_RE.match(stripped):
            continue
        m = ACCOUNT_LINE_RE.match(ml) or ACCOUNT_ONLY_RE.match(ml)
        if m:
            acct = m.group(2).strip()
            # Skip the source (tracked) account — we want the destination category.
            # Heuristic: category accounts start with Expenses: or Income:.
            if acct.startswith("Expenses:") or acct.startswith("Income:") or acct.startswith("Revenue:"):
                manual_category = acct
                break

    if not manual_category:
        raise UndoFailedError("Could not determine category from restored manual block")

    # --- Backup both files ---
    backup_file(journal_path, "undo")
    if archive_path.is_file():
        backup_file(archive_path, "undo")

    # --- Step 1: Re-stamp the imported transaction in the main journal ---
    text = journal_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    try:
        header_idx = locate_header(lines, header_line)
    except (HeaderNotFoundError, AmbiguousHeaderError) as exc:
        raise UndoFailedError(f"Could not locate imported transaction: {exc}") from exc

    block_start, block_end = find_transaction_block(lines, header_idx)

    # Insert :manual: and match-id: tags after the header (same order as unknowns_service).
    # Process in reverse so indices stay valid: match-id first, then :manual:.
    lines.insert(block_start + 1, f"    ; match-id: {match_id}")
    lines.insert(block_start + 1, "    ; :manual:")
    # block_end shifted by 2 due to insertions.
    block_end += 2

    # Rewrite destination posting from Expenses:Unknown to the original category.
    for i in range(block_start + 3, block_end):  # +3 to skip header + two new tag lines.
        stripped = lines[i].strip()
        if stripped.startswith(";") or stripped == "":
            continue
        m = ACCOUNT_LINE_RE.match(lines[i]) or ACCOUNT_ONLY_RE.match(lines[i])
        if m and m.group(2).strip() == "Expenses:Unknown":
            new_line, changed = rewrite_posting_account(lines[i], manual_category)
            if changed:
                lines[i] = new_line
            break

    # --- Step 2: Find and remove the restored manual entry from the main journal ---
    # The manual entry was inserted by the original unmatch. Its header is the
    # first line of restored_manual_block, and it does NOT have the match-id tag
    # (the tag was stripped during the unmatch).
    manual_header = manual_lines[0] if manual_lines else ""
    manual_entry_idx: int | None = None
    for i, line in enumerate(lines):
        if line == manual_header and i != header_idx:
            # Verify it's a plausible match by checking for the manual tag.
            if i + 1 < len(lines) and ":manual:" in lines[i + 1]:
                manual_entry_idx = i
                break

    if manual_entry_idx is None:
        raise UndoFailedError("Could not locate restored manual entry in journal")

    manual_block_start, manual_block_end = find_transaction_block(lines, manual_entry_idx)
    # Consume a preceding blank line.
    remove_start = manual_block_start
    if remove_start > 0 and lines[remove_start - 1].strip() == "":
        remove_start -= 1
    lines = lines[:remove_start] + lines[manual_block_end:]

    journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    # --- Step 3: Re-archive the manual entry ---
    # Use the original block lines (without the match-id tag that archive_manual_entry adds).
    # archive_manual_entry inserts the match-id tag itself on the second line.
    block_for_archive = [l for l in manual_lines if l.strip() != f"; match-id: {match_id}"]
    archive_manual_entry(archive_path, match_id, block_for_archive)

    # --- Return hashes ---
    result: dict[str, str] = {journal_rel: hash_file(journal_path)}
    if archive_path.is_file():
        result[rel_path(archive_path, workspace_path)] = hash_file(archive_path)
    return result


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

def _undo_transaction_notes_updated(workspace_path: Path, event: dict) -> dict[str, str]:
    """Restore the previous notes value (or absence) on a transaction."""
    payload = event.get("payload", {})
    journal_rel = payload.get("journal_path", "")
    header_line = payload.get("header_line", "")

    if "previous_notes" not in payload:
        # Pre-migration event: no captured prior value, no safe inverse.
        raise UndoFailedError(
            "Pre-existing notes event lacks previous_notes — cannot undo"
        )

    previous_notes = payload.get("previous_notes", "") or ""

    if not journal_rel or not header_line:
        raise UndoFailedError("Incomplete event payload")

    journal_path = workspace_path / journal_rel
    text = journal_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    try:
        header_idx = locate_header(lines, header_line)
    except (HeaderNotFoundError, AmbiguousHeaderError) as exc:
        raise UndoFailedError(str(exc)) from exc

    block_start, block_end = find_transaction_block(lines, header_idx)

    backup_file(journal_path, "undo")

    # Find the current notes line in the block (post-forward-write state).
    notes_idx: int | None = None
    for i in range(block_start + 1, block_end):
        if _NOTES_RE.match(lines[i]):
            notes_idx = i
            break

    if previous_notes:
        restored_line = f"    ; notes: {previous_notes}"
        if notes_idx is not None:
            lines[notes_idx] = restored_line
        else:
            # Forward write deleted the line — re-insert at the same position
            # the forward path would have used (immediately after the header).
            lines.insert(block_start + 1, restored_line)
    else:
        # No prior notes line existed — remove the one the forward write added.
        if notes_idx is not None:
            del lines[notes_idx]

    journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    return {journal_rel: hash_file(journal_path)}


_HANDLERS: dict[str, HandlerFn] = {
    "transaction.deleted.v1": _undo_transaction_deleted,
    "transaction.recategorized.v1": _undo_transaction_recategorized,
    "transaction.status_toggled.v1": _undo_transaction_status_toggled,
    "manual_entry.created.v1": _undo_manual_entry_created,
    "transaction.unmatched.v1": _undo_transaction_unmatched,
    "transaction.notes_updated.v1": _undo_transaction_notes_updated,
}


def is_undoable_type(event_type: str) -> bool:
    """True iff a forward event of *event_type* has a registered undo handler."""
    return event_type in _HANDLERS
