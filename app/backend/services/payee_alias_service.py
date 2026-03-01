from __future__ import annotations

import csv
from pathlib import Path

from .config_service import AppConfig


def ensure_payee_alias_dat(config: AppConfig) -> Path:
    alias_csv = config.init_dir / config.payee_aliases
    alias_dat = config.init_dir / f"{Path(config.payee_aliases).stem}.dat"

    config.init_dir.mkdir(parents=True, exist_ok=True)
    if not alias_csv.exists():
        alias_csv.write_text("payee,alias\n", encoding="utf-8")

    aliases: dict[str, list[str]] = {}
    with alias_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            payee = (row.get("payee") or "").strip()
            alias = (row.get("alias") or "").strip()
            if not payee or not alias:
                continue
            aliases.setdefault(payee, []).append(alias)

    lines: list[str] = []
    for payee in sorted(aliases.keys()):
        lines.append(f"payee {payee}")
        for alias in sorted(set(aliases[payee])):
            lines.append(f"\talias {alias}")

    alias_dat.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return alias_dat
