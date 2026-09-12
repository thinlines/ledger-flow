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
the change as a compensating operation.  Operation history is never rewritten.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

from services import journal_writer, transaction_edit_service
from services.config_service import AppConfig
from services.header_parser import TransactionStatus
from services.journal_block_service import locate_block_by_id
from services.operations_service import (
    hash_file,
    list_operations,
    operation_is_compensated,
)
from services.projection_service import (
    ProjectedTransactionRef,
    find_projected_transaction,
    find_projected_transaction_match,
    projected_transaction_block,
    refresh_projection,
    render_file,
)

logger = logging.getLogger(__name__)


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


# Handler protocol: handlers take ``(config, event)`` and own emission — the
# transaction-level ones through the edit session, the batch ones through
# ``journal_writer.mutate``. They return the compensating event id.
HandlerFn = Callable[[AppConfig, dict], str]


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


def _block_range(lines: list[str], ref: ProjectedTransactionRef) -> tuple[int, int]:
    """Relocate a transaction by durable identity inside a mutation."""
    located = locate_block_by_id(lines, ref.id)
    if located is None:
        raise UndoFailedError("This transaction changed since the action — cannot undo")
    return located


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
    return list(reversed(list_operations(config.root_dir)))


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
    events = _read_history(config)

    # 1. Locate the forward event.
    forward = _find_event(events, event_id)
    if forward is None:
        return UndoResult(UndoOutcome.NOT_FOUND, "Event not found", None, event_id)

    # 2. Idempotency check.
    existing = operation_is_compensated(config.root_dir, event_id) or _is_compensated(events, event_id)
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


@contextmanager
def _compensating(config: AppConfig, event: dict) -> Iterator[transaction_edit_service.Session]:
    """One edit session that compensates *event*.

    The inverse of every transaction-level verb is another verb, so each
    handler below is a call into the session with the payload's prior value.
    The session owns the journal, the projection, and the operation record;
    this layer owns only the semantic precondition — that the transaction
    still holds the state the forward action produced.
    """
    try:
        with transaction_edit_service.edit(config, compensating=event) as session:
            yield session
    except transaction_edit_service.EditError as exc:
        raise UndoFailedError(str(exc)) from exc


def _undo_transaction_deleted(config: AppConfig, event: dict) -> str:
    """Restore a deleted transaction block at its date-ordered position."""
    payload = event.get("payload", {})
    journal_rel = payload.get("deleted_journal_path") or payload.get("journal_path") or ""
    deleted_block = payload.get("deleted_block", "")
    if not journal_rel or not deleted_block:
        raise UndoFailedError("Incomplete event payload — missing journal_path or deleted_block")

    with _compensating(config, event) as session:
        session.restore(journal_rel, deleted_block)
    return session.result.operation_id


def _undo_transaction_recategorized(config: AppConfig, event: dict) -> str:
    """Put the previous category back on a recategorized transaction."""
    payload = event.get("payload", {})
    previous_account = payload.get("previous_account", "")
    new_account = payload.get("new_account", "Expenses:Unknown")
    if not previous_account:
        raise UndoFailedError("Incomplete event payload")

    with _compensating(config, event) as session:
        transaction = session.open(_payload_txn_id(payload))
        if transaction.category_account != new_account:
            raise UndoFailedError(f"Destination account {new_account} not found on transaction")
        transaction.set_category(previous_account)
    return session.result.operation_id


def _undo_transaction_account_reassigned(config: AppConfig, event: dict) -> str:
    """Put the previous tracked account back on a reassigned transaction."""
    payload = event.get("payload", {})
    previous_account = payload.get("previous_account", "")
    new_account = payload.get("new_account", "")
    if not previous_account:
        raise UndoFailedError("Incomplete event payload")

    with _compensating(config, event) as session:
        transaction = session.open(_payload_txn_id(payload))
        if transaction.source_account != new_account:
            raise UndoFailedError(f"Source account {new_account} not found on transaction")
        transaction.set_source_account(previous_account)
    return session.result.operation_id


def _undo_transaction_status_toggled(config: AppConfig, event: dict) -> str:
    """Put the previous clearing status back on a toggled transaction."""
    payload = event.get("payload", {})
    previous_status_str = payload.get("previous_status", "")
    new_status_str = payload.get("new_status", "")
    if not previous_status_str:
        raise UndoFailedError("Incomplete event payload")
    try:
        previous_status = TransactionStatus(previous_status_str)
    except ValueError as exc:
        raise UndoFailedError(f"Invalid previous_status in event: {previous_status_str}") from exc

    with _compensating(config, event) as session:
        transaction = session.open(_payload_txn_id(payload))
        if transaction.status.value != new_status_str:
            raise UndoFailedError(
                "Transaction status changed since this action — undo the later change first"
            )
        transaction.set_status(previous_status)
    return session.result.operation_id


def _undo_manual_entry_created(config: AppConfig, event: dict) -> str:
    """Delete the manual entry that was created."""
    with _compensating(config, event) as session:
        session.open(_payload_txn_id(event.get("payload", {}))).delete()
    return session.result.operation_id


def _undo_transaction_notes_updated(config: AppConfig, event: dict) -> str:
    """Put the previous note back (or take the added one away)."""
    payload = event.get("payload", {})
    if "previous_notes" not in payload:
        # Pre-migration event: no captured prior value, no safe inverse.
        raise UndoFailedError("Pre-existing notes event lacks previous_notes — cannot undo")

    with _compensating(config, event) as session:
        session.open(_payload_txn_id(payload)).set_notes(payload.get("previous_notes") or "")
    return session.result.operation_id


def _undo_transaction_unmatched(config: AppConfig, event: dict) -> str:
    """Re-create a match from the restoration recorded by unmatch."""
    with _compensating(config, event) as session:
        restoration = transaction_edit_service.MatchRestoration.from_payload(event.get("payload", {}))
        session.match(restoration)
    return session.result.operation_id


