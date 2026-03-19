from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config_service import AppConfig, load_config
from .custom_csv_service import normalize_custom_profile
from .import_identity_service import source_payload_hash_for_lines
from .import_index import ImportIndex
from .institution_registry import get_template
from .opening_balance_service import opening_balance_index, write_opening_balance

TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
JOURNAL_INCLUDE_LINES = (
    "include ../rules/10-accounts.dat",
    "include ../rules/12-tags.dat",
    "include ../rules/13-commodities.dat",
)
BASE_CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
}


def standard_commodity_blocks(base_currency: str) -> list[tuple[str, list[str]]]:
    currency = str(base_currency or "USD").strip().upper() or "USD"
    blocks: list[tuple[str, list[str]]] = [
        (
            currency,
            [
                f"commodity {currency}",
                f"\tformat {currency}1,000.00",
            ],
        )
    ]
    symbol = BASE_CURRENCY_SYMBOLS.get(currency)
    if symbol:
        blocks.append(
            (
                symbol,
                [
                    f"commodity {symbol}",
                    f"\tformat {symbol}1,000.00",
                ],
            )
        )
    return blocks


def ensure_standard_commodities_file(commodities_path: Path, base_currency: str) -> None:
    existing_lines = commodities_path.read_text(encoding="utf-8").splitlines() if commodities_path.exists() else []
    existing_text = "\n".join(existing_lines)
    blocks_to_append: list[list[str]] = []

    for commodity_name, block_lines in standard_commodity_blocks(base_currency):
        if f"commodity {commodity_name}" in existing_text:
            continue
        blocks_to_append.append(block_lines)

    if not commodities_path.exists() and not blocks_to_append:
        return

    lines = list(existing_lines)
    for block_lines in blocks_to_append:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block_lines)

    if not commodities_path.exists() and not lines:
        return

    text = "\n".join(lines).rstrip() + "\n"
    if commodities_path.exists() and commodities_path.read_text(encoding="utf-8") == text:
        return

    commodities_path.parent.mkdir(parents=True, exist_ok=True)
    commodities_path.write_text(text, encoding="utf-8")


def ensure_journal_includes(journal_path: Path) -> None:
    existing_lines = journal_path.read_text(encoding="utf-8").splitlines() if journal_path.exists() else []
    include_set = set(JOURNAL_INCLUDE_LINES)
    filtered_lines = [line for line in existing_lines if line.strip() not in include_set]

    normalized_lines: list[str] = [*JOURNAL_INCLUDE_LINES]
    if filtered_lines:
        if filtered_lines[0].strip():
            normalized_lines.append("")
        normalized_lines.extend(filtered_lines)

    text = "\n".join(normalized_lines).rstrip() + "\n"
    if journal_path.exists() and journal_path.read_text(encoding="utf-8") == text:
        return

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(text, encoding="utf-8")


