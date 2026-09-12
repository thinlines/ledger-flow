"""The transaction edit session — the only writer of transaction blocks.

This module is the write-side counterpart of the projection. The projection
answers *what does this transaction say*; the session answers *change it to
say this*. A caller opens a session, opens one or more transactions by
durable id, calls verbs in the user's vocabulary, and lets the session
commit::

    with edit(config, tag="recategorize",
              event_type="transaction.recategorized.v1") as session:
        txn = session.open(txn_id, expect_hash=block_hash)
        txn.set_category("Expenses:Groceries")

    session.result.operation_id   # the recorded operation
    session.result.identity(txn_id)  # post-edit durable id + block hash

Everything beneath the verbs belongs to the session: locating the block,
staleness, posting classification, rendering, trailing-newline preservation,
the journal mutation, re-projection, and the undo payload. Callers never
assemble payloads and never compute a workspace path.

Every verb returns the value it replaced — the prior category, account,
status, note, metadata value, tag presence, or block text — so a caller that
needs to report or re-apply the old state never has to read it out first.

Refusals are typed (:class:`EditError` subclasses) and carry the message the
user sees, so the first-party application and automation clients read the
same text. One translation table maps them to HTTP status codes, in the API
layer.

Two private layers live below the seam and are not exported: a posting-line
codec (``_parse_posting``, over the line primitives in ``journal_syntax``)
and a journal-file layer
(:class:`_JournalFile` — locate, splice, date-ordered insert, trailing-newline
preservation, drop a file left holding only comments). They are implementation
of the session; promote either only when a second public consumer appears.

Adding an action means adding one verb here whose inverse is another verb —
``set_category`` inverts itself with the prior account, ``delete`` inverts to
``restore``, ``unmatch`` to ``match``. A verb with no inverse in that table is
at the wrong grain.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from functools import cached_property
from pathlib import Path

from . import journal_writer
from .archive_service import archive_manual_entry
from .commodity import parse_amount, split_balance_assertion
from .config_service import AppConfig
from .header_parser import TransactionStatus, parse_header, set_header_status
from .journal_block_service import hash_block, locate_block_by_hash, locate_block_by_id
from .journal_syntax import (
    LF_TXN_ID_META_RE,
    META_RE,
    POSTING_RE,
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


class AlreadyInState(EditError):
    """The transaction already holds the requested value; nothing to change."""


# ---------------------------------------------------------------------------
# Public value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Posting:
    """One leg of a transaction, addressed by role or by ``index``.

    Postings have no identity of their own in the journal: they are a value
    read from the transaction and changed through its verbs.
    """

    index: int
    account: str
    amount: Decimal | None = None
    commodity: str | None = None
    assertion: str | None = None


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
# Posting-line codec (private)
# ---------------------------------------------------------------------------


def _parse_posting(line: str, index: int) -> Posting | None:
    """Read one posting line into a value, or ``None`` if it is not a posting."""
    account = posting_account(line)
    if account is None:
        return None
    match = POSTING_RE.match(line)
    amount_text = (match.group(2) or "") if match else ""
    _, assertion = split_balance_assertion(amount_text)
    parsed = parse_amount(amount_text)
    return Posting(
        index=index,
        account=account,
        amount=parsed.value if parsed is not None else None,
        commodity=parsed.commodity if parsed is not None else None,
        assertion=assertion,
    )


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
        return self._file.lines[self._start : self._end]

    @property
    def block_text(self) -> str:
        """The block's current text, reflecting verbs already applied."""
        return "\n".join(self._block)

    @property
    def header(self) -> str:
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
    def postings(self) -> tuple[Posting, ...]:
        return tuple(posting for _, posting in self._posting_lines())

    @property
    def source_posting(self) -> Posting | None:
        """The tracked-account leg, or ``None`` when the block has none."""
        tracked = [p for p in self.postings if p.account in self._session._tracked]
        if len(tracked) > 1:
            raise SplitTransaction("Cannot reassign a multi-account transaction")
        return tracked[0] if tracked else None

    @property
    def category_posting(self) -> Posting | None:
        """The single non-tracked leg. ``None`` for a transfer; raises for a split."""
        others = [p for p in self.postings if p.account not in self._session._tracked]
        if len(others) > 1:
            raise SplitTransaction("Cannot re-categorize a split transaction")
        return others[0] if others else None

    # -- verbs -------------------------------------------------------------

    def set_category(self, account: str | None) -> str:
        """Move the category leg. ``None`` resets it to uncategorized."""
        requested = (account or "").strip()
        target = requested or UNCATEGORIZED_ACCOUNT
        posting = self.category_posting
        if posting is None:
            raise NotACategory("Cannot re-categorize a transfer")
        if posting.account == target:
            raise AlreadyInState(
                "Transaction is already uncategorized"
                if not requested
                else "Transaction already has this category"
            )
        self._rewrite_account(posting.index, target)
        self._session._record(previous_account=posting.account, new_account=target)
        self._session._describe(
            f"Recategorized: {self.payee} on {self.date} ({posting.account} → {target})"
        )
        return posting.account

    def set_source_account(self, ledger_account: str) -> str:
        """Move the transaction to a different tracked account."""
        target = (ledger_account or "").strip()
        if target not in self._session._tracked:
            raise NotTracked("Not a tracked account")
        posting = self.source_posting
        if posting is None:
            raise NotACategory("Cannot reassign account on this transaction")
        if posting.account == target:
            raise AlreadyInState("Transaction already belongs to this account")
        self._rewrite_account(posting.index, target)
        self._session._record(previous_account=posting.account, new_account=target)
        self._session._describe(
            f"Reassigned account: {self.payee} on {self.date} "
            f"({posting.account} → {target})"
        )
        return posting.account

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

    def set_tag(self, name: str) -> bool:
        """Add a bare ``; :name:`` tag to the block. Idempotent."""
        return self._write_tag(name, present=True)

    def clear_tag(self, name: str) -> bool:
        """Remove a bare ``; :name:`` tag from the block. Idempotent."""
        return self._write_tag(name, present=False)

    def delete(self) -> str:
        """Remove the transaction from the journal."""
        phrase = f"Deleted transaction: {self.payee} on {self.date}"
        block_text = self._remove(drop_empty_file=False)
        self._session._describe(phrase)
        return block_text

    # -- internals ---------------------------------------------------------

    def _posting_lines(self) -> list[tuple[int, Posting]]:
        found: list[tuple[int, Posting]] = []
        for index in range(self._start + 1, self._end):
            posting = _parse_posting(self._file.lines[index], len(found))
            if posting is not None:
                found.append((index, posting))
        return found

    def _rewrite_account(self, posting_index: int, account: str) -> None:
        line_index, _ = self._posting_lines()[posting_index]
        rewritten, _ = rewrite_posting_account(self._file.lines[line_index], account)
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
    """One journal mutation, one recorded operation, any number of verbs."""

    def __init__(
        self,
        config: AppConfig,
        *,
        tag: str,
        event_type: str,
        actor: str,
        compensates: str | None,
        summary: str | None,
        payload: dict | None,
    ) -> None:
        self._config = config
        self._tag = tag
        self._event_type = event_type
        self._actor = actor
        self._compensates = compensates
        self._summary_override = summary
        self._payload_override = payload
        self._files: dict[str, _JournalFile] = {}
        self._deferred: list[tuple[Path, Callable[[Path], None]]] = []
        self._opened: list[Transaction] = []
        self._refs: dict[str, ProjectedTransactionRef] = {}
        self._removed: set[str] = set()
        self._phrases: list[str] = []
        self._refreshed = False
        self._payload: dict = {}
        self.result: EditResult | None = None

    # -- opening -----------------------------------------------------------

    def open(self, txn_id: str, *, expect_hash: str | None = None) -> Transaction:
        """Open one transaction by durable id, refusing a stale block hash."""
        if not self._refreshed:
            refresh_projection(self._config)
            self._refreshed = True
        ref = find_projected_transaction(self._config, txn_id)
        if ref is None:
            raise TransactionNotFound(_NOT_FOUND_DETAIL)
        if expect_hash is not None and expect_hash != ref.raw_block_hash:
            raise StaleTransaction(_STALE_DETAIL)
        file = self._file(ref.journal_path)
        span = file.locate(ref.id, ref.raw_block_hash)
        transaction = Transaction(self, ref.id, file, span)
        self._opened.append(transaction)
        self._refs[ref.id] = ref
        if not self._payload:
            self._payload = {
                "journal_path": ref.journal_path,
                "header_line": ref.raw_header,
                "txn_id": ref.id,
            }
        return transaction

    # -- session-level verbs ----------------------------------------------

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

    def unmatch(self, imported: Transaction, *, match_id: str) -> None:
        """Undo a match: unstamp the imported row, bring the manual entry back."""
        match = find_projected_transaction_match(self._config, match_id)
        if match is None or match.imported_transaction_id != imported.id:
            raise TransactionNotFound("Transaction match not found")
        try:
            archived = self.open(match.archived_manual_transaction_id)
        except TransactionNotFound as exc:
            raise TransactionNotFound("Archived manual transaction not found") from exc

        imported.clear_tag("manual")
        imported.clear_metadata("lf_match_id")
        imported.clear_metadata("match-id")
        category = imported.category_posting
        if category is not None and category.account != UNCATEGORIZED_ACCOUNT:
            imported.set_category(None)

        archived.clear_metadata("lf_match_id")
        archived.clear_metadata("match-id")
        restored = archived.block_text
        archived._remove(drop_empty_file=True)
        self.restore(imported.journal_path, restored)

        self._record(match_id=match_id)
        self._phrases = [
            f"Unmatched: {imported.payee} on {imported.date} (match-id: {match_id})"
        ]

    def match(
        self,
        imported: Transaction,
        *,
        match_id: str,
        manual_block: str,
        archive_path: str,
        category: str | None = None,
    ) -> None:
        """Re-create a match: restamp the imported row, re-archive the manual
        entry — unmatch's inverse."""
        imported.set_tag("manual")
        imported.set_metadata("lf_match_id", match_id)
        if category and category != UNCATEGORIZED_ACCOUNT:
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
        paths = [file.path for file in self._files.values()]
        paths.extend(path for path, _ in self._deferred if path not in paths)
        if not paths:
            return
        with journal_writer.mutate(
            config=self._config,
            paths=paths,
            tag=self._tag,
            event_type=self._event_type,
            actor=self._actor,
        ) as mutation:
            for file in self._files.values():
                file.flush()
            for path, action in self._deferred:
                action(path)
            mutation.summary = (
                self._summary_override
                if self._summary_override is not None
                else "; ".join(self._phrases)
            )
            mutation.payload = (
                dict(self._payload_override)
                if self._payload_override is not None
                else dict(self._payload)
            )
            mutation.compensates = self._compensates
        self.result = EditResult(mutation.event_id, self._identities())

    def _identities(self) -> dict[str, Identity]:
        found: dict[str, Identity] = {}
        for transaction in self._opened:
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
    config: AppConfig,
    *,
    tag: str,
    event_type: str,
    actor: str = "user",
    compensates: str | None = None,
    summary: str | None = None,
    payload: dict | None = None,
) -> Iterator[Session]:
    """Open an edit session. Verbs run in memory; the session writes on exit.

    Args:
        config: the workspace.
        tag: short slug for the writer's backup filenames.
        event_type: operation type recorded on success.
        actor: recorded as the operation's actor. Defaults to ``"user"``.
        compensates: the forward operation this session undoes, if any.
        summary: overrides the summary the verbs would have written.
        payload: replaces the undo payload the verbs would have written —
            a compensating operation carries the forward event's payload
            rather than its own inverse.

    Yields:
        A :class:`Session`. Read ``session.result`` after the block for the
        operation id and each opened transaction's post-edit identity.

    Raises:
        EditError: any domain refusal; the journal is left untouched.
    """
    session = Session(
        config,
        tag=tag,
        event_type=event_type,
        actor=actor,
        compensates=compensates,
        summary=summary,
        payload=payload,
    )
    yield session
    session._commit()
