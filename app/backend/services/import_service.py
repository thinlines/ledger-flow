from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .commodity_service import canonicalize_base_currency_posting
from .config_service import AppConfig
from .csv_normalizer import normalize_csv_to_intermediate
from .event_log_service import emit_event, rel_path
from .import_index import ImportIndex
from .import_identity_service import source_payload_hash_for_lines
from .import_profile_service import import_source_summary, resolve_import_source
from .ledger_runner import CommandError, run_cmd
from .payee_alias_service import ensure_payee_alias_dat
from .workspace_service import ensure_standard_commodities_file, ensure_workspace_journal_includes

_log = logging.getLogger(__name__)


INBOX_FILE_RE = re.compile(
    r"^(?P<year>\d{4})__(?P<import_account_id>[a-z0-9_]+)__(?P<label>.+)\.csv$"
)
from .header_parser import HEADER_RE

TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
POSTING_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
SOURCE_IDENTITY_KEY_RE = re.compile(r"^source_identity(?:_(?P<suffix>\d+))?$")
SOURCE_PAYLOAD_KEY_RE = re.compile(r"^source_payload_hash(?:_(?P<suffix>\d+))?$")
IMPORTER_VERSION = "mvp2"


@dataclass(frozen=True)
class ImportCandidate:
    file_name: str
    abs_path: str
    size_bytes: int
    mtime: float
    detected_year: str | None
    detected_import_account_id: str | None
    detected_institution_id: str | None
    is_configured_import_account: bool
    transaction_count: int | None = None
    date_range: tuple[str, str] | None = None


