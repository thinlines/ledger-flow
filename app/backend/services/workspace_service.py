from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config_service import AppConfig, load_config
from .institution_registry import get_template


@dataclass(frozen=True)
class WorkspaceManager:
    app_root: Path

    @property
    def state_path(self) -> Path:
        return self.app_root / ".workflow" / "app_state.json"

    def _ensure_state_dir(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def get_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def set_active_workspace(self, workspace_path: Path) -> None:
        self._ensure_state_dir()
        payload = {"workspacePath": str(workspace_path.resolve())}
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_active_workspace_path(self) -> Path | None:
        state = self.get_state()
        raw = state.get("workspacePath")
        if not raw:
            return None
        return Path(raw)

    def load_active_config(self) -> AppConfig | None:
        workspace = self.get_active_workspace_path()
        if workspace is None:
            return None
        config_path = workspace / "settings" / "workspace.toml"
        if not config_path.exists():
            return None
        return load_config(config_path)

    def bootstrap_workspace(
        self,
        workspace_path: Path,
        workspace_name: str,
        base_currency: str,
        start_year: int,
        institutions: list[str],
    ) -> Path:
        root = workspace_path.resolve()
        settings = root / "settings"
        journals = root / "journals"
        inbox = root / "inbox"
        rules = root / "rules"
        opening = root / "opening"
        imports = root / "imports"

        for d in [settings, journals, inbox, rules, opening, imports]:
            d.mkdir(parents=True, exist_ok=True)

        cfg_lines = [
            f'payee_aliases = "payee_aliases.csv"',
            "",
            "[workspace]",
            f'name = "{workspace_name}"',
            f'base_currency = "{base_currency}"',
            f"start_year = {start_year}",
            "",
            "[dirs]",
            'csv_dir = "inbox"',
            'journal_dir = "journals"',
            'init_dir = "rules"',
            'opening_bal_dir = "opening"',
            'imports_dir = "imports"',
            "",
        ]

        for inst in institutions:
            template = get_template(inst)
            if template is None:
                continue
            cfg_lines.append(f"[institutions.{inst}]")
            for k, v in template.as_config().items():
                if isinstance(v, str):
                    cfg_lines.append(f'{k} = "{v}"')
                else:
                    cfg_lines.append(f"{k} = {v}")
            cfg_lines.append("")

        (settings / "workspace.toml").write_text("\n".join(cfg_lines).rstrip() + "\n", encoding="utf-8")

        (imports / "import-log.ndjson").touch(exist_ok=True)

        payee_alias_csv = rules / "payee_aliases.csv"
        if not payee_alias_csv.exists():
            payee_alias_csv.write_text("payee,alias\n", encoding="utf-8")

        match_rules = rules / "20-match-rules.ndjson"
        if not match_rules.exists():
            match_rules.write_text("", encoding="utf-8")

        accounts_dat = rules / "10-accounts.dat"
        if not accounts_dat.exists():
            accounts_dat.write_text(
                "\n".join(
                    [
                        "account Assets:Bank:Checking",
                        "    ; type: Cash",
                        "account Assets:Bank:Savings",
                        "    ; type: Cash",
                        "account Assets:Alipay",
                        "    ; type: Cash",
                        "account Assets:Investments:Schwab",
                        "    ; type: Asset",
                        "account Liabilities:Credit Card",
                        "    ; type: Liability",
                        "account Expenses:Unknown",
                        "    ; type: Expense",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

        tags_dat = rules / "12-tags.dat"
        if not tags_dat.exists():
            tags_dat.write_text("tag Imported\ntag UUID\n", encoding="utf-8")

        commodities_dat = rules / "13-commodities.dat"
        if not commodities_dat.exists():
            commodities_dat.write_text(
                f"commodity {base_currency}\n\tformat {base_currency}1,000.00\n",
                encoding="utf-8",
            )

        year_journal = journals / f"{start_year}.journal"
        if not year_journal.exists():
            year_journal.write_text(
                "\n".join(
                    [
                        f"; {workspace_name} financial journal",
                        "; Generated by Ledger Flow setup",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

        self.set_active_workspace(root)
        return root
