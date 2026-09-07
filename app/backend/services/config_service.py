from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
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


def _clean(value: object) -> str | None:
    """Config strings arrive from TOML with inconsistent blank/None handling."""
    text = str(value or "").strip()
    return text or None


@dataclass(frozen=True)
class Account:
    """One account the workspace tracks, resolved from config.

    Callers ask ``AppConfig`` for accounts and read attributes; they do not
    reach into the underlying TOML dicts. ``raw`` stays available for the
    long-tail keys (opening balance, minimum payment, custom CSV profile)
    that only ``workspace_service`` writes and reads.
    """

    id: str
    display_name: str
    ledger_account: str
    subtype: str | None = None
    institution: str | None = None
    last4: str | None = None
    import_account_id: str | None = None
    tracked_account_id: str | None = None
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def kind(self) -> str:
        """``asset`` / ``liability`` / … inferred from the ledger account name."""
        return infer_account_kind(self.ledger_account)


def _account_from_cfg(account_id: str, cfg: dict) -> Account:
    return Account(
        id=account_id,
        display_name=str(cfg.get("display_name") or account_id),
        ledger_account=str(cfg.get("ledger_account") or "").strip(),
        subtype=_clean(cfg.get("subtype")),
        institution=_clean(cfg.get("institution")),
        last4=_clean(cfg.get("last4")),
        import_account_id=_clean(cfg.get("import_account_id")),
        tracked_account_id=_clean(cfg.get("tracked_account_id")),
        raw=cfg,
    )


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    config_toml: Path
    workspace: dict
    dirs: dict
    institution_templates: dict
    import_accounts: dict
    tracked_accounts: dict = field(default_factory=dict)
    import_profiles: dict = field(default_factory=dict)

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

    # -- Accounts ----------------------------------------------------------
    #
    # The account lookups every service needs, resolved once here instead of
    # re-derived from the raw config dicts at each call site.

    @cached_property
    def accounts(self) -> tuple[Account, ...]:
        """Every tracked account, in config order."""
        return tuple(
            _account_from_cfg(account_id, cfg)
            for account_id, cfg in self.tracked_accounts.items()
        )

    @cached_property
    def import_account_entries(self) -> tuple[Account, ...]:
        """Every import account, in config order."""
        return tuple(
            _account_from_cfg(account_id, cfg)
            for account_id, cfg in self.import_accounts.items()
        )

    @cached_property
    def _accounts_by_id(self) -> dict[str, Account]:
        return {account.id: account for account in self.accounts}

    @cached_property
    def _accounts_by_ledger(self) -> dict[str, Account]:
        """First tracked account wins when two declare the same ledger account
        — the precedence every hand-rolled reverse lookup already used."""
        index: dict[str, Account] = {}
        for account in self.accounts:
            if account.ledger_account:
                index.setdefault(account.ledger_account, account)
        return index

    @cached_property
    def _import_accounts_by_id(self) -> dict[str, Account]:
        return {account.id: account for account in self.import_account_entries}

    def account(self, account_id: str | None) -> Account | None:
        """The tracked account with this id, or ``None``."""
        if not account_id:
            return None
        return self._accounts_by_id.get(account_id)

    def account_for_ledger(self, ledger_account: str | None) -> Account | None:
        """The tracked account posting to this ledger account, or ``None``."""
        if not ledger_account:
            return None
        return self._accounts_by_ledger.get(str(ledger_account).strip())

    def import_account(self, import_account_id: str | None) -> Account | None:
        """The import account with this id, or ``None``."""
        if not import_account_id:
            return None
        return self._import_accounts_by_id.get(import_account_id)

    def ledger_account_for(self, account_id: str | None) -> str:
        """This tracked account's ledger account name, or ``""``."""
        account = self.account(account_id)
        return account.ledger_account if account else ""


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
        import_profiles=raw.get("import_profiles", {}),
    )