class ImportPreviewBlockedError(Exception):
    def __init__(
        self,
        message: str,
        *,
        csv_path: Path | None = None,
        file_kept_in_inbox: bool = False,
        code: str = "statement_preview_blocked",
        cause_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.csv_path = str(csv_path.resolve()) if csv_path is not None else None
        self.file_name = csv_path.name if csv_path is not None else None
        self.file_kept_in_inbox = file_kept_in_inbox
        self.cause_message = cause_message

    def as_detail(self) -> dict:
        detail: dict = {
            "code": self.code,
            "message": self.message,
            "csvPath": self.csv_path,
            "fileName": self.file_name,
            "fileKeptInInbox": self.file_kept_in_inbox,
        }
        if self.cause_message:
            detail["causeMessage"] = self.cause_message
        return detail


def _scan_csv_stats(
    config: AppConfig, csv_path: Path, account_cfg: dict
) -> tuple[int, tuple[str, str]] | tuple[None, None]:
    """Return (transaction_count, (min_date, max_date)) for a CSV file.

    Parses the file lightly using the existing adapter/profile infrastructure.
    Returns (None, None) on any failure so the caller can treat errors silently.
    """
    import csv as _csv

    try:
        source = resolve_import_source(config, account_cfg)
        dates: list[str] = []

        if source["mode"] == "custom":
            from .custom_csv_service import normalize_custom_csv_to_intermediate

            intermediate_text = normalize_custom_csv_to_intermediate(csv_path, source["profile"])
            reader = _csv.DictReader(intermediate_text.splitlines())
            for row in reader:
                d = (row.get("date") or "").strip()
                if d:
                    dates.append(d)
        else:
            from .parsers import registry

            institution_template_id = str(source["institution_id"])
            inst_cfg = config.institution_templates[institution_template_id]
            head = int(inst_cfg.get("head", 0))
            tail_cfg = inst_cfg.get("tail", 0)
            tail = int(tail_cfg) if tail_cfg else 0
            encoding = str(inst_cfg.get("encoding", "utf-8"))

            with csv_path.open("r", encoding=encoding) as f:
                lines = f.readlines()

            end_idx = -tail if tail else len(lines)
            sliced = lines[head:end_idx]

            registry.discover()
            adapter = registry.get_adapter(institution_template_id)
            records = list(adapter.parse("".join(sliced)))
            dates = [r.date.isoformat() for r in records]

        if not dates:
            return None, None

        return len(dates), (min(dates), max(dates))
    except Exception:
        return None, None


def scan_candidates(config: AppConfig) -> list[ImportCandidate]:
    rows: list[ImportCandidate] = []
    for csv_path in sorted(config.csv_dir.glob("*.csv")):
        m = INBOX_FILE_RE.match(csv_path.name)
        detected_year = m.group("year") if m else None
        detected_import_account_id = m.group("import_account_id") if m else None
        account_cfg = config.import_accounts.get(detected_import_account_id or "")
        detected_institution_id = None
        transaction_count = None
        date_range = None
        if account_cfg:
            detected_institution_id = import_source_summary(config, account_cfg).get("institution_id")
            transaction_count, date_range = _scan_csv_stats(config, csv_path, account_cfg)
        rows.append(
            ImportCandidate(
                file_name=csv_path.name,
                abs_path=str(csv_path.resolve()),
                size_bytes=csv_path.stat().st_size,
                mtime=csv_path.stat().st_mtime,
                detected_year=detected_year,
                detected_import_account_id=detected_import_account_id,
                detected_institution_id=detected_institution_id,
                is_configured_import_account=detected_import_account_id in config.import_accounts
                if detected_import_account_id
                else False,
                transaction_count=transaction_count,
                date_range=date_range,
            )
        )
    return rows


def _is_inbox_path(config: AppConfig, csv_path: Path) -> bool:
    try:
        return csv_path.resolve().is_relative_to(config.csv_dir.resolve())
    except OSError:
        return False


def _preview_blocked_message(
    config: AppConfig,
    import_account_id: str,
    *,
    file_kept_in_inbox: bool,
    was_inbox_path: bool,
) -> str:
    account_cfg = config.import_accounts.get(import_account_id, {})
    display_name = str(account_cfg.get("display_name") or import_account_id)
    if file_kept_in_inbox:
        return (
            f"This file doesn't look like it matches {display_name}. "
            "Choose the matching account and preview again, or remove this file from the inbox."
        )
    if was_inbox_path:
        return (
            f"This file doesn't look like it matches {display_name}. "
            "Choose the matching account and preview again. Nothing was added to the inbox."
        )
    return f"This file doesn't look like it matches {display_name}. Choose the matching account and preview again."


def preview_import_safely(
    config: AppConfig,
    csv_path: Path,
    year: str,
    import_account_id: str,
    *,
    keep_file_on_failure: bool,
) -> dict:
    was_inbox_path = _is_inbox_path(config, csv_path)
    try:
        return preview_import(config, csv_path, year, import_account_id)
    except (ValueError, CommandError) as e:
        if was_inbox_path and not keep_file_on_failure and csv_path.exists():
            try:
                csv_path.unlink()
            except OSError:
                pass
        file_kept_in_inbox = was_inbox_path and csv_path.exists()
        cause_message = str(e).strip() or None
        raise ImportPreviewBlockedError(
            _preview_blocked_message(
                config,
                import_account_id,
                file_kept_in_inbox=file_kept_in_inbox,
                was_inbox_path=was_inbox_path,
            ),
            csv_path=csv_path,
            file_kept_in_inbox=file_kept_in_inbox,
            cause_message=cause_message,
        ) from e


def remove_inbox_csv(config: AppConfig, csv_path: Path) -> str:
    if not csv_path.exists():
        raise FileNotFoundError(str(csv_path))
    if not _is_inbox_path(config, csv_path):
        raise ValueError("Only statements waiting in the inbox can be removed here.")

    resolved = csv_path.resolve()
    csv_path.unlink()
    return str(resolved)


def archive_inbox_csv(
    config: AppConfig,
    csv_path: Path,
    year: str,
    import_account_id: str,
    source_file_sha256: str,
) -> str | None:
    if not csv_path.exists():
        return None

    source = csv_path.resolve()
    inbox_dir = config.csv_dir.resolve()
    if not source.is_relative_to(inbox_dir):
        return None

    archive_dir = config.imports_dir / "processed" / year / import_account_id
    archive_dir.mkdir(parents=True, exist_ok=True)

    suffix = source.suffix or ".csv"
    digest = source_file_sha256[:12] if source_file_sha256 else "imported"
    dest = archive_dir / f"{source.stem}-{digest}{suffix}"
    if dest.exists():
        source.unlink()
        return str(dest.resolve())

    source.replace(dest)
    return str(dest.resolve())


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 64)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _split_transactions(journal_text: str) -> list[list[str]]:
    txns: list[list[str]] = []
    current: list[str] = []
    for raw in journal_text.splitlines():
        if TXN_START_RE.match(raw):
            if current:
                txns.append(current)
            current = [raw]
        elif current:
            current.append(raw)
    if current:
        txns.append(current)
    return txns


