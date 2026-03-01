from __future__ import annotations

import csv
import importlib.util
import io
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .config_service import AppConfig


@lru_cache(maxsize=1)
def _load_create_bank_csv() -> Callable:
    scripts_dir = Path(__file__).resolve().parents[3] / "Scripts"
    bankcsv_path = scripts_dir / "BankCSV.py"
    spec = importlib.util.spec_from_file_location("bankcsv_module", bankcsv_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load BankCSV module from {bankcsv_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_bank_csv


def normalize_csv_to_intermediate(config: AppConfig, csv_path: Path, institution: str) -> str:
    if institution not in config.institutions:
        raise ValueError(f"Unknown institution: {institution}")

    inst_cfg = config.institutions[institution]
    head = int(inst_cfg.get("head", 0))
    tail_cfg = inst_cfg.get("tail", 0)
    tail = int(tail_cfg) if tail_cfg else 0
    encoding = str(inst_cfg.get("encoding", "utf-8"))

    create_bank_csv = _load_create_bank_csv()

    with csv_path.open("r", encoding=encoding) as f:
        lines = f.readlines()

    end_idx = -tail if tail else len(lines)
    sliced = lines[head:end_idx]

    create_cfg = {
        "institutions": {
            institution: {
                "parser": inst_cfg.get("parser", institution),
            }
        }
    }

    bank_csv = create_bank_csv(institution, sliced, create_cfg)
    reader = bank_csv.reader()

    output_rows = []
    for row in reader:
        output_rows.append(
            {
                "date": bank_csv.date(row),
                "code": bank_csv.code(row),
                "description": bank_csv.description(row),
                "amount": bank_csv.amount(row),
                "total": bank_csv.total(row),
                "note": bank_csv.note(row),
                "symbol": bank_csv.symbol(row),
                "price": bank_csv.price(row),
            }
        )

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=bank_csv.fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(reversed(output_rows))
    return out.getvalue()
