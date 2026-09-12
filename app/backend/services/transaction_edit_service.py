"""The transaction edit session — the only writer of transaction blocks.

This module is the write-side counterpart of the projection. The projection
answers *what does this transaction say*; the session answers *change it to
say this*. A caller opens a session, opens a transaction by
durable id, calls verbs in the user's vocabulary, and lets the session
commit::

    with edit(config) as session:
        txn = session.open(txn_id, expect_hash=block_hash)
        txn.set_category("Expenses:Groceries")

    session.result.operation_id   # the recorded operation
    session.result.identity(txn_id)  # post-edit durable id + block hash

Everything beneath the verbs belongs to the session: locating the block,
staleness, posting classification, rendering, trailing-newline preservation,
the journal mutation, re-projection, and the undo payload. Callers never
assemble payloads and never compute a workspace path.

Each session records one semantic action; its verb determines the event type.
Account changes return both the previous and applied account. Other verbs
return the prior value. Match and unmatch compose their edits privately.

Refusals are typed (:class:`EditError` subclasses) and carry the message the
user sees, so the first-party application and automation clients read the
same text. One translation table maps them to HTTP status codes, in the API
layer.

Two private layers live below the seam and are not exported: posting role
selection and a journal-file layer
(:class:`_JournalFile` — locate, splice, date-ordered insert, trailing-newline
preservation, drop a file left holding only comments). They are implementation
of the session; promote either only when a second public consumer appears.

Adding an action means adding one verb here whose inverse is another verb —
``set_category`` inverts itself with the prior account, ``delete`` inverts to
``restore``, ``unmatch`` to ``match``. A verb with no inverse in that table is
at the wrong grain.

Undo dispatch supports the existing row actions. Standalone metadata, tag,
restore, and match actions have direct inverse verbs but no dispatcher handlers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from functools import cached_property, wraps
from pathlib import Path

from . import journal_writer
from .archive_service import archive_manual_entry
from .config_service import AppConfig
from .header_parser import TransactionStatus, parse_header, set_header_status
from .journal_block_service import hash_block, locate_block_by_hash, locate_block_by_id
from .journal_syntax import (
    LF_TXN_ID_META_RE,
    META_RE,
    TXN_START_RE,
    posting_account,
    rewrite_posting_account,
)
from .projection_service import (
    ProjectedTransactionRef,
    find_projected_transaction,
    find_projected_transaction_at,
    find_projected_transaction_match,
    refresh_projection,
)

UNCATEGORIZED_ACCOUNT = "Expenses:Unknown"

_NOT_FOUND_DETAIL = "Transaction not found (stale data — try refreshing)"
_STALE_DETAIL = "This transaction changed since it was loaded — refresh and try again."


# ---------------------------------------------------------------------------
# Typed refusals
# ---------------------------------------------------------------------------


class EditError(Exception):
    """Base for every refusal the session raises. Carries the user's message."""


class TransactionNotFound(EditError):
    """No transaction with this durable id (or no such match / archived entry)."""


class StaleTransaction(EditError):
    """The block changed since the caller loaded it; its hash no longer matches."""


class SplitTransaction(EditError):
    """The transaction has more than one posting in the requested role."""


class NotACategory(EditError):
    """The requested role posting is absent — a transfer has no category leg,
    and a transaction with no tracked leg has no source posting."""


class NotTracked(EditError):
    """The target account is not one of the workspace's tracked accounts."""


class ActionConflict(EditError):
    """A session attempted more than one semantic action."""


class AlreadyInState(EditError):
    """The transaction already holds the requested value; nothing to change."""


# ---------------------------------------------------------------------------
# Public value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountChange:
    """The previous account and the normalized account actually applied."""

    previous: str
    applied: str