def _parse_posted_on(value: str) -> date:
    cleaned = value.strip().replace("/", "-")
    if not cleaned:
        raise ValueError("Imported transaction is missing a date")
    return date.fromisoformat(cleaned)


def _normalize_transaction_block(raw_text: str) -> list[str]:
    lines = raw_text.strip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _split_journal_preamble_and_transactions(journal_text: str) -> tuple[list[str], list[list[str]]]:
    lines = journal_text.splitlines()
    first_txn_idx = next((index for index, line in enumerate(lines) if TXN_START_RE.match(line)), len(lines))
    preamble = lines[:first_txn_idx]
    txns = _split_transactions("\n".join(lines[first_txn_idx:]))
    return preamble, [_normalize_transaction_block("\n".join(txn)) for txn in txns if txn]


def _transaction_block_posted_on(lines: list[str]) -> date:
    if not lines:
        raise ValueError("Imported transaction block is empty")
    header_match = HEADER_RE.match(lines[0])
    if not header_match:
        raise ValueError(f"Transaction header is missing a date: {lines[0]}")
    return _parse_posted_on(header_match.group("date"))


def _render_journal_text(preamble_lines: list[str], transaction_blocks: list[list[str]]) -> str:
    preamble_text = "\n".join(preamble_lines).rstrip()
    transaction_text = "\n\n".join("\n".join(block) for block in transaction_blocks if block)
    parts = [part for part in [preamble_text, transaction_text] if part]
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n"


def _merge_transaction_blocks(existing_blocks: list[list[str]], new_blocks: list[list[str]]) -> list[list[str]]:
    existing_dated = [(_transaction_block_posted_on(block), block) for block in existing_blocks]
    new_dated = sorted(
        [(_transaction_block_posted_on(block), block) for block in new_blocks],
        key=lambda item: item[0],
    )

    merged: list[list[str]] = []
    new_index = 0
    for existing_date, existing_block in existing_dated:
        while new_index < len(new_dated) and new_dated[new_index][0] < existing_date:
            merged.append(new_dated[new_index][1])
            new_index += 1
        merged.append(existing_block)

    merged.extend(block for _, block in new_dated[new_index:])
    return merged


def _normalize_payee(payee: str) -> str:
    return re.sub(r"\s+", " ", payee.strip().lower())


def _extract_institution_amount(postings: list[dict], institution_account: str) -> str:
    for p in postings:
        if p["account"] == institution_account:
            return re.sub(r"\s+", " ", p["amount"].strip())
    if postings:
        return re.sub(r"\s+", " ", postings[0]["amount"].strip())
    return ""


def _parse_transaction(
    lines: list[str],
    import_account_id: str,
    institution_account: str,
    *,
    base_currency: str,
) -> dict:
    header = lines[0]
    hm = HEADER_RE.match(header)
    if not hm:
        date = ""
        payee = ""
    else:
        date = hm.group("date").replace("-", "/")
        payee = hm.group("payee").strip()

    postings = []
    metadata = {}
    for line in lines[1:]:
        mm = META_RE.match(line)
        if mm:
            metadata[mm.group(1).strip().lower()] = mm.group(2).strip()
            continue
        pm = POSTING_RE.match(line)
        if pm:
            postings.append({"account": pm.group(2).strip(), "amount": pm.group(4).strip()})

    inst_amount = _extract_institution_amount(postings, institution_account)
    identity_base = "|".join([
        import_account_id,
        date,
        _normalize_payee(payee),
        inst_amount,
    ])
    source_identity = _sha256_text(identity_base)

    normalized_body = "\n".join(line.rstrip() for line in lines).strip() + "\n"
    source_payload_hash = source_payload_hash_for_lines(
        lines,
        institution_account,
        base_currency=base_currency,
    )

    return {
        "date": date,
        "payee": payee,
        "postings": postings,
        "raw": normalized_body,
        "metadata": metadata,
        "sourceIdentity": source_identity,
        "sourcePayloadHash": source_payload_hash,
    }