def _iter_transaction_ranges(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, line in enumerate(lines) if TXN_START_RE.match(line)]
    ranges: list[tuple[int, int]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        ranges.append((start, end))
    return ranges


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

    def get_setup_state(self, config: AppConfig | None) -> dict:
        if config is None:
            return {
                "needsWorkspace": True,
                "needsAccounts": False,
                "needsFirstImport": False,
                "needsReview": False,
                "hasImportedActivity": False,
                "currentStep": "workspace",
                "completedSteps": [],
            }

        has_accounts = bool(config.import_accounts)
        has_imported_activity = self._has_imported_activity(config)
        needs_accounts = not has_accounts
        needs_first_import = has_accounts and not has_imported_activity
        needs_review = has_imported_activity and self._has_unknown_activity(config)

        completed_steps = ["workspace"]
        if has_accounts:
            completed_steps.append("accounts")
        if has_imported_activity:
            completed_steps.append("import")
        if has_imported_activity and not needs_review:
            completed_steps.append("review")

        if needs_accounts:
            current_step = "accounts"
        elif needs_first_import:
            current_step = "import"
        elif needs_review:
            current_step = "review"
        else:
            current_step = "done"

        return {
            "needsWorkspace": False,
            "needsAccounts": needs_accounts,
            "needsFirstImport": needs_first_import,
            "needsReview": needs_review,
            "hasImportedActivity": has_imported_activity,
            "currentStep": current_step,
            "completedSteps": completed_steps,
        }

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

    def _has_imported_activity(self, config: AppConfig) -> bool:
        for journal_path in sorted(config.journal_dir.glob("*.journal")):
            if not journal_path.exists():
                continue
            with journal_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if TXN_START_RE.match(line):
                        return True
        return False

    def _has_unknown_activity(self, config: AppConfig) -> bool:
        for journal_path in sorted(config.journal_dir.glob("*.journal")):
            if not journal_path.exists():
                continue
            if "Expenses:Unknown" in journal_path.read_text(encoding="utf-8"):
                return True
        return False

    def _toml_value(self, value: str | int | bool) -> str:
        if isinstance(value, str):
            return json.dumps(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _clean_optional_string(self, value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def _ledger_suffix(self, institution_display_name: str, display_name: str) -> str:
        candidate = display_name.strip()
        template_name = institution_display_name.strip()
        if template_name and candidate.lower().startswith(template_name.lower()):
            remainder = candidate[len(template_name):].strip(" :-_")
            if remainder:
                candidate = remainder
        parts = [part.title() for part in re.split(r"[^A-Za-z0-9]+", candidate) if part]
        return ":".join(parts) or "Account"

    def _suggest_ledger_account(
        self,
        institution_id: str,
        display_name: str,
        last4: str | None,
        existing_import_accounts: dict[str, dict] | None = None,
        existing_account_id: str | None = None,
    ) -> str:
        template = get_template(institution_id)
        if template is None:
            raise ValueError(f"Unknown institution template: {institution_id}")

        candidate = f"{template.suggested_ledger_prefix}:{self._ledger_suffix(template.display_name, display_name)}"
        if not last4 or not existing_import_accounts:
            return candidate

        existing_targets = {
            str(account_cfg.get("ledger_account", "")).strip()
            for account_id, account_cfg in existing_import_accounts.items()
            if account_id != existing_account_id
        }
        if candidate in existing_targets:
            return f"{candidate}:{last4}"
        return candidate

    def _normalize_import_account(
        self,
        raw: dict,
        used_account_ids: set[str],
        existing_import_accounts: dict[str, dict] | None = None,
        existing_account_id: str | None = None,
    ) -> tuple[dict, object]:
        institution_id = self._clean_optional_string(raw.get("institutionId")) or ""
        template = get_template(institution_id)
        if template is None:
            raise ValueError(f"Unknown institution template: {institution_id}")

        display_name = self._clean_optional_string(raw.get("displayName")) or ""
        if not display_name:
            raise ValueError("Import account display name is required")

        last4 = self._clean_optional_string(raw.get("last4"))
        ledger_account = self._clean_optional_string(raw.get("ledgerAccount")) or ""
        if not ledger_account:
            ledger_account = self._suggest_ledger_account(
                institution_id,
                display_name,
                last4,
                existing_import_accounts=existing_import_accounts,
                existing_account_id=existing_account_id,
            )

        base_id = self._slugify(display_name)
        if last4:
            base_id = f"{base_id}_{self._slugify(last4)}"

        return (
            {
                "id": existing_account_id or self._unique_account_id(base_id, used_account_ids),
                "display_name": display_name,
                "institution": institution_id,
                "ledger_account": ledger_account,
                "last4": last4,
            },
            template,
        )

    def _normalize_custom_import_profile(
        self,
        raw: dict,
        *,
        default_currency: str,
        default_display_name: str,
    ) -> dict:
        profile_raw = raw.get("customProfile") or {}
        if not profile_raw:
            raise ValueError("Custom import accounts require a CSV profile")

        return normalize_custom_profile(
            {
                "display_name": profile_raw.get("displayName"),
                "encoding": profile_raw.get("encoding"),
                "delimiter": profile_raw.get("delimiter"),
                "skip_rows": profile_raw.get("skipRows"),
                "skip_footer_rows": profile_raw.get("skipFooterRows"),
                "reverse_order": profile_raw.get("reverseOrder", True),
                "date_column": profile_raw.get("dateColumn"),
                "date_format": profile_raw.get("dateFormat"),
                "description_column": profile_raw.get("descriptionColumn"),
                "secondary_description_column": profile_raw.get("secondaryDescriptionColumn"),
                "amount_mode": profile_raw.get("amountMode"),
                "amount_column": profile_raw.get("amountColumn"),
                "debit_column": profile_raw.get("debitColumn"),
                "credit_column": profile_raw.get("creditColumn"),
                "balance_column": profile_raw.get("balanceColumn"),
                "code_column": profile_raw.get("codeColumn"),
                "note_column": profile_raw.get("noteColumn"),
                "currency": profile_raw.get("currency"),
            },
            default_currency=default_currency,
            default_display_name=default_display_name,
        )

    def _normalize_custom_import_account(
        self,
        raw: dict,
        used_account_ids: set[str],
        *,
        default_currency: str,
        existing_account_id: str | None = None,
    ) -> tuple[dict, dict]:
        display_name = self._clean_optional_string(raw.get("displayName")) or ""
        if not display_name:
            raise ValueError("Import account display name is required")

        ledger_account = self._clean_optional_string(raw.get("ledgerAccount")) or ""
        if not ledger_account or ":" not in ledger_account:
            raise ValueError("Custom import accounts require a ledger account")

        last4 = self._clean_optional_string(raw.get("last4"))
        base_id = self._slugify(display_name)
        if last4:
            base_id = f"{base_id}_{self._slugify(last4)}"

        account_id = existing_account_id or self._unique_account_id(base_id, used_account_ids)
        profile = self._normalize_custom_import_profile(
            raw,
            default_currency=default_currency,
            default_display_name=f"{display_name} CSV",
        )

        return (
            {
                "id": account_id,
                "display_name": display_name,
                "institution": None,
                "ledger_account": ledger_account,
                "last4": last4,
                "import_profile_id": account_id,
            },
            profile,
        )

    def _normalize_tracked_account(
        self,
        raw: dict,
        used_account_ids: set[str],
        existing_account_id: str | None = None,
    ) -> dict:
        display_name = self._clean_optional_string(raw.get("displayName")) or ""
        if not display_name:
            raise ValueError("Tracked account display name is required")

        ledger_account = self._clean_optional_string(raw.get("ledgerAccount")) or ""
        if not ledger_account or ":" not in ledger_account:
            raise ValueError("Tracked account ledger account is required")

        institution_id = self._clean_optional_string(raw.get("institutionId"))
        if institution_id and get_template(institution_id) is None:
            raise ValueError(f"Unknown institution template: {institution_id}")

        last4 = self._clean_optional_string(raw.get("last4"))

        base_id = self._slugify(display_name)
        if last4:
            base_id = f"{base_id}_{self._slugify(last4)}"

        return {
            "id": existing_account_id or self._unique_account_id(base_id, used_account_ids),
            "display_name": display_name,
            "ledger_account": ledger_account,
            "institution": institution_id,
            "last4": last4,
            "import_account_id": raw.get("importAccountId"),
        }

    def _tracked_account_from_import_account(
        self,
        tracked_account_id: str,
        import_account_id: str,
        account_cfg: dict,
    ) -> dict:
        return {
            "display_name": account_cfg.get("display_name", tracked_account_id),
            "ledger_account": account_cfg.get("ledger_account", ""),
            "institution": account_cfg.get("institution"),
            "last4": account_cfg.get("last4"),
            "import_account_id": import_account_id,
        }

    def _write_workspace_config(
        self,
        config_toml: Path,
        *,
        payee_aliases: str,
        workspace: dict,
        dirs: dict,
        institution_templates: dict[str, dict],
        import_profiles: dict[str, dict],
        tracked_accounts: dict[str, dict],
        import_accounts: dict[str, dict],
    ) -> None:
        cfg_lines = [
            f"payee_aliases = {json.dumps(payee_aliases)}",
            "",
            "[workspace]",
            f"name = {json.dumps(str(workspace.get('name', 'Workspace')))}",
            f"base_currency = {json.dumps(str(workspace.get('base_currency', 'USD')))}",
            f"start_year = {int(workspace.get('start_year', 2026))}",
            "",
            "[dirs]",
            f"csv_dir = {json.dumps(str(dirs['csv_dir']))}",
            f"journal_dir = {json.dumps(str(dirs['journal_dir']))}",
            f"init_dir = {json.dumps(str(dirs['init_dir']))}",
            f"opening_bal_dir = {json.dumps(str(dirs['opening_bal_dir']))}",
            f"imports_dir = {json.dumps(str(dirs['imports_dir']))}",
            "",
        ]

        for template_id, template_cfg in sorted(institution_templates.items(), key=lambda item: item[0]):
            cfg_lines.append(f"[institution_templates.{template_id}]")
            for key, value in template_cfg.items():
                cfg_lines.append(f"{key} = {self._toml_value(value)}")
            cfg_lines.append("")

        for profile_id, profile_cfg in sorted(import_profiles.items(), key=lambda item: item[0]):
            cfg_lines.append(f"[import_profiles.{profile_id}]")
            for key, value in profile_cfg.items():
                if value is None:
                    continue
                cfg_lines.append(f"{key} = {self._toml_value(value)}")
            cfg_lines.append("")

        for account_id, account_cfg in sorted(tracked_accounts.items(), key=lambda item: item[0]):
            cfg_lines.append(f"[tracked_accounts.{account_id}]")
            cfg_lines.append(f"display_name = {json.dumps(str(account_cfg.get('display_name', account_id)))}")
            cfg_lines.append(f"ledger_account = {json.dumps(str(account_cfg.get('ledger_account', '')))}")
            institution = str(account_cfg.get("institution") or "").strip()
            if institution:
                cfg_lines.append(f"institution = {json.dumps(institution)}")
            last4 = str(account_cfg.get("last4") or "").strip()
            if last4:
                cfg_lines.append(f"last4 = {json.dumps(last4)}")
            import_account_id = str(account_cfg.get("import_account_id") or "").strip()
            if import_account_id:
                cfg_lines.append(f"import_account_id = {json.dumps(import_account_id)}")
            cfg_lines.append("")

        for account_id, account_cfg in sorted(import_accounts.items(), key=lambda item: item[0]):
            cfg_lines.append(f"[import_accounts.{account_id}]")
            cfg_lines.append(f"display_name = {json.dumps(str(account_cfg.get('display_name', account_id)))}")
            cfg_lines.append(f"institution = {json.dumps(str(account_cfg.get('institution') or ''))}")
            cfg_lines.append(f"ledger_account = {json.dumps(str(account_cfg.get('ledger_account', '')))}")
            last4 = str(account_cfg.get("last4") or "").strip()
            if last4:
                cfg_lines.append(f"last4 = {json.dumps(last4)}")
            tracked_account_id = str(account_cfg.get("tracked_account_id") or "").strip()
            if tracked_account_id:
                cfg_lines.append(f"tracked_account_id = {json.dumps(tracked_account_id)}")
            import_profile_id = str(account_cfg.get("import_profile_id") or "").strip()
            if import_profile_id:
                cfg_lines.append(f"import_profile_id = {json.dumps(import_profile_id)}")
            cfg_lines.append("")

        config_toml.parent.mkdir(parents=True, exist_ok=True)
        config_toml.write_text("\n".join(cfg_lines).rstrip() + "\n", encoding="utf-8")

    def _ensure_seeded_accounts(self, accounts_dat: Path, tracked_accounts: list[dict]) -> None:
        lines = accounts_dat.read_text(encoding="utf-8").splitlines() if accounts_dat.exists() else []
        known_accounts = {
            line[len("account "):].strip()
            for line in lines
            if line.startswith("account ")
        }
        changed = not accounts_dat.exists()

        def append_account(account_name: str, account_type: str) -> None:
            nonlocal changed
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"account {account_name}")
            lines.append(f"    ; type: {account_type}")
            known_accounts.add(account_name)
            changed = True

        for account in tracked_accounts:
            ledger_account = str(account.get("ledger_account", "")).strip()
            if not ledger_account or ledger_account in known_accounts:
                continue
            append_account(ledger_account, self._infer_account_type(ledger_account))

        if "Expenses:Unknown" not in known_accounts:
            append_account("Expenses:Unknown", "Expense")
        if "Equity:Opening-Balances" not in known_accounts:
            append_account("Equity:Opening-Balances", "Equity")

        if changed:
            accounts_dat.parent.mkdir(parents=True, exist_ok=True)
            accounts_dat.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _sync_opening_balance(
        self,
        config: AppConfig,
        tracked_account_id: str,
        ledger_account: str,
        opening_balance: str | None = None,
        opening_balance_date: str | None = None,
    ) -> None:
        openings_by_id, _ = opening_balance_index(config)
        if opening_balance is not None:
            write_opening_balance(config, tracked_account_id, ledger_account, opening_balance, opening_balance_date)
            return

        existing = openings_by_id.get(tracked_account_id)
        if existing is None:
            return

        write_opening_balance(
            config,
            tracked_account_id,
            ledger_account,
            str(existing.amount),
            opening_balance_date or existing.date,
        )

    def _rewrite_posting_account(
        self,
        line: str,
        source_ledger_account: str,
        target_ledger_account: str,
    ) -> tuple[str, bool]:
        match = ACCOUNT_LINE_RE.match(line)
        if match and match.group(2).strip() == source_ledger_account:
            return (
                f"{match.group(1)}{target_ledger_account}{match.group(3)}{match.group(4)}",
                True,
            )

        match = ACCOUNT_ONLY_RE.match(line)
        if match and match.group(2).strip() == source_ledger_account:
            return (f"{match.group(1)}{target_ledger_account}", True)

        return line, False

    def _rewrite_transaction_source_payload_hash(
        self,
        txn_lines: list[str],
        *,
        import_account_id: str,
        target_ledger_account: str,
    ) -> tuple[list[str], dict | None]:
        metadata: dict[str, str] = {}
        source_payload_hash_idx: int | None = None

        for idx, line in enumerate(txn_lines[1:], start=1):
            match = META_RE.match(line)
            if not match:
                continue
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            metadata[key] = value
            if key == "source_payload_hash":
                source_payload_hash_idx = idx

        if metadata.get("import_account_id") != import_account_id:
            return txn_lines, None

        source_identity = metadata.get("source_identity")
        if not source_identity:
            return txn_lines, None

        source_payload_hash = source_payload_hash_for_lines(txn_lines, target_ledger_account)
        updated_lines = list(txn_lines)
        payload_line = f"    ; source_payload_hash: {source_payload_hash}"
        if source_payload_hash_idx is None:
            updated_lines.insert(1, payload_line)
        else:
            updated_lines[source_payload_hash_idx] = payload_line

        return (
            updated_lines,
            {
                "sourceIdentity": source_identity,
                "sourcePayloadHash": source_payload_hash,
                "sourceFileSha256": metadata.get("source_file_sha256", ""),
            },
        )

    def _migrate_journal_postings(
        self,
        config: AppConfig,
        source_ledger_account: str,
        target_ledger_account: str,
        *,
        import_account_id: str | None = None,
    ) -> None:
        source = source_ledger_account.strip()
        target = target_ledger_account.strip()
        if not source or not target or source == target:
            return

        db = ImportIndex(config.root_dir / ".workflow" / "state.db") if import_account_id else None
        for journal_path in sorted(config.journal_dir.glob("*.journal")):
            if not journal_path.exists():
                continue

            lines = journal_path.read_text(encoding="utf-8").splitlines()
            ranges = _iter_transaction_ranges(lines)
            if not ranges:
                continue

            updated_lines: list[str] = []
            migrated_hashes: list[dict] = []
            changed = False
            cursor = 0
            for start, end in ranges:
                updated_lines.extend(lines[cursor:start])
                txn_lines = list(lines[start:end])
                txn_changed = False

                for idx, line in enumerate(txn_lines):
                    rewritten, replaced = self._rewrite_posting_account(line, source, target)
                    if not replaced:
                        continue
                    txn_lines[idx] = rewritten
                    txn_changed = True

                if txn_changed and import_account_id:
                    txn_lines, payload_update = self._rewrite_transaction_source_payload_hash(
                        txn_lines,
                        import_account_id=import_account_id,
                        target_ledger_account=target,
                    )
                    if payload_update is not None:
                        migrated_hashes.append(payload_update)

                updated_lines.extend(txn_lines)
                changed = changed or txn_changed
                cursor = end

            updated_lines.extend(lines[cursor:])

            if changed:
                journal_path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")

            if db is not None and migrated_hashes:
                grouped_by_source_sha: dict[str, list[dict]] = {}
                for txn in migrated_hashes:
                    source_file_sha256 = str(txn.pop("sourceFileSha256", ""))
                    grouped_by_source_sha.setdefault(source_file_sha256, []).append(txn)

                for source_file_sha256, txns in grouped_by_source_sha.items():
                    db.upsert_transactions(
                        import_account_id=import_account_id,
                        year=journal_path.stem,
                        journal_path=journal_path,
                        source_file_sha256=source_file_sha256,
                        txns=txns,
                    )

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

        normalized_accounts: dict[str, dict] = {}
        selected_templates: dict[str, dict] = {}
        used_account_ids: set[str] = set()
        normalized_input_rows: list[tuple[dict, dict]] = []

        for raw in import_accounts:
            normalized, template = self._normalize_import_account(raw, used_account_ids)
            normalized_accounts[normalized["id"]] = {
                "display_name": normalized["display_name"],
                "institution": normalized["institution"],
                "ledger_account": normalized["ledger_account"],
                "last4": normalized["last4"],
                "tracked_account_id": normalized["id"],
            }
            selected_templates[normalized["institution"]] = template.as_config()
            normalized_input_rows.append((raw, normalized_accounts[normalized["id"]]))

        tracked_accounts = {
            account_id: self._tracked_account_from_import_account(account_id, account_id, account_cfg)
            for account_id, account_cfg in normalized_accounts.items()
        }

        self._write_workspace_config(
            settings / "workspace.toml",
            payee_aliases="payee_aliases.csv",
            workspace={
                "name": workspace_name,
                "base_currency": base_currency,
                "start_year": start_year,
            },
            dirs={
                "csv_dir": "inbox",
                "journal_dir": "journals",
                "init_dir": "rules",
                "opening_bal_dir": "opening",
                "imports_dir": "imports",
            },
            institution_templates=selected_templates,
            import_profiles={},
            tracked_accounts=tracked_accounts,
            import_accounts=normalized_accounts,
        )

        (imports / "import-log.ndjson").touch(exist_ok=True)

        payee_alias_csv = rules / "payee_aliases.csv"
        if not payee_alias_csv.exists():
            payee_alias_csv.write_text("payee,alias\n", encoding="utf-8")

        match_rules = rules / "20-match-rules.ndjson"
        if not match_rules.exists():
            match_rules.write_text("", encoding="utf-8")

        accounts_dat = rules / "10-accounts.dat"
        self._ensure_seeded_accounts(accounts_dat, list(tracked_accounts.values()))

        tags_dat = rules / "12-tags.dat"
        if not tags_dat.exists():
            tags_dat.write_text("tag Imported\ntag UUID\n", encoding="utf-8")

        commodities_dat = rules / "13-commodities.dat"
        ensure_standard_commodities_file(commodities_dat, base_currency)

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
        ensure_journal_includes(year_journal)

        config = load_config(settings / "workspace.toml")
        for raw, normalized_account in normalized_input_rows:
            opening_balance = raw.get("openingBalance")
            if opening_balance is None:
                continue
            write_opening_balance(
                config,
                str(normalized_account.get("tracked_account_id", "")),
                str(normalized_account.get("ledger_account", "")),
                str(opening_balance),
                str(raw.get("openingBalanceDate", "") or ""),
            )

        self.set_active_workspace(root)
        return root

    def upsert_import_account(
        self,
        config: AppConfig,
        account: dict,
        account_id: str | None = None,
        *,
        opening_balance: str | None = None,
        opening_balance_date: str | None = None,
    ) -> tuple[str, dict]:
        existing_accounts = {
            key: dict(value)
            for key, value in config.import_accounts.items()
        }
        existing_tracked_accounts = {
            key: dict(value)
            for key, value in config.tracked_accounts.items()
        }
        existing_import_profiles = {
            key: dict(value)
            for key, value in config.import_profiles.items()
        }
        used_account_ids = set(existing_accounts) | set(existing_tracked_accounts)

        if account_id:
            if account_id not in existing_accounts:
                raise ValueError(f"Unknown import account: {account_id}")
            used_account_ids.discard(account_id)

        normalized, template = self._normalize_import_account(
            account,
            used_account_ids,
            existing_import_accounts=existing_accounts,
            existing_account_id=account_id,
        )
        existing_row = existing_accounts.get(account_id or normalized["id"], {})
        previous_ledger_account = str(existing_row.get("ledger_account", "")).strip()
        tracked_account_id = str(existing_row.get("tracked_account_id", "")).strip() or normalized["id"]
        stale_profile_id = str(existing_row.get("import_profile_id") or "").strip()

        existing_accounts[normalized["id"]] = {
            "display_name": normalized["display_name"],
            "institution": normalized["institution"],
            "ledger_account": normalized["ledger_account"],
            "last4": normalized["last4"],
            "tracked_account_id": tracked_account_id,
        }
        if stale_profile_id:
            existing_import_profiles.pop(stale_profile_id, None)
        existing_tracked_accounts[tracked_account_id] = self._tracked_account_from_import_account(
            tracked_account_id,
            normalized["id"],
            existing_accounts[normalized["id"]],
        )

        institution_templates = {
            key: dict(value)
            for key, value in config.institution_templates.items()
        }
        institution_templates[normalized["institution"]] = template.as_config()

        self._write_workspace_config(
            config.config_toml,
            payee_aliases=config.payee_aliases,
            workspace=dict(config.workspace),
            dirs=dict(config.dirs),
            institution_templates=institution_templates,
            import_profiles=existing_import_profiles,
            tracked_accounts=existing_tracked_accounts,
            import_accounts=existing_accounts,
        )
        refreshed = load_config(config.config_toml)
        self._ensure_seeded_accounts(config.init_dir / "10-accounts.dat", list(existing_tracked_accounts.values()))
        self._migrate_journal_postings(
            refreshed,
            previous_ledger_account,
            existing_accounts[normalized["id"]]["ledger_account"],
            import_account_id=normalized["id"],
        )
        self._sync_opening_balance(
            refreshed,
            tracked_account_id,
            existing_accounts[normalized["id"]]["ledger_account"],
            opening_balance=opening_balance,
            opening_balance_date=opening_balance_date,
        )

        return normalized["id"], existing_accounts[normalized["id"]]

    def upsert_custom_import_account(
        self,
        config: AppConfig,
        account: dict,
        account_id: str | None = None,
        *,
        opening_balance: str | None = None,
        opening_balance_date: str | None = None,
    ) -> tuple[str, dict]:
        existing_accounts = {
            key: dict(value)
            for key, value in config.import_accounts.items()
        }
        existing_tracked_accounts = {
            key: dict(value)
            for key, value in config.tracked_accounts.items()
        }
        existing_import_profiles = {
            key: dict(value)
            for key, value in config.import_profiles.items()
        }
        used_account_ids = set(existing_accounts) | set(existing_tracked_accounts)

        if account_id:
            if account_id not in existing_accounts:
                raise ValueError(f"Unknown import account: {account_id}")
            used_account_ids.discard(account_id)

        normalized, profile = self._normalize_custom_import_account(
            account,
            used_account_ids,
            default_currency=str(config.workspace.get("base_currency", "USD")),
            existing_account_id=account_id,
        )
        previous_ledger_account = str(
            existing_accounts.get(account_id or normalized["id"], {}).get("ledger_account", "")
        ).strip()
        tracked_account_id = str(
            existing_accounts.get(account_id or normalized["id"], {}).get("tracked_account_id", "")
        ).strip() or normalized["id"]
        stale_profile_id = str(
            existing_accounts.get(account_id or normalized["id"], {}).get("import_profile_id", "")
        ).strip()
        if stale_profile_id and stale_profile_id != normalized["import_profile_id"]:
            existing_import_profiles.pop(stale_profile_id, None)

        existing_accounts[normalized["id"]] = {
            "display_name": normalized["display_name"],
            "institution": None,
            "ledger_account": normalized["ledger_account"],
            "last4": normalized["last4"],
            "tracked_account_id": tracked_account_id,
            "import_profile_id": normalized["import_profile_id"],
        }
        existing_import_profiles[normalized["import_profile_id"]] = profile
        existing_tracked_accounts[tracked_account_id] = self._tracked_account_from_import_account(
            tracked_account_id,
            normalized["id"],
            existing_accounts[normalized["id"]],
        )

        self._write_workspace_config(
            config.config_toml,
            payee_aliases=config.payee_aliases,
            workspace=dict(config.workspace),
            dirs=dict(config.dirs),
            institution_templates=dict(config.institution_templates),
            import_profiles=existing_import_profiles,
            tracked_accounts=existing_tracked_accounts,
            import_accounts=existing_accounts,
        )
        refreshed = load_config(config.config_toml)
        self._ensure_seeded_accounts(config.init_dir / "10-accounts.dat", list(existing_tracked_accounts.values()))
        self._migrate_journal_postings(
            refreshed,
            previous_ledger_account,
            existing_accounts[normalized["id"]]["ledger_account"],
            import_account_id=normalized["id"],
        )
        self._sync_opening_balance(
            refreshed,
            tracked_account_id,
            existing_accounts[normalized["id"]]["ledger_account"],
            opening_balance=opening_balance,
            opening_balance_date=opening_balance_date,
        )

        return normalized["id"], existing_accounts[normalized["id"]]

    def upsert_tracked_account(
        self,
        config: AppConfig,
        account: dict,
        account_id: str | None = None,
        *,
        opening_balance: str | None = None,
        opening_balance_date: str | None = None,
    ) -> tuple[str, dict]:
        existing_tracked_accounts = {
            key: dict(value)
            for key, value in config.tracked_accounts.items()
        }
        used_account_ids = set(existing_tracked_accounts) | set(config.import_accounts)

        if account_id:
            if account_id not in existing_tracked_accounts:
                raise ValueError(f"Unknown tracked account: {account_id}")
            if existing_tracked_accounts[account_id].get("import_account_id"):
                raise ValueError("Import-enabled accounts must be edited through import account flow")
            used_account_ids.discard(account_id)

        normalized = self._normalize_tracked_account(
            account,
            used_account_ids,
            existing_account_id=account_id,
        )
        previous_ledger_account = str(
            existing_tracked_accounts.get(account_id or normalized["id"], {}).get("ledger_account", "")
        ).strip()

        existing_tracked_accounts[normalized["id"]] = {
            "display_name": normalized["display_name"],
            "ledger_account": normalized["ledger_account"],
            "institution": normalized["institution"],
            "last4": normalized["last4"],
            "import_account_id": None,
        }

        self._write_workspace_config(
            config.config_toml,
            payee_aliases=config.payee_aliases,
            workspace=dict(config.workspace),
            dirs=dict(config.dirs),
            institution_templates=dict(config.institution_templates),
            import_profiles=dict(config.import_profiles),
            tracked_accounts=existing_tracked_accounts,
            import_accounts={
                key: dict(value)
                for key, value in config.import_accounts.items()
            },
        )
        refreshed = load_config(config.config_toml)
        self._ensure_seeded_accounts(config.init_dir / "10-accounts.dat", list(existing_tracked_accounts.values()))
        self._migrate_journal_postings(
            refreshed,
            previous_ledger_account,
            normalized["ledger_account"],
        )
        self._sync_opening_balance(
            refreshed,
            normalized["id"],
            normalized["ledger_account"],
            opening_balance=opening_balance,
            opening_balance_date=opening_balance_date,
        )
        return normalized["id"], existing_tracked_accounts[normalized["id"]]