@dataclass(frozen=True)
class MatchRestoration:
    """Everything needed to reverse an unmatch, produced by that action."""

    txn_id: str
    match_id: str
    manual_block: str
    archive_path: str
    category: str | None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.txn_id, self.match_id, self.manual_block, self.archive_path
        )) or (self.category is not None and (
            not isinstance(self.category, str) or not self.category.strip()
        )):
            raise EditError("Incomplete event payload for match restoration")

    @classmethod
    def from_payload(cls, payload: Mapping) -> MatchRestoration:
        """Read a current restoration or normalize a historical unmatch payload."""
        recorded = payload.get("match_restoration")
        if recorded is not None:
            try:
                return cls(**recorded)
            except TypeError as exc:
                raise EditError("Incomplete event payload for match restoration") from exc
        txn_id = str(payload.get("txn_id") or "").strip()
        match_id = payload.get("match_id", "")
        block = payload.get("restored_block") or payload.get("restored_manual_block") or ""
        if not txn_id or not match_id or not block:
            raise EditError("Incomplete event payload for match restoration")
        category = payload.get("previous_account")
        if not category:
            category = next(
                (account for line in block.splitlines()
                 if (account := posting_account(line)) is not None
                 and account.startswith(("Expenses:", "Income:", "Revenue:"))),
                None,
            )
        if not category:
            raise EditError("Could not determine category from restored manual block")
        archive = (payload.get("deleted_journal_path") or payload.get("archive_path")
                   or "journals/archived-manual.journal")
        return cls(txn_id, match_id, block, archive, category)


@dataclass(frozen=True)
class Identity:
    """A transaction's post-edit identity, for re-spreading onto a live row."""

    txn_id: str
    block_hash: str | None


@dataclass(frozen=True)
class EditResult:
    """What one committed session produced."""

    operation_id: str
    identities: dict[str, Identity]

    def identity(self, txn_id: str) -> Identity:
        """Post-edit identity of the transaction opened under *txn_id*."""
        return self.identities.get(txn_id, Identity(txn_id, None))


# ---------------------------------------------------------------------------
# Action recording (private)
# ---------------------------------------------------------------------------


def _action(tag: str, event_type: str):
    """Record one semantic action while allowing its private composition."""

    def decorate(verb):
        @wraps(verb)
        def call(subject, *args, **kwargs):
            session = subject._session if isinstance(subject, Transaction) else subject
            session._check_active()
            if isinstance(subject, Transaction):
                subject._check_live()
            if session._composing:
                return verb(subject, *args, **kwargs)
            if session._action is not None:
                session._failed = True
                raise ActionConflict("An edit session permits only one action")
            session._action = (tag, event_type)
            session._payload = {}
            if isinstance(subject, Transaction):
                session._target(subject)
            session._composing = True
            try:
                return verb(subject, *args, **kwargs)
            except Exception:
                session._failed = True
                raise
            finally:
                session._composing = False
        return call

    return decorate


_TAG_LINE_RE = re.compile(r"^(\s*);\s*:([^;]*?):\s*$")


def _block_txn_id(block_text: str) -> str | None:
    for line in block_text.splitlines():
        match = LF_TXN_ID_META_RE.match(line)
        if match:
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Journal-file layer (private)
# ---------------------------------------------------------------------------


