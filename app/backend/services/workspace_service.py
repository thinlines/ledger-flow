from __future__ import annotations

import json
import re
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

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        return slug or "account"

    def _unique_account_id(self, base: str, used: set[str]) -> str:
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        return candidate

    def _infer_account_type(self, account: str) -> str:
        prefix = account.split(":", 1)[0].strip().lower()
        if prefix == "assets":
            return "Asset"
        if prefix in {"liabilities", "liability"}:
            return "Liability"
        if prefix in {"expenses", "expense"}:
            return "Expense"
        if prefix in {"income", "revenue"}:
            return "Income"
        if prefix in {"equity", "capital"}:
            return "Equity"
        return "Asset"

    def bootstrap_workspace(
        self,
        workspace_path: Path,
        workspace_name: str,
        base_currency: str,
        start_year: int,
        import_accounts: list[dict],
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
            f"name = {json.dumps(workspace_name)}",
            f"base_currency = {json.dumps(base_currency)}",
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

        normalized_accounts: list[dict] = []
        selected_templates: dict[str, object] = {}
        used_account_ids: set[str] = set()

        for raw in import_accounts:
            institution_id = str(raw.get("institutionId", "")).strip()
            template = get_template(institution_id)
            if template is None:
                raise ValueError(f"Unknown institution template: {institution_id}")

            display_name = str(raw.get("displayName", "")).strip()
            ledger_account = str(raw.get("ledgerAccount", "")).strip()
            if not display_name:
                raise ValueError("Import account display name is required")
            if not ledger_account:
                raise ValueError(f"Ledger account is required for {display_name}")

            last4 = str(raw.get("last4", "")).strip() or None

            base_id = self._slugify(display_name)
            if last4:
                base_id = f"{base_id}_{self._slugify(last4)}"

            normalized_accounts.append(
                {
                    "id": self._unique_account_id(base_id, used_account_ids),
                    "display_name": display_name,
                    "institution": institution_id,
                    "ledger_account": ledger_account,
                    "last4": last4,
                }
            )
            selected_templates[institution_id] = template

        for template_id, template in sorted(selected_templates.items(), key=lambda x: x[0]):
            cfg_lines.append(f"[institution_templates.{template_id}]")
            for k, v in template.as_config().items():
                if isinstance(v, str):
                    cfg_lines.append(f"{k} = {json.dumps(v)}")
                else:
                    cfg_lines.append(f"{k} = {v}")
            cfg_lines.append("")

        for account in normalized_accounts:
            cfg_lines.append(f"[import_accounts.{account['id']}]")
            cfg_lines.append(f"display_name = {json.dumps(account['display_name'])}")
            cfg_lines.append(f"institution = {json.dumps(account['institution'])}")
            cfg_lines.append(f"ledger_account = {json.dumps(account['ledger_account'])}")
            if account["last4"]:
                cfg_lines.append(f"last4 = {json.dumps(account['last4'])}")
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
            seeded_accounts: list[str] = []
            seen_accounts: set[str] = set()
            for account in normalized_accounts:
                ledger_account = account["ledger_account"]
                if ledger_account in seen_accounts:
                    continue
                seen_accounts.add(ledger_account)
                seeded_accounts.extend(
                    [
                        f"account {ledger_account}",
                        f"    ; type: {self._infer_account_type(ledger_account)}",
                    ]
                )

            seeded_accounts.extend(
                [
                    "account Expenses:Unknown",
                    "    ; type: Expense",
                ]
            )
            accounts_dat.write_text("\n".join(seeded_accounts) + "\n", encoding="utf-8")

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
