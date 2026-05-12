from pathlib import Path

from services.category_suggestion_service import (
    _build_frequency_map,
    _is_category_account,
    suggest_category,
)
from services.config_service import AppConfig
from services.rules_service import ensure_rules_store, upsert_payee_rule


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2026, "base_currency": "USD"},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
        tracked_accounts={
            "checking": {
                "display_name": "Checking",
                "ledger_account": "Assets:Bank:Checking",
                "import_account_id": "checking",
            },
        },
        payee_aliases="payee_aliases.csv",
    )


def _write_journal(journal_dir: Path, content: str) -> None:
    journal = journal_dir / "2026.journal"
    journal.write_text(content.strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Rule match tests
# ---------------------------------------------------------------------------


def test_rule_match_returns_category_with_full_confidence(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    accounts_dat = config.init_dir / "10-accounts.dat"
    accounts_dat.write_text(
        "account Expenses:Food:Groceries\n    ; type: Expense\n",
        encoding="utf-8",
    )
    rules_file = ensure_rules_store(config.init_dir, accounts_dat)
    upsert_payee_rule(rules_file, "Whole Foods", "Expenses:Food:Groceries")

    result = suggest_category("Whole Foods", config)
    assert result["suggestion"] == "Expenses:Food:Groceries"
    assert result["confidence"] == 1.0
    assert result["source"] == "rule"
    assert result["alternatives"] == []


# ---------------------------------------------------------------------------
# Journal frequency tests
# ---------------------------------------------------------------------------


def test_journal_frequency_returns_most_common_category(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    accounts_dat = config.init_dir / "10-accounts.dat"
    accounts_dat.write_text("", encoding="utf-8")
    ensure_rules_store(config.init_dir, accounts_dat)

    _write_journal(
        config.journal_dir,
        """
2026-01-10 Starbucks
    Expenses:Food:Coffee  $5.00
    Assets:Bank:Checking

2026-01-15 Starbucks
    Expenses:Food:Coffee  $6.00
    Assets:Bank:Checking

2026-01-20 Starbucks
    Expenses:Food:Dining  $12.00
    Assets:Bank:Checking
""",
    )

    # Clear the module-level cache so fresh data is loaded
    import services.category_suggestion_service as mod
    mod._freq_cache = None
    mod._freq_cache_mtime = None

    result = suggest_category("Starbucks", config)
    assert result["suggestion"] == "Expenses:Food:Coffee"
    assert result["source"] == "history"
    assert result["confidence"] > 0.5


# ---------------------------------------------------------------------------
# Empty payee
# ---------------------------------------------------------------------------


def test_empty_payee_returns_no_suggestion(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    result = suggest_category("", config)
    assert result["suggestion"] is None
    assert result["confidence"] == 0.0
    assert result["source"] is None
    assert result["alternatives"] == []


def test_whitespace_payee_returns_no_suggestion(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    result = suggest_category("   ", config)
    assert result["suggestion"] is None


# ---------------------------------------------------------------------------
# Similar payees aggregate frequencies
# ---------------------------------------------------------------------------


def test_similar_payees_aggregate_frequencies(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    accounts_dat = config.init_dir / "10-accounts.dat"
    accounts_dat.write_text("", encoding="utf-8")
    ensure_rules_store(config.init_dir, accounts_dat)

    _write_journal(
        config.journal_dir,
        """
2026-02-01 Amazon.com
    Expenses:Shopping  $25.00
    Assets:Bank:Checking

2026-02-05 Amazon
    Expenses:Shopping  $30.00
    Assets:Bank:Checking

2026-02-10 Amazon Prime
    Expenses:Subscriptions  $15.00
    Assets:Bank:Checking
""",
    )

    import services.category_suggestion_service as mod
    mod._freq_cache = None
    mod._freq_cache_mtime = None

    result = suggest_category("Amazon", config)
    assert result["suggestion"] is not None
    assert result["source"] == "history"
    # Shopping should dominate (2 hits vs 1 for Subscriptions)
    assert result["suggestion"] == "Expenses:Shopping"


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_is_category_account() -> None:
    assert _is_category_account("Expenses:Food:Coffee") is True
    assert _is_category_account("Income:Salary") is True
    assert _is_category_account("Equity:Opening") is True
    assert _is_category_account("Assets:Bank:Checking") is False
    assert _is_category_account("Liabilities:Credit") is False


def test_build_frequency_map_handles_inferred_postings(tmp_path: Path) -> None:
    """Transactions with an inferred (blank amount) posting should still contribute."""
    from datetime import date
    from decimal import Decimal
    from services.journal_query_service import ParsedTransaction, Posting

    txns = [
        ParsedTransaction(
            posted_on=date(2026, 3, 1),
            payee="Target",
            postings=[
                Posting(account="Expenses:Shopping", amount=Decimal("50.00"), commodity="$"),
                Posting(account="Assets:Bank:Checking", amount=Decimal("-50.00"), commodity="$", inferred=True),
            ],
            metadata={},
        ),
    ]
    freq = _build_frequency_map(txns)
    assert "target" in freq
    assert freq["target"]["Expenses:Shopping"] == 1


def test_no_matching_history_returns_empty(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    accounts_dat = config.init_dir / "10-accounts.dat"
    accounts_dat.write_text("", encoding="utf-8")
    ensure_rules_store(config.init_dir, accounts_dat)

    _write_journal(
        config.journal_dir,
        """
2026-01-10 Starbucks
    Expenses:Food:Coffee  $5.00
    Assets:Bank:Checking
""",
    )

    import services.category_suggestion_service as mod
    mod._freq_cache = None
    mod._freq_cache_mtime = None

    result = suggest_category("Totally Unrelated Vendor XYZ", config)
    assert result["suggestion"] is None
    assert result["source"] is None
