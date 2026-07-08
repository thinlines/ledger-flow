from __future__ import annotations

import json
import os
import sys
import tomllib
import types
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import ledger_flow_cli
import pytest

from ledger_flow_cli import main
from services.event_log_service import read_events


def test_packaging_includes_server_top_level_modules() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert {"ledger_flow_cli", "main", "models"}.issubset(
        set(pyproject["tool"]["setuptools"]["py-modules"])
    )


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

    events = read_events(workspace)
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
    assert output["block"][0] == "2026-07-02 Burger King"
    assert output["block"][1].startswith("    ; lf_txn_id: txn_")
    assert output["block"][2:] == [
        "    ; :manual:",
        "    Expenses:Eating Out  $20.00",
        "    Assets:Credit Card",
    ]
    assert not (workspace / "journals" / "2026.journal").exists()
    assert not (workspace / "events.jsonl").exists()


def test_transactions_create_posts_api_payload_and_prints_json(monkeypatch, capsys) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def __enter__(self):
            return BytesIO(b'{"created":true,"txnId":"txn_123"}')

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        calls.append({
            "url": request.full_url,
            "method": request.get_method(),
            "headers": dict(request.header_items()),
            "body": json.loads(request.data.decode("utf-8")),
            "timeout": timeout,
        })
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    status = main([
        "transactions",
        "create",
        "--api-url",
        "http://ledger.test/base/",
        "--account",
        "Assets:Checking",
        "--to",
        "Expenses:Eating Out",
        "--payee",
        "Burger King",
        "--amount",
        "20.00",
        "--date",
        "2026-07-02",
        "--note",
        "receipt saved",
        "--json",
    ])

    assert status == 0
    assert json.loads(capsys.readouterr().out) == {"created": True, "txnId": "txn_123"}
    assert calls == [
        {
            "url": "http://ledger.test/base/api/transactions/create",
            "method": "POST",
            "headers": {"Content-type": "application/json"},
            "body": {
                "sourceAccount": "Assets:Checking",
                "date": "2026-07-02",
                "payee": "Burger King",
                "amount": "20.00",
                "destinationAccount": "Expenses:Eating Out",
                "notes": "receipt saved",
            },
            "timeout": 10,
        }
    ]


def test_transactions_create_help_describes_to_as_destination_posting_account(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["transactions", "create", "--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--to" in help_text
    assert "destination posting account" in " ".join(help_text.split()).lower()


def test_transactions_create_omits_destination_when_to_is_not_provided(
    monkeypatch, capsys
) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def __enter__(self):
            return BytesIO(
                b'{"created":true,"destinationAccount":"Expenses:Eating Out"}'
            )

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        calls.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    status = main([
        "transactions",
        "create",
        "--account",
        "Assets:Checking",
        "--payee",
        "Burger King",
        "--amount",
        "20.00",
        "--date",
        "2026-07-02",
        "--json",
    ])

    assert status == 0
    assert json.loads(capsys.readouterr().out) == {
        "created": True,
        "destinationAccount": "Expenses:Eating Out",
    }
    assert calls == [
        {
            "sourceAccount": "Assets:Checking",
            "date": "2026-07-02",
            "payee": "Burger King",
            "amount": "20.00",
        }
    ]


def test_transactions_create_defaults_api_url_date_and_quiet_output(monkeypatch, capsys) -> None:
    calls: list[dict] = []

    class FixedDate(ledger_flow_cli.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 5)

    class FakeResponse:
        def __enter__(self):
            return BytesIO(b'{"created":true}')

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        calls.append({
            "url": request.full_url,
            "body": json.loads(request.data.decode("utf-8")),
        })
        return FakeResponse()

    monkeypatch.setattr(ledger_flow_cli, "date", FixedDate)
    monkeypatch.setenv("LEDGER_FLOW_API_URL", "http://env-ledger.test")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    status = main([
        "transactions",
        "create",
        "--account",
        "Assets:Checking",
        "--to",
        "Expenses:Eating Out",
        "--payee",
        "Burger King",
        "--amount",
        "20.00",
    ])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == ""
    assert captured.err == ""
    assert calls == [
        {
            "url": "http://env-ledger.test/api/transactions/create",
            "body": {
                "sourceAccount": "Assets:Checking",
                "date": "2026-07-05",
                "payee": "Burger King",
                "amount": "20.00",
                "destinationAccount": "Expenses:Eating Out",
            },
        }
    ]


def test_transactions_create_rejects_invalid_input_before_api_call(monkeypatch, capsys) -> None:
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise AssertionError("request should not be sent")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    bad_date_status = main([
        "transactions",
        "create",
        "--account",
        "Assets:Checking",
        "--to",
        "Expenses:Eating Out",
        "--payee",
        "Burger King",
        "--amount",
        "20.00",
        "--date",
        "07/02/2026",
    ])
    bad_date = capsys.readouterr()

    bad_amount_status = main([
        "transactions",
        "create",
        "--account",
        "Assets:Checking",
        "--to",
        "Expenses:Eating Out",
        "--payee",
        "Burger King",
        "--amount",
        "0",
    ])
    bad_amount = capsys.readouterr()

    assert bad_date_status == 1
    assert "Invalid date" in bad_date.err
    assert bad_amount_status == 1
    assert "positive decimal" in bad_amount.err
    assert calls == 0


def test_transactions_create_accepts_relative_date_aliases(monkeypatch) -> None:
    dates: list[str] = []

    class FixedDate(ledger_flow_cli.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 5)

    class FakeResponse:
        def __enter__(self):
            return BytesIO(b'{"created":true}')

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        dates.append(json.loads(request.data.decode("utf-8"))["date"])
        return FakeResponse()

    monkeypatch.setattr(ledger_flow_cli, "date", FixedDate)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    for raw_date in ["today", "yesterday"]:
        assert main([
            "transactions",
            "create",
            "--account",
            "Assets:Checking",
            "--to",
            "Expenses:Eating Out",
            "--payee",
            "Burger King",
            "--amount",
            "20.00",
            "--date",
            raw_date,
        ]) == 0

    assert dates == ["2026-07-05", "2026-07-04"]


def test_transactions_create_api_failure_prints_concise_error(monkeypatch, capsys) -> None:
    def fake_urlopen(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"detail":"no matching source account"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    status = main([
        "transactions",
        "create",
        "--account",
        "Assets:Missing",
        "--to",
        "Expenses:Eating Out",
        "--payee",
        "Burger King",
        "--amount",
        "20.00",
    ])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err == "API request failed: HTTP 400\n"


def test_server_starts_api_for_workspace(tmp_path: Path, monkeypatch, capsys) -> None:
    workspace = _workspace(tmp_path)
    calls: list[dict] = []

    def fake_run(app, **kwargs):
        calls.append({"app": app, **kwargs})

    monkeypatch.delenv("LEDGER_FLOW_ROOT", raising=False)
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_run))

    status = main([
        "server",
        "--workspace",
        str(workspace),
        "--host",
        "0.0.0.0",
        "--port",
        "8123",
        "--reload",
    ])

    assert status == 0
    assert calls == [
        {
            "app": "main:app",
            "host": "0.0.0.0",
            "port": 8123,
            "reload": True,
        }
    ]
    assert os.environ["LEDGER_FLOW_ROOT"] == str(workspace)
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "host": "0.0.0.0",
        "port": 8123,
        "reload": True,
        "workspace": str(workspace),
    }
