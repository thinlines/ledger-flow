"""Project-wide invariants around journal date format (ISO 8601).

These checks fail closed:
- Any committed test fixture journal whose transaction header drifts back to
  ``YYYY/MM/DD`` is a regression.
- ``run_cmd`` must always inject ``LEDGER_DATE_FORMAT="%Y-%m-%d"`` into the
  subprocess environment without clobbering inherited variables (e.g., PATH).
- The known journal-writer code paths must emit ISO header lines.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest

from services.ledger_runner import LEDGER_DATE_FORMAT, run_cmd
from services.manual_entry_service import build_manual_transaction_block
from services.opening_balance_service import write_opening_balance
from services.reconciliation_service import _build_assertion_block

ISO_HEADER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s")
SLASH_HEADER_RE = re.compile(r"^\d{4}/\d{2}/\d{2}", re.MULTILINE)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Test-fixture audit
# ---------------------------------------------------------------------------


def test_no_fixture_journals_use_slash_dates() -> None:
    offenders: list[str] = []
    for path in FIXTURES_DIR.rglob("*.journal"):
        text = path.read_text(encoding="utf-8")
        if SLASH_HEADER_RE.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Test fixtures contain slash-format dates; convert to ISO (YYYY-MM-DD): "
        + ", ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Runner env
# ---------------------------------------------------------------------------


def test_run_cmd_sets_ledger_date_format(tmp_path: Path) -> None:
    captured: dict[str, dict[str, str] | None] = {"env": None}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _spy(args, **kwargs):  # noqa: ANN001
        captured["env"] = kwargs.get("env")
        return _Result()

    with mock.patch("services.ledger_runner.subprocess.run", side_effect=_spy):
        run_cmd(["ledger", "--version"], cwd=tmp_path)

    env = captured["env"]
    assert env is not None, "run_cmd must pass an explicit env to subprocess.run"
    assert env.get("LEDGER_DATE_FORMAT") == "%Y-%m-%d"
    assert env.get("LEDGER_DATE_FORMAT") == LEDGER_DATE_FORMAT


def test_run_cmd_preserves_inherited_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", "/sentinel/bin:/usr/bin")
    monkeypatch.setenv("LEDGER_FLOW_TEST_VAR", "carry-through")

    captured: dict[str, dict[str, str] | None] = {"env": None}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _spy(args, **kwargs):  # noqa: ANN001
        captured["env"] = kwargs.get("env")
        return _Result()

    with mock.patch("services.ledger_runner.subprocess.run", side_effect=_spy):
        run_cmd(["ledger", "--version"], cwd=tmp_path)

    env = captured["env"]
    assert env is not None
    assert env.get("PATH") == "/sentinel/bin:/usr/bin"
    assert env.get("LEDGER_FLOW_TEST_VAR") == "carry-through"
    assert env.get("LEDGER_DATE_FORMAT") == "%Y-%m-%d"


def test_run_cmd_overrides_caller_supplied_format(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A pre-existing ``LEDGER_DATE_FORMAT`` in the parent env must be overridden."""
    monkeypatch.setenv("LEDGER_DATE_FORMAT", "%m/%d/%Y")

    captured: dict[str, dict[str, str] | None] = {"env": None}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _spy(args, **kwargs):  # noqa: ANN001
        captured["env"] = kwargs.get("env")
        return _Result()

    with mock.patch("services.ledger_runner.subprocess.run", side_effect=_spy):
        run_cmd(["ledger", "--version"], cwd=tmp_path)

    env = captured["env"]
    assert env is not None
    assert env.get("LEDGER_DATE_FORMAT") == "%Y-%m-%d"


# ---------------------------------------------------------------------------
# Writer audit — every journal-writing code path emits ISO headers.
# ---------------------------------------------------------------------------


def test_manual_entry_writer_emits_iso_header() -> None:
    block = build_manual_transaction_block(
        txn_date="2026-03-28",
        payee="Uber",
        amount=Decimal("45.95"),
        destination_account="Expenses:Transportation:Rides",
        tracked_ledger_account="Assets:Bank:Checking",
    )
    assert ISO_HEADER_RE.match(block[0]), block[0]


def test_reconciliation_writer_emits_iso_header() -> None:
    block = _build_assertion_block(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        closing_balance=Decimal("1234.56"),
        currency="USD",
        display_name="Test Card",
        ledger_account="Liabilities:Test:Card",
        event_id="01HX0123456789ABCDEFGHIJKL",
    )
    assert ISO_HEADER_RE.match(block[0]), block[0]


def test_opening_balance_writer_emits_iso_header(tmp_path: Path) -> None:
    from services.config_service import AppConfig

    workspace = tmp_path / "workspace"
    for rel in ("settings", "journals", "inbox", "rules", "opening", "imports"):
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test", "start_year": 2026, "base_currency": "USD"},
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
            },
        },
    )

    write_opening_balance(
        config=config,
        tracked_account_id="checking",
        ledger_account="Assets:Bank:Checking",
        amount_text="1000.00",
        opening_date="2026-01-01",
    )

    target = workspace / "opening" / "checking.journal"
    text = target.read_text(encoding="utf-8")
    first_line = text.splitlines()[0]
    assert ISO_HEADER_RE.match(first_line), first_line
