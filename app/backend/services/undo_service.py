"""Semantic undo for journal mutations via compensating events.

Dispatches on the forward event type, locates the target transaction by the
``txn_id`` recorded in the forward payload (spec: Mutation-Time Projection),
verifies the transaction still holds the state the forward action produced,
applies the inverse mutation, and writes a compensating event linked back to
the original.

Staleness is judged per transaction, not per file: an unrelated later edit
to the same journal no longer blocks undo. A conflicting edit to the target
transaction fails the handler's semantic precondition instead.

Journals remain the canonical source of truth — undo writes journals and records
the change in the event log.  The event log is never rewritten.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from services import journal_writer
from services.archive_service import archive_manual_entry
from services.config_service import AppConfig
from services.event_log_service import hash_file, read_events
from services.header_parser import TransactionStatus, set_header_status
from services.journal_block_service import find_transaction_block
from services.journal_query_service import TXN_START_RE
from services.projection_service import (
    ProjectedTransactionRef,
    find_projected_transaction,
    refresh_projection,
)
from services.operations_service import list_operations, operation_is_compensated
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


# Handler protocol: handlers take ``(config, event)`` and own emission via
# ``journal_writer.mutate``; they return the compensating event id.
HandlerFn = Callable[[AppConfig, dict], str]


# Matches the migration/minting line shape: ``    ; lf_txn_id: txn_...``.
_LF_TXN_ID_META_RE = re.compile(r"^\s*;\s*lf_txn_id:\s*(\S+)\s*$")


def _payload_txn_id(payload: dict) -> str:
    txn_id = str(payload.get("txn_id") or "").strip()
    if not txn_id:
        raise UndoFailedError(
            "Event lacks txn_id (predates stable identity) — cannot undo"
        )
    return txn_id


def _locate_projected(config: AppConfig, txn_id: str) -> ProjectedTransactionRef:
    """Locate the target transaction through a fresh projection."""
    refresh_projection(config)
    ref = find_projected_transaction(config, txn_id)
    if ref is None:
        raise UndoFailedError("Transaction no longer exists — cannot undo")
    return ref


def _header_index(lines: list[str], ref: ProjectedTransactionRef) -> int:
    """The projected header position, re-checked against the file bytes."""
    header_idx = ref.source_start_line - 1
    if header_idx >= len(lines) or lines[header_idx] != ref.raw_header:
        raise UndoFailedError("This transaction changed since the action — cannot undo")
    return header_idx


def _block_txn_id(block_text: str) -> str | None:
    for line in block_text.splitlines():
        match = _LF_TXN_ID_META_RE.match(line)
        if match:
            return match.group(1)
    return None


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


def _read_history(config: AppConfig) -> list[dict]:
    operations = list(reversed(list_operations(config)))
    legacy = read_events(config.root_dir)
    seen = {str(event.get("id")) for event in legacy}
    return legacy + [operation for operation in operations if str(operation.get("id")) not in seen]


def _has_file_drift(config: AppConfig, event: dict) -> bool:
    for file_ref in event.get("files") or event.get("journal_refs") or []:
        path = str(file_ref.get("path") or "").strip()
        expected = str(file_ref.get("hash_after") or "").strip()
        if not path or not expected:
            continue
        if hash_file(config.root_dir / path) != expected:
            return True
    return False


# ---------------------------------------------------------------------------
# Undo dispatcher
# ---------------------------------------------------------------------------


def undo_event(config: AppConfig, event_id: str) -> UndoResult:
    """Attempt to undo the event identified by *event_id*.

    Returns an :class:`UndoResult` describing the outcome.
    """
    workspace_path = config.root_dir
    events = _read_history(config)

    # 1. Locate the forward event.
    forward = _find_event(events, event_id)
    if forward is None:
        return UndoResult(UndoOutcome.NOT_FOUND, "Event not found", None, event_id)

    # 2. Idempotency check.
    existing = operation_is_compensated(config, event_id) or _is_compensated(events, event_id)
    if existing is not None:
        return UndoResult(
            UndoOutcome.ALREADY_COMPENSATED,
            "Already undone",
            existing,
            event_id,
        )

    if _has_file_drift(config, forward):
        return UndoResult(
            UndoOutcome.DRIFT,
            "Affected file changed since this operation — cannot undo",
            None,
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

    # 4. Apply the compensating action. Handlers own per-transaction
    # staleness (locate by txn_id, verify the forward state still holds)
    # and emission via journal_writer.
    forward_summary = forward.get("summary", "")
    try:
        compensating_id = handler(config, forward)
    except UndoFailedError as exc:
        return UndoResult(UndoOutcome.FAILED, str(exc), None, event_id)

    return UndoResult(
        UndoOutcome.SUCCESS,
        f"Undid: {forward_summary}",
        compensating_id,
        event_id,
    )


# ---------------------------------------------------------------------------
# Compensating-action handlers
# ---------------------------------------------------------------------------


def _undo_transaction_deleted(config: AppConfig, event: dict) -> str:
    """Restore a deleted transaction block at the correct date-ordered position.

    Routed through ``journal_writer.mutate`` — the writer owns backup, hashing,
    rollback, and emission of the compensating event.
    """
    workspace_path = config.root_dir
    payload = event.get("payload", {})
    journal_rel = payload.get("journal_path", "")
    header_line = payload.get("header_line", "")
    deleted_block = payload.get("deleted_block", "")
    forward_event_id = event.get("id", "")
    forward_summary = event.get("summary", "")
    forward_type = event.get("type", "")

    if not journal_rel or not deleted_block:
        raise UndoFailedError("Incomplete event payload — missing journal_path or deleted_block")

    journal_path = workspace_path / journal_rel

    # Safety: refuse if the deleted transaction already exists again. The
    # block's own lf_txn_id is the reliable signal; header-text equality is
    # the fallback for blocks that never carried one.
    deleted_txn_id = _block_txn_id(deleted_block)
    if deleted_txn_id is not None:
        refresh_projection(config)
        if find_projected_transaction(config, deleted_txn_id) is not None:
            raise UndoFailedError("Transaction was re-created — refusing to duplicate")
    else:
        text = journal_path.read_text(encoding="utf-8") if journal_path.is_file() else ""
        if header_line and any(line == header_line for line in text.splitlines()):
            raise UndoFailedError("Transaction was re-created — refusing to duplicate")

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="undo",
        event_type=f"{forward_type}.compensated.v1",
    ) as mut:
        # Re-read inside the block so the writer's pre-mutation hash sees what
        # we are about to write against.
        text = journal_path.read_text(encoding="utf-8") if journal_path.is_file() else ""
        lines = text.splitlines()

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

        journal_path.write_text(
            "\n".join(lines) + ("\n" if text.endswith("\n") or not text else "\n"),
            encoding="utf-8",
        )

        mut.summary = f"Undid: {forward_summary}"
        mut.payload = {**payload, "compensated_event_id": forward_event_id}
        mut.compensates = forward_event_id

    return mut.event_id


def _undo_transaction_recategorized(config: AppConfig, event: dict) -> str:
    """Restore the previous category account on a recategorized transaction.

    Routed through ``journal_writer.mutate`` — the writer owns backup, hashing,
    rollback, and emission of the compensating event.
    """
    workspace_path = config.root_dir
    payload = event.get("payload", {})
    previous_account = payload.get("previous_account", "")
    new_account = payload.get("new_account", "Expenses:Unknown")
    forward_event_id = event.get("id", "")
    forward_summary = event.get("summary", "")
    forward_type = event.get("type", "")

    if not previous_account:
        raise UndoFailedError("Incomplete event payload")

    ref = _locate_projected(config, _payload_txn_id(payload))
    journal_path = workspace_path / ref.journal_path

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="undo",
        event_type=f"{forward_type}.compensated.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        header_idx = _header_index(lines, ref)
        block_start, block_end = find_transaction_block(lines, header_idx)

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

        mut.summary = f"Undid: {forward_summary}"
        mut.payload = {**payload, "compensated_event_id": forward_event_id}
        mut.compensates = forward_event_id

    return mut.event_id


def _undo_transaction_account_reassigned(config: AppConfig, event: dict) -> str:
    """Restore the previous source account on a reassigned transaction.

    Routed through ``journal_writer.mutate`` — the writer owns backup, hashing,
    rollback, and emission of the compensating event.
    """
    workspace_path = config.root_dir
    payload = event.get("payload", {})
    previous_account = payload.get("previous_account", "")
    new_account = payload.get("new_account", "")
    forward_event_id = event.get("id", "")
    forward_summary = event.get("summary", "")
    forward_type = event.get("type", "")

    if not previous_account:
        raise UndoFailedError("Incomplete event payload")

    ref = _locate_projected(config, _payload_txn_id(payload))
    journal_path = workspace_path / ref.journal_path

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="undo",
        event_type=f"{forward_type}.compensated.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        header_idx = _header_index(lines, ref)
        block_start, block_end = find_transaction_block(lines, header_idx)

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
            raise UndoFailedError(f"Source account {new_account} not found on transaction")

        journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

        mut.summary = f"Undid: {forward_summary}"
        mut.payload = {**payload, "compensated_event_id": forward_event_id}
        mut.compensates = forward_event_id

    return mut.event_id


def _undo_transaction_status_toggled(config: AppConfig, event: dict) -> str:
    """Restore the previous clearing status on a toggled transaction.

    Routed through ``journal_writer.mutate`` — the writer owns backup, hashing,
    rollback, and emission of the compensating event.
    """
    workspace_path = config.root_dir
    payload = event.get("payload", {})
    previous_status_str = payload.get("previous_status", "")
    new_status_str = payload.get("new_status", "")
    forward_event_id = event.get("id", "")
    forward_summary = event.get("summary", "")
    forward_type = event.get("type", "")

    if not previous_status_str:
        raise UndoFailedError("Incomplete event payload")

    try:
        previous_status = TransactionStatus(previous_status_str)
    except ValueError as exc:
        raise UndoFailedError(f"Invalid previous_status in event: {previous_status_str}") from exc

    ref = _locate_projected(config, _payload_txn_id(payload))
    # Semantic staleness gate: the transaction must still hold the status
    # the forward toggle produced; a later toggle supersedes this event.
    if ref.status != new_status_str:
        raise UndoFailedError(
            "Transaction status changed since this action — undo the later change first"
        )
    journal_path = workspace_path / ref.journal_path

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="undo",
        event_type=f"{forward_type}.compensated.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        header_idx = _header_index(lines, ref)
        restored_line = set_header_status(ref.raw_header, previous_status)
        lines[header_idx] = restored_line
        journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

        mut.summary = f"Undid: {forward_summary}"
        mut.payload = {**payload, "compensated_event_id": forward_event_id}
        mut.compensates = forward_event_id

    return mut.event_id


def _undo_manual_entry_created(config: AppConfig, event: dict) -> str:
    """Delete the manual entry that was created.

    Routed through ``journal_writer.mutate`` — the writer owns backup, hashing,
    rollback, and emission of the compensating event.
    """
    workspace_path = config.root_dir
    payload = event.get("payload", {})
    forward_event_id = event.get("id", "")
    forward_summary = event.get("summary", "")
    forward_type = event.get("type", "")

    ref = _locate_projected(config, _payload_txn_id(payload))
    journal_path = workspace_path / ref.journal_path

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="undo",
        event_type=f"{forward_type}.compensated.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        header_idx = _header_index(lines, ref)
        block_start, block_end = find_transaction_block(lines, header_idx)

        # Consume a preceding blank line to avoid double-blank-line gaps.
        remove_start = block_start
        if remove_start > 0 and lines[remove_start - 1].strip() == "":
            remove_start -= 1
        new_lines = lines[:remove_start] + lines[block_end:]

        journal_path.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

        mut.summary = f"Undid: {forward_summary}"
        mut.payload = {**payload, "compensated_event_id": forward_event_id}
        mut.compensates = forward_event_id

    return mut.event_id


def _undo_transaction_unmatched(config: AppConfig, event: dict) -> str:
    """Re-create the match that was undone: re-stamp the imported transaction,
    remove the restored manual entry from the main journal, and re-archive it.

    Routed through ``journal_writer.mutate`` — the writer owns backup, hashing,
    rollback, and emission of the compensating event across both files.
    """
    workspace_path = config.root_dir
    payload = event.get("payload", {})
    archive_rel = payload.get("archive_path", "")
    match_id = payload.get("match_id", "")
    restored_manual_block = payload.get("restored_manual_block", "")
    forward_event_id = event.get("id", "")
    forward_summary = event.get("summary", "")
    forward_type = event.get("type", "")

    if not match_id or not restored_manual_block:
        raise UndoFailedError("Incomplete event payload")

    ref = _locate_projected(config, _payload_txn_id(payload))
    journal_path = workspace_path / ref.journal_path
    archive_path = workspace_path / archive_rel if archive_rel else workspace_path / "journals" / "archived-manual.journal"

    # The restored manual entry carries its own identity; locate it through
    # the same fresh projection instead of scanning for header text.
    manual_txn_id = _block_txn_id(restored_manual_block)
    manual_ref = (
        find_projected_transaction(config, manual_txn_id)
        if manual_txn_id is not None
        else None
    )

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

    with journal_writer.mutate(
        config=config,
        paths=[journal_path, archive_path],
        tag="undo",
        event_type=f"{forward_type}.compensated.v1",
    ) as mut:
        # --- Step 1: Re-stamp the imported transaction in the main journal ---
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        header_idx = _header_index(lines, ref)
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
        # The manual entry was inserted by the original unmatch. Prefer its
        # projected identity; fall back to a header scan for blocks that
        # never carried an lf_txn_id. Step 1 inserted two tag lines, so any
        # projected position after the imported header has shifted by two.
        manual_header = manual_lines[0] if manual_lines else ""
        manual_entry_idx: int | None = None
        if manual_ref is not None and manual_ref.journal_path == ref.journal_path:
            candidate_idx = manual_ref.source_start_line - 1
            if candidate_idx > header_idx:
                candidate_idx += 2
            if candidate_idx < len(lines) and lines[candidate_idx] == manual_ref.raw_header:
                manual_entry_idx = candidate_idx
        if manual_entry_idx is None:
            for i, line in enumerate(lines):
                if line == manual_header and i != header_idx:
                    # Verify it's a plausible match by checking for the manual tag.
                    block_head = "\n".join(lines[i : i + 3])
                    if ":manual:" in block_head:
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

        mut.summary = f"Undid: {forward_summary}"
        mut.payload = {**payload, "compensated_event_id": forward_event_id}
        mut.compensates = forward_event_id

    return mut.event_id


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

def _undo_transaction_notes_updated(config: AppConfig, event: dict) -> str:
    """Restore the previous notes value (or absence) on a transaction.

    Routed through ``journal_writer.mutate`` — the writer owns backup, hashing,
    rollback, and emission of the compensating event.
    """
    workspace_path = config.root_dir
    payload = event.get("payload", {})
    forward_event_id = event.get("id", "")
    forward_summary = event.get("summary", "")
    forward_type = event.get("type", "")

    if "previous_notes" not in payload:
        # Pre-migration event: no captured prior value, no safe inverse.
        raise UndoFailedError(
            "Pre-existing notes event lacks previous_notes — cannot undo"
        )

    previous_notes = payload.get("previous_notes", "") or ""

    ref = _locate_projected(config, _payload_txn_id(payload))
    journal_path = workspace_path / ref.journal_path

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="undo",
        event_type=f"{forward_type}.compensated.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        header_idx = _header_index(lines, ref)
        block_start, block_end = find_transaction_block(lines, header_idx)

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

        mut.summary = f"Undid: {forward_summary}"
        mut.payload = {**payload, "compensated_event_id": forward_event_id}
        mut.compensates = forward_event_id

    return mut.event_id


_HANDLERS: dict[str, HandlerFn] = {
    "transaction.deleted.v1": _undo_transaction_deleted,
    "transaction.recategorized.v1": _undo_transaction_recategorized,
    "transaction.account_reassigned.v1": _undo_transaction_account_reassigned,
    "transaction.status_toggled.v1": _undo_transaction_status_toggled,
    "manual_entry.created.v1": _undo_manual_entry_created,
    "transaction.unmatched.v1": _undo_transaction_unmatched,
    "transaction.notes_updated.v1": _undo_transaction_notes_updated,
}


def is_undoable_type(event_type: str) -> bool:
    """True iff a forward event of *event_type* has a registered undo handler."""
    return event_type in _HANDLERS
