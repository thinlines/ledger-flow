from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .config_service import AppConfig
from .ledger_runner import run_cmd


YEAR_INST_RE = re.compile(r"^(?P<year>\d{4})-(?P<institution>[^.]+)\.csv$")
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")


@dataclass(frozen=True)
class ImportCandidate:
    file_name: str
    abs_path: str
    size_bytes: int
    mtime: float
    detected_year: str | None
    detected_institution: str | None
    is_configured_institution: bool


def scan_candidates(config: AppConfig) -> list[ImportCandidate]:
    rows: list[ImportCandidate] = []
    for csv_path in sorted(config.csv_dir.glob("*.csv")):
        m = YEAR_INST_RE.match(csv_path.name)
        detected_year = m.group("year") if m else None
        detected_inst = m.group("institution") if m else None
        rows.append(
            ImportCandidate(
                file_name=csv_path.name,
                abs_path=str(csv_path.resolve()),
                size_bytes=csv_path.stat().st_size,
                mtime=csv_path.stat().st_mtime,
                detected_year=detected_year,
                detected_institution=detected_inst,
                is_configured_institution=detected_inst in config.institutions if detected_inst else False,
            )
        )
    return rows


def _generate_payees(config: AppConfig) -> None:
    alias_csv = config.init_dir / config.payee_aliases
    alias_dat = config.init_dir / f"{Path(config.payee_aliases).stem}.dat"
    run_cmd(
        [sys.executable, "Scripts/generate_payees.py", "-o", str(alias_dat), str(alias_csv)],
        cwd=config.root_dir,
    )


def _txn_count(journal_text: str) -> int:
    return sum(1 for line in journal_text.splitlines() if TXN_START_RE.match(line))


def preview_import(config: AppConfig, csv_path: Path, year: str, institution: str) -> dict:
    if institution not in config.institutions:
        raise ValueError(f"Unknown institution: {institution}")
    if not csv_path.exists():
        raise FileNotFoundError(str(csv_path))

    institution_cfg = config.institutions[institution]
    account = institution_cfg["account"]
    date_fmt = institution_cfg["CSV_date_format"]

    _generate_payees(config)

    converted_csv = run_cmd(
        [sys.executable, "Scripts/convert_csv.py", str(csv_path), institution],
        cwd=config.root_dir,
    )

    converted_journal = run_cmd(
        [
            "ledger",
            "-f",
            f"{year}.journal",
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

    txns = []
    current = []
    for line in converted_journal.splitlines():
        if TXN_START_RE.match(line) and current:
            txns.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        txns.append("\n".join(current))

    return {
        "convertedJournal": converted_journal,
        "summary": {
            "count": _txn_count(converted_journal),
            "unknownCount": converted_journal.count("Expenses:Unknown"),
        },
        "preview": txns[:200],
        "targetJournalPath": str((config.journal_dir / f"{year}-{institution}.journal").resolve()),
    }


def apply_import(config: AppConfig, stage: dict) -> tuple[str, int]:
    target = Path(stage["targetJournalPath"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.touch()

    fragment = stage["convertedJournal"].strip()
    with target.open("a", encoding="utf-8") as f:
        if target.stat().st_size > 0:
            f.write("\n\n")
        f.write(fragment)
        f.write("\n")

    dat_files = sorted(config.init_dir.glob("*.dat"))
    args = ["ledger"]
    for dat in dat_files:
        args.extend(["-f", str(dat)])
    args.extend(["-f", str(target), "--permissive", "print"])
    normalized = run_cmd(args, cwd=config.root_dir)
    target.write_text(normalized, encoding="utf-8")

    return str(target.resolve()), _txn_count(fragment)