def _existing_identity_map_from_journal(config: AppConfig, target_journal: Path) -> dict[str, str | None]:
    if not target_journal.exists():
        return {}
    text = target_journal.read_text(encoding="utf-8")
    out: dict[str, str | None] = {}
    for lines in _split_transactions(text):
        identities_by_suffix: dict[str, str] = {}
        payloads_by_suffix: dict[str, str | None] = {}
        import_account_id = None
        for line in lines[1:]:
            mm = META_RE.match(line)
            if not mm:
                continue
            key = mm.group(1).strip().lower()
            value = mm.group(2).strip()
            identity_match = SOURCE_IDENTITY_KEY_RE.match(key)
            payload_match = SOURCE_PAYLOAD_KEY_RE.match(key)
            if identity_match:
                suffix = identity_match.group("suffix") or "1"
                identities_by_suffix[suffix] = value
            elif payload_match:
                suffix = payload_match.group("suffix") or "1"
                payloads_by_suffix[suffix] = value or None
            elif key == "import_account_id":
                import_account_id = value
        if identities_by_suffix:
            ledger_account = None
            if import_account_id:
                ledger_account = str(config.import_accounts.get(import_account_id, {}).get("ledger_account", "")).strip() or None
            computed_payload_hash = None
            if ledger_account:
                computed_payload_hash = source_payload_hash_for_lines(
                    lines,
                    ledger_account,
                    base_currency=str(config.workspace.get("base_currency", "USD")),
                )
            for suffix, source_identity in identities_by_suffix.items():
                if suffix == "1":
                    out[source_identity] = (
                        computed_payload_hash if computed_payload_hash is not None else payloads_by_suffix.get(suffix)
                    )
                else:
                    out[source_identity] = payloads_by_suffix.get(suffix)
    return out


def _classify_transaction(txn: dict, existing_map: dict[str, str | None]) -> str:
    existing_hash = existing_map.get(txn["sourceIdentity"])
    if existing_hash is None and txn["sourceIdentity"] not in existing_map:
        return "new"
    if existing_hash is None:
        return "duplicate"
    if existing_hash == txn["sourcePayloadHash"]:
        return "duplicate"
    return "conflict"


def _tracked_account_id_for_import_account(config: AppConfig, import_account_id: str) -> str | None:
    """Return the tracked-account id linked to *import_account_id*, if any."""
    if not import_account_id:
        return None
    import_cfg = config.import_accounts.get(import_account_id, {})
    direct = str(import_cfg.get("tracked_account_id") or "").strip()
    if direct:
        return direct
    # Fall back to scanning tracked_accounts for the back-link.
    for tracked_id, tracked_cfg in config.tracked_accounts.items():
        if str(tracked_cfg.get("import_account_id") or "").strip() == import_account_id:
            return tracked_id
    return None


def apply_reconciliation_fence(
    txns: list[dict],
    *,
    tracked_account_id: str | None,
    latest_dates: dict[str, date],
) -> None:
    """In-place: flip rows on/before the per-account reconciled date to conflicts.

    Adds two fields on every row to keep the response shape stable for the
    frontend:
    - ``conflictReason``: ``None`` for non-conflicts, ``"identity_collision"``
      for existing conflicts, ``"reconciled_date_fence"`` for new
      fence-triggered conflicts.
    - ``reconciledThrough``: ``None`` unless the fence triggered, then the
      iso-date string.

    *tracked_account_id* — when ``None`` (orphan import), the fence is skipped
    entirely and existing classifications are preserved.
    """
    fenced_through: date | None = (
        latest_dates.get(tracked_account_id) if tracked_account_id else None
    )

    for txn in txns:
        # Default: keep existing classification, no reason, no fence date.
        existing_status = txn.get("matchStatus")
        if existing_status == "conflict":
            txn.setdefault("conflictReason", "identity_collision")
            txn.setdefault("reconciledThrough", None)
            continue

        txn.setdefault("conflictReason", None)
        txn.setdefault("reconciledThrough", None)

        if fenced_through is None:
            continue

        raw_date = str(txn.get("date") or "").strip()
        if not raw_date:
            continue
        try:
            row_date = date.fromisoformat(raw_date.replace("/", "-"))
        except ValueError:
            continue
        if row_date <= fenced_through:
            txn["matchStatus"] = "conflict"
            txn["conflictReason"] = "reconciled_date_fence"
            txn["reconciledThrough"] = fenced_through.isoformat()