def _undo_import_applied(config: AppConfig, event: dict) -> str:
    """Undo an import through the shared compensation dispatcher."""
    from services.import_history_service import undo_import

    forward_event_id = str(event.get("id") or "")
    if not forward_event_id:
        raise UndoFailedError("Import operation is missing an id")

    try:
        undo_import(config, forward_event_id)
    except KeyError as exc:
        raise UndoFailedError("Import history entry not found") from exc
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise UndoFailedError(str(exc)) from exc

    compensating_id = operation_is_compensated(config.root_dir, forward_event_id)
    if compensating_id is None:
        raise UndoFailedError("Import undo did not record a compensating operation")
    return compensating_id


def _undo_matches_applied(config: AppConfig, event: dict) -> str:
    """Restore the exact pre-match imported and manual transaction blocks."""
    payload = event.get("payload", {})
    matches = payload.get("matches")
    if not matches and payload.get("match_id"):
        matches = [payload]
    if not matches:
        raise UndoFailedError("Match event lacks durable per-match records")

    paths: list = []
    prepared: list[tuple[dict, ProjectedTransactionRef, ProjectedTransactionRef]] = []
    refresh_projection(config)
    for record in matches:
        match_id = str(record.get("match_id") or "")
        projected = find_projected_transaction_match(config, match_id)
        if projected is None:
            raise UndoFailedError(f"Active match {match_id!r} no longer exists")
        imported_ref = find_projected_transaction(config, projected.imported_transaction_id)
        archived_ref = find_projected_transaction(config, projected.archived_manual_transaction_id)
        if imported_ref is None or archived_ref is None:
            raise UndoFailedError("Matched transaction is missing")
        prepared.append((record, imported_ref, archived_ref))
        paths.extend(
            [config.root_dir / imported_ref.journal_path, config.root_dir / archived_ref.journal_path]
        )
        manual_rel = str(record.get("manual_journal_path") or "").strip()
        if manual_rel:
            paths.append(config.root_dir / manual_rel)

    with journal_writer.mutate(
        config=config,
        paths=list(dict.fromkeys(paths)),
        tag="undo",
        event_type=f"{event.get('type', '')}.compensated.v1",
    ) as mut:
        for record, imported_ref, archived_ref in prepared:
            original_imported = str(record.get("original_imported_block") or "")
            original_manual = str(record.get("original_manual_block") or "")
            if not original_imported or not original_manual:
                raise UndoFailedError("Match record lacks original transaction blocks")

            imported_path = config.root_dir / imported_ref.journal_path
            text = imported_path.read_text(encoding="utf-8")
            lines = text.splitlines()
            start, end = _block_range(lines, imported_ref)
            lines[start:end] = original_imported.splitlines()
            insert_at = int(record.get("manual_insert_index") or 0)
            manual_lines = original_manual.splitlines()
            manual_rel = str(
                record.get("manual_journal_path") or imported_ref.journal_path
            )
            manual_path = config.root_dir / manual_rel
            if manual_path == imported_path:
                lines[insert_at:insert_at] = manual_lines + [""]
            imported_path.write_text(
                "\n".join(lines) + ("\n" if text.endswith("\n") else ""),
                encoding="utf-8",
            )
            if manual_path != imported_path:
                manual_text = manual_path.read_text(encoding="utf-8")
                manual_journal_lines = manual_text.splitlines()
                manual_journal_lines[insert_at:insert_at] = manual_lines + [""]
                manual_path.write_text(
                    "\n".join(manual_journal_lines)
                    + ("\n" if manual_text.endswith("\n") else ""),
                    encoding="utf-8",
                )

            archive_path = config.root_dir / archived_ref.journal_path
            archive_text = render_file(config, archived_ref.journal_path)
            archive_lines = archive_text.splitlines()
            archive_block = projected_transaction_block(config, archived_ref.id)
            if archive_block is None:
                raise UndoFailedError("Archived manual transaction block is missing")
            located_archive = locate_block_by_id(archive_lines, archived_ref.id)
            if located_archive is None:
                raise UndoFailedError("Archived manual transaction block is missing")
            archive_start, archive_end = located_archive
            while archive_end < len(archive_lines) and not archive_lines[archive_end].strip():
                archive_end += 1
            del archive_lines[archive_start:archive_end]
            if any(line.strip() and not line.strip().startswith(";") for line in archive_lines):
                archive_path.write_text("\n".join(archive_lines) + "\n", encoding="utf-8")
            else:
                archive_path.unlink(missing_ok=True)

        mut.summary = f"Undid: {event.get('summary', '')}"
        mut.payload = {**payload, "compensated_event_id": event.get("id", "")}
        mut.compensates = event.get("id", "")
    return mut.event_id


_HANDLERS: dict[str, HandlerFn] = {
    "import.applied.v1": _undo_import_applied,
    "transaction.deleted.v1": _undo_transaction_deleted,
    "transaction.recategorized.v1": _undo_transaction_recategorized,
    "transaction.account_reassigned.v1": _undo_transaction_account_reassigned,
    "transaction.status_toggled.v1": _undo_transaction_status_toggled,
    "manual_entry.created.v1": _undo_manual_entry_created,
    "transaction.unmatched.v1": _undo_transaction_unmatched,
    "transaction.notes_updated.v1": _undo_transaction_notes_updated,
    "unknowns.applied.v1": _undo_matches_applied,
    "reconciliation.imported_transaction_used.v1": _undo_matches_applied,
}


def is_undoable_type(event_type: str) -> bool:
    """True iff a forward event of *event_type* has a registered undo handler."""
    return event_type in _HANDLERS
