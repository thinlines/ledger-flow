from __future__ import annotations

from pathlib import Path

from .custom_csv_service import normalize_custom_csv_to_intermediate
from .config_service import AppConfig
from .import_profile_service import resolve_import_source
from .parsers import registry
from .parsers.intermediate_writer import write_intermediate


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

    registry.discover()
    try:
        adapter = registry.get_adapter(institution_template_id)
    except KeyError:
        raise ValueError(
            f"No adapter registered for institution {institution_template_id!r}"
        )

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
    transactions.reverse()
    return write_intermediate(transactions)
