"""Statement reconciliation: writer, fence lookup, and read-side failure detection.

Reconciliation is recorded as a single zero-amount transaction with a balance
assertion on the asserted account's posting.  This module owns the journal
write (assertion is always last on its date in the file), the post-write
verification via ``ledger bal --strict``, the lookup that powers the
import fence, and the read-side detection of broken assertions surfaced in
account/dashboard responses.

The journal text remains the source of truth.  This service never persists a
second copy of any reconciliation state — every read recomputes from the
journal.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid7

from .config_service import AppConfig
from .journal_query_service import TXN_START_RE
from .ledger_runner import CommandError, run_cmd
from .manual_entry_service import _format_currency_amount

logger = logging.getLogger(__name__)


# Caller-facing constants
RECONCILE_HEADER_PREFIX = "Statement reconciliation"

# Match `; reconciliation_event_id: <id>` on a metadata line.
_RECON_EVENT_ID_RE = re.compile(r"^\s*;\s*reconciliation_event_id\s*:\s*(\S.*?)\s*$")
_STATEMENT_PERIOD_RE = re.compile(
    r"^\s*;\s*statement_period\s*:\s*(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})\s*$"
)

# Match a posting line with an explicit balance assertion: `<account> <amount> = <balance>`.
# Group 1 is the account name (whitespace-padded), group 2 is the asserted balance text.
_ASSERTION_POSTING_RE = re.compile(
    r"^\s+(?P<account>[^\s].*?)\s{2,}\S.*?=\s*(?P<balance>\S.+?)\s*$"
)

# Ledger balance-assertion error.  Real ledger output looks like:
#   Error: Balance assertion off by $-12.57 (expected to see $2,500.00)
# and is preceded by a `While parsing file "<path>", line <N>:` block.
_LEDGER_ASSERTION_FILE_LINE_RE = re.compile(
    r'While parsing file "(?P<file>[^"]+)", line (?P<line>\d+)'
)
_LEDGER_ASSERTION_OFFSET_RE = re.compile(
    r"Balance assertion off by\s+(?P<off>\S+)\s+\(expected to see\s+(?P<expected>\S.+?)\)",
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssertionWriteResult:
    """Successful reconciliation write outcome."""

    journal_path: Path
    journal_rel: str
    header_line: str
    line_number: int
    event_id: str


@dataclass(frozen=True)
class AssertionFailure:
    """Structured ledger assertion failure surfaced by the writer or detector."""

    expected: str | None
    actual: str | None
    raw_error: str
    file: str | None = None
    line: int | None = None


# ---------------------------------------------------------------------------
# Currency parsing — reuses the same shape as manual_entry_service
# ---------------------------------------------------------------------------


def parse_closing_balance(raw: str) -> Decimal:
    """Parse a user-supplied closing balance string into a Decimal.

    Accepts the same shapes as the manual-entry currency parser: optional
    leading ``$`` sign, comma group separators, optional minus sign.
    """
    cleaned = (raw or "").strip().lstrip("$").replace(",", "")
    if not cleaned:
        raise ValueError(f"Invalid closing balance: {raw!r}")
    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(f"Invalid closing balance: {raw!r}") from e


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _format_assertion_balance(amount: Decimal, currency: str) -> str:
    """Format a balance for the right-hand side of `<acct>  $0 = $...`."""
    return _format_currency_amount(amount, currency)


def _format_zero(currency: str) -> str:
    """Compact zero amount for the assertion posting (`$0` for USD).

    The spec calls this out explicitly: ``<ledger_account>  $0 = $<balance>``.
    Ledger accepts either ``$0`` or ``$0.00`` — we use the spec form.
    """
    if (currency or "").upper() == "USD":
        return "$0"
    return f"0 {currency}"


def _build_assertion_block(
    *,
    period_start: date,
    period_end: date,
    closing_balance: Decimal,
    currency: str,
    display_name: str,
    ledger_account: str,
    event_id: str,
) -> list[str]:
    period_end_iso = period_end.isoformat()
    period_start_iso = period_start.isoformat()
    header = (
        f"{period_end_iso} * {RECONCILE_HEADER_PREFIX} · "
        f"{display_name} · ending {period_end_iso}"
    )
    posting = (
        f"    {ledger_account}  {_format_zero(currency)} = "
        f"{_format_assertion_balance(closing_balance, currency)}"
    )
    return [
        header,
        f"    ; reconciliation_event_id: {event_id}",
        f"    ; statement_period: {period_start_iso}..{period_end_iso}",
        posting,
    ]


def _find_block_end(lines: list[str], start: int) -> int:
    """Return the exclusive end index of the transaction block starting at *start*."""
    end = start + 1
    while end < len(lines) and not TXN_START_RE.match(lines[end]):
        end += 1
    return end


def _insertion_index_for_date(lines: list[str], target_date: str) -> int:
    """Return the index in *lines* where the new block should be inserted.

    The new block becomes the last transaction with date ``target_date`` in
    file order.  If no transaction with that date exists, the block is placed
    after the last transaction with date < ``target_date``.  If every
    transaction in the file is later than ``target_date``, insert at the start
    (before the first transaction header).  Otherwise, append at end of file.
    """
    last_same_date_end = -1
    last_earlier_date_end = -1
    first_later_start = -1
    for i, line in enumerate(lines):
        if not TXN_START_RE.match(line):
            continue
        block_date = line[:10]
        block_end = _find_block_end(lines, i)
        if block_date == target_date:
            last_same_date_end = block_end
        elif block_date < target_date:
            last_earlier_date_end = block_end
        elif first_later_start == -1:
            first_later_start = i

    if last_same_date_end != -1:
        return last_same_date_end
    if last_earlier_date_end != -1:
        return last_earlier_date_end
    if first_later_start != -1:
        return first_later_start
    return len(lines)


def _splice_block(lines: list[str], insert_idx: int, block: list[str]) -> tuple[list[str], int]:
    """Insert *block* into *lines* with appropriate blank-line padding.

    Returns ``(new_lines, header_line_index_zero_based)``.

    Rules:
    - If inserting at the start of file (``insert_idx == 0``), no leading blank.
    - Otherwise ensure exactly one blank line precedes the block.
    - Ensure exactly one blank line follows the block when more content follows
      (don't introduce a trailing blank at end-of-file beyond the existing pattern).
    """
    new_lines = list(lines)

    # Ensure leading blank when not inserting at file start.
    if insert_idx > 0:
        # Count back through any trailing blanks that already exist before
        # ``insert_idx`` so we end up with exactly one separator blank.
        while insert_idx > 0 and new_lines[insert_idx - 1].strip() == "":
            insert_idx -= 1
        new_lines[insert_idx:insert_idx] = ["", *block]
        header_idx = insert_idx + 1
        # If the next line (originally at insert_idx + len(block) + 1) is the
        # start of another transaction, ensure a blank between them.
        after = header_idx + len(block)
        if after < len(new_lines) and new_lines[after].strip() != "":
            new_lines.insert(after, "")
    else:
        new_lines[0:0] = list(block)
        header_idx = 0
        after = len(block)
        if after < len(new_lines) and new_lines[after].strip() != "":
            new_lines.insert(after, "")
    return new_lines, header_idx


def _write_lines(path: Path, lines: list[str], original_text: str | None) -> None:
    text = "\n".join(lines)
    # Preserve trailing newline if the file already had one or is brand new.
    if original_text is None:
        text = text + "\n"
    elif original_text.endswith("\n") or original_text == "":
        text = text + "\n"
    path.write_text(text, encoding="utf-8")


def write_assertion_transaction(
    *,
    config: AppConfig,
    tracked_account_cfg: dict,
    period_start: date,
    period_end: date,
    closing_balance: Decimal,
    currency: str,
    event_id: str | None = None,
) -> tuple[AssertionWriteResult, Path]:
    """Write the reconciliation assertion to the year-derived journal file.

    Returns ``(result, backup_path)``.  The caller is responsible for verifying
    the assertion via :func:`verify_assertion` and rolling back from
    *backup_path* if verification fails.

    *event_id* lets the caller pre-allocate the id so the same value can be
    written into the journal metadata and re-used when emitting the event.
    """
    ledger_account = str(tracked_account_cfg.get("ledger_account", "")).strip()
    if not ledger_account:
        raise ValueError("Tracked account is missing a ledger account.")

    display_name = (
        str(tracked_account_cfg.get("display_name", "")).strip()
        or ledger_account
    )

    if event_id is None:
        event_id = str(uuid7())

    year = f"{period_end.year:04d}"
    journal_path = config.journal_dir / f"{year}.journal"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    if not journal_path.exists():
        journal_path.write_text("", encoding="utf-8")

    # Backup BEFORE any mutation so we can roll back on verification failure.
    from .backup_service import backup_file  # local import keeps import graph tidy
    backup_path = backup_file(journal_path, "reconcile")

    original_text = journal_path.read_text(encoding="utf-8")
    original_lines = original_text.splitlines()

    block = _build_assertion_block(
        period_start=period_start,
        period_end=period_end,
        closing_balance=closing_balance,
        currency=currency,
        display_name=display_name,
        ledger_account=ledger_account,
        event_id=event_id,
    )

    insert_idx = _insertion_index_for_date(original_lines, period_end.isoformat())
    new_lines, header_idx = _splice_block(original_lines, insert_idx, block)

    _write_lines(journal_path, new_lines, original_text or None)

    journal_rel = str(journal_path.resolve().relative_to(config.root_dir.resolve()))
    return (
        AssertionWriteResult(
            journal_path=journal_path,
            journal_rel=journal_rel,
            header_line=block[0],
            # Zero-indexed offset of the header line in the file — matches the
            # contract used by ``locate_header_at`` so the API consumer can
            # round-trip into the existing transaction.delete handler.
            line_number=header_idx,
            event_id=event_id,
        ),
        backup_path,
    )


def restore_from_backup(journal_path: Path, backup_path: Path) -> None:
    """Restore *journal_path* from *backup_path* byte-for-byte."""
    shutil.copyfile(str(backup_path), str(journal_path))


# ---------------------------------------------------------------------------
# Verification (post-write)
# ---------------------------------------------------------------------------


def _journal_files(config: AppConfig) -> list[Path]:
    """Return all year journals as a sorted list (excluding the archive sidecar)."""
    if not config.journal_dir.is_dir():
        return []
    from .archive_service import ARCHIVED_MANUAL_JOURNAL_NAME

    return [
        p
        for p in sorted(config.journal_dir.glob("*.journal"))
        if p.name != ARCHIVED_MANUAL_JOURNAL_NAME
    ]


def _ledger_strict_args(config: AppConfig) -> list[str]:
    """Build the ``ledger -f ... -f ... bal --strict`` argument list."""
    args = ["ledger"]
    for journal in _journal_files(config):
        args.extend(["-f", str(journal)])
    args.extend(["bal", "--strict"])
    return args


def _parse_ledger_assertion_failure(stderr_text: str) -> AssertionFailure | None:
    """Parse a ledger ``Balance assertion off by`` failure string.

    Returns ``None`` when the error doesn't look like an assertion failure.
    """
    if not stderr_text or "Balance assertion off by" not in stderr_text:
        return None

    expected: str | None = None
    actual: str | None = None
    file: str | None = None
    line: int | None = None

    file_match = _LEDGER_ASSERTION_FILE_LINE_RE.search(stderr_text)
    if file_match:
        file = file_match.group("file")
        try:
            line = int(file_match.group("line"))
        except ValueError:
            line = None

    offset_match = _LEDGER_ASSERTION_OFFSET_RE.search(stderr_text)
    if offset_match:
        # Ledger's wording is the inverse of ours: its "expected to see" is the
        # journal-derived balance (our ``actual``), and ``assertion = actual +
        # off`` recovers the user-asserted balance (our ``expected``).
        actual = offset_match.group("expected").strip()
        off_raw = offset_match.group("off").strip()
        expected = _compute_assertion_from_actual_and_offset(actual, off_raw)

    return AssertionFailure(
        expected=expected,
        actual=actual,
        raw_error=stderr_text.strip(),
        file=file,
        line=line,
    )


def _strip_currency(text: str) -> tuple[str, Decimal | None]:
    """Return ``(prefix, decimal_value)`` for a currency-formatted text.

    Best-effort: returns ``(text, None)`` when parsing fails.  The prefix
    captures whatever non-digit/non-sign text leads the value (typically ``$``)
    so we can re-apply it when reformatting.
    """
    if not text:
        return "", None
    leading = ""
    rest = text
    while rest and rest[0] in "$£€¥":
        leading += rest[0]
        rest = rest[1:]
    cleaned = rest.replace(",", "").strip()
    try:
        return leading, Decimal(cleaned)
    except InvalidOperation:
        return text, None


def _compute_assertion_from_actual_and_offset(actual: str, off: str) -> str | None:
    """Given ledger's ``expected to see`` (real balance) and ``off`` strings, derive the user assertion.

    Ledger reports ``off = assertion - actual``, so ``assertion = actual + off``.
    Returns ``None`` when either side cannot be parsed as a decimal.
    """
    actual_prefix, actual_value = _strip_currency(actual)
    _, off_value = _strip_currency(off)
    if actual_value is None or off_value is None:
        return None
    assertion_value = actual_value + off_value
    sign = "-" if assertion_value < 0 else ""
    return f"{sign}{actual_prefix}{abs(assertion_value):,.2f}"


def verify_assertion(config: AppConfig) -> AssertionFailure | None:
    """Run ``ledger bal --strict`` and parse any assertion failure.

    Returns:
    - ``None`` when the strict balance check passes.
    - An :class:`AssertionFailure` when ledger reports a balance-assertion
      error (parsed) or when ledger fails for any other reason (raw_error
      preserved, expected/actual ``None``).

    Raises ``RuntimeError`` only when ledger is unavailable on the host (the
    caller treats that as a write failure but with a distinct copy).
    """
    args = _ledger_strict_args(config)
    if len(args) <= 3:  # only ['ledger', 'bal', '--strict'] — no journal files
        return None
    try:
        run_cmd(args, cwd=config.root_dir)
    except FileNotFoundError as exc:
        # ledger CLI missing entirely.  Surface as runtime error so the
        # endpoint can return a 500 with an explicit message.
        raise RuntimeError("ledger CLI is unavailable") from exc
    except CommandError as exc:
        stderr = str(exc)
        parsed = _parse_ledger_assertion_failure(stderr)
        if parsed is not None:
            return parsed
        return AssertionFailure(expected=None, actual=None, raw_error=stderr)
    return None


# ---------------------------------------------------------------------------
# Latest-reconciliation lookup (powers the import fence)
# ---------------------------------------------------------------------------


def _scan_journal_for_assertions(path: Path) -> list[dict]:
    """Yield every reconciliation-marked assertion in *path*.

    Returns dicts with ``date``, ``ledger_account``, ``event_id``,
    ``period_start``, ``period_end``.  Only transactions carrying a
    ``reconciliation_event_id`` metadata line count — hand-written assertions
    are intentionally excluded from the fence per the plan.
    """
    if not path.is_file():
        return []

    out: list[dict] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    starts = [i for i, line in enumerate(lines) if TXN_START_RE.match(line)]
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        block = lines[start:end]

        event_id: str | None = None
        period_start: str | None = None
        period_end: str | None = None
        assertion_account: str | None = None

        for raw in block[1:]:
            event_match = _RECON_EVENT_ID_RE.match(raw)
            if event_match:
                event_id = event_match.group(1).strip()
                continue
            period_match = _STATEMENT_PERIOD_RE.match(raw)
            if period_match:
                period_start = period_match.group(1)
                period_end = period_match.group(2)
                continue
            posting_match = _ASSERTION_POSTING_RE.match(raw)
            if posting_match and assertion_account is None:
                assertion_account = posting_match.group("account").strip()

        if event_id and assertion_account:
            out.append({
                "date": block[0][:10].replace("/", "-"),
                "ledger_account": assertion_account,
                "event_id": event_id,
                "period_start": period_start,
                "period_end": period_end,
                "journal_path": path,
            })
    return out


def _latest_dates_by_ledger_account(config: AppConfig) -> dict[str, date]:
    """Return ``{ledger_account: most_recent_reconciled_date}`` across all journals."""
    latest: dict[str, date] = {}
    for journal in _journal_files(config):
        for entry in _scan_journal_for_assertions(journal):
            try:
                d = date.fromisoformat(entry["date"])
            except ValueError:
                continue
            account = entry["ledger_account"]
            existing = latest.get(account)
            if existing is None or d > existing:
                latest[account] = d
    return latest


def latest_reconciliation_date(config: AppConfig, ledger_account: str) -> date | None:
    """Return the most recent reconciled date for *ledger_account*, or None.

    Only assertions written by the reconcile flow (carrying
    ``reconciliation_event_id``) count.  Hand-written assertions are
    intentionally excluded — they participate in failure detection but not in
    the import fence.
    """
    target = (ledger_account or "").strip()
    if not target:
        return None
    return _latest_dates_by_ledger_account(config).get(target)


def latest_reconciliation_dates_by_tracked_id(config: AppConfig) -> dict[str, date]:
    """Return ``{tracked_account_id: most_recent_reconciled_date}``.

    Used by the import fence to avoid re-scanning journals once per row.
    """
    by_account = _latest_dates_by_ledger_account(config)
    out: dict[str, date] = {}
    for tracked_id, cfg in config.tracked_accounts.items():
        ledger_account = str(cfg.get("ledger_account", "")).strip()
        if not ledger_account:
            continue
        d = by_account.get(ledger_account)
        if d is not None:
            out[tracked_id] = d
    return out


# ---------------------------------------------------------------------------
# Read-side failure detection
# ---------------------------------------------------------------------------


def reconciliation_status(config: AppConfig) -> dict[str, dict]:
    """Run a single ledger strict check and translate failures by tracked account.

    Result shape: ``{tracked_account_id: {"ok": True}}`` or
    ``{tracked_account_id: {"ok": False, "broken": {...}}}``.

    Accounts with no failures (and accounts the user has not configured) get
    ``{"ok": True}``.  Orphaned assertions on ledger accounts that no tracked
    account currently maps to are logged but never crash the lookup.

    If the ledger CLI is missing or fails for a non-assertion reason, every
    account is reported ``{"ok": True}`` — failure detection is data, not copy,
    and the caller decides whether to surface "last verified" hints.
    """
    out: dict[str, dict] = {tid: {"ok": True} for tid in config.tracked_accounts.keys()}

    args = _ledger_strict_args(config)
    if len(args) <= 3:
        return out

    try:
        run_cmd(args, cwd=config.root_dir)
        return out
    except FileNotFoundError:
        logger.warning("ledger CLI is unavailable — skipping reconciliation_status")
        return out
    except CommandError as exc:
        stderr = str(exc)

    failures = _parse_all_assertion_failures(stderr)
    if not failures:
        # Non-assertion ledger error — log and report all-ok rather than
        # painting every account as broken.
        logger.warning("ledger strict check failed but no assertion errors parsed: %s", stderr[:200])
        return out

    ledger_to_tracked = _ledger_account_to_tracked_id(config)

    for failure in failures:
        ledger_account, assertion_date = _resolve_failed_assertion_account(failure)
        if not ledger_account:
            logger.warning("Could not attribute ledger assertion failure to an account: %s", failure.raw_error[:200])
            continue
        tracked_id = ledger_to_tracked.get(ledger_account)
        if tracked_id is None:
            logger.warning("Orphaned reconciliation failure on %s — no tracked account maps to it", ledger_account)
            continue
        out[tracked_id] = {
            "ok": False,
            "broken": {
                "date": assertion_date,
                "expected": failure.expected,
                "actual": failure.actual,
                "rawError": failure.raw_error,
            },
        }
    return out


def _ledger_account_to_tracked_id(config: AppConfig) -> dict[str, str]:
    out: dict[str, str] = {}
    for tracked_id, cfg in config.tracked_accounts.items():
        ledger_account = str(cfg.get("ledger_account", "")).strip()
        if ledger_account and ledger_account not in out:
            out[ledger_account] = tracked_id
    return out


def _parse_all_assertion_failures(stderr_text: str) -> list[AssertionFailure]:
    """Split the stderr into per-failure chunks and parse each.

    Ledger emits one failure block per failed assertion.  Blocks are separated
    by blank lines or by the next ``While parsing file`` header.  We do a
    simple scan: each ``Balance assertion off by`` line yields one failure,
    and we attach the most recent ``While parsing file`` context to it.
    """
    if not stderr_text:
        return []

    failures: list[AssertionFailure] = []
    current_file: str | None = None
    current_line: int | None = None
    for raw in stderr_text.splitlines():
        file_match = _LEDGER_ASSERTION_FILE_LINE_RE.search(raw)
        if file_match:
            current_file = file_match.group("file")
            try:
                current_line = int(file_match.group("line"))
            except ValueError:
                current_line = None
            continue
        offset_match = _LEDGER_ASSERTION_OFFSET_RE.search(raw)
        if offset_match:
            actual = offset_match.group("expected").strip()
            off_raw = offset_match.group("off").strip()
            expected = _compute_assertion_from_actual_and_offset(actual, off_raw)
            failures.append(
                AssertionFailure(
                    expected=expected,
                    actual=actual,
                    raw_error=raw.strip(),
                    file=current_file,
                    line=current_line,
                )
            )
    return failures


def _resolve_failed_assertion_account(failure: AssertionFailure) -> tuple[str | None, str | None]:
    """Read the journal at ``failure.file:line`` and return the asserted account + date.

    The line number ledger reports points at the asserting posting.  We walk
    upward from there to find the transaction header (date prefix).
    """
    if not failure.file or failure.line is None:
        return None, None
    path = Path(failure.file)
    if not path.is_file():
        return None, None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None

    line_idx = failure.line - 1
    if line_idx < 0 or line_idx >= len(lines):
        return None, None

    posting_match = _ASSERTION_POSTING_RE.match(lines[line_idx])
    ledger_account = posting_match.group("account").strip() if posting_match else None

    assertion_date: str | None = None
    for j in range(line_idx, -1, -1):
        if TXN_START_RE.match(lines[j]):
            assertion_date = lines[j][:10].replace("/", "-")
            break

    return ledger_account, assertion_date
