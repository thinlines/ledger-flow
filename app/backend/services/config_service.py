from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    config_toml: Path
    workspace: dict
    dirs: dict
    institution_templates: dict
    import_accounts: dict
    payee_aliases: str

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

    return AppConfig(
        root_dir=config_toml.parent.parent,
        config_toml=config_toml,
        workspace=raw.get("workspace", {}),
        dirs=raw["dirs"],
        institution_templates=raw.get("institution_templates", {}),
        import_accounts=raw.get("import_accounts", {}),
        payee_aliases=raw.get("payee_aliases", "payee_aliases.csv"),
    )
