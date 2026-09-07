"""``AppConfig`` account lookups (issue #007, seam 1).

These replace the ledger-account reverse lookup that was hand-rolled in ~20
services. The behaviour they pin down is the behaviour those loops already
had — first tracked account wins, blanks resolve to ``None``, unknown ids
return ``None`` rather than raising.
"""
from __future__ import annotations

from pathlib import Path

from services.config_service import AppConfig, load_config

_DIRS = {
    "csv_dir": "inbox",
    "journal_dir": "journals",
    "init_dir": "rules",
    "opening_bal_dir": "opening",
    "imports_dir": "imports",
}


def _config(
    *,
    tracked: dict | None = None,
    imports: dict | None = None,
    root: Path = Path("/tmp/does-not-need-to-exist"),
) -> AppConfig:
    return AppConfig(
        root_dir=root,
        config_toml=root / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2026},
        dirs=_DIRS,
        institution_templates={},
        import_accounts=imports if imports is not None else {},
        tracked_accounts=tracked if tracked is not None else {},
    )


_CHECKING = {
    "display_name": "Wells Fargo Checking",
    "ledger_account": "Assets:Bank:Checking",
    "institution": "wells_fargo",
    "last4": "4770",
    "subtype": "checking",
    "import_account_id": "checking",
}
_CARD = {
    "display_name": "Visa",
    "ledger_account": "Liabilities:Visa",
    "subtype": "credit_card",
}


def test_accounts_resolve_fields_from_config() -> None:
    config = _config(tracked={"checking": _CHECKING})
    account = config.account("checking")

    assert account is not None
    assert account.id == "checking"
    assert account.display_name == "Wells Fargo Checking"
    assert account.ledger_account == "Assets:Bank:Checking"
    assert account.institution == "wells_fargo"
    assert account.last4 == "4770"
    assert account.subtype == "checking"
    assert account.import_account_id == "checking"


def test_account_kind_is_inferred_from_ledger_account() -> None:
    config = _config(tracked={"checking": _CHECKING, "visa": _CARD})

    assert config.account("checking").kind == "asset"
    assert config.account("visa").kind == "liability"


def test_account_for_ledger_is_the_reverse_lookup() -> None:
    config = _config(tracked={"checking": _CHECKING, "visa": _CARD})

    assert config.account_for_ledger("Liabilities:Visa").id == "visa"
    assert config.account_for_ledger("Assets:Bank:Checking").id == "checking"


def test_account_for_ledger_tolerates_surrounding_whitespace() -> None:
    config = _config(tracked={"checking": _CHECKING})

    assert config.account_for_ledger("  Assets:Bank:Checking  ").id == "checking"


def test_first_tracked_account_wins_a_shared_ledger_account() -> None:
    """The precedence the hand-rolled loops already had (``setdefault``)."""
    config = _config(
        tracked={
            "primary": {"display_name": "A", "ledger_account": "Assets:Shared"},
            "secondary": {"display_name": "B", "ledger_account": "Assets:Shared"},
        }
    )

    assert config.account_for_ledger("Assets:Shared").id == "primary"


def test_accounts_without_a_ledger_account_are_not_reverse_indexed() -> None:
    config = _config(tracked={"stub": {"display_name": "Stub", "ledger_account": ""}})

    assert config.account("stub").ledger_account == ""
    assert config.account_for_ledger("") is None


def test_missing_and_blank_lookups_return_none() -> None:
    config = _config(tracked={"checking": _CHECKING})

    assert config.account("nope") is None
    assert config.account(None) is None
    assert config.account("") is None
    assert config.account_for_ledger("Assets:Nope") is None
    assert config.account_for_ledger(None) is None


def test_blank_optional_fields_normalize_to_none() -> None:
    config = _config(
        tracked={
            "sparse": {
                "display_name": "Sparse",
                "ledger_account": "Assets:Sparse",
                "institution": "",
                "last4": "   ",
            }
        }
    )
    account = config.account("sparse")

    assert account.institution is None
    assert account.last4 is None
    assert account.subtype is None


def test_display_name_falls_back_to_the_account_id() -> None:
    config = _config(tracked={"unnamed": {"ledger_account": "Assets:Unnamed"}})

    assert config.account("unnamed").display_name == "unnamed"


def test_ledger_account_for_returns_empty_string_when_unknown() -> None:
    config = _config(tracked={"checking": _CHECKING})

    assert config.ledger_account_for("checking") == "Assets:Bank:Checking"
    assert config.ledger_account_for("nope") == ""
    assert config.ledger_account_for(None) == ""


def test_import_accounts_are_resolved_separately_from_tracked() -> None:
    config = _config(
        tracked={"checking": _CHECKING},
        imports={
            "wf_checking": {
                "display_name": "WF Checking CSV",
                "ledger_account": "Assets:Bank:Checking",
                "tracked_account_id": "checking",
            }
        },
    )

    imported = config.import_account("wf_checking")
    assert imported is not None
    assert imported.tracked_account_id == "checking"
    # The tracked index is not polluted by import accounts.
    assert config.account("wf_checking") is None


def test_accounts_preserve_config_order() -> None:
    config = _config(
        tracked={
            "b": {"display_name": "B", "ledger_account": "Assets:B"},
            "a": {"display_name": "A", "ledger_account": "Assets:A"},
        }
    )

    assert [account.id for account in config.accounts] == ["b", "a"]


def test_raw_stays_available_for_long_tail_keys() -> None:
    config = _config(
        tracked={
            "loan": {
                "display_name": "Loan",
                "ledger_account": "Liabilities:Loan",
                "minimum_payment": "25.00",
            }
        }
    )

    assert config.account("loan").raw["minimum_payment"] == "25.00"


def test_lookups_work_on_a_config_loaded_from_toml(tmp_path: Path) -> None:
    """``load_config`` derives tracked accounts from import accounts when the
    workspace predates the ``[tracked_accounts]`` table — the lookups must see
    those derived entries too."""
    settings = tmp_path / "settings"
    settings.mkdir(parents=True)
    (settings / "workspace.toml").write_text(
        """
[workspace]
name = "Derived"
start_year = 2026

[dirs]
csv_dir = "inbox"
journal_dir = "journals"
init_dir = "rules"
opening_bal_dir = "opening"
imports_dir = "imports"

[import_accounts.wf_checking]
display_name = "WF Checking"
ledger_account = "Assets:Bank:Checking"
institution = "wells_fargo"
last4 = "4770"
""",
        encoding="utf-8",
    )

    config = load_config(settings / "workspace.toml")

    derived = config.account_for_ledger("Assets:Bank:Checking")
    assert derived is not None
    assert derived.id == "wf_checking"
    assert derived.last4 == "4770"
    assert derived.import_account_id == "wf_checking"