def _annotated_raw_txn(
    txn: dict,
    source_file_sha256: str,
    import_account_id: str,
    institution_template_id: str,
    *,
    base_currency: str,
) -> str:
    lines = txn["raw"].rstrip("\n").splitlines()
    if not lines:
        return ""

    existing_keys = set()
    for line in lines[1:]:
        mm = META_RE.match(line)
        if mm:
            existing_keys.add(mm.group(1).strip().lower())

    metadata_lines = []
    if "import_account_id" not in existing_keys:
        metadata_lines.append(f"    ; import_account_id: {import_account_id}")
    if "institution_template" not in existing_keys:
        metadata_lines.append(f"    ; institution_template: {institution_template_id}")
    if "source_identity" not in existing_keys:
        metadata_lines.append(f"    ; source_identity: {txn['sourceIdentity']}")
    if "source_payload_hash" not in existing_keys:
        metadata_lines.append(f"    ; source_payload_hash: {txn['sourcePayloadHash']}")
    if "source_file_sha256" not in existing_keys:
        metadata_lines.append(f"    ; source_file_sha256: {source_file_sha256}")
    if "importer_version" not in existing_keys:
        metadata_lines.append(f"    ; importer_version: {IMPORTER_VERSION}")

    out = [lines[0], *metadata_lines, *lines[1:]]
    return (
        "\n".join(canonicalize_base_currency_posting(line, base_currency) for line in out).rstrip()
        + "\n"
    )


def _build_existing_map(config: AppConfig, import_account_id: str, target_journal: Path) -> dict[str, str | None]:
    db = ImportIndex(config.root_dir / ".workflow" / "state.db")
    db_map = db.get_identity_map(import_account_id)
    journal_map = _existing_identity_map_from_journal(config, target_journal)

    merged = dict(db_map)
    for key, payload_hash in journal_map.items():
        if payload_hash is not None:
            merged[key] = payload_hash
        elif key not in merged:
            merged[key] = payload_hash
    return merged


