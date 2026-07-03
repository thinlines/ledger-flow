from __future__ import annotations

import json
from pathlib import Path

from ledger_flow_cli import main


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "settings").mkdir(parents=True)
    (workspace / "journals").mkdir()
    (workspace / "rules").mkdir()
    (workspace / "inbox").mkdir()
    (workspace / "imports").mkdir()
    (workspace / "opening-balances").mkdir()
    (workspace / "settings" / "workspace.toml").write_text(
        """
[workspace]
name = "Test"
start_year = 2026
base_currency = "USD"

[dirs]
csv_dir = "inbox"
journal_dir = "journals"
init_dir = "rules"
opening_bal_dir = "opening-balances"
imports_dir = "imports"

[tracked_accounts.card]
display_name = "Credit Card"
ledger_account = "Assets:Credit Card"
""".lstrip(),
        encoding="utf-8",
    )
    (workspace / "rules" / "10-accounts.dat").write_text(
        "account Assets:Credit Card\naccount Expenses:Eating Out\n",
        encoding="utf-8",
    )
    return workspace


def test_add_creates_manual_entry_in_year_journal(tmp_path: Path, capsys) -> None:
    workspace = _workspace(tmp_path)

    status = main([
        "--config",
        str(workspace / "settings" / "workspace.toml"),
        "add",
        "--payee",
        "Burger King",
        "--amount",
        "20.00",
        "--date",
        "2026-07-02",
        "--to",
        "Expenses:Eating Out",
        "--from",
        "Assets:Credit Card",
    ])

    assert status == 0
    output = json.loads(capsys.readouterr().out)
    assert output["created"] is True
    assert output["eventId"]

    journal = (workspace / "journals" / "2026.journal").read_text(encoding="utf-8")
    assert "2026-07-02 Burger King" in journal
    assert "    ; :manual:" in journal
    assert "    Expenses:Eating Out  $20.00" in journal
    assert "    Assets:Credit Card" in journal

    events = [
        json.loads(line)
        for line in (workspace / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["type"] == "manual_entry.created.v1"
    assert events[-1]["payload"]["source_account"] == "Assets:Credit Card"


def test_add_dry_run_prints_preview_without_writing(tmp_path: Path, capsys) -> None:
    workspace = _workspace(tmp_path)

    status = main([
        "--config",
        str(workspace / "settings" / "workspace.toml"),
        "add",
        "--payee",
        "Burger King",
        "--amount",
        "20.00",
        "--date",
        "2026-07-02",
        "--to",
        "Expenses:Eating Out",
        "--from",
        "Assets:Credit Card",
        "--dry-run",
    ])

    assert status == 0
    output = json.loads(capsys.readouterr().out)
    assert output["created"] is False
    assert output["dryRun"] is True
    assert output["journalPath"].endswith("journals/2026.journal")
    assert output["block"] == [
        "2026-07-02 Burger King",
        "    ; :manual:",
        "    Expenses:Eating Out  $20.00",
        "    Assets:Credit Card",
    ]
    assert not (workspace / "journals" / "2026.journal").exists()
    assert not (workspace / "events.jsonl").exists()
