"""Tests for minimum_payment metadata on opening balance entries."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from services.config_service import AppConfig
from services.opening_balance_service import (
    load_opening_balance_entries,
    opening_balance_index,
    write_opening_balance,
)


def _make_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2025, "base_currency": "USD"},
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
            "mortgage": {
                "display_name": "Home Mortgage",
                "ledger_account": "Liabilities:Mortgage",
            },
        },
        payee_aliases="payee_aliases.csv",
    )


def test_write_and_read_minimum_payment(tmp_path: Path) -> None:
    """Round-trip: write with minimum_payment, read it back."""
    config = _make_config(tmp_path / "workspace")
    write_opening_balance(
        config,
        tracked_account_id="mortgage",
        ledger_account="Liabilities:Mortgage",
        amount_text="-250000.00",
        opening_date="2026-01-01",
        minimum_payment="1850.00",
    )

    entries = load_opening_balance_entries(config)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.tracked_account_id == "mortgage"
    assert entry.amount == Decimal("-250000.00")
    assert entry.minimum_payment == Decimal("1850.00")


def test_read_without_minimum_payment_returns_none(tmp_path: Path) -> None:
    """Backward compatibility: entry without minimum_payment metadata returns None."""
    config = _make_config(tmp_path / "workspace")
    write_opening_balance(
        config,
        tracked_account_id="mortgage",
        ledger_account="Liabilities:Mortgage",
        amount_text="-250000.00",
        opening_date="2026-01-01",
    )

    entries = load_opening_balance_entries(config)
    assert len(entries) == 1
    assert entries[0].minimum_payment is None


def test_minimum_payment_empty_string_omitted(tmp_path: Path) -> None:
    """Empty string minimum_payment should not produce metadata."""
    config = _make_config(tmp_path / "workspace")
    write_opening_balance(
        config,
        tracked_account_id="mortgage",
        ledger_account="Liabilities:Mortgage",
        amount_text="-250000.00",
        minimum_payment="",
    )

    entries = load_opening_balance_entries(config)
    assert len(entries) == 1
    assert entries[0].minimum_payment is None

    # Verify the file doesn't contain the metadata line
    journal_text = (config.opening_bal_dir / "mortgage.journal").read_text()
    assert "minimum_payment" not in journal_text


def test_malformed_minimum_payment_returns_none(tmp_path: Path) -> None:
    """Malformed minimum_payment metadata should result in None."""
    config = _make_config(tmp_path / "workspace")
    journal_path = config.opening_bal_dir / "mortgage.journal"
    journal_path.write_text(
        "\n".join([
            "2026-01-01 Opening balance",
            "    ; tracked_account_id: mortgage",
            "    ; minimum_payment: abc",
            "    Liabilities:Mortgage  USD -250000.00",
            "    Equity:Opening-Balances",
            "",
        ]),
        encoding="utf-8",
    )

    entries = load_opening_balance_entries(config)
    assert len(entries) == 1
    assert entries[0].minimum_payment is None


def test_minimum_payment_with_currency_symbols(tmp_path: Path) -> None:
    """minimum_payment with $, commas should be parsed correctly."""
    config = _make_config(tmp_path / "workspace")
    write_opening_balance(
        config,
        tracked_account_id="mortgage",
        ledger_account="Liabilities:Mortgage",
        amount_text="-250000.00",
        minimum_payment="$1,850.00",
    )

    entries = load_opening_balance_entries(config)
    assert len(entries) == 1
    assert entries[0].minimum_payment == Decimal("1850.00")


def test_minimum_payment_preserved_in_index(tmp_path: Path) -> None:
    """opening_balance_index returns minimum_payment."""
    config = _make_config(tmp_path / "workspace")
    write_opening_balance(
        config,
        tracked_account_id="mortgage",
        ledger_account="Liabilities:Mortgage",
        amount_text="-250000.00",
        minimum_payment="1850",
    )

    by_id, by_ledger = opening_balance_index(config)
    assert by_id["mortgage"].minimum_payment == Decimal("1850")
    assert by_ledger["Liabilities:Mortgage"].minimum_payment == Decimal("1850")


def test_minimum_payment_different_decimal_places(tmp_path: Path) -> None:
    """Round-trip with various decimal places."""
    config = _make_config(tmp_path / "workspace")

    for amount in ["100", "99.9", "1234.56"]:
        write_opening_balance(
            config,
            tracked_account_id="mortgage",
            ledger_account="Liabilities:Mortgage",
            amount_text="-250000.00",
            minimum_payment=amount,
        )

        entries = load_opening_balance_entries(config)
        assert len(entries) == 1
        # The writer quantizes to 2 decimal places
        assert entries[0].minimum_payment is not None


def test_minimum_payment_metadata_position_in_file(tmp_path: Path) -> None:
    """minimum_payment metadata should appear after tracked_account_id."""
    config = _make_config(tmp_path / "workspace")
    write_opening_balance(
        config,
        tracked_account_id="mortgage",
        ledger_account="Liabilities:Mortgage",
        amount_text="-250000.00",
        minimum_payment="1850.00",
    )

    journal_text = (config.opening_bal_dir / "mortgage.journal").read_text()
    lines = journal_text.splitlines()

    tracked_id_idx = next(i for i, l in enumerate(lines) if "tracked_account_id" in l)
    min_payment_idx = next(i for i, l in enumerate(lines) if "minimum_payment" in l)
    posting_idx = next(i for i, l in enumerate(lines) if "Liabilities:Mortgage" in l)

    assert tracked_id_idx < min_payment_idx < posting_idx