def preview_import(
    config: AppConfig,
    csv_path: Path,
    year: str,
    import_account_id: str,
) -> dict:
    if import_account_id not in config.import_accounts:
        raise ValueError(f"Unknown import account: {import_account_id}")
    if not csv_path.exists():
        raise FileNotFoundError(str(csv_path))

    account_cfg = config.import_accounts[import_account_id]
    source = resolve_import_source(config, account_cfg)
    account = str(account_cfg["ledger_account"])
    date_fmt = (
        str(source["profile"].get("CSV_date_format") or "%Y/%m/%d")
        if source["mode"] == "institution"
        else "%Y/%m/%d"
    )

    ensure_payee_alias_dat(config)
    ensure_standard_commodities_file(config.init_dir / "13-commodities.dat", str(config.workspace.get("base_currency", "USD")))
    converted_csv = normalize_csv_to_intermediate(config, csv_path, account_cfg)

    year_journal = config.journal_dir / f"{year}.journal"
    if not year_journal.exists():
        year_journal.write_text("", encoding="utf-8")
    ensure_workspace_journal_includes(config)

    converted_journal = run_cmd(
        [
            "ledger",
            "-f",
            str(year_journal),
            "convert",
            "--invert",
            "--account",
            account,
            "--input-date-format",
            date_fmt,
            "--rich-data",
            "--permissive",
            "/dev/stdin",
        ],
        cwd=config.root_dir,
        stdin=converted_csv,
    )

    target_journal = config.journal_dir / f"{year}.journal"
    source_file_sha256 = _sha256_file(csv_path)

    txns = []
    existing_map = _build_existing_map(config, import_account_id, target_journal)
    base_currency = str(config.workspace.get("base_currency", "USD"))
    for lines in _split_transactions(converted_journal):
        txn = _parse_transaction(
            lines,
            import_account_id,
            account,
            base_currency=base_currency,
        )
        txn["matchStatus"] = _classify_transaction(txn, existing_map)
        if txn["matchStatus"] == "conflict":
            # Capture the journal-side payload hash so apply_import can emit a
            # diagnostic event for identity collisions without re-reading the
            # journal. None means the existing entry lacked a stored hash.
            txn["storedPayloadHash"] = existing_map.get(txn["sourceIdentity"])
        txn["annotatedRaw"] = _annotated_raw_txn(
            txn,
            source_file_sha256,
            import_account_id,
            str(source.get("institution_id") or source.get("profile_id") or "custom_csv"),
            base_currency=base_currency,
        )
        txns.append(txn)

    # Reconciled-date import fence — flip on-or-before-reconcile rows to
    # conflicts, attach stable conflictReason / reconciledThrough fields.
    from .reconciliation_service import latest_reconciliation_dates_by_tracked_id
    apply_reconciliation_fence(
        txns,
        tracked_account_id=_tracked_account_id_for_import_account(config, import_account_id),
        latest_dates=latest_reconciliation_dates_by_tracked_id(config),
    )

    new_txns = [t for t in txns if t["matchStatus"] == "new"]
    duplicate_txns = [t for t in txns if t["matchStatus"] == "duplicate"]
    fence_txns = [
        t for t in txns
        if t["matchStatus"] == "conflict" and t.get("conflictReason") == "reconciled_date_fence"
    ]
    collision_txns = [
        t for t in txns
        if t["matchStatus"] == "conflict" and t.get("conflictReason") != "reconciled_date_fence"
    ]

    return {
        "sourceFileSha256": source_file_sha256,
        "importAccountId": import_account_id,
        "destinationAccount": account,
        "importAccountDisplayName": account_cfg.get("display_name", import_account_id),
        "institutionTemplateId": source.get("institution_id"),
        "importMode": source["mode"],
        "importSourceDisplayName": source.get("display_name"),
        # Linked tracked account (if any) so the conflict-resolution view can
        # deep-link to /accounts/<id> for un-reconcile. None for orphan imports.
        "trackedAccountId": _tracked_account_id_for_import_account(config, import_account_id),
        "summary": {
            "count": len(txns),
            "unknownCount": converted_journal.count("Expenses:Unknown"),
            "newCount": len(new_txns),
            # Identity collisions fold into duplicateCount — both mean "already
            # imported, nothing to add" from the user's perspective. See
            # DECISIONS §21.
            "duplicateCount": len(duplicate_txns) + len(collision_txns),
            # fenceCount counts only reconciled_date_fence rows — the only
            # conflict reason the UI surfaces.
            "fenceCount": len(fence_txns),
        },
        # Render-ready fence rows for the conflict-resolution view. Only fence
        # conflicts appear here — identity collisions stay invisible to the UI.
        "conflicts": _build_fence_conflicts(txns, account),
        "preview": [t["annotatedRaw"].strip() for t in txns[:200]],
        "targetJournalPath": str(target_journal.resolve()),
        "preparedTransactions": txns,
    }


def _build_fence_conflicts(all_txns: list[dict], institution_account: str) -> list[dict]:
    """Render-ready dicts for reconciled-date-fence rows. Includes ``amount``
    so the conflict view can present them in transactions-register style.
    Identity-collision rows are excluded — they never reach the UI."""
    out: list[dict] = []
    for t in all_txns:
        if t.get("matchStatus") != "conflict":
            continue
        if t.get("conflictReason") != "reconciled_date_fence":
            continue
        out.append({
            "date": t.get("date"),
            "payee": t.get("payee"),
            "amount": _extract_institution_amount(t.get("postings") or [], institution_account),
            "sourceIdentity": t.get("sourceIdentity"),
            "conflictReason": t.get("conflictReason"),
            "reconciledThrough": t.get("reconciledThrough"),
        })
    return out