class _JournalFile:
    """One journal file held as lines, spliced in place, written once.

    Open transactions register with the file so their line ranges survive
    edits made elsewhere in the same file.
    """

    def __init__(self, path: Path, rel: str) -> None:
        self.path = path
        self.rel = rel
        self.original = path.read_text(encoding="utf-8") if path.is_file() else ""
        self.lines = self.original.splitlines()
        self._trailing_newline = self.original.endswith("\n") or not self.original
        self._remove = False
        self._blocks: list[Transaction] = []

    # -- reading -----------------------------------------------------------

    def locate(self, txn_id: str, block_hash: str) -> tuple[int, int]:
        located = locate_block_by_id(self.lines, txn_id) or locate_block_by_hash(
            self.lines, block_hash
        )
        if located is None or hash_block(self.lines, *located) != block_hash:
            raise StaleTransaction(_STALE_DETAIL)
        return located

    # -- writing -----------------------------------------------------------

    def splice(self, start: int, end: int, new_lines: list[str]) -> None:
        """Replace ``lines[start:end]``, keeping open block ranges correct."""
        delta = len(new_lines) - (end - start)
        self.lines[start:end] = new_lines
        if not delta:
            return
        for block in self._blocks:
            if block._start >= end:
                block._start += delta
                block._end += delta
            elif block._start <= start and block._end >= end:
                block._end += delta

    def insert_in_date_order(self, block_lines: list[str]) -> None:
        """Place a block after the last transaction dated on or before it,
        separated by exactly one blank line."""
        posted_on = block_lines[0][:10] if block_lines else ""
        for index in range(len(self.lines) - 1, -1, -1):
            if TXN_START_RE.match(self.lines[index]) and self.lines[index][:10] <= posted_on:
                end = index + 1
                while end < len(self.lines) and not TXN_START_RE.match(self.lines[end]):
                    end += 1
                while end > index + 1 and not self.lines[end - 1].strip():
                    end -= 1
                self.splice(end, end, [""] + block_lines if end else list(block_lines))
                return

        # Nothing is dated earlier: sit above the first transaction, or at the
        # end of a file that holds none.
        first = next(
            (i for i, line in enumerate(self.lines) if TXN_START_RE.match(line)),
            len(self.lines),
        )
        if first < len(self.lines):
            payload = block_lines + [""]
        else:
            payload = ([""] if self.lines and self.lines[-1].strip() else []) + block_lines
        self.splice(first, first, payload)

    def drop_if_only_comments(self) -> None:
        """A journal left holding nothing but comments is removed outright."""
        if not any(
            line.strip() and not line.strip().startswith(";") for line in self.lines
        ):
            self._remove = True

    def flush(self) -> None:
        if self.original and self.path.read_text(encoding="utf-8") != self.original:
            raise StaleTransaction(_STALE_DETAIL)
        if self._remove:
            self.path.unlink(missing_ok=True)
            return
        text = "\n".join(self.lines) + ("\n" if self._trailing_newline else "")
        if text == self.original:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Transaction handle
# ---------------------------------------------------------------------------


