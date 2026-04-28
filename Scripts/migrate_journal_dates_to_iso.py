#!/usr/bin/env python3
"""Migrate transaction header dates from `YYYY/MM/DD` to `YYYY-MM-DD` (ISO 8601).

Idempotent: re-running on an already-ISO journal is a no-op (no backup, no rewrite).

Scope
-----
- Targets `workspace/journals/*.journal` and `workspace/opening/*.journal`.
- Skips any file matching `*.bak.*` (historical backups stay slash-formatted).
- Only mutates lines whose first ten characters look like `YYYY/MM/DD` followed
  by whitespace — i.e., transaction headers anchored at the start of a line.
  Metadata comments (e.g., `; CSV: 2026/01/01,...`) are untouched.

Usage
-----
    python Scripts/migrate_journal_dates_to_iso.py [WORKSPACE_DIR]

If WORKSPACE_DIR is omitted, the script defaults to the `workspace/` directory
adjacent to the repository root (i.e., the parent of this script's directory).
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

HEADER_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})(\s)", flags=re.MULTILINE)


def _is_backup(path: Path) -> bool:
    return ".bak." in path.name


def _migrate_file(path: Path) -> tuple[bool, int]:
    """Migrate a single file. Return ``(was_modified, replacement_count)``.

    Writes a `<name>.iso-migration.bak.<timestamp>` backup before mutating.
    """
    text = path.read_text(encoding="utf-8")
    new_text, count = HEADER_RE.subn(r"\1-\2-\3\4", text)
    if count == 0 or new_text == text:
        return False, 0

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.iso-migration.bak.{timestamp}")
    shutil.copy2(str(path), str(backup))
    path.write_text(new_text, encoding="utf-8")
    return True, count


def _candidate_files(workspace_dir: Path) -> list[Path]:
    targets: list[Path] = []
    for sub in ("journals", "opening"):
        directory = workspace_dir / sub
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.journal")):
            if _is_backup(path):
                continue
            targets.append(path)
    return targets


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print("usage: migrate_journal_dates_to_iso.py [WORKSPACE_DIR]", file=sys.stderr)
        return 2

    if len(argv) == 2:
        workspace_dir = Path(argv[1]).resolve()
    else:
        workspace_dir = Path(__file__).resolve().parent.parent / "workspace"

    if not workspace_dir.is_dir():
        print(f"workspace directory not found: {workspace_dir}", file=sys.stderr)
        return 1

    files = _candidate_files(workspace_dir)
    if not files:
        print(f"No journal files found under {workspace_dir}.")
        return 0

    modified: list[tuple[Path, int]] = []
    skipped: list[Path] = []

    for path in files:
        try:
            changed, count = _migrate_file(path)
        except OSError as exc:
            print(f"  ERROR: failed to migrate {path}: {exc}", file=sys.stderr)
            return 1
        if changed:
            modified.append((path, count))
            print(f"  migrated {path} ({count} header(s))")
        else:
            skipped.append(path)

    print()
    print(f"Summary: {len(modified)} migrated, {len(skipped)} already ISO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
