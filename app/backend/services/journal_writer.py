"""Single chokepoint for journal mutations.

Every journal-class write in Ledger Flow flows through ``journal_writer.mutate``.
The writer owns the ritual that previously lived inline in every route and
undo handler: drift detect, hash, backup, mutate, verify, re-project, hash,
emit-event, rollback-on-failure.

Callers describe **what** they want to change as a path set plus event metadata;
the writer enforces **how** the change is safely applied.

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="manual-entry",
        event_type="manual_entry.created.v1",
    ) as mut:
        do_the_actual_write(...)
        mut.summary = "Created manual entry"
        mut.payload = {"date": "...", "amount": "..."}

Failure semantics ride on Python exceptions:

* Exception inside the block → restore every backed-up path, re-raise.
* Verifier returns ``VerifyFailure`` → restore, raise ``WriterRejected``.
* Verifier raises ``RuntimeError`` → restore, raise ``WriterUnavailable``.
* Re-projection raises → restore every backed-up path, re-raise. The
  projection's own SQLite transaction rolls back with the exception, so
  files and projection commit or revert together (spec: Mutation-Time
  Projection).
* One or more per-path restores fail during rollback → raise aggregate
  ``WriterError`` carrying per-file outcomes.
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid7

from .config_service import AppConfig
from .event_log_service import check_drift, hash_file, rel_path
from .operations_service import record_operation
from .projection_service import refresh_projection


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class VerifyFailure:
    """Marker base class.

    Verifiers return a ``VerifyFailure`` subclass (with whatever structured
    detail the caller needs) to signal that the post-mutation state is
    unacceptable. The writer does not introspect the failure — it attaches it
    to ``WriterRejected.failure`` and the caller decides how to surface it.
    """


Verifier = Callable[[AppConfig, list[Path]], "VerifyFailure | None"]


class WriterRejected(Exception):
    """Verifier returned a ``VerifyFailure``; the mutation has been rolled back."""

    def __init__(self, failure: VerifyFailure) -> None:
        super().__init__(f"journal_writer: verifier rejected mutation ({type(failure).__name__})")
        self.failure = failure


class WriterUnavailable(Exception):
    """Verifier raised ``RuntimeError`` (e.g. ledger CLI missing); rolled back."""


@dataclass(frozen=True)
class RestoreFailure:
    """One per-path failure encountered during rollback."""

    path: Path
    error: BaseException


class WriterError(Exception):
    """One or more per-path restores failed during rollback.

    Carries ``restore_failures`` for inspection by operators. The triggering
    exception (block failure, verifier failure) is preserved via Python's
    standard ``__context__`` chaining when ``WriterError`` is raised inside
    an ``except`` clause.
    """

    def __init__(self, restore_failures: list[RestoreFailure]) -> None:
        super().__init__(
            f"journal_writer: partial rollback — {len(restore_failures)} path(s) failed to restore"
        )
        self.restore_failures = restore_failures


@dataclass
class JournalMutation:
    """The mutation handle yielded by ``mutate``.

    ``event_id`` is minted on context entry. Ops that need to embed it in
    journal metadata (e.g. reconciliation per DECISIONS §15) read it before
    performing the write. ``summary``, ``payload``, and ``compensates`` are
    set inside the block and consumed when the event is emitted on exit.
    """

    event_id: str
    summary: str = ""
    payload: dict = field(default_factory=dict)
    compensates: str | None = None


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def _has_journal_class_path(paths: list[Path]) -> bool:
    return any(p.name.endswith(".journal") for p in paths)


def _backup(path: Path, tag: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.{tag}.bak.{timestamp}")
    backup_path.write_bytes(path.read_bytes())
    return backup_path


def _rollback(
    paths: list[Path],
    pre_existed: dict[Path, bool],
    backups: dict[Path, Path],
) -> None:
    """Restore every path to its pre-mutation state.

    * Path existed pre-mutation → byte-for-byte copy from its backup.
    * Path did not exist pre-mutation → delete it if the block created it.

    If any per-path restore raises, every other path is still attempted and an
    aggregate ``WriterError`` is raised with the collected failures.
    """
    failures: list[RestoreFailure] = []
    for path in paths:
        try:
            if pre_existed[path]:
                shutil.copyfile(str(backups[path]), str(path))
            elif path.is_file():
                path.unlink()
        except BaseException as exc:  # noqa: BLE001 — aggregate any per-path failure
            failures.append(RestoreFailure(path=path, error=exc))
    if failures:
        raise WriterError(failures)


@contextmanager
def mutate(
    *,
    config: AppConfig,
    paths: list[Path],
    tag: str,
    event_type: str,
    verify: Verifier | None = None,
    actor: str = "user",
) -> Iterator[JournalMutation]:
    """Mutate one or more journal-class files atomically.

    Args:
        config: workspace config — supplies ``root_dir`` for operation writes.
        paths: every journal-class file the op might touch. Must contain at
            least one ``*.journal`` path. Co-candidates such as
            ``10-accounts.dat`` may ride along.
        tag: short slug used in backup filenames (e.g. ``"manual-entry"``,
            ``"reconcile"``, ``"undo"``).
        event_type: operation type recorded on success.
        verify: optional post-mutation verifier. ``None`` → pass.
            ``VerifyFailure`` → reject (rollback + ``WriterRejected``).
            ``raise RuntimeError`` → unavailable (rollback +
            ``WriterUnavailable``).
        actor: forwarded to ``emit_event``. Defaults to ``"user"``.

    Yields:
        A ``JournalMutation`` with a freshly minted ``event_id`` and writable
        ``summary``/``payload``/``compensates`` attributes.

    Raises:
        ValueError: ``paths`` contains no ``*.journal`` file.
        WriterRejected: verifier returned a ``VerifyFailure``.
        WriterUnavailable: verifier raised ``RuntimeError``.
        WriterError: one or more per-path restores failed during rollback.
        Exception: whatever the block raised, after rolling back.
    """
    if not _has_journal_class_path(paths):
        raise ValueError(
            "journal_writer.mutate requires at least one *.journal path; "
            f"got {[p.name for p in paths]}"
        )

    workspace = config.root_dir
    event_id = str(uuid7())

    pre_existed: dict[Path, bool] = {p: p.is_file() for p in paths}
    hashes_before: dict[Path, str] = {}
    backups: dict[Path, Path] = {}

    for path in paths:
        if pre_existed[path]:
            hashes_before[path] = check_drift(workspace, path)
            backups[path] = _backup(path, tag)
        else:
            hashes_before[path] = "sha256:none"

    mutation = JournalMutation(event_id=event_id)

    try:
        yield mutation
    except BaseException:
        _rollback(paths, pre_existed, backups)
        raise

    if verify is not None:
        try:
            failure = verify(config, paths)
        except RuntimeError as exc:
            _rollback(paths, pre_existed, backups)
            raise WriterUnavailable(str(exc)) from exc
        if failure is not None:
            _rollback(paths, pre_existed, backups)
            raise WriterRejected(failure)

    # Mutation-time projection: bring the projection in line with the files
    # just written, inside refresh_projection's own SQLite transaction. On
    # failure that transaction rolls back and the files are restored, so
    # neither side can commit without the other.
    try:
        refresh_projection(config)
    except BaseException:
        _rollback(paths, pre_existed, backups)
        raise

    journal_refs: list[dict] = []
    for path in paths:
        hash_after = hash_file(path)
        if hash_after != hashes_before[path]:
            journal_refs.append(
                {
                    "path": rel_path(path, workspace),
                    "hash_before": hashes_before[path],
                    "hash_after": hash_after,
                }
            )

    record_operation(
        config,
        operation_id=event_id,
        operation_type=event_type,
        summary=mutation.summary,
        payload=dict(mutation.payload),
        files=journal_refs,
        actor_type=actor,
        compensates_operation_id=mutation.compensates,
    )