class Transaction:
    """One open transaction. Verbs read like the action the user took."""

    def __init__(self, session: Session, txn_id: str, file: _JournalFile, span: tuple[int, int]) -> None:
        self._session = session
        self._file = file
        self._start, self._end = span
        self.id = txn_id
        self.journal_path = file.rel
        self._opened_header = file.lines[self._start]
        self._deleted = False
        file._blocks.append(self)

    # -- reading -----------------------------------------------------------

    @property
    def _block(self) -> list[str]:
        self._check_live()
        return self._file.lines[self._start : self._end]

    @property
    def block_text(self) -> str:
        """The block's current text, reflecting verbs already applied."""
        return "\n".join(self._block)

    @property
    def header(self) -> str:
        self._check_live()
        return self._file.lines[self._start]

    @property
    def date(self) -> str:
        parsed = parse_header(self.header)
        return parsed.date if parsed else ""

    @property
    def payee(self) -> str:
        parsed = parse_header(self.header)
        return parsed.payee if parsed else self.header[:60]

    @property
    def status(self) -> TransactionStatus:
        parsed = parse_header(self.header)
        return parsed.status if parsed else TransactionStatus.unmarked

    @property
    def metadata(self) -> Mapping[str, str]:
        found: dict[str, str] = {}
        for line in self._block[1:]:
            match = META_RE.match(line)
            if match:
                found[match.group(1).strip().lower()] = match.group(2).strip()
        return found

    @property
    def tags(self) -> frozenset[str]:
        names: set[str] = set()
        for line in self._block[1:]:
            match = _TAG_LINE_RE.match(line)
            if match:
                names.update(part for part in match.group(2).split(":") if part)
        return frozenset(names)

    @property
    def notes(self) -> str:
        return self.metadata.get("notes", "")

    @property
    def source_account(self) -> str | None:
        """The single tracked account, absent when no posting has that role."""
        posting = self._role_posting(tracked=True)
        return posting[1] if posting else None

    @property
    def category_account(self) -> str | None:
        """The single category account; absent for a transfer, refused for a split."""
        posting = self._role_posting(tracked=False)
        return posting[1] if posting else None

    # -- verbs -------------------------------------------------------------

    @_action("recategorize", "transaction.recategorized.v1")
    def set_category(self, account: str | None) -> AccountChange:
        """Move the category leg. ``None`` resets it to uncategorized."""
        requested = (account or "").strip()
        target = requested or UNCATEGORIZED_ACCOUNT
        posting = self._role_posting(tracked=False)
        if posting is None:
            raise NotACategory("Cannot re-categorize a transfer")
        if posting[1] == target:
            raise AlreadyInState(
                "Transaction is already uncategorized"
                if not requested
                else "Transaction already has this category"
            )
        self._rewrite_account(posting[0], target)
        self._session._record(previous_account=posting[1], new_account=target)
        self._session._describe(
            f"Recategorized: {self.payee} on {self.date} ({posting[1]} → {target})"
        )
        return AccountChange(posting[1], target)

    @_action("reassign-account", "transaction.account_reassigned.v1")
    def set_source_account(self, ledger_account: str) -> AccountChange:
        """Move the transaction to a different tracked account."""
        target = (ledger_account or "").strip()
        if target not in self._session._tracked:
            raise NotTracked("Not a tracked account")
        posting = self._role_posting(tracked=True)
        if posting is None:
            raise NotACategory("Cannot reassign account on this transaction")
        if posting[1] == target:
            raise AlreadyInState("Transaction already belongs to this account")
        self._rewrite_account(posting[0], target)
        self._session._record(previous_account=posting[1], new_account=target)
        self._session._describe(
            f"Reassigned account: {self.payee} on {self.date} "
            f"({posting[1]} → {target})"
        )
        return AccountChange(posting[1], target)

    @_action("toggle-status", "transaction.status_toggled.v1")
    def set_status(self, status: TransactionStatus) -> TransactionStatus:
        """Set the clearing status the bank has confirmed."""
        previous = self.status
        if previous == status:
            raise AlreadyInState("Transaction already has this status")
        self._file.splice(
            self._start, self._start + 1, [set_header_status(self.header, status)]
        )
        self._session._record(previous_status=previous.value, new_status=status.value)
        self._session._describe(
            f"Toggled status to {status.value}: {self._opened_header[:60]}"
        )
        return previous

    @_action("notes", "transaction.notes_updated.v1")
    def set_notes(self, notes: str) -> str:
        """Set (or, with an empty string, remove) the transaction's note."""
        previous = self.notes
        value = notes or ""
        if value == previous:
            raise AlreadyInState("Transaction already has these notes")
        self._write_metadata("notes", value or None)
        self._session._record(notes=value, previous_notes=previous)
        self._session._describe(f"Notes updated: {self.payee} on {self.date}")
        return previous

    @_action("metadata", "transaction.metadata_updated.v1")
    def set_metadata(self, key: str, value: str | None) -> str | None:
        """Set one journal metadata key; ``None`` clears it. Idempotent."""
        name = key.strip().lower()
        previous = self.metadata.get(name)
        if previous == value:
            return previous
        self._write_metadata(name, value)
        self._session._log_metadata(self.id, name, previous, value)
        return previous

    def clear_metadata(self, key: str) -> str | None:
        """Remove one journal metadata key. Idempotent."""
        return self.set_metadata(key, None)

    @_action("tag", "transaction.tags_updated.v1")
    def set_tag(self, name: str) -> bool:
        """Add a bare ``; :name:`` tag to the block. Idempotent."""
        return self._write_tag(name, present=True)

    @_action("tag", "transaction.tags_updated.v1")
    def clear_tag(self, name: str) -> bool:
        """Remove a bare ``; :name:`` tag from the block. Idempotent."""
        return self._write_tag(name, present=False)

    @_action("delete", "transaction.deleted.v1")
    def delete(self) -> str:
        """Remove the transaction from the journal."""
        phrase = f"Deleted transaction: {self.payee} on {self.date}"
        block_text = self._remove(drop_empty_file=False)
        self._session._describe(phrase)
        return block_text

    # -- internals ---------------------------------------------------------

    def _check_live(self) -> None:
        self._session._check_active()
        if self._deleted:
            raise TransactionNotFound("Transaction was deleted in this session")

    def _role_posting(self, *, tracked: bool) -> tuple[int, str] | None:
        self._check_live()
        postings = [
            (index, account)
            for index in range(self._start + 1, self._end)
            if (account := posting_account(self._file.lines[index])) is not None
            and (account in self._session._tracked) == tracked
        ]
        if len(postings) > 1:
            raise SplitTransaction(
                "Cannot reassign a multi-account transaction" if tracked
                else "Cannot re-categorize a split transaction"
            )
        return postings[0] if postings else None

    def _rewrite_account(self, line_index: int, account: str) -> None:
        rewritten = rewrite_posting_account(self._file.lines[line_index], account)
        self._file.splice(line_index, line_index + 1, [rewritten])

    def _comment_insert_index(self) -> int:
        index = self._start + 1
        while index < self._end and self._file.lines[index].strip().startswith(";"):
            index += 1
        return index

    def _write_metadata(self, key: str, value: str | None) -> None:
        for index in range(self._start + 1, self._end):
            match = META_RE.match(self._file.lines[index])
            if match and match.group(1).strip().lower() == key:
                self._file.splice(
                    index, index + 1, [] if value is None else [f"    ; {key}: {value}"]
                )
                return
        if value is None:
            return
        at = self._comment_insert_index()
        self._file.splice(at, at, [f"    ; {key}: {value}"])

    def _write_tag(self, name: str, *, present: bool) -> bool:
        """Add or remove one tag name; answers whether it was there before."""
        wanted = name.strip()
        for index in range(self._start + 1, self._end):
            match = _TAG_LINE_RE.match(self._file.lines[index])
            if not match:
                continue
            names = [part for part in match.group(2).split(":") if part]
            if (wanted in names) == present:
                return present
            if present:
                names.append(wanted)
            else:
                names = [part for part in names if part != wanted]
            replacement = [f"{match.group(1)}; :{':'.join(names)}:"] if names else []
            self._file.splice(index, index + 1, replacement)
            self._session._log_tag(self.id, wanted, not present, present)
            return not present
        if not present:
            return False
        at = self._comment_insert_index()
        self._file.splice(at, at, [f"    ; :{wanted}:"])
        self._session._log_tag(self.id, wanted, False, True)
        return False

    def _remove(self, *, drop_empty_file: bool) -> str:
        block_text = self.block_text
        start, end = self._start, self._end
        if start > 0 and not self._file.lines[start - 1].strip():
            start -= 1
        elif end < len(self._file.lines) and not self._file.lines[end].strip():
            end += 1
        self._file.splice(start, end, [])
        self._deleted = True
        self._file._blocks.remove(self)
        self._session._removed.add(self.id)
        if drop_empty_file:
            self._file.drop_if_only_comments()
        self._session._record(
            deleted_block=block_text, deleted_journal_path=self._file.rel
        )
        return block_text


