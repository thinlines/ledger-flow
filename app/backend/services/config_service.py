from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


def infer_account_kind(account: str) -> str:
    prefix = account.split(":", 1)[0].strip().lower()
    if prefix == "assets":
        return "asset"
    if prefix in {"liabilities", "liability"}:
        return "liability"
    if prefix in {"expenses", "expense"}:
        return "expense"
    if prefix in {"income", "revenue"}:
        return "income"
    if prefix in {"equity", "capital"}:
        return "equity"
    return "other"


def _derive_tracked_accounts(import_accounts: dict) -> dict:
    tracked_accounts: dict[str, dict] = {}
    for import_account_id, account_cfg in import_accounts.items():
        tracked_account_id = str(account_cfg.get("tracked_account_id", "")).strip() or import_account_id
        tracked_accounts.setdefault(
            tracked_account_id,
            {
                "display_name": account_cfg.get("display_name", tracked_account_id),
                "ledger_account": account_cfg.get("ledger_account", ""),
                "institution": account_cfg.get("institution"),
                "last4": account_cfg.get("last4"),
                "import_account_id": import_account_id,
            },
        )
    return tracked_accounts


def _normalized_tracked_accounts(raw_tracked_accounts: dict, import_accounts: dict) -> dict:
    tracked_accounts = {
        account_id: dict(account_cfg)
        for account_id, account_cfg in raw_tracked_accounts.items()
    }

    for account_cfg in tracked_accounts.values():
        account_cfg.setdefault("import_account_id", None)

    for import_account_id, import_account_cfg in import_accounts.items():
        tracked_account_id = str(import_account_cfg.get("tracked_account_id", "")).strip() or import_account_id
        tracked_account_cfg = tracked_accounts.setdefault(
            tracked_account_id,
            {
                "display_name": import_account_cfg.get("display_name", tracked_account_id),
                "ledger_account": import_account_cfg.get("ledger_account", ""),
            },
        )
        tracked_account_cfg.setdefault("import_account_id", import_account_id)
        tracked_account_cfg.setdefault("institution", import_account_cfg.get("institution"))
        tracked_account_cfg.setdefault("last4", import_account_cfg.get("last4"))
        tracked_account_cfg.setdefault("display_name", import_account_cfg.get("display_name", tracked_account_id))
        tracked_account_cfg.setdefault("ledger_account", import_account_cfg.get("ledger_account", ""))

    return tracked_accounts


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    config_toml: Path
    workspace: dict
    dirs: dict
    institution_templates: dict
    import_accounts: dict
    tracked_accounts: dict = field(default_factory=dict)
    payee_aliases: str = "payee_aliases.csv"

    @property
    def name(self) -> str:
        return str(self.workspace.get("name", "Workspace"))

    @property
    def start_year(self) -> int:
        return int(self.workspace.get("start_year", 2026))

    @property
    def csv_dir(self) -> Path:
        return self.root_dir / self.dirs["csv_dir"]

    @property
    def journal_dir(self) -> Path:
        return self.root_dir / self.dirs["journal_dir"]

    @property
    def init_dir(self) -> Path:
        return self.root_dir / self.dirs["init_dir"]

    @property
    def opening_bal_dir(self) -> Path:
        return self.root_dir / self.dirs["opening_bal_dir"]

    @property
    def imports_dir(self) -> Path:
        return self.root_dir / self.dirs["imports_dir"]


def load_config(config_toml: Path) -> AppConfig:
    with config_toml.open("rb") as f:
        raw = tomllib.load(f)

    import_accounts = raw.get("import_accounts", {})
    raw_tracked_accounts = raw.get("tracked_accounts")
    tracked_accounts = (
        _normalized_tracked_accounts(raw_tracked_accounts, import_accounts)
        if raw_tracked_accounts is not None
        else _derive_tracked_accounts(import_accounts)
    )

    return AppConfig(
        root_dir=config_toml.parent.parent,
        config_toml=config_toml,
        workspace=raw.get("workspace", {}),
        dirs=raw["dirs"],
        institution_templates=raw.get("institution_templates", {}),
        import_accounts=import_accounts,
        tracked_accounts=tracked_accounts,
        payee_aliases=raw.get("payee_aliases", "payee_aliases.csv"),
    )
