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
    dirs: dict
    institutions: dict
    payee_aliases: str

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


def load_config(root_dir: Path) -> AppConfig:
    config_toml = root_dir / "config.toml"
    with config_toml.open("rb") as f:
        raw = tomllib.load(f)

    return AppConfig(
        root_dir=root_dir,
        config_toml=config_toml,
        dirs=raw["dirs"],
        institutions=raw["institutions"],
        payee_aliases=raw["payee_aliases"],
    )
