from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .config_service import AppConfig
from .csv_normalizer import normalize_csv_to_intermediate
from .import_index import ImportIndex
from .import_profile_service import import_source_summary, resolve_import_source
from .ledger_runner import run_cmd
from .payee_alias_service import ensure_payee_alias_dat
from .workspace_service import ensure_journal_includes, ensure_standard_commodities_file


INBOX_FILE_RE = re.compile(
    r"^(?P<year>\d{4})__(?P<import_account_id>[a-z0-9_]+)__(?P<label>.+)\.csv$"
)
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
HEADER_RE = re.compile(
    r"^(?P<date>\d{4}[-/]\d{2}[-/]\d{2})"
    r"(?:\s+[*!])?"
    r"(?:\s+\([^)]+\))?"
    r"\s*(?P<payee>.*)$"
)
POSTING_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
IMPORTER_VERSION = "mvp2"
TRAILING_SYMBOL_COMMODITY_RE = re.compile(r"(?P<amount>-?\d+(?:\.\d+)?)(?:\s+)(?P<symbol>[$€£¥])(?=(?:\s|$))")


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


def scan_candidates(config: AppConfig) -> list[ImportCandidate]:
    rows: list[ImportCandidate] = []
    for csv_path in sorted(config.csv_dir.glob("*.csv")):
        m = INBOX_FILE_RE.match(csv_path.name)
        detected_year = m.group("year") if m else None
        detected_import_account_id = m.group("import_account_id") if m else None
        account_cfg = config.import_accounts.get(detected_import_account_id or "")
        detected_institution_id = None
        if account_cfg:
            detected_institution_id = import_source_summary(config, account_cfg).get("institution_id")
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
            )
        )
    return rows


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


def _normalize_payee(payee: str) -> str:
    return re.sub(r"\s+", " ", payee.strip().lower())


def _extract_institution_amount(postings: list[dict], institution_account: str) -> str:
    for p in postings:
        if p["account"] == institution_account:
            return re.sub(r"\s+", " ", p["amount"].strip())
    if postings:
        return re.sub(r"\s+", " ", postings[0]["amount"].strip())
    return ""


def _parse_transaction(lines: list[str], import_account_id: str, institution_account: str) -> dict:
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
    source_payload_hash = _sha256_text(normalized_body)

    return {
        "date": date,
        "payee": payee,
        "postings": postings,
        "raw": normalized_body,
        "metadata": metadata,
        "sourceIdentity": source_identity,
        "sourcePayloadHash": source_payload_hash,
    }


def _existing_identity_map_from_journal(target_journal: Path) -> dict[str, str | None]:
    if not target_journal.exists():
        return {}
    text = target_journal.read_text(encoding="utf-8")
    out: dict[str, str | None] = {}
    for lines in _split_transactions(text):
        source_identity = None
        source_payload_hash = None
        for line in lines[1:]:
            mm = META_RE.match(line)
            if not mm:
                continue
            key = mm.group(1).strip().lower()
            value = mm.group(2).strip()
            if key == "source_identity":
                source_identity = value
            elif key == "source_payload_hash":
                source_payload_hash = value
        if source_identity:
            out[source_identity] = source_payload_hash
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


def _annotated_raw_txn(
    txn: dict,
    source_file_sha256: str,
    import_account_id: str,
    institution_template_id: str,
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
    return _normalize_symbol_commodity_display("\n".join(out).rstrip() + "\n")


def _normalize_symbol_commodity_display(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"{match.group('symbol')}{match.group('amount')}"

    return TRAILING_SYMBOL_COMMODITY_RE.sub(repl, text)


def _build_existing_map(config: AppConfig, import_account_id: str, target_journal: Path) -> dict[str, str | None]:
    db = ImportIndex(config.root_dir / ".workflow" / "state.db")
    db_map = db.get_identity_map(import_account_id)
    journal_map = _existing_identity_map_from_journal(target_journal)

    merged = dict(db_map)
    for key, payload_hash in journal_map.items():
        if key not in merged:
            merged[key] = payload_hash
        elif merged[key] is None and payload_hash is not None:
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
    ensure_journal_includes(year_journal)

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
    for lines in _split_transactions(converted_journal):
        txn = _parse_transaction(lines, import_account_id, account)
        txn["matchStatus"] = _classify_transaction(txn, existing_map)
        txn["annotatedRaw"] = _annotated_raw_txn(
            txn,
            source_file_sha256,
            import_account_id,
            str(source.get("institution_id") or source.get("profile_id") or "custom_csv"),
        )
        txns.append(txn)

    new_txns = [t for t in txns if t["matchStatus"] == "new"]
    duplicate_txns = [t for t in txns if t["matchStatus"] == "duplicate"]
    conflict_txns = [t for t in txns if t["matchStatus"] == "conflict"]

    return {
        "sourceFileSha256": source_file_sha256,
        "importAccountId": import_account_id,
        "destinationAccount": account,
        "importAccountDisplayName": account_cfg.get("display_name", import_account_id),
        "institutionTemplateId": source.get("institution_id"),
        "importMode": source["mode"],
        "importSourceDisplayName": source.get("display_name"),
        "summary": {
            "count": len(txns),
            "unknownCount": converted_journal.count("Expenses:Unknown"),
            "newCount": len(new_txns),
            "duplicateCount": len(duplicate_txns),
            "conflictCount": len(conflict_txns),
        },
        "preview": [t["annotatedRaw"].strip() for t in txns[:200]],
        "targetJournalPath": str(target_journal.resolve()),
        "preparedTransactions": txns,
    }


def apply_import(config: AppConfig, stage: dict) -> tuple[str, int, int, list[dict]]:
    target = Path(stage["targetJournalPath"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.touch()

    all_txns = stage.get("preparedTransactions", [])
    new_txns = [t for t in all_txns if t.get("matchStatus") == "new"]
    conflicts = [
        {
            "date": t.get("date"),
            "payee": t.get("payee"),
            "sourceIdentity": t.get("sourceIdentity"),
        }
        for t in all_txns
        if t.get("matchStatus") == "conflict"
    ]

    if new_txns:
        with target.open("a", encoding="utf-8") as f:
            if target.stat().st_size > 0:
                f.write("\n\n")
            f.write("\n\n".join(t["annotatedRaw"].strip() for t in new_txns))
            f.write("\n")

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

    return str(target.resolve()), len(new_txns), len([t for t in all_txns if t.get("matchStatus") == "duplicate"]), conflicts
