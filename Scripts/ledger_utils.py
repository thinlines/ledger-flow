#!/usr/bin/env python3
"""Shared helpers for ledger-backed tools."""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from typing import Dict, List, Optional, Tuple


_AMOUNT_RE = re.compile(r"[+-]?[\d,]+(?:\.\d+)?")
_HEADER_LINE_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")

_file_cache: Dict[str, List[str]] = {}
_backup_made: Dict[Tuple[str, str], str] = {}


def run_ledger(ledger_bin: str, args: List[str]) -> str:
    proc = subprocess.run(
        [ledger_bin] + args,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(msg if msg else f"ledger failed: {proc.returncode}")
    return proc.stdout


def parse_amount(s: str) -> float:
    raw = s.strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = f"-{raw[1:-1]}"
    raw = raw.replace("$", "")
    m = _AMOUNT_RE.search(raw)
    if not m:
        raise ValueError(f"bad amount: {s}")
    return float(m.group(0).replace(",", ""))


def parse_first_number(s: str) -> Optional[float]:
    m = _AMOUNT_RE.search(s)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def is_header_line(line: str) -> bool:
    return bool(_HEADER_LINE_RE.match(line))


def read_lines(path: str) -> List[str]:
    if path not in _file_cache:
        with open(path, "r", encoding="utf-8") as f:
            _file_cache[path] = f.readlines()
    return _file_cache[path]


def write_lines(path: str, lines: List[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    _file_cache[path] = lines


def clear_cache() -> None:
    _file_cache.clear()


def ensure_backup(path: str, tag: str) -> str:
    key = (path, tag)
    if key in _backup_made:
        return _backup_made[key]
    ts = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    backup = f"{path}.{tag}.bak.{ts}"
    with open(path, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    _backup_made[key] = backup
    return backup


def find_header_line_no(filename: str, near_line_no: int) -> int:
    lines = read_lines(filename)
    i = min(max(near_line_no - 1, 0), len(lines) - 1)
    while i >= 0:
        if is_header_line(lines[i]):
            return i + 1
        i -= 1
    return 1


def register_rows(
    ledger_bin: str,
    ledger_file: str,
    account: str,
    begin_date: Optional[str],
    end_date: Optional[str],
) -> List[Tuple[str, int, str, str, str, str]]:
    fmt = "%(filename)\t%(beg_line)\t%(date)\t%(status)\t%(payee)\t%(amount)\n"
    args = [
        "-f", ledger_file,
        "register", account,
        "--register-format", fmt,
        "--no-color",
    ]
    if begin_date:
        args += ["--begin", begin_date]
    if end_date:
        args += ["--end", end_date]
    out = run_ledger(ledger_bin, args)
    rows: List[Tuple[str, int, str, str, str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        fn, beg, date, status, payee, amt = parts
        try:
            beg_i = int(beg)
        except ValueError:
            continue
        rows.append((fn, beg_i, date, status, payee, amt))
    return rows