def apply_import(config: AppConfig, stage: dict) -> tuple[str, int, int, list[dict]]:
    target = Path(stage["targetJournalPath"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.touch()

    all_txns = stage.get("preparedTransactions", [])
    new_txns = [t for t in all_txns if t.get("matchStatus") == "new"]
    # The conflicts list returned to callers contains only reconciled-date-
    # fence rows — the only conflict reason the UI surfaces. Identity-collision
    # conflicts are silently skipped at write time (still excluded from
    # new_txns) and emit a diagnostic event for support visibility instead.
    # See DECISIONS §21.
    conflicts = _build_fence_conflicts(all_txns, stage.get("destinationAccount", ""))

    if new_txns:
        preamble_lines, existing_blocks = _split_journal_preamble_and_transactions(target.read_text(encoding="utf-8"))
        new_blocks = [_normalize_transaction_block(str(t["annotatedRaw"])) for t in new_txns]
        merged_blocks = _merge_transaction_blocks(existing_blocks, new_blocks)
        target.write_text(_render_journal_text(preamble_lines, merged_blocks), encoding="utf-8")

    db = ImportIndex(config.root_dir / ".workflow" / "state.db")
    db.upsert_transactions(
        import_account_id=stage["importAccountId"],
        year=stage["year"],
        journal_path=target,
        source_file_sha256=stage.get("sourceFileSha256", ""),
        txns=[
            {
                "sourceIdentity": t["sourceIdentity"],
                "sourcePayloadHash": t.get("sourcePayloadHash"),
            }
            for t in new_txns
        ],
    )

    # Skipped count folds duplicates + identity collisions: both are silent
    # non-writes from the user's perspective. Fence rows are reported via
    # the conflicts list, not the skipped count. See DECISIONS §21.
    skipped_count = sum(
        1
        for t in all_txns
        if t.get("matchStatus") == "duplicate"
        or (
            t.get("matchStatus") == "conflict"
            and t.get("conflictReason") != "reconciled_date_fence"
        )
    )

    # Diagnostic event per identity-collision row. Observability only —
    # never block or fail the import. See DECISIONS §21.
    _emit_identity_collision_events(
        config,
        target_journal=target,
        import_account_id=stage.get("importAccountId", ""),
        all_txns=all_txns,
    )

    return str(target.resolve()), len(new_txns), skipped_count, conflicts


def _emit_identity_collision_events(
    config: AppConfig,
    *,
    target_journal: Path,
    import_account_id: str,
    all_txns: list[dict],
) -> None:
    """Emit one ``import.identity_collision.v1`` per identity-collision row.

    Identity collisions are silently skipped at write time (excluded from
    new_txns) and never surface in the UI. Per DECISIONS §21 we log them
    to the event stream so support and debugging have a record of which
    rows the importer refused to overwrite, with both the stored and the
    newly-computed payload hashes for diff inspection.

    The function is fail-soft: any emission error is logged and discarded
    so a misbehaving event log cannot fail an otherwise-successful import.
    """
    journal_ref = rel_path(target_journal, config.root_dir)
    for txn in all_txns:
        if txn.get("matchStatus") != "conflict":
            continue
        if txn.get("conflictReason") != "identity_collision":
            continue
        try:
            emit_event(
                config.root_dir,
                event_type="import.identity_collision.v1",
                summary=(
                    f"Identity collision skipped: {txn.get('payee') or 'unknown payee'} "
                    f"on {txn.get('date') or 'unknown date'}"
                ),
                payload={
                    "import_account_id": import_account_id,
                    "source_identity": txn.get("sourceIdentity"),
                    "stored_payload_hash": txn.get("storedPayloadHash"),
                    "new_payload_hash": txn.get("sourcePayloadHash"),
                    "target_journal": journal_ref,
                    "date": txn.get("date"),
                    "payee": txn.get("payee"),
                },
                # Diagnostic, not a mutation: no journal_refs.
                journal_refs=[],
                actor="system",
            )
        except Exception:
            _log.warning(
                "Failed to emit import.identity_collision.v1 event for %s",
                txn.get("sourceIdentity"),
                exc_info=True,
            )
