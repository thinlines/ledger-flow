from __future__ import annotations

import csv
import importlib.util
import io
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .custom_csv_service import normalize_custom_csv_to_intermediate
from .config_service import AppConfig
from .import_profile_service import resolve_import_source
from .parsers import registry
from .parsers.intermediate_writer import write_intermediate


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


def normalize_csv_to_intermediate(config: AppConfig, csv_path: Path, account_cfg: dict) -> str:
    source = resolve_import_source(config, account_cfg)
    if source["mode"] == "custom":
        return normalize_custom_csv_to_intermediate(csv_path, source["profile"])

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

    # --- Dispatch seam: registered adapters take priority over legacy BankCSV ---
    registry.discover()
    try:
        adapter = registry.get_adapter(institution_template_id)
    except KeyError:
        adapter = None

    if adapter is not None:
        translator_name = getattr(adapter, "translator_name", None)
        if translator_name is None:
            raise RuntimeError(
                f"Adapter {adapter.name!r} did not declare translator_name; "
                f"cannot route without an explicit translator"
            )
        translator = registry.get_translator(translator_name)
        account = str(account_cfg["ledger_account"])

        text = "".join(sliced)
        records = adapter.parse(text)
        transactions = [translator.translate(r, account) for r in records]
        # Legacy pipeline reverses output rows; preserve that for byte-exact parity.
        transactions.reverse()
        return write_intermediate(transactions)

    # --- Legacy fallback for institutions without a registered adapter ---
    create_bank_csv = _load_create_bank_csv()

    create_cfg = {
        "institutions": {
            institution_template_id: {
                "parser": inst_cfg.get("parser", institution_template_id),
            }
        }
    }

    bank_csv = create_bank_csv(institution_template_id, sliced, create_cfg)
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