# ---------------------------------------------------------------------------
# The session
# ---------------------------------------------------------------------------


class Session:
    """One semantic action, one journal mutation, one recorded operation."""

    def __init__(self, config: AppConfig, *, actor: str, compensating: Mapping | None) -> None:
        self._config = config
        self._actor = actor
        self._compensating = compensating
        self._action: tuple[str, str] | None = None
        self._composing = False
        self._failed = False
        self._active = True
        self._files: dict[str, _JournalFile] = {}
        self._deferred: list[tuple[Path, Callable[[Path], None]]] = []
        self._opened: dict[str, Transaction] = {}
        self._refs: dict[str, ProjectedTransactionRef] = {}
        self._removed: set[str] = set()
        self._phrases: list[str] = []
        self._refreshed = False
        self._payload: dict = {}
        self.result: EditResult | None = None

    # -- opening -----------------------------------------------------------

    def open(self, txn_id: str, *, expect_hash: str | None = None) -> Transaction:
        """Open one transaction by durable id, refusing a stale block hash."""
        self._check_active()
        if not self._refreshed:
            refresh_projection(self._config)
            self._refreshed = True
        ref = find_projected_transaction(self._config, txn_id)
        if ref is None:
            raise TransactionNotFound(_NOT_FOUND_DETAIL)
        if expect_hash is not None and expect_hash != ref.raw_block_hash:
            raise StaleTransaction(_STALE_DETAIL)
        existing = self._opened.get(ref.id)
        if existing is not None:
            existing._check_live()
            if not self._payload:
                self._target(existing)
            return existing
        file = self._file(ref.journal_path)
        span = file.locate(ref.id, ref.raw_block_hash)
        transaction = Transaction(self, ref.id, file, span)
        self._opened[ref.id] = transaction
        self._refs[ref.id] = ref
        if not self._payload:
            self._target(transaction)
        return transaction

    # -- session-level verbs ----------------------------------------------

    @_action("restore", "transaction.restored.v1")
    def restore(self, journal_path: str, block_text: str) -> None:
        """Put a previously deleted block back, in date order — delete's inverse."""
        block_lines = block_text.rstrip("\n").splitlines()
        if not block_lines:
            raise TransactionNotFound("Nothing to restore — the recorded block is empty")
        file = self._file(journal_path)
        txn_id = _block_txn_id(block_text)
        if txn_id is not None and (
            locate_block_by_id(file.lines, txn_id) is not None
            or (
                txn_id not in self._removed
                and find_projected_transaction(self._config, txn_id) is not None
            )
        ):
            raise AlreadyInState("Transaction was re-created — refusing to duplicate")
        file.insert_in_date_order(block_lines)
        self._record(restored_block=block_text, restored_journal_path=journal_path)
        parsed = parse_header(block_lines[0])
        self._describe(
            f"Restored transaction: {parsed.payee} on {parsed.date}"
            if parsed
            else "Restored transaction"
        )

    @_action("unmatch", "transaction.unmatched.v1")
    def unmatch(
        self, txn_id: str, *, match_id: str, expect_hash: str | None = None
    ) -> MatchRestoration:
        """Undo a match: unstamp the imported row, bring the manual entry back."""
        imported = self.open(txn_id, expect_hash=expect_hash)
        match = find_projected_transaction_match(self._config, match_id)
        if match is None or match.imported_transaction_id != imported.id:
            raise TransactionNotFound("Transaction match not found")
        try:
            archived = self.open(match.archived_manual_transaction_id)
        except TransactionNotFound as exc:
            raise TransactionNotFound("Archived manual transaction not found") from exc

        category = imported.category_account
        archive_path = archived.journal_path
        imported.clear_tag("manual")
        imported.clear_metadata("lf_match_id")
        imported.clear_metadata("match-id")
        if category is not None and category != UNCATEGORIZED_ACCOUNT:
            imported.set_category(None)

        archived.clear_metadata("lf_match_id")
        archived.clear_metadata("match-id")
        restored = archived.block_text
        archived._remove(drop_empty_file=True)
        self.restore(imported.journal_path, restored)

        restoration = MatchRestoration(imported.id, match_id, restored, archive_path, category)
        self._record(match_id=match_id, match_restoration=asdict(restoration))
        self._phrases = [
            f"Unmatched: {imported.payee} on {imported.date} (match-id: {match_id})"
        ]
        return restoration

    @_action("match", "transaction.matched.v1")
    def match(self, restoration: MatchRestoration) -> None:
        """Reverse an unmatch using the restoration it produced."""
        imported = self.open(restoration.txn_id)
        match_id = restoration.match_id
        manual_block = restoration.manual_block
        archive_path = restoration.archive_path
        category = restoration.category
        imported.set_tag("manual")
        imported.set_metadata("lf_match_id", match_id)
        if category is not None and imported.category_account != category:
            imported.set_category(category)

        manual_id = _block_txn_id(manual_block)
        if manual_id is None:
            raise TransactionNotFound("Could not locate restored manual entry in journal")
        manual = self.open(manual_id)
        manual._remove(drop_empty_file=False)

        keep = [
            line
            for line in manual_block.rstrip("\n").splitlines()
            if line.strip() not in {f"; lf_match_id: {match_id}", f"; match-id: {match_id}"}
        ]
        self._defer(
            archive_path, lambda path: archive_manual_entry(path, match_id, keep)
        )
        self._record(match_id=match_id)
        self._phrases = [
            f"Re-matched: {imported.payee} on {imported.date} (match-id: {match_id})"
        ]

    # -- internals ---------------------------------------------------------

    def _check_active(self) -> None:
        if not self._active:
            raise EditError("The edit session is closed")

    def _target(self, transaction: Transaction) -> None:
        ref = self._refs[transaction.id]
        self._payload = {
            "journal_path": ref.journal_path,
            "header_line": ref.raw_header,
            "txn_id": ref.id,
        }

    @cached_property
    def _tracked(self) -> frozenset[str]:
        return frozenset(
            account.ledger_account
            for account in self._config.accounts
            if account.ledger_account
        )

    def _file(self, journal_path: str) -> _JournalFile:
        existing = self._files.get(journal_path)
        if existing is None:
            existing = _JournalFile(self._config.root_dir / journal_path, journal_path)
            self._files[journal_path] = existing
        return existing

    def _defer(self, journal_path: str, action: Callable[[Path], None]) -> None:
        self._deferred.append((self._config.root_dir / journal_path, action))

    def _record(self, **values: object) -> None:
        self._payload.update(values)

    def _log_metadata(self, txn_id: str, key: str, previous: str | None, value: str | None) -> None:
        log = self._payload.setdefault("metadata", {}).setdefault(txn_id, {})
        log[key] = {"previous": previous, "new": value}

    def _log_tag(self, txn_id: str, name: str, previous: bool, value: bool) -> None:
        log = self._payload.setdefault("tags", {}).setdefault(txn_id, {})
        log[name] = {"previous": previous, "new": value}

    def _describe(self, phrase: str) -> None:
        self._phrases.append(phrase)

    def _commit(self) -> None:
        if self._failed:
            raise ActionConflict("The edit action failed; the session cannot commit")
        if self._action is None:
            return
        tag, event_type = self._action
        forward = self._compensating
        if forward is not None:
            tag = "undo"
            event_type = f"{forward.get('type', '')}.compensated.v1"
        paths = [file.path for file in self._files.values()]
        paths.extend(path for path, _ in self._deferred if path not in paths)
        if not paths:
            return
        with journal_writer.mutate(
            config=self._config,
            paths=paths,
            tag=tag,
            event_type=event_type,
            actor=self._actor,
        ) as mutation:
            for file in self._files.values():
                file.flush()
            for path, action in self._deferred:
                action(path)
            mutation.summary = (
                f"Undid: {forward.get('summary', '')}" if forward is not None
                else "; ".join(self._phrases)
            )
            mutation.payload = (
                {**forward.get("payload", {}), "compensated_event_id": forward.get("id", "")}
                if forward is not None else dict(self._payload)
            )
            mutation.compensates = forward.get("id", "") if forward is not None else None
        self.result = EditResult(mutation.event_id, self._identities())

    def _identities(self) -> dict[str, Identity]:
        found: dict[str, Identity] = {}
        for transaction in self._opened.values():
            if transaction._deleted:
                continue
            ref = self._refs[transaction.id]
            updated = find_projected_transaction(
                self._config, transaction.id
            ) or find_projected_transaction_at(
                self._config, ref.journal_file_id, ref.txn_order
            )
            found[transaction.id] = Identity(
                updated.id if updated else transaction.id,
                updated.raw_block_hash if updated else None,
            )
        return found


@contextmanager
def edit(
    config: AppConfig, *, actor: str = "user", compensating: Mapping | None = None
) -> Iterator[Session]:
    """Apply one semantic action in memory and commit on successful exit.

    The verb chooses the event type, backup tag, summary, and undo payload.
    A second action refuses the entire session. Match and unmatch compose
    their related changes internally. Opening or reading handles records nothing.
    Reopening an id returns its existing handle; deleted handles are refused.
    Handles are valid only inside the context. Read ``session.result`` after exit.

    ``compensating`` is the forward event being undone. Its operation metadata
    is derived here rather than assembled by each inverse caller.
    """
    session = Session(config, actor=actor, compensating=compensating)
    try:
        yield session
        session._commit()
    finally:
        session._active = False
